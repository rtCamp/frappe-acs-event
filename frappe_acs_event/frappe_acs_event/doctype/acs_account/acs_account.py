# Copyright (c) 2026, rtCamp and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class ACSAccount(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        from frappe_acs_event.frappe_acs_event.doctype.acs_email_account.acs_email_account import ACSEmailAccount

        acs_resource_id: DF.Data
        email_accounts: DF.Table[ACSEmailAccount]
        enable_webhook: DF.Check
        event_retention_days: DF.Int
        webhook_secret: DF.Password
    # end: auto-generated types

    def validate(self):
        self.acs_resource_id = (self.acs_resource_id or "").strip()

        seen = set()
        for row in self.email_accounts:
            if row.email_account in seen:
                frappe.throw(_("Email Account {0} is listed more than once.").format(row.email_account))
            seen.add(row.email_account)

    def on_update(self):
        frappe.cache.delete_value(ENABLED_ACCOUNTS_CACHE_KEY)

    def on_trash(self):
        frappe.cache.delete_value(ENABLED_ACCOUNTS_CACHE_KEY)

    def get_target_email_accounts(self) -> list[str]:
        """Email Accounts whose outgoing mail this ACS resource is responsible for."""
        return [row.email_account for row in self.email_accounts if row.email_account]

    @staticmethod
    def default_list_data():
        columns = [
            {"label": "Name", "type": "Data", "key": "name", "width": "10rem"},
            {"label": "Enable ACS Webhook", "type": "Check", "key": "enable_webhook", "width": "12rem"},
            {"label": "ACS Resource ID", "type": "Data", "key": "acs_resource_id", "width": "30rem"},
        ]
        rows = ["name", "enable_webhook", "acs_resource_id"]
        return {"columns": columns, "rows": rows}


ENABLED_ACCOUNTS_CACHE_KEY = "acs_event:enabled_accounts"

# Saving an account clears this cache. The expiry only matters if a row
# changes without going through save, e.g. a direct db.set_value.
_ENABLED_ACCOUNTS_CACHE_TTL = 300


def get_enabled_accounts() -> list[dict]:
    """Enabled ACS Accounts, cached, ready for the webhook to route a call.

    Returns dicts of name and acs_resource_id (lowercased). Secrets are never
    cached, they're read per request from the account itself.
    """
    accounts = frappe.cache.get_value(ENABLED_ACCOUNTS_CACHE_KEY)
    if accounts is not None:
        return accounts

    rows = frappe.get_all(
        "ACS Account",
        filters={"enable_webhook": 1},
        fields=["name", "acs_resource_id"],
        order_by="creation asc",
    )
    accounts = [{"name": row.name, "acs_resource_id": (row.acs_resource_id or "").strip().lower()} for row in rows]

    frappe.cache.set_value(ENABLED_ACCOUNTS_CACHE_KEY, accounts, expires_in_sec=_ENABLED_ACCOUNTS_CACHE_TTL)
    return accounts
