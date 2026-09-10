# Copyright (c) 2026, rtCamp and Contributors
# See license.txt

"""Validation on ACS Account.

Most of these call validate() directly rather than inserting, to prove each
rule fires for its own reason. An insert would also raise LinkValidationError
for a missing Email Account, which would let a broken rule pass unnoticed.
"""

import frappe
from frappe.tests import IntegrationTestCase

# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]

RESOURCE_ID = (
    "/subscriptions/00000000-0000-0000-0000-000000000000/resourcegroups/email/providers/"
    "microsoft.communication/communicationservices/test-cs"
)


class IntegrationTestACSAccount(IntegrationTestCase):
    """Integration tests for ACSAccount."""

    def _account(self, **kwargs):
        values = {
            "doctype": "ACS Account",
            "enable_webhook": 0,
            "acs_resource_id": RESOURCE_ID,
            "webhook_secret": "s3cret",
        }
        values.update(kwargs)
        return frappe.get_doc(values)

    def test_a_configured_account_validates(self):
        self._account().validate()

    def test_the_resource_id_is_stripped(self):
        account = self._account(acs_resource_id=f"  {RESOURCE_ID}  ")
        account.validate()
        self.assertEqual(account.acs_resource_id, RESOURCE_ID)

    def test_the_same_email_account_cannot_be_listed_twice(self):
        account = self._account()
        account.append("email_accounts", {"email_account": "Notifications"})
        account.append("email_accounts", {"email_account": "Notifications"})
        with self.assertRaises(frappe.ValidationError) as caught:
            account.validate()
        self.assertIn("more than once", str(caught.exception))

    def test_the_secret_is_mandatory(self):
        """Enforced by reqd on the field, so this one needs a real insert to fire."""
        account = self._account(
            webhook_secret=None,
            acs_resource_id=f"{RESOURCE_ID}-no-secret",
            email_accounts=[{"email_account": "_Test Email Account 1"}],
        )
        self.assertRaises(frappe.MandatoryError, account.insert)
