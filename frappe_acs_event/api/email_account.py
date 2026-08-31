import json

import frappe
from frappe.desk.search import sanitize_searchfield
from frappe.query_builder import DocType
from frappe.utils import cint
from pypika import Order

# Frappe's Email Account "service" list has no ACS entry, so an ACS account is
# set up as a plain SMTP account and the only reliable marker is the relay host.
ACS_SMTP_HOST_FRAGMENT = "azurecomm.net"


@frappe.whitelist()
def acs_email_account_query(
    doctype: str | None = None,
    txt: str = "",
    searchfield: str = "name",
    start: int = 0,
    page_length: int = 20,
    filters: dict | None = None,
):
    """Link-field query offering only outgoing Email Accounts that relay through ACS."""

    frappe.has_permission("Email Account", ptype="create", throw=True)

    sanitize_searchfield(searchfield)

    start = cint(start)
    page_length = cint(page_length)

    if isinstance(filters, str):
        try:
            filters = json.loads(filters)
        except Exception:
            filters = None

    EmailAccount = DocType("Email Account")

    query = (
        frappe.qb.from_(EmailAccount)
        .select(EmailAccount.name)
        .where(EmailAccount.enable_outgoing == 1)
        .where(EmailAccount.smtp_server.like(f"%{ACS_SMTP_HOST_FRAGMENT}%"))
    )

    if txt:
        query = query.where(EmailAccount[searchfield].like(f"%{txt}%"))

    return query.orderby(EmailAccount.name, order=Order.asc).limit(page_length).offset(start).run()
