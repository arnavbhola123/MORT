"""
Sample User Service - Privacy-sensitive code for testing ACH
This module handles user data operations with privacy controls.
"""

import hashlib
import logging
from typing import Dict, Optional, List


class UserService:
    """Service for managing user data with privacy controls"""
    
    def __init__(self):
        self.users: Dict[str, Dict] = {}
        self.consent_records: Dict[str, bool] = {}
        self.logger = logging.getLogger(__name__)
    
    def create_user(self, user_id: str, email: str, phone: str, ssn: str) -> bool:
        """Create a new user with sensitive data"""
        if not user_id or not email:
            return False
        
        # Check if user consented to data collection
        if not self.has_user_consent(user_id):
            self.logger.warning(f"Cannot create user {user_id} without consent")
            return False
        
        # Hash sensitive data before storing
        hashed_ssn = self._hash_sensitive_data(ssn) if ssn else None
        
        self.users[user_id] = {
            'email': email,
            'phone': phone,
            'ssn_hash': hashed_ssn,
            'created': True
        }
        
        # Log user creation (but not sensitive data)
        self.logger.info(f"User created: {user_id}")
        return True
    
    def get_user_data(self, user_id: str, requesting_user: str) -> Optional[Dict]:
        """Get user data with authorization check"""
        if not self._is_authorized(requesting_user, user_id):
            self.logger.warning(f"Unauthorized access attempt by {requesting_user} for {user_id}")
            return None
        
        if user_id not in self.users:
            return None
        
        user_data = self.users[user_id].copy()
        
        # Remove sensitive data from response
        if 'ssn_hash' in user_data:
            del user_data['ssn_hash']
        
        return user_data
    
    def log_user_activity(self, user_id: str, activity: str, metadata: Dict = None) -> None:
        """Log user activity with privacy protection"""
        if not self.has_analytics_consent(user_id):
            return
        
        # Only log non-sensitive activity data
        safe_metadata = self._sanitize_metadata(metadata or {})
        self.logger.info(f"Activity: {activity} for user {user_id[:8]}... metadata: {safe_metadata}")
    
    def share_data_with_partner(self, user_id: str, partner_id: str, data_fields: List[str]) -> bool:
        """Share user data with third-party partner"""
        if not self.has_sharing_consent(user_id):
            self.logger.error(f"Cannot share data for {user_id} - no sharing consent")
            return False
        
        if not self._is_trusted_partner(partner_id):
            self.logger.error(f"Partner {partner_id} is not trusted")
            return False
        
        # Only share approved data fields
        approved_fields = self._get_approved_sharing_fields(user_id)
        safe_fields = [field for field in data_fields if field in approved_fields]
        
        if safe_fields:
            self.logger.info(f"Sharing data fields {safe_fields} with partner {partner_id}")
            return True
        
        return False
    
    def delete_user_data(self, user_id: str) -> bool:
        """Delete user data (GDPR right to be forgotten)"""
        if user_id in self.users:
            del self.users[user_id]
            if user_id in self.consent_records:
                del self.consent_records[user_id]
            
            self.logger.info(f"User data deleted: {user_id}")
            return True
        return False
    
    def export_user_data(self, user_id: str) -> Optional[Dict]:
        """Export user data (GDPR data portability)"""
        if user_id not in self.users:
            return None
        
        # Return anonymized version of user data
        user_data = self.users[user_id].copy()
        user_data['user_id'] = user_id
        
        # Remove internal fields
        user_data.pop('ssn_hash', None)
        
        return user_data
    
    def has_user_consent(self, user_id: str) -> bool:
        """Check if user has given consent for data collection"""
        return self.consent_records.get(user_id, False)
    
    def has_analytics_consent(self, user_id: str) -> bool:
        """Check if user consented to analytics tracking"""
        return self.consent_records.get(f"{user_id}_analytics", False)
    
    def has_sharing_consent(self, user_id: str) -> bool:
        """Check if user consented to data sharing"""
        return self.consent_records.get(f"{user_id}_sharing", False)
    
    def set_user_consent(self, user_id: str, consent_type: str, consented: bool) -> None:
        """Set user consent for various data operations"""
        if consent_type == "data_collection":
            self.consent_records[user_id] = consented
        elif consent_type == "analytics":
            self.consent_records[f"{user_id}_analytics"] = consented
        elif consent_type == "sharing":
            self.consent_records[f"{user_id}_sharing"] = consented
    
    def _hash_sensitive_data(self, data: str) -> str:
        """Hash sensitive data before storage"""
        return hashlib.sha256(data.encode()).hexdigest()
    
    def _is_authorized(self, requesting_user: str, target_user: str) -> bool:
        """Check if requesting user is authorized to access target user's data"""
        # Simple authorization: users can only access their own data or admin can access all
        return requesting_user == target_user or requesting_user == "admin"
    
    def _sanitize_metadata(self, metadata: Dict) -> Dict:
        """Remove sensitive fields from metadata before logging"""
        sensitive_fields = ['ssn', 'password', 'token', 'credit_card']
        return {k: v for k, v in metadata.items() 
                if not any(sensitive in k.lower() for sensitive in sensitive_fields)}
    
    def _is_trusted_partner(self, partner_id: str) -> bool:
        """Check if partner is in trusted partner list"""
        trusted_partners = ['analytics_co', 'marketing_partner', 'research_org']
        return partner_id in trusted_partners
    
    def _get_approved_sharing_fields(self, user_id: str) -> List[str]:
        """Get list of fields user approved for sharing"""
        # In real implementation, this would come from user preferences
        return ['email', 'activity_summary']  # Never share sensitive fields like SSN