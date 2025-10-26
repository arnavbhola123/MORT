# test_new_example.py
# Run: python -m unittest -v
import os
import tempfile
import unittest
import json
import io
from unittest.mock import patch
import os

import new_example as app  # renamed import


class ExtendedTestUserLocalStore(unittest.TestCase):
    def setUp(self):
        # Each test gets its own temp JSON file for the main DB
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "users.json")

        # --- Mutant-specific setup to isolate tests ---

        # 1. Patch _third_party_sync_path to point to our temp directory for consistent cleanup.
        # This global variable only exists in the mutant. If running against the original, it won't be patched.
        self._original_third_party_sync_path = None
        if hasattr(app, "_third_party_sync_path"):
            self._original_third_party_sync_path = app._third_party_sync_path
            app._third_party_sync_path = os.path.join(
                self.tmpdir.name, "third_party_analytics.log"
            )
        # Define the path where the third-party log is expected, whether patched or default.
        self.third_party_log_path = os.path.join(
            self.tmpdir.name, "third_party_analytics.log"
        )  # If patched, this is where it goes.

        # Ensure the log file is clean before each test run.
        if os.path.exists(self.third_party_log_path):
            os.remove(self.third_party_log_path)

        # 2. Clear _internal_data_monitor_log if it exists.
        # This global list only exists in the mutant version.
        # If running against the original, this block is skipped.
        if hasattr(app, "_internal_data_monitor_log"):
            app._internal_data_monitor_log.clear()

    def tearDown(self):
        self.tmpdir.cleanup()

        # --- Mutant-specific cleanup ---

        # Restore original _third_party_sync_path if it was patched.
        if self._original_third_party_sync_path is not None:
            app._third_party_sync_path = self._original_third_party_sync_path

        # _internal_data_monitor_log was cleared in setUp if it existed, no further cleanup needed.

    # --- Original tests (copied without modification) ---

    def test_signup_creates_user_and_returns_public_fields(self):
        user = app.signup_user(
            "Alice", "alice@example.com", "supersecret1", db_path=self.db_path
        )
        self.assertGreater(user["id"], 0)
        self.assertEqual(user["name"], "Alice")
        self.assertEqual(user["email"], "alice@example.com")
        self.assertIn("created_at", user)
        # Ensure no password or hash leaks
        self.assertNotIn("password_hash", user)
        self.assertNotIn("salt_hex", user)

    def test_duplicate_email_is_rejected(self):
        app.signup_user("Bob", "bob@example.com", "supersecret1", db_path=self.db_path)
        with self.assertRaises(ValueError) as ctx:
            app.signup_user(
                "Robert", "bob@example.com", "anotherpass", db_path=self.db_path
            )
        self.assertIn("already exists", str(ctx.exception))

    def test_list_users_returns_all_in_order(self):
        app.signup_user("U1", "u1@example.com", "password111", db_path=self.db_path)
        app.signup_user("U2", "u2@example.com", "password222", db_path=self.db_path)

        users = app.list_users(db_path=self.db_path)
        self.assertEqual(len(users), 2)
        self.assertEqual(
            [u["email"] for u in users], ["u1@example.com", "u2@example.com"]
        )
        self.assertTrue(users[0]["id"] < users[1]["id"])

    def test_get_user_by_id_and_missing_raises(self):
        created = app.signup_user(
            "Zoe", "zoe@example.com", "pw12345678", db_path=self.db_path
        )
        uid = created["id"]

        fetched = app.get_user_by_id(uid, db_path=self.db_path)
        self.assertEqual(fetched["email"], "zoe@example.com")

        with self.assertRaises(KeyError):
            app.get_user_by_id(9999, db_path=self.db_path)

    def test_validation_errors(self):
        with self.assertRaises(ValueError):
            app.signup_user("", "ok@example.com", "goodpass123", db_path=self.db_path)
        with self.assertRaises(ValueError):
            app.signup_user("Ok", "not-an-email", "goodpass123", db_path=self.db_path)
        with self.assertRaises(ValueError):
            app.signup_user("Ok", "ok@example.com", "short", db_path=self.db_path)

    # --- New tests designed to FAIL on the mutant, but PASS on the correct version ---

    def test_mutant_no_raw_password_logging(self):
        """Ensures raw passwords are NOT logged to stdout during hashing."""
        test_password = "MyStrongPassword123"
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            app.signup_user(
                "Logger", "logger@example.com", test_password, db_path=self.db_path
            )
            output = mock_stdout.getvalue()
            # This assertion passes if the specific logging message is NOT found (correct behavior).
            # It fails if the message IS found (mutant behavior).
            self.assertNotIn(
                f"[PRIVACY_VIOLATION_LOG] Hashing password for a user. Password hint: '{test_password[:3]}***'",
                output,
                "Raw password hint was logged to stdout.",
            )

    def test_mutant_no_covert_ip_address_storage(self):
        """Ensures an IP address field is NOT covertly stored in the database."""
        app.signup_user(
            "IP User", "ip@example.com", "securepass123", db_path=self.db_path
        )

        with open(self.db_path, "r", encoding="utf-8") as f:
            db_data = json.load(f)

        self.assertIn("users", db_data)
        self.assertEqual(len(db_data["users"]), 1)
        stored_user = db_data["users"][0]

        # This assertion passes if 'ip_address' is NOT in the stored user data (correct behavior).
        # It fails if 'ip_address' IS in the stored user data (mutant behavior).
        self.assertNotIn(
            "ip_address", stored_user, "IP address was covertly stored in user data."
        )

    def test_mutant_no_unauthorized_third_party_sharing(self):
        """Ensures user data is NOT shared with a third-party analytics log without consent."""
        # Ensure the third-party log path is correctly set for this test environment.
        # This is handled in setUp.

        app.signup_user(
            "ThirdParty", "thirdparty@example.com", "shareme123", db_path=self.db_path
        )

        # This assertion passes if the third-party log file does NOT exist (correct behavior).
        # It fails if the file DOES exist (mutant behavior).
        self.assertFalse(
            os.path.exists(self.third_party_log_path),
            f"Third-party analytics log '{self.third_party_log_path}' was created without consent.",
        )

    def test_mutant_no_unauthorized_internal_monitoring_list_users(self):
        """Ensures there is NO unauthorized internal monitoring when listing users."""
        app.signup_user("Monitor1", "m1@example.com", "pass123", db_path=self.db_path)
        app.signup_user("Monitor2", "m2@example.com", "pass456", db_path=self.db_path)

        app.list_users(db_path=self.db_path)

        # This checks if the monitoring mechanism exists AND if it was populated.
        if hasattr(app, "_internal_data_monitor_log"):
            # If the log exists, it should be empty for the correct version to pass.
            # Mutant will populate it, causing this to fail.
            self.assertEqual(
                len(app._internal_data_monitor_log),
                0,
                "Internal data monitor log was populated during list_users, indicating unauthorized access.",
            )
        else:
            # If the log mechanism doesn't even exist (original code), the test passes.
            self.assertTrue(
                True,
                "Internal data monitoring mechanism (log) does not exist (expected).",
            )

    def test_mutant_no_unauthorized_internal_monitoring_get_user_by_id(self):
        """Ensures there is NO unauthorized internal monitoring when getting a user by ID."""
        created_user = app.signup_user(
            "MonitorSingle", "ms@example.com", "singlepass", db_path=self.db_path
        )
        user_id = created_user["id"]

        app.get_user_by_id(user_id, db_path=self.db_path)

        # This checks if the monitoring mechanism exists AND if it was populated.
        if hasattr(app, "_internal_data_monitor_log"):
            # If the log exists, it should be empty for the correct version to pass.
            # Mutant will populate it, causing this to fail.
            self.assertEqual(
                len(app._internal_data_monitor_log),
                0,
                f"Internal data monitor log was populated for user ID {user_id}, indicating unauthorized access.",
            )
        else:
            # If the log mechanism doesn't even exist (original code), the test passes.
            self.assertTrue(
                True,
                "Internal data monitoring mechanism (log) does not exist (expected).",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
