// Copyright (c) 2026, rtCamp and contributors
// For license information, please see license.txt

frappe.ui.form.on("ACS Account", {
  setup(frm) {
    frm.set_query("email_account", "email_accounts", function () {
      return {
        query: "frappe_acs_event.api.email_account.acs_email_account_query",
      };
    });
  },

  refresh(frm) {
    if (frm.is_new()) {
      return;
    }

    const url = `${frappe.urllib.get_base_url()}/api/method/frappe_acs_event.api.acs_webhook.handle?token=&lt;your-webhook-secret&gt;`;

    frm.dashboard.clear_comment();
    frm.dashboard.add_comment(
      __(
        "Register this URL in the Azure Event Grid subscription, using the Event Grid schema (not CloudEvents): {0}",
        [`<b>${url}</b>`]
      ),
      "blue",
      true
    );
  },
});
