# Copyright (c) 2026, rtCamp and contributors
# For license information, please see license.txt

from frappe.model.document import Document


def normalise_status(acs_status: str | None) -> str:
    """Lowercases and trims ACS's raw ``data.status`` for a consistent event_type.

    Stored as ACS sends it, not remapped, so a status Azure adds later shows
    up under its own name instead of needing a matching entry here first.
    """
    return (acs_status or "").strip().lower() or "unknown"


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
