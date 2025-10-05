# test_new_example.py
# Run: python -m unittest -v
import os
import tempfile
import unittest

import new_example as app  # renamed import

class TestUserLocalStore(unittest.TestCase):
    def setUp(self):
        # Each test gets its own temp JSON file
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "users.json")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_signup_creates_user_and_returns_public_fields(self):
        user = app.signup_user("Alice", "alice@example.com", "supersecret1", db_path=self.db_path)
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
            app.signup_user("Robert", "bob@example.com", "anotherpass", db_path=self.db_path)
        self.assertIn("already exists", str(ctx.exception))

    def test_list_users_returns_all_in_order(self):
        app.signup_user("U1", "u1@example.com", "password111", db_path=self.db_path)
        app.signup_user("U2", "u2@example.com", "password222", db_path=self.db_path)

        users = app.list_users(db_path=self.db_path)
        self.assertEqual(len(users), 2)
        self.assertEqual([u["email"] for u in users], ["u1@example.com", "u2@example.com"])
        self.assertTrue(users[0]["id"] < users[1]["id"])

    def test_get_user_by_id_and_missing_raises(self):
        created = app.signup_user("Zoe", "zoe@example.com", "pw12345678", db_path=self.db_path)
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

if __name__ == "__main__":
    unittest.main(verbosity=2)
