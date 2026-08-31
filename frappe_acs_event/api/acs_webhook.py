"""Receives Azure Communication Services email delivery events via Event Grid.

Must answer fast: authenticate, filter, bulk insert as Pending, return 200.
All matching and cleanup happens later in tasks/process_acs_events.py.

Use the Event Grid schema for the subscription, not CloudEvents: CloudEvents
proves ownership with an HTTP OPTIONS request, and Frappe answers every
OPTIONS with an empty response before routing, so no whitelisted method
could ever see it.
"""

from __future__ import annotations

import hmac
import json
from datetime import UTC, datetime

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.utils import convert_utc_to_system_timezone, get_datetime
from werkzeug.wrappers import Response

from frappe_acs_event.frappe_acs_event.doctype.acs_account.acs_account import get_enabled_accounts
from frappe_acs_event.frappe_acs_event.doctype.acs_email_event.acs_email_event import normalise_status
from frappe_acs_event.utils import matching

DELIVERY_EVENT_TYPE = "Microsoft.Communication.EmailDeliveryReportReceived"
SUBSCRIPTION_VALIDATION_EVENT_TYPE = "Microsoft.EventGrid.SubscriptionValidationEvent"

_MAX_EVENTS_PER_BATCH = 5_000

_TOKEN_QUERY_PARAM = "token"
_TOKEN_HEADER = "X-ACS-Webhook-Token"

_INSERT_FIELDS = [
    "name",
    "event_id",
    "acs_message_id",
    "internet_message_id",
    "message_id",
    "email_queue",
    "acs_account",
    "event_type",
    "acs_status",
    "sender_email",
    "recipient_email",
    "event_timestamp",
    "status_message",
    "recipient_mail_server",
    "processing_status",
    "raw_payload",
    "creation",
    "modified",
    "owner",
    "modified_by",
]


@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep  Trusted endpoint, secret verified in code
def handle():
    """Entry point for the Event Grid webhook.

    Returns the bare `{"validationResponse": "<code>"}` body for the ownership
    handshake, built as a werkzeug Response so Frappe's usual `{"message": ...}`
    wrapper doesn't hide it. Otherwise returns `{"status": "ok", "accepted": n, "total": m}`.
    """
    raw_payload: str = frappe.request.get_data(as_text=True)
    if not raw_payload:
        frappe.throw(_("Empty request body"), frappe.ValidationError)

    try:
        events = json.loads(raw_payload)
    except json.JSONDecodeError, TypeError:
        frappe.throw(_("Invalid JSON payload"), frappe.ValidationError)

    if not isinstance(events, list):
        frappe.throw(_("Payload must be a JSON array"), frappe.ValidationError)

    if len(events) > _MAX_EVENTS_PER_BATCH:
        frappe.throw(
            _("Payload exceeds maximum of {0} events").format(_MAX_EVENTS_PER_BATCH),
            frappe.ValidationError,
        )

    acs_account = get_associated_acs_account(events)

    validation_event = _find_validation_event(events)
    if validation_event:
        return _answer_subscription_validation(validation_event, acs_account)

    # Unknown or disabled account gets a 200, not an error, so Event Grid
    # doesn't retry the same rejected batch for 24 hours.
    if not acs_account:
        return {"status": "ok", "accepted": 0, "total": len(events)}

    delivery_events = [
        event for event in events if isinstance(event, dict) and event.get("eventType") == DELIVERY_EVENT_TYPE
    ]

    accepted = 0
    if delivery_events:
        accepted = _bulk_insert_events(delivery_events, acs_account)

    return {"status": "ok", "accepted": accepted, "total": len(events)}


def _find_validation_event(events: list) -> dict | None:
    """Finds the one-off subscription ownership check, if this batch is one."""
    for event in events:
        if isinstance(event, dict) and event.get("eventType") == SUBSCRIPTION_VALIDATION_EVENT_TYPE:
            return event
    return None


def _answer_subscription_validation(event: dict, acs_account: str | None) -> Response:
    """Echoes the validation code back, only for a caller we can authenticate.

    An unauthenticated handshake gets a bare 200. Event Grid then falls back to
    its manual route: the validationUrl in the event, good for 10 minutes.
    """
    data = event.get("data") or {}
    validation_code = data.get("validationCode")
    validation_url = data.get("validationUrl")

    if not acs_account:
        frappe.logger("acs_webhook").warning(
            "Unauthenticated Event Grid subscription validation for topic "
            f"{event.get('topic')!r}. Configure an enabled ACS Account whose ACS Resource ID matches, "
            f"or complete the handshake manually at: {validation_url}"
        )
        return Response(json.dumps({}), content_type="application/json", status=200)

    frappe.logger("acs_webhook").info(
        f"Answering Event Grid subscription validation for ACS Account {acs_account}. "
        f"Manual fallback URL (valid 10 minutes): {validation_url}"
    )

    return Response(
        json.dumps({"validationResponse": validation_code}),
        content_type="application/json",
        status=200,
    )


def get_associated_acs_account(events: list) -> str | None:
    """Finds which ACS Account this call belongs to and checks its secret.

    Matches the event's topic against each account's ACS Resource ID first.
    Falls back to trying every enabled account's secret when the topic is
    missing or unrecognised, which is what lets the first handshake succeed.
    """
    accounts = get_enabled_accounts()
    if not accounts:
        return None

    topic = ""
    for event in events:
        if isinstance(event, dict) and event.get("topic"):
            topic = event["topic"].strip().lower()
            break

    if topic:
        matched = [account for account in accounts if account["acs_resource_id"] == topic]
        if matched:
            accounts = matched

    for account in accounts:
        if _authenticate(account):
            return account["name"]

    return None


def _authenticate(account: dict) -> bool:
    """Compares the presented secret against the account's, in constant time."""
    try:
        expected = frappe.get_cached_doc("ACS Account", account["name"]).get_password(
            "webhook_secret", raise_exception=False
        )
    except frappe.DoesNotExistError:
        return False

    if not expected:
        return False

    return hmac.compare_digest(_presented_token().encode(), str(expected).encode())


def _presented_token() -> str:
    """The shared secret, from the query string or the header."""
    if not getattr(frappe, "request", None):
        return ""
    return frappe.request.args.get(_TOKEN_QUERY_PARAM) or frappe.request.headers.get(_TOKEN_HEADER, "") or ""


def _bulk_insert_events(events: list[dict], acs_account: str) -> int:
    """Inserts new events in one batch, skipping ones we already have."""
    target_email_accounts = frappe.get_cached_doc("ACS Account", acs_account).get_target_email_accounts()

    now = frappe.utils.now()
    user = "Administrator"

    event_ids = {(event.get("id") or "").strip() for event in events}
    event_ids.discard("")
    existing_event_ids = set()
    if event_ids:
        existing_event_ids = set(
            frappe.get_all(
                "ACS Email Event",
                filters={"event_id": ("in", list(event_ids))},
                pluck="event_id",
            )
        )

    parsed: list[dict] = []
    seen_in_batch: set[str] = set()
    for event in events:
        event_id = (event.get("id") or "").strip()
        if not event_id or event_id in existing_event_ids or event_id in seen_in_batch:
            continue
        seen_in_batch.add(event_id)
        parsed.append(_parse_event(event, event_id))

    if not parsed:
        return 0

    exact_index = matching.build_exact_index(
        {row["message_id"] for row in parsed if row["message_id"]},
        target_email_accounts,
    )

    rows: list[list] = []
    for row in parsed:
        email_queue = matching.pick_queue_row(exact_index.get(row["message_id"]), row["event_timestamp"])

        rows.append(
            [
                make_autoname("hash", doctype="ACS Email Event"),
                row["event_id"],
                row["acs_message_id"],
                row["internet_message_id"],
                row["message_id"],
                email_queue,
                acs_account,
                row["event_type"],
                row["acs_status"],
                row["sender_email"],
                row["recipient_email"],
                row["event_timestamp"],
                row["status_message"],
                row["recipient_mail_server"],
                "Pending",
                row["raw_payload"],
                now,
                now,
                user,
                user,
            ]
        )

    frappe.db.bulk_insert("ACS Email Event", fields=_INSERT_FIELDS, values=rows, ignore_duplicates=True)
    return len(rows)


def _parse_event(event: dict, event_id: str) -> dict:
    """Extracts our columns from one raw Event Grid delivery event."""
    data = event.get("data") or {}
    status_details = data.get("deliveryStatusDetails") or {}
    internet_message_id = data.get("internetMessageId") or ""

    return {
        "event_id": _trim(event_id, "event_id"),
        "acs_message_id": _trim(data.get("messageId"), "acs_message_id"),
        "internet_message_id": _trim(internet_message_id, "internet_message_id"),
        "message_id": _trim(matching.clean_message_id(internet_message_id), "message_id"),
        "event_type": normalise_status(data.get("status")),
        "acs_status": _trim(data.get("status"), "acs_status"),
        "sender_email": _trim(data.get("sender"), "sender_email"),
        "recipient_email": _trim(data.get("recipient"), "recipient_email"),
        # Both casings of this field are accepted.
        "event_timestamp": _to_system_datetime(
            data.get("deliveryAttemptTimestamp") or data.get("deliveryAttemptTimeStamp")
        ),
        # Empty string on success, not absent. Test truthiness, not key presence.
        "status_message": status_details.get("statusMessage") or None,
        "recipient_mail_server": _trim(status_details.get("recipientMailServerHostName"), "recipient_mail_server"),
        "raw_payload": json.dumps(event, default=str),
    }


def _to_system_datetime(value) -> datetime | None:
    """Parses ACS's ISO-8601 timestamp into a site-timezone datetime."""
    if not value:
        return None

    parsed = None
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        # get_datetime can raise on a bad string instead of returning None.
        try:
            parsed = get_datetime(value)
        except Exception:
            return None

    if not isinstance(parsed, datetime):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)

    return convert_utc_to_system_timezone(parsed).replace(tzinfo=None)


def _trim(value, fieldname: str) -> str | None:
    """Bulk insert skips document validation, so column limits are ours to keep.

    The limit is read from the field itself, not repeated here, so it can't
    drift out of sync with the DocType.
    """
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    length = frappe.get_meta("ACS Email Event").get_field(fieldname).length
    return value[:length]
