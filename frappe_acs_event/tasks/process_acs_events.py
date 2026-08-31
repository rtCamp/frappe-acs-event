"""Background processor for ACS email delivery events.

The webhook answers Azure quickly and leaves the rest here. This job:

1. Retries matching for events that arrived before their Email Queue row
   was visible to the webhook's transaction.
2. Fills in the subject from the queued MIME message.
3. Deletes events older than each account's retention setting.

Runs in batches, two bulk updates per batch, and isolates one event's
failure so it doesn't block the rest. Safe to re-run after a crash.
"""

from __future__ import annotations

import email
from email.header import decode_header

import frappe
from frappe.utils import add_days, now_datetime

from frappe_acs_event.utils import matching

BATCH_SIZE = 500

# Email Queue rows hold the whole MIME message, attachments included, so
# reading 500 of them whole would be a huge read for one header line.
_MESSAGE_HEAD_CHARS = 32_768

_SUBJECT_CHUNK_SIZE = 50


def execute() -> None:
    """Entry point called by the scheduler every 5 minutes."""

    pending_events = frappe.db.get_all(
        "ACS Email Event",
        fields=[
            "name",
            "event_id",
            "message_id",
            "email_queue",
            "event_timestamp",
            "acs_account",
        ],
        filters={"processing_status": "Pending"},
        order_by="creation asc",
        limit=BATCH_SIZE,
    )

    if not pending_events:
        _cleanup_old_events()
        return

    unmatched = [e for e in pending_events if not e.email_queue and e.message_id]
    exact_indexes = _build_exact_indexes(unmatched)

    results = [_process_single_event(event, exact_indexes) for event in pending_events]

    subjects = _get_email_subjects({r["email_queue"] for r in results if r.get("email_queue")})

    processed_updates: dict = {}
    failed_updates: dict = {}

    for result in results:
        name = result.pop("name")
        if result.pop("has_error"):
            failed_updates[name] = result
        else:
            result["email_subject"] = subjects.get(result.get("email_queue"))
            processed_updates[name] = result

    if processed_updates:
        frappe.db.bulk_update("ACS Email Event", processed_updates)
    if failed_updates:
        frappe.db.bulk_update("ACS Email Event", failed_updates)

    _cleanup_old_events()


def _build_exact_indexes(unmatched: list) -> dict[str, dict]:
    """One bulk Email Queue lookup per account, reused across its events."""
    by_account: dict[str, set[str]] = {}
    for event in unmatched:
        if event.acs_account:
            by_account.setdefault(event.acs_account, set()).add(event.message_id)

    indexes = {}
    for account, message_ids in by_account.items():
        try:
            target_email_accounts = frappe.get_cached_doc("ACS Account", account).get_target_email_accounts()
        except frappe.DoesNotExistError:
            continue
        indexes[account] = matching.build_exact_index(message_ids, target_email_accounts)

    return indexes


def _process_single_event(event: dict, exact_indexes: dict[str, dict]) -> dict:
    """Matches if still needed. The subject is filled in afterwards, in bulk."""
    try:
        email_queue = event.get("email_queue")

        if not email_queue:
            index = exact_indexes.get(event.get("acs_account")) or {}
            email_queue = matching.pick_queue_row(index.get(event.get("message_id")), event.get("event_timestamp"))

        return {
            "name": event.get("name"),
            "processing_status": "Processed",
            "email_queue": email_queue,
            "has_error": False,
        }
    except Exception:
        return {
            "name": event.get("name"),
            "processing_status": "Failed",
            "error_log": frappe.get_traceback(),
            "has_error": True,
        }


def _get_email_subjects(email_queues: set[str]) -> dict[str, str]:
    """Subject line per Email Queue row, read in bounded chunks."""
    email_queues = {name for name in email_queues if name}
    if not email_queues:
        return {}

    names = sorted(email_queues)
    subjects: dict[str, str] = {}

    for start in range(0, len(names), _SUBJECT_CHUNK_SIZE):
        chunk = names[start : start + _SUBJECT_CHUNK_SIZE]
        rows = frappe.db.sql(
            """
            select `name`, left(`message`, %s) as message_head
            from `tabEmail Queue`
            where `name` in %s
            """,
            (_MESSAGE_HEAD_CHARS, tuple(chunk)),
            as_dict=True,
        )
        for row in rows:
            subject = _decode_subject(row.message_head)
            if subject:
                subjects[row.name] = subject

    return subjects


def _decode_subject(raw_message: str | None) -> str | None:
    """Decodes an RFC 2047 Subject header out of a raw message."""
    if not raw_message:
        return None

    message = email.message_from_string(raw_message)
    raw_subject = message.get("Subject") or ""

    fragments = []
    for fragment, charset in decode_header(raw_subject):
        if isinstance(fragment, bytes):
            charset = charset or "utf-8"
            try:
                fragment = fragment.decode(charset, errors="replace")
            except LookupError:
                fragment = fragment.decode("utf-8", errors="replace")
        fragments.append(fragment)

    subject = "".join(fragments).strip()
    if not subject:
        return None

    max_length = frappe.get_meta("ACS Email Event").get_field("email_subject").length
    return subject[:max_length]


def _cleanup_old_events() -> None:
    """Deletes events older than each account's retention setting.

    Only Processed and Failed events are deleted. Pending events are left
    alone even past retention, since they're still awaiting a match.
    """
    accounts = frappe.get_all(
        "ACS Account",
        filters={"event_retention_days": (">", 0)},
        fields=["name", "event_retention_days"],
    )

    for account in accounts:
        cutoff_date = add_days(now_datetime(), -int(account.event_retention_days))
        frappe.db.delete(
            "ACS Email Event",
            filters={
                "acs_account": account.name,
                "processing_status": ("in", ["Processed", "Failed"]),
                "creation": ("<", cutoff_date),
            },
        )
