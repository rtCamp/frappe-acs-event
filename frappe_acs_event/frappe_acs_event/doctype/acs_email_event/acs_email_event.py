# Copyright (c) 2026, rtCamp and contributors
# For license information, please see license.txt

from frappe.model.document import Document

# ACS status -> our normalised event_type. Anything ACS adds later is stored as
# "unknown" rather than dropped, so a new status never loses a delivery result.
STATUS_MAP = {
    "delivered": "delivered",
    "bounced": "bounce",
    "filteredspam": "spam",
    "quarantined": "quarantined",
    "failed": "failed",
    "suppressed": "suppressed",
    "expanded": "expanded",
}


def normalise_status(acs_status: str | None) -> str:
    """Map a raw ACS ``data.status`` onto our event_type vocabulary."""
    return STATUS_MAP.get((acs_status or "").strip().lower(), "unknown")


class ACSEmailEvent(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        acs_account: DF.Link | None
        acs_message_id: DF.Data | None
        acs_status: DF.Data | None
        email_queue: DF.Link | None
        email_subject: DF.Data | None
        error_log: DF.Code | None
        event_id: DF.Data
        event_timestamp: DF.Datetime | None
        event_type: DF.Data
        internet_message_id: DF.Data | None
        message_id: DF.Data | None
        processing_status: DF.Literal["Pending", "Processed", "Failed"]
        raw_payload: DF.JSON | None
        recipient_email: DF.Data | None
        recipient_mail_server: DF.Data | None
        sender_email: DF.Data | None
        status_message: DF.Code | None
    # end: auto-generated types

    @staticmethod
    def default_list_data():
        columns = [
            {
                "label": "Name",
                "type": "Data",
                "key": "name",
                "width": "10rem",
            },
            {
                "label": "Recipient Email",
                "type": "Data",
                "key": "recipient_email",
                "width": "18rem",
            },
            {
                "label": "Event Type",
                "type": "Data",
                "key": "event_type",
                "width": "9rem",
            },
            {
                "label": "Event Timestamp",
                "type": "Datetime",
                "key": "event_timestamp",
                "width": "10rem",
            },
            {
                "label": "Subject",
                "type": "Data",
                "key": "email_subject",
                "width": "20rem",
            },
        ]

        rows = [
            "name",
            "recipient_email",
            "event_type",
            "event_timestamp",
            "email_subject",
        ]
        return {
            "columns": columns,
            "rows": rows,
        }
