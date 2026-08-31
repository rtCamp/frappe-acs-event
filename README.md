# Frappe ACS Event

Receive and track Azure Communication Services email delivery events in Frappe, via Azure Event Grid.

Sending through the ACS SMTP relay is unaffected. This app adds a webhook receiver for what happens after a mail is handed to ACS: delivered, bounced, filtered as spam, quarantined, failed, or suppressed. Each result is stored and, where possible, linked back to the `Email Queue` row it came from.

## Features

- Fast endpoint: authenticates, filters, bulk-inserts as `Pending`, returns 200. Matching and cleanup run in a background job every 5 minutes.
- Redelivery safe: Event Grid delivers at least once. The event id is unique, so repeats are dropped.
- Unmatched results are kept. ACS's `internetMessageId` matches `Email Queue.message_id` reliably for Gmail, but is reported to be rewritten for Microsoft mailboxes. A miss is expected and the result is still saved.
- Account specific filtering: each `ACS Account` lists the Email Accounts it sends for. Events are routed by their Event Grid `topic`, so more than one resource can share the endpoint.
- Authenticated by default: Event Grid doesn't sign its calls, so every call is checked against the account's secret in constant time.

## The seven results

| ACS status | `event_type` | Meaning |
|---|---|---|
| `Delivered` | `delivered` | Reached the recipient's mail server. Not proof of inbox delivery. |
| `Bounced` | `bounced` | Refused for good. |
| `FilteredSpam` | `filteredspam` | Rejected as spam. |
| `Quarantined` | `quarantined` | Accepted, then held. The recipient likely never sees it. |
| `Failed` | `failed` | Catch-all. Reason is free text in `status_message`. |
| `Suppressed` | `suppressed` | Never tried. Address is on ACS's block list. |
| `Expanded` | `expanded` | A group address was expanded. Informational. |

`event_type` is ACS's own `data.status`, lowercased, not remapped to a different name. Anything ACS adds later is stored under its own lowercased name; a missing status is stored as `unknown`.

## Setup

### In Frappe

1. Go to **ACS Account** and create a record.
2. Tick **Enable ACS Webhook**.
3. Set **ACS Resource ID** to the Communication Services resource ID, as it appears in Event Grid's `topic` field (matched case-insensitively).
4. Set a **Webhook Secret** and register it with Azure as `?token=<secret>` on the webhook URL (or the `X-ACS-Webhook-Token` header).
5. Add the outgoing **Email Accounts** this resource sends for. Only accounts with an `azurecomm.net` SMTP server are offered.
6. Optionally set **Event Retention (Days)** to clean up old records.

### In Azure

1. Register the **Event Grid** resource provider, if it isn't already.
2. On the Communication Services resource, add an **Event Subscription**:
   - **Event Schema:** Event Grid Schema (required, not CloudEvents).
   - **Endpoint:** Web Hook, pointing at `https://<your-site>/api/method/frappe_acs_event.api.acs_webhook.handle?token=<secret>`
   - **Event type:** `Microsoft.Communication.EmailDeliveryReportReceived`
3. The site needs HTTPS with a certificate from a real authority. Event Grid won't call a self-signed one.
4. Ask Azure to raise the send quota if you're on a verified custom domain. The default is 30/minute, 100/hour.

Create the `ACS Account` in Frappe before adding the Azure subscription, so the validation handshake is authenticated.

## Matching a result to a mail

The match is exact: `internetMessageId`, stripped of its angle brackets, against `Email Queue.message_id`, scoped to the account's own Email Accounts, matched case-insensitively. A miss is expected for Microsoft mailboxes; the result is still saved with an empty `Email Queue` link.

Resending a mail reuses the original Communication's `message_id`, so two Email Queue rows can share one. The app picks the newest row created before the event.

## Not handled

- Open and click tracking (needs a second event type and a domain setting).
- Log Analytics (needs a workspace and a polling job).
- Managing ACS's suppression list.
- Polling ACS for a single mail's status.

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch main
bench install-app frappe_acs_event

# If ACS Account doesn't appear after install, doctypes weren't synced yet:
bench --site $SITE migrate
bench restart
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/frappe_acs_event
pre-commit install
```

### License

GNU AFFERO GENERAL PUBLIC LICENSE (v3)
