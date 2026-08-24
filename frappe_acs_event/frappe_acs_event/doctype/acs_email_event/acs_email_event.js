// Copyright (c) 2026, rtCamp and contributors
// For license information, please see license.txt

frappe.ui.form.on("ACS Email Event", {
  refresh(frm) {
    frm.dashboard.clear_headline();

    if (!frm.doc.email_queue) {
      frm.dashboard.set_headline(
        __(
          "This result could not be tied to a mail we sent. It still tells you the outcome for this recipient."
        ),
        "orange"
      );
    }

    if (frm.doc.event_type === "suppressed") {
      frm.dashboard.add_comment(
        __(
          "ACS never attempted delivery — the recipient is on a block list. Resending inside the block window (24 hours, growing to 14 days) will be suppressed too."
        ),
        "red",
        true
      );
    } else if (frm.doc.event_type === "quarantined") {
      frm.dashboard.add_comment(
        __(
          "The receiving server accepted the mail and then held it as spam, bulk or phishing. The recipient will most likely never see it."
        ),
        "orange",
        true
      );
    } else if (frm.doc.event_type === "delivered") {
      frm.dashboard.add_comment(
        __(
          "The receiving mail server accepted the handover. ACS cannot see past that, so this is not proof the mail reached the inbox."
        ),
        "blue",
        true
      );
    }
  },
});
