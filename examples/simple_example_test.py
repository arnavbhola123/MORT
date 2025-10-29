import unittest
from simple_example import UserValidator


class TestUserValidator(unittest.TestCase):
    """Test cases for UserValidator class"""

    def setUp(self):
        """Set up test fixtures"""
        self.validator = UserValidator()

    def test_validate_age_valid(self):
        """Test that valid ages are accepted"""
        self.assertTrue(self.validator.validate_age(25))
        self.assertTrue(self.validator.validate_age(18))
        self.assertTrue(self.validator.validate_age(120))

    def test_validate_age_too_young(self):
        """Test that ages below minimum are rejected"""
        self.assertFalse(self.validator.validate_age(17))
        self.assertFalse(self.validator.validate_age(0))

    def test_validate_age_too_old(self):
        """Test that ages above maximum are rejected"""
        self.assertFalse(self.validator.validate_age(121))
        self.assertFalse(self.validator.validate_age(150))

    def test_validate_email_valid(self):
        """Test that valid emails are accepted"""
        self.assertTrue(self.validator.validate_email("user@example.com"))
        self.assertTrue(self.validator.validate_email("test@domain.org"))

    def test_validate_email_invalid(self):
        """Test that invalid emails are rejected"""
        self.assertFalse(self.validator.validate_email(""))
        self.assertFalse(self.validator.validate_email("notanemail"))
        self.assertFalse(self.validator.validate_email("missing@domain"))
        self.assertFalse(self.validator.validate_email("@nodomain.com"))

    def test_validate_username_valid(self):
        """Test that valid usernames are accepted"""
        self.assertTrue(self.validator.validate_username("john123"))
        self.assertTrue(self.validator.validate_username("user"))

    def test_validate_username_invalid(self):
        """Test that invalid usernames are rejected"""
        self.assertFalse(self.validator.validate_username(""))
        self.assertFalse(self.validator.validate_username("ab"))
        self.assertFalse(self.validator.validate_username("a" * 21))
        self.assertFalse(self.validator.validate_username("user@123"))


if __name__ == "__main__":
    unittest.main()
