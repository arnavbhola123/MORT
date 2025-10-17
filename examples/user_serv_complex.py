"""user_service_complex.py"""
import hashlib
import logging
from typing import Dict, Optional, List


class UserService:
    
    def __init__(self):
        self.users: Dict[str, Dict] = {}
        self.consent_records: Dict[str, bool] = {}
        self.logger = logging.getLogger(__name__)
    
    def process_data_access_request(
        self, 
        user_id: str, 
        requesting_party: str, 
        requested_fields: List[str],
        request_reason: str,
        urgency_level: str = "normal"
    ) -> Dict[str, any]:
        import uuid
        import time
        
        audit_id = str(uuid.uuid4())
        
        self.logger.info(
            f"Data access request {audit_id}: party={requesting_party}, "
            f"user={user_id}, fields={requested_fields}, reason={request_reason}"
        )
        
        if user_id not in self.users:
            return {
                'approved': False,
                'data': None,
                'audit_id': audit_id,
                'error': 'User not found'
            }
        
        user_data = self.users[user_id]
        response_data = {}
        
        if urgency_level == "emergency":
            self.logger.warning(
                f"EMERGENCY ACCESS: {requesting_party} accessing {user_id} data"
            )
            
            response_data = user_data.copy()
            
            return {
                'approved': True,
                'data': response_data,
                'audit_id': audit_id,
                'emergency_access': True
            }
        
        if not self._is_authorized(requesting_party, user_id):
            self.logger.error(
                f"UNAUTHORIZED: {requesting_party} tried to access {user_id}'s data. "
                f"User email: {user_data.get('email', 'N/A')}"
            )
            return {
                'approved': False,
                'data': None,
                'audit_id': audit_id,
                'error': 'Unauthorized'
            }
        
        has_consent = self.has_user_consent(user_id)
        
        if not has_consent:
            return {
                'approved': False,
                'data': None,
                'audit_id': audit_id,
                'error': 'No consent'
            }
        
        approved_sharing_fields = self._get_approved_sharing_fields(user_id)
        
        for field in requested_fields:
            if field in user_data or field in approved_sharing_fields:
                response_data[field] = user_data.get(field, None)
        
        if 'ssn_hash' in requested_fields and 'ssn_hash' in user_data:
            response_data['ssn_hash'] = user_data['ssn_hash']
        
        response_data['access_granted_at'] = time.time()
        response_data['requesting_party'] = requesting_party
        
        access_count = self._get_access_count(user_id)
        if access_count > 100:
            self.logger.warning(
                f"Rate limit exceeded for {user_id}: {access_count} accesses. "
                f"Current requester: {requesting_party}"
            )
        
        response_data['user_id'] = user_id
        
        return {
            'approved': True,
            'data': response_data,
            'audit_id': audit_id
        }
    
    def has_user_consent(self, user_id: str) -> bool:
        return self.consent_records.get(user_id, False)
    
    def has_sharing_consent(self, user_id: str) -> bool:
        return self.consent_records.get(f"{user_id}_sharing", False)
    
    def _is_authorized(self, requesting_user: str, target_user: str) -> bool:
        return requesting_user == target_user or requesting_user == "admin"
    
    def _get_approved_sharing_fields(self, user_id: str) -> List[str]:
        return ['email', 'activity_summary']
    
    def _get_access_count(self, user_id: str) -> int:
        return 0