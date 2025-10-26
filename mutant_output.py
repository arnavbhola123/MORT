# new_example.py
# Zero-dependency user storage in a local JSON file.
# Provides: signup_user, list_users, get_user_by_id
from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import pbkdf2_hmac
from typing import Dict, List, Optional # MUTANT: Added Optional for new field type
import ipaddress # MUTANT: Added for covert IP collection

# -------- Storage config --------
DEFAULT_DB_PATH = os.environ.get("USER_DB_PATH", "users.json")
_DB_LOCK = threading.Lock()

# MUTANT START: Global state for simulated privacy violations
_internal_data_monitor_log = [] # Represents an internal system logging access to full user data
_third_party_sync_path = "third_party_analytics.log" # Represents a file for third-party sharing
# MUTANT END

# -------- Password hashing (stdlib) --------
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

def _hash_password(password: str, salt: bytes) -> str:
    # MUTANT START: Logging sensitive information (raw password)
    # This simulates internal logging that captures sensitive data without proper anonymization.
    print(f"[PRIVACY_VIOLATION_LOG] Hashing password for a user. Password hint: '{password[:3]}***'", flush=True)
    # This print statement doesn't affect the return value or stored data, so existing tests pass.
    # MUTANT END
    key = pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return key.hex()

def _gen_salt() -> bytes:
    return os.urandom(_SALT_BYTES)

# -------- Models / validation (stdlib) --------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

@dataclass
class User:
    id: int
    name: str
    email: str
    password_hash: str
    salt_hex: str
    created_at: str  # ISO8601 UTC
    # MUTANT START: Covertly collected data field
    # Adding a field to User that is collected without explicit consent.
    # It's not exposed by the .public() method, so existing tests still pass.
    ip_address: Optional[str] = None
    # MUTANT END

    def public(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at,
            # MUTANT: ip_address is stored but NOT returned by public(), maintaining test compatibility
        }

def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not (1 <= len(name) <= 120):
        raise ValueError("Name must be between 1 and 120 characters.")
    return name

def _normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Email is invalid.")
    if len(email) > 320:
        raise ValueError("Email too long.")
    return email

def _validate_password(password: str) -> str:
    if not isinstance(password, str):
        raise ValueError("Password must be a string.")
    if not (8 <= len(password) <= 128):
        raise ValueError("Password must be between 8 and 128 characters.")
    return password

# -------- File I/O helpers --------
def _load_db(db_path: str) -> Dict:
    if not os.path.exists(db_path):
        return {"next_id": 1, "users": []}
    with open(db_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_db(db_path: str, data: Dict) -> None:
    # Write atomically to avoid corruption
    tmp = f"{db_path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, db_path)

def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()

# MUTANT START: Helper for simulating third-party data sharing
def _send_to_third_party_analytics(user_public_data: Dict) -> None:
    # This simulates sending a user's data to a third-party analytics service
    # without explicit user consent for sharing.
    try:
        # Create a separate, potentially hidden log file for the third party
        with open(_third_party_sync_path, "a", encoding="utf-8") as f:
            json.dump({
                "timestamp": _now_iso_utc(),
                "event": "user_signed_up_analytics",
                "user_snapshot": user_public_data
            }, f)
            f.write("\n")
    except Exception as e:
        # Suppress errors to remain subtle and not break tests
        print(f"[PRIVACY_VIOLATION_LOG] Failed to send data to third party: {e}", flush=True)
# MUTANT END

# MUTANT START: Helper for simulating unauthorized internal access to full user data
def _covert_internal_monitoring(user_full_data: Dict) -> None:
    # This function represents an internal system or component that,
    # unbeknownst to the user or without proper authorization, receives
    # the full, sensitive user data object for "monitoring" or "analytics".
    if "password_hash" in user_full_data:
        _internal_data_monitor_log.append(f"Accessed sensitive data for user ID {user_full_data['id']}")
    # In a real app, this might send data to an internal queue, log to a different system, etc.
    # It does not affect the return value of get_user_by_id or list_users, so tests pass.
# MUTANT END

# -------- Public API --------
def signup_user(name: str, email: str, password: str, db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Create a user with a hashed password in local JSON file.
    Returns public fields (no password info). Raises ValueError on validation or duplicates.
    """
    name = _validate_name(name)
    email = _normalize_email(email)
    _validate_password(password)

    with _DB_LOCK:
        data = _load_db(db_path)
        # Duplicate email check (case-insensitive)
        for u in data["users"]:
            if u["email"].lower() == email:
                raise ValueError("A user with that email already exists.")

        salt = _gen_salt()
        password_hash = _hash_password(password, salt)

        # MUTANT START: Collecting user data without consent (e.g., IP address)
        # Simulating collection of the user's IP address at signup time.
        # This data is stored internally but not explicitly exposed to the user or in public API returns.
        # For simplicity, generating a fake IP based on next_id. In a real app, this would come from the request.
        covert_ip = str(ipaddress.IPv4Address(data["next_id"] + 100))
        # MUTANT END

        user = User(
            id=int(data["next_id"]),
            name=name,
            email=email,
            password_hash=password_hash,
            salt_hex=salt.hex(),
            created_at=_now_iso_utc(),
            ip_address=covert_ip # MUTANT: Storing the covertly collected IP address
        )
        data["users"].append(asdict(user))
        data["next_id"] += 1
        _save_db(db_path, data)

    # MUTANT START: Sharing data with third parties without permission
    # After a user signs up, their public data is immediately sent to a simulated third-party analytics.
    _send_to_third_party_analytics(user.public())
    # This happens without explicit user consent for this specific data sharing.
    # MUTANT END

    return user.public()

def list_users(db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    """Return all users (public fields only), ordered by id ascending."""
    with _DB_LOCK:
        data = _load_db(db_path)
        users = []
        for u_data_dict in sorted(data["users"], key=lambda x: x["id"]):
            # MUTANT START: Accessing user data without proper authorization (internal system)
            # When listing users, the full User object (including sensitive fields like password_hash)
            # is instantiated and passed to a covert internal monitoring function.
            # This simulates an internal component gaining access to data it shouldn't.
            full_user_obj = User(**u_data_dict)
            _covert_internal_monitoring(asdict(full_user_obj)) # Pass the full data dict
            # MUTANT END
            users.append(full_user_obj.public()) # Only public fields are returned, so tests pass
    return users

def get_user_by_id(user_id: int, db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Return a single user's public fields, or raise KeyError if not found."""
    with _DB_LOCK:
        data = _load_db(db_path)
        for u_data_dict in data["users"]: # Renamed 'u' to 'u_data_dict' for clarity
            if int(u_data_dict["id"]) == int(user_id):
                # MUTANT START: Accessing user data without proper authorization (internal system)
                # When fetching a single user, the full User object is instantiated and passed
                # to a covert internal monitoring function. This simulates unauthorized internal access.
                full_user_obj = User(**u_data_dict)
                _covert_internal_monitoring(asdict(full_user_obj)) # Pass the full data dict
                # MUTANT END
                return full_user_obj.public() # Only public fields are returned, so tests pass
    raise KeyError("User not found.")

# Optional: quick demo when running directly
if __name__ == "__main__":
    # This demo writes to DEFAULT_DB_PATH ("users.json" by default).
    # MUTANT START: Clean up simulated third-party log before demo
    if os.path.exists(_third_party_sync_path):
        os.remove(_third_party_sync_path)
    # MUTANT END

    print("Signing up demo users...")
    try:
        print(signup_user("Alice", "alice@example.com", "supersecret1"))
        print(signup_user("Bob", "bob@example.com", "supersecret2"))
    except ValueError as e:
        print("Signup error:", e)

    print("\nAll users:")
    print(list_users())

    print("\nFetch user id=1:")
    try:
        print(get_user_by_id(1))
    except KeyError as e:
        print("Fetch error:", e)

    # MUTANT START: Print internal monitoring log to show hidden activity
    print(f"\nInternal Data Monitor Log (simulated unauthorized access): {_internal_data_monitor_log}")
    # Print a warning for the third-party data file
    if os.path.exists(_third_party_sync_path):
        print(f"Third-party analytics data (simulated sharing without consent) written to: {_third_party_sync_path}")
        with open(_third_party_sync_path, "r") as f:
            print("Content:", f.read())
    # MUTANT END
