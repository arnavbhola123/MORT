"""
Test file for UserService - Tests privacy-sensitive functionality
"""

import unittest
import logging
from io import StringIO
from user_service import UserService


class TestUserService(unittest.TestCase):
    """Test cases for UserService privacy functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.service = UserService()
        
        # Set up logging capture
        self.log_capture = StringIO()
        handler = logging.StreamHandler(self.log_capture)
        logging.getLogger('user_service').addHandler(handler)
        logging.getLogger('user_service').setLevel(logging.INFO)
    
    def tearDown(self):
        """Clean up after tests"""
        # Clear log handlers
        logging.getLogger('user_service').handlers.clear()
    
    def test_create_user_with_consent(self):
        """Test creating user when consent is given"""
        user_id = "user123"
        
        # Give consent first
        self.service.set_user_consent(user_id, "data_collection", True)
        
        result = self.service.create_user(
            user_id=user_id,
            email="test@example.com",
            phone="555-1234",
            ssn="123-45-6789"
        )
        
        self.assertTrue(result)
        self.assertIn(user_id, self.service.users)
        self.assertEqual(self.service.users[user_id]['email'], "test@example.com")
    
    def test_create_user_without_consent(self):
        """Test that user creation fails without consent"""
        user_id = "user456"
        
        # Don't give consent
        result = self.service.create_user(
            user_id=user_id,
            email="test@example.com",
            phone="555-1234",
            ssn="123-45-6789"
        )
        
        self.assertFalse(result)
        self.assertNotIn(user_id, self.service.users)
    
    def test_get_user_data_authorized(self):
        """Test getting user data with proper authorization"""
        user_id = "user789"
        
        # Set up user
        self.service.set_user_consent(user_id, "data_collection", True)
        self.service.create_user(user_id, "test@example.com", "555-1234", "123-45-6789")
        
        # User can access their own data
        data = self.service.get_user_data(user_id, requesting_user=user_id)
        
        self.assertIsNotNone(data)
        self.assertEqual(data['email'], "test@example.com")
        self.assertNotIn('ssn_hash', data)  # Sensitive data should be removed
    
    def test_get_user_data_unauthorized(self):
        """Test that unauthorized access is denied"""
        user_id = "user111"
        other_user = "user222"
        
        # Set up user
        self.service.set_user_consent(user_id, "data_collection", True)
        self.service.create_user(user_id, "test@example.com", "555-1234", "123-45-6789")
        
        # Other user tries to access data
        data = self.service.get_user_data(user_id, requesting_user=other_user)
        
        self.assertIsNone(data)
    
    def test_log_activity_with_analytics_consent(self):
        """Test activity logging when user consented to analytics"""
        user_id = "user333"
        
        # Give analytics consent
        self.service.set_user_consent(user_id, "analytics", True)
        
        self.service.log_user_activity(
            user_id=user_id,
            activity="page_view",
            metadata={"page": "/dashboard", "time_spent": 120}
        )
        
        log_output = self.log_capture.getvalue()
        self.assertIn("Activity: page_view", log_output)
        self.assertIn("user333", log_output)
    
    def test_log_activity_without_analytics_consent(self):
        """Test that activity is not logged without analytics consent"""
        user_id = "user444"
        
        # Don't give analytics consent
        self.service.log_user_activity(
            user_id=user_id,
            activity="page_view",
            metadata={"page": "/dashboard"}
        )
        
        log_output = self.log_capture.getvalue()
        self.assertEqual(log_output.strip(), "")  # No logging should occur
    
    def test_share_data_with_consent(self):
        """Test data sharing when user has given sharing consent"""
        user_id = "user555"
        
        # Give sharing consent
        self.service.set_user_consent(user_id, "sharing", True)
        
        result = self.service.share_data_with_partner(
            user_id=user_id,
            partner_id="analytics_co",
            data_fields=["email", "activity_summary"]
        )
        
        self.assertTrue(result)
    
    def test_share_data_without_consent(self):
        """Test that data sharing fails without consent"""
        user_id = "user666"
        
        # Don't give sharing consent
        result = self.service.share_data_with_partner(
            user_id=user_id,
            partner_id="analytics_co",
            data_fields=["email"]
        )
        
        self.assertFalse(result)
    
    def test_share_data_untrusted_partner(self):
        """Test that data is not shared with untrusted partners"""
        user_id = "user777"
        
        # Give sharing consent
        self.service.set_user_consent(user_id, "sharing", True)
        
        result = self.service.share_data_with_partner(
            user_id=user_id,
            partner_id="malicious_company",  # Not in trusted list
            data_fields=["email"]
        )
        
        self.assertFalse(result)
    
    def test_delete_user_data(self):
        """Test user data deletion (GDPR right to be forgotten)"""
        user_id = "user888"
        
        # Set up user
        self.service.set_user_consent(user_id, "data_collection", True)
        self.service.create_user(user_id, "test@example.com", "555-1234", "123-45-6789")
        
        # Delete user data
        result = self.service.delete_user_data(user_id)
        
        self.assertTrue(result)
        self.assertNotIn(user_id, self.service.users)
        self.assertNotIn(user_id, self.service.consent_records)
    
    def test_export_user_data(self):
        """Test user data export (GDPR data portability)"""
        user_id = "user999"
        
        # Set up user
        self.service.set_user_consent(user_id, "data_collection", True)
        self.service.create_user(user_id, "test@example.com", "555-1234", "123-45-6789")
        
        # Export user data
        exported_data = self.service.export_user_data(user_id)
        
        self.assertIsNotNone(exported_data)
        self.assertEqual(exported_data['email'], "test@example.com")
        self.assertNotIn('ssn_hash', exported_data)  # Sensitive data excluded
    
    def test_metadata_sanitization(self):
        """Test that sensitive metadata is sanitized from logs"""
        user_id = "user_meta"
        
        # Give analytics consent
        self.service.set_user_consent(user_id, "analytics", True)
        
        # Try to log with sensitive metadata
        sensitive_metadata = {
            "page": "/profile",
            "user_ssn": "123-45-6789",  # Should be filtered out
            "credit_card": "4111111111111111",  # Should be filtered out
            "session_duration": 300  # Should be kept
        }
        
        self.service.log_user_activity(user_id, "profile_view", sensitive_metadata)
        
        log_output = self.log_capture.getvalue()
        self.assertNotIn("123-45-6789", log_output)
        self.assertNotIn("4111111111111111", log_output)
        self.assertIn("session_duration", log_output)


if __name__ == '__main__':
    # Run the tests
    unittest.main()