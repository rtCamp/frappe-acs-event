# Copyright (c) 2026, rtCamp and Contributors
# See license.txt

from datetime import datetime, timedelta

from frappe.tests import UnitTestCase
from frappe.utils import convert_utc_to_system_timezone

from frappe_acs_event.api.acs_webhook import (
    DELIVERY_EVENT_TYPE,
    _find_validation_event,
    _parse_event,
    _to_system_datetime,
)
from frappe_acs_event.frappe_acs_event.doctype.acs_email_event.acs_email_event import normalise_status
from frappe_acs_event.utils import matching

# A real Event Grid delivery report from ACS.
REAL_EVENT = {
    "id": "0e0df3cb-ff8f-4f0a-9830-cfe76145d517",
    "topic": "/subscriptions/x/resourcegroups/email/providers/microsoft.communication/"
    "communicationservices/frappe-email-cs",
    "subject": "sender/DoNotReply@guid.us1.azurecomm.net/message/fb9e3380-428f-4e59-95a1-fc82e99a5219",
    "data": {
        "sender": "DoNotReply@guid.us1.azurecomm.net",
        "recipient": "someone@gmail.com",
        "internetMessageId": "<178718194781.13391.1129954722203963622@apex.localhost>",
        "messageId": "fb9e3380-428f-4e59-95a1-fc82e99a5219",
        "status": "Delivered",
        "deliveryStatusDetails": {
            "statusMessage": "",
            "recipientMailServerHostName": "gmail-smtp-in.l.google.com",
        },
        "deliveryAttemptTimestamp": "2026-08-19T23:26:32.99+00:00",
    },
    "eventType": "Microsoft.Communication.EmailDeliveryReportReceived",
    "dataVersion": "1.0",
    "metadataVersion": "1",
    "eventTime": "2026-08-19T23:28:55.2532364Z",
}


class UnitTestACSEmailEvent(UnitTestCase):
    """Unit tests for the pure parts of the ACS event pipeline."""

    def test_every_documented_status_is_lowercased_as_is(self):
        self.assertEqual(normalise_status("Delivered"), "delivered")
        self.assertEqual(normalise_status("Bounced"), "bounced")
        self.assertEqual(normalise_status("FilteredSpam"), "filteredspam")
        self.assertEqual(normalise_status("Quarantined"), "quarantined")
        self.assertEqual(normalise_status("Failed"), "failed")
        self.assertEqual(normalise_status("Suppressed"), "suppressed")
        self.assertEqual(normalise_status("Expanded"), "expanded")

    def test_status_casing_is_not_trusted(self):
        self.assertEqual(normalise_status("delivered"), "delivered")
        self.assertEqual(normalise_status("  BOUNCED "), "bounced")

    def test_a_new_status_is_kept_under_its_own_name(self):
        self.assertEqual(normalise_status("SomethingAzureAddedLater"), "somethingazureaddedlater")

    def test_a_missing_status_falls_back_to_unknown(self):
        self.assertEqual(normalise_status(None), "unknown")
        self.assertEqual(normalise_status(""), "unknown")

    def test_message_id_loses_its_angle_brackets(self):
        self.assertEqual(
            matching.clean_message_id("<178718194781.13391.1129954722203963622@apex.localhost>"),
            "178718194781.13391.1129954722203963622@apex.localhost",
        )
        self.assertEqual(matching.clean_message_id("  <a@b>  "), "a@b")
        self.assertEqual(matching.clean_message_id(None), "")

    def test_real_payload_parses_into_our_columns(self):
        parsed = _parse_event(REAL_EVENT, REAL_EVENT["id"])

        self.assertEqual(parsed["event_id"], "0e0df3cb-ff8f-4f0a-9830-cfe76145d517")
        self.assertEqual(parsed["acs_message_id"], "fb9e3380-428f-4e59-95a1-fc82e99a5219")
        self.assertEqual(parsed["event_type"], "delivered")
        self.assertEqual(parsed["acs_status"], "Delivered")
        self.assertEqual(parsed["recipient_email"], "someone@gmail.com")
        self.assertEqual(parsed["message_id"], "178718194781.13391.1129954722203963622@apex.localhost")
        self.assertEqual(parsed["recipient_mail_server"], "gmail-smtp-in.l.google.com")
        # Empty string on success, so it must not become an empty-looking value
        self.assertIsNone(parsed["status_message"])
        self.assertIsNotNone(parsed["event_timestamp"])

    def test_timestamp_field_is_the_lowercase_s_one(self):
        parsed = _parse_event(REAL_EVENT, REAL_EVENT["id"])
        expected = convert_utc_to_system_timezone(datetime.fromisoformat("2026-08-19T23:26:32.99+00:00")).replace(
            tzinfo=None
        )
        self.assertEqual(parsed["event_timestamp"], expected)

    def test_capitalised_timestamp_field_still_works(self):
        event = {"data": {"status": "Bounced", "deliveryAttemptTimeStamp": "2026-08-19T23:26:32Z"}}
        self.assertIsNotNone(_parse_event(event, "some-id")["event_timestamp"])

    def test_timestamps_are_iso_not_unix(self):
        self.assertIsNone(_to_system_datetime(None))
        self.assertIsNone(_to_system_datetime("not a timestamp"))
        self.assertIsNone(_to_system_datetime(0))
        self.assertIsNotNone(_to_system_datetime("2026-08-19T23:28:55.2532364Z"))

    def test_resend_shares_a_message_id_so_the_newest_earlier_send_wins(self):
        event_time = datetime(2026, 8, 19, 23, 26, 32)
        candidates = [
            {"name": "EQ-resend", "creation": event_time + timedelta(minutes=5)},
            {"name": "EQ-original", "creation": event_time - timedelta(minutes=1)},
        ]
        self.assertEqual(matching.pick_queue_row(candidates, event_time), "EQ-original")

    def test_a_result_that_predates_every_queue_row_still_matches_something(self):
        event_time = datetime(2026, 8, 19, 23, 26, 32)
        candidates = [
            {"name": "EQ-newer", "creation": event_time + timedelta(minutes=5)},
            {"name": "EQ-oldest", "creation": event_time + timedelta(minutes=1)},
        ]
        self.assertEqual(matching.pick_queue_row(candidates, event_time), "EQ-oldest")

    def test_no_candidates_means_no_match(self):
        self.assertIsNone(matching.pick_queue_row([], datetime(2026, 8, 19)))
        self.assertIsNone(matching.pick_queue_row(None, None))

    def test_no_target_email_accounts_means_no_lookup(self):
        self.assertEqual(matching.build_exact_index({"a@b"}, []), {})
        self.assertEqual(matching.build_exact_index(set(), ["ACS"]), {})

    def test_only_delivery_reports_are_kept(self):
        self.assertEqual(DELIVERY_EVENT_TYPE, "Microsoft.Communication.EmailDeliveryReportReceived")

    def test_the_validation_event_is_spotted(self):
        validation = {
            "eventType": "Microsoft.EventGrid.SubscriptionValidationEvent",
            "data": {"validationCode": "512d38b6"},
        }
        self.assertIs(_find_validation_event([validation]), validation)
        self.assertIsNone(_find_validation_event([REAL_EVENT]))
