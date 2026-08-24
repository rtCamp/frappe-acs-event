"""Ties an ACS delivery result back to the mail we sent.

Frappe puts a Message-Id header on every outgoing mail and stores the same
value on Email Queue.message_id, which is indexed. ACS reports it back as
internetMessageId, wrapped in angle brackets, so that is the matching key.
ACS's own messageId is a GUID it never shares with an SMTP sender.

A miss is normal, not a bug: the header comes back untouched for Gmail, but
Microsoft mailboxes rewrite it. Unmatched results are saved anyway, since
"mail to this address bounced" is worth knowing even without a ticket to
pin it on.

A resend deliberately reuses the original Communication's message_id so
replies keep landing on the same ticket, so two Email Queue rows can share
one Message-ID. We pick the newest row created before the event.
"""

from __future__ import annotations

import frappe
from frappe.utils import get_datetime


def clean_message_id(internet_message_id: str | None) -> str:
    """Strips the angle brackets and whitespace ACS sends around a Message-ID.

    Email Queue.message_id is stored bare, so both sides need normalising.
    """
    return (internet_message_id or "").strip().strip("<>").strip()


def build_exact_index(message_ids: set[str], target_email_accounts: list[str]) -> dict[str, list[dict]]:
    """Fetches every Email Queue row for a batch of Message-IDs in one query.

    Restricted to the account's own Email Accounts, so a Message-ID collision
    with mail sent through some other transport can't produce a false link.
    Rows are grouped by message_id, newest first.
    """
    message_ids = {m for m in message_ids if m}
    if not message_ids or not target_email_accounts:
        return {}

    rows = frappe.get_all(
        "Email Queue",
        filters={
            "message_id": ("in", list(message_ids)),
            "email_account": ("in", target_email_accounts),
        },
        fields=["name", "message_id", "creation"],
        order_by="creation desc",
        limit_page_length=0,
    )

    index: dict[str, list[dict]] = {}
    for row in rows:
        index.setdefault(row.message_id, []).append(row)
    return index


def pick_queue_row(candidates: list[dict] | None, event_timestamp=None) -> str | None:
    """Chooses which of several same-Message-ID queue rows a result belongs to.

    candidates must be newest-first. We want the newest send that had already
    happened when ACS reported (the resend case). If every row looks newer
    than the event, fall back to the oldest rather than returning nothing.
    """
    if not candidates:
        return None

    if event_timestamp:
        event_timestamp = get_datetime(event_timestamp)
        for row in candidates:
            if get_datetime(row["creation"]) <= event_timestamp:
                return row["name"]
        return candidates[-1]["name"]

    return candidates[0]["name"]
