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
from typing import Dict, List

# -------- Storage config --------
DEFAULT_DB_PATH = os.environ.get("USER_DB_PATH", "users.json")
_DB_LOCK = threading.Lock()

# -------- Password hashing (stdlib) --------
_PBKDF2_ITERATIONS = 200_000
_SALT_BYTES = 16

def _hash_password(password: str, salt: bytes) -> str:
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

    def public(self) -> Dict:
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at,
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
        user = User(
            id=int(data["next_id"]),
            name=name,
            email=email,
            password_hash=password_hash,
            salt_hex=salt.hex(),
            created_at=_now_iso_utc(),
        )
        data["users"].append(asdict(user))
        data["next_id"] += 1
        _save_db(db_path, data)

    return user.public()

def list_users(db_path: str = DEFAULT_DB_PATH) -> List[Dict]:
    """Return all users (public fields only), ordered by id ascending."""
    with _DB_LOCK:
        data = _load_db(db_path)
        users = [User(**u).public() for u in sorted(data["users"], key=lambda x: x["id"])]
    return users

def get_user_by_id(user_id: int, db_path: str = DEFAULT_DB_PATH) -> Dict:
    """Return a single user's public fields, or raise KeyError if not found."""
    with _DB_LOCK:
        data = _load_db(db_path)
        for u in data["users"]:
            if int(u["id"]) == int(user_id):
                return User(**u).public()
    raise KeyError("User not found.")

# Optional: quick demo when running directly
if __name__ == "__main__":
    # This demo writes to DEFAULT_DB_PATH ("users.json" by default).
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
