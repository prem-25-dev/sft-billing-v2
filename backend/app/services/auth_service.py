"""Authentication service for SFT Billing.

Provides secure password hashing, session management, and password recovery.
All security-sensitive operations are centralized here.
"""

from __future__ import annotations

import os
import secrets
import hashlib
import base64
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

import bcrypt as native_bcrypt
from jose import jwt, JWTError
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.database.models import User, Session, PasswordResetToken, RecoveryAttempt
from app.database.session import get_db_session

# Configuration
SESSION_EXPIRY_DAYS = 30
RESET_TOKEN_EXPIRY_HOURS = 1
RECOVERY_KEY_LENGTH = 32  # 32 bytes = 256 bits entropy
RECOVERY_KEY_FORMAT = "XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX"  # 8 groups of 4 hex chars
MAX_LOGIN_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_MINUTES = 15
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_ATTEMPT_WINDOW_MINUTES = 60

# JWT secret - in production, this should be a strong random key stored securely
# For local desktop app, we generate a consistent secret from machine-specific data
def _get_jwt_secret() -> str:
    """Get or create a persistent JWT secret for this installation."""
    secret_path = os.path.join(os.path.dirname(__file__), "..", "..", "data", ".jwt_secret")
    secret_path = os.path.abspath(secret_path)

    if os.path.exists(secret_path):
        with open(secret_path, "r") as f:
            return f.read().strip()

    # Generate new secret
    secret = secrets.token_urlsafe(64)
    os.makedirs(os.path.dirname(secret_path), exist_ok=True)
    with open(secret_path, "w") as f:
        f.write(secret)
    os.chmod(secret_path, 0o600)
    return secret


JWT_SECRET = _get_jwt_secret()
JWT_ALGORITHM = "HS256"


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_utc() -> datetime:
    """Current UTC time as datetime."""
    return datetime.now(timezone.utc)


def _hash_password(password: str) -> str:
    """Hash a password using bcrypt with SHA-256 pre-hashing to handle long passwords."""
    # Pre-hash with SHA-256 to handle passwords longer than 72 bytes
    pre_hashed = hashlib.sha256(password.encode()).digest()
    pre_hashed_b64 = base64.b64encode(pre_hashed).decode('ascii')
    # Use bcrypt directly to avoid passlib's 72-byte check on the pre-hashed value
    import bcrypt as bcrypt_lib
    salt = bcrypt_lib.gensalt(rounds=12)
    return bcrypt_lib.hashpw(pre_hashed_b64.encode('ascii'), salt).decode('ascii')


def _verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its bcrypt hash."""
    try:
        pre_hashed = hashlib.sha256(password.encode()).digest()
        pre_hashed_b64 = base64.b64encode(pre_hashed).decode('ascii')
        import bcrypt as bcrypt_lib
        return bcrypt_lib.checkpw(pre_hashed_b64.encode('ascii'), password_hash.encode('ascii'))
    except Exception:
        return False


def _hash_token(token: str) -> str:
    """Create a SHA-256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _generate_recovery_key() -> str:
    """Generate a cryptographically secure recovery key."""
    raw = secrets.token_bytes(RECOVERY_KEY_LENGTH)
    hex_str = raw.hex().upper()
    # Format as XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
    return "-".join(hex_str[i:i+4] for i in range(0, len(hex_str), 4))


def _generate_session_token() -> str:
    """Generate a cryptographically secure session token."""
    return secrets.token_urlsafe(32)


def _generate_reset_token() -> str:
    """Generate a cryptographically secure password reset token."""
    return secrets.token_urlsafe(32)


def _create_jwt(payload: dict, expires_delta: timedelta) -> str:
    """Create a JWT token."""
    to_encode = payload.copy()
    expire = _now_utc() + expires_delta
    to_encode.update({"exp": expire, "iat": _now_utc()})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode_jwt(token: str) -> Optional[dict]:
    """Decode and validate a JWT token."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Get user by username (case-insensitive)."""
    return db.execute(
        select(User).where(User.username.ilike(username))
    ).scalar_one_or_none()


def normalize_mobile(value: str) -> Optional[str]:
    """Return a 10-digit mobile number (country code and separators ignored), or None."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) > 10 and digits.startswith(("91", "091")):
        digits = digits[-10:]
    return digits if len(digits) == 10 else None


MOBILE_RESET_KEY = "mobile-reset"
MAX_MOBILE_RESET_ATTEMPTS = 5


def verify_mobile(db: Session, mobile: str) -> Optional[User]:
    """Match a mobile number to the account holder. Rate-limited across all attempts."""
    since = (_now_utc() - timedelta(minutes=RECOVERY_ATTEMPT_WINDOW_MINUTES)).isoformat(timespec="seconds")
    recent = db.execute(
        select(RecoveryAttempt).where(
            RecoveryAttempt.username == MOBILE_RESET_KEY,
            RecoveryAttempt.created_at > since,
        )
    ).scalars().all()
    if len(recent) >= MAX_MOBILE_RESET_ATTEMPTS:
        return None

    number = normalize_mobile(mobile)
    user = None
    if number:
        user = db.execute(select(User).where(User.mobile == number)).scalars().first()
    if user is None:
        db.add(RecoveryAttempt(id=str(uuid4()), username=MOBILE_RESET_KEY, created_at=_now_iso()))
        db.commit()  # persist the failed attempt even though the request will error out
        return None

    db.execute(delete(RecoveryAttempt).where(RecoveryAttempt.username == MOBILE_RESET_KEY))
    return user


def create_user(
    db: Session,
    username: str,
    password: str,
    is_admin: bool = True,
    mobile: Optional[str] = None,
) -> tuple[User, str]:
    """Create a new user with password and recovery key.

    Returns (user, recovery_key) - recovery_key is only shown once!
    """
    recovery_key = _generate_recovery_key()

    user = User(
        id=str(uuid4()),
        username=username,
        password_hash=_hash_password(password),
        recovery_key_hash=_hash_token(recovery_key),
        mobile=normalize_mobile(mobile) if mobile else None,
        is_admin=is_admin,
        created_at=_now_iso(),
    )
    db.add(user)
    db.flush()
    return user, recovery_key


def verify_credentials(db: Session, username: str, password: str) -> Optional[User]:
    """Verify username and password. Returns user if valid, None otherwise."""
    user = get_user_by_username(db, username)
    if not user:
        return None
    if not _verify_password(password, user.password_hash):
        return None
    return user


def create_session(db: Session, user_id: str, remember: bool = False) -> tuple[Session, str]:
    """Create a new session for a user. Returns (session, raw_token)."""
    raw_token = _generate_session_token()
    token_hash = _hash_token(raw_token)

    expiry_days = SESSION_EXPIRY_DAYS if remember else 1
    expires_at = _now_utc() + timedelta(days=expiry_days)

    session = Session(
        id=str(uuid4()),
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at.isoformat(timespec="seconds"),
        created_at=_now_iso(),
    )
    db.add(session)
    db.flush()
    return session, raw_token


def validate_session(db: Session, token: str) -> Optional[User]:
    """Validate a session token and return the associated user if valid."""
    token_hash = _hash_token(token)

    session = db.execute(
        select(Session).where(
            Session.token_hash == token_hash,
            Session.expires_at > _now_iso(),
        )
    ).scalar_one_or_none()

    if not session:
        return None

    # Update last used timestamp. Commit immediately: leaving this write open
    # until the request finishes holds SQLite's write lock for the whole
    # request, so the handler's own writes (separate connection) would block
    # on it and fail with "database is locked".
    session.last_used_at = _now_iso()
    db.commit()

    user = db.get(User, session.user_id)
    return user


def invalidate_session(db: Session, token: str) -> bool:
    """Invalidate a session by token."""
    token_hash = _hash_token(token)
    result = db.execute(
        delete(Session).where(Session.token_hash == token_hash)
    )
    return result.rowcount > 0


def invalidate_all_user_sessions(db: Session, user_id: str) -> int:
    """Invalidate all sessions for a user. Returns count of deleted sessions."""
    result = db.execute(
        delete(Session).where(Session.user_id == user_id)
    )
    return result.rowcount


def cleanup_expired_sessions(db: Session) -> int:
    """Remove expired sessions. Returns count of deleted sessions."""
    result = db.execute(
        delete(Session).where(Session.expires_at <= _now_iso())
    )
    return result.rowcount


def verify_recovery_key(db: Session, username: str, recovery_key: str) -> Optional[User]:
    """Verify a recovery key for a user. Returns user if valid, None otherwise.

    Uses constant-time comparison to prevent timing attacks.
    Implements rate limiting: max 3 failed attempts per 60-minute window.
    """
    # Check rate limiting first (before any user lookup to prevent enumeration)
    recent_attempts = db.execute(
        select(RecoveryAttempt).where(
            RecoveryAttempt.username == username,
            RecoveryAttempt.created_at > (_now_utc() - timedelta(minutes=RECOVERY_ATTEMPT_WINDOW_MINUTES)).isoformat(timespec="seconds")
        )
    ).scalars().all()

    if len(recent_attempts) >= MAX_RECOVERY_ATTEMPTS:
        # Rate limited - return None (same as invalid key to prevent enumeration)
        # Still hash the provided key to maintain constant time
        _hash_token(recovery_key)
        return None

    user = get_user_by_username(db, username)
    if not user or not user.recovery_key_hash:
        # Still hash the provided key to maintain constant time
        _hash_token(recovery_key)

        # Record failed attempt
        attempt = RecoveryAttempt(
            id=str(uuid4()),
            username=username,
            created_at=_now_iso(),
        )
        db.add(attempt)
        db.flush()
        return None

    provided_hash = _hash_token(recovery_key)
    # Constant-time comparison
    if not secrets.compare_digest(provided_hash, user.recovery_key_hash):
        # Record failed attempt
        attempt = RecoveryAttempt(
            id=str(uuid4()),
            username=username,
            created_at=_now_iso(),
        )
        db.add(attempt)
        db.flush()
        return None

    # Success - clear failed attempts for this user
    db.execute(
        delete(RecoveryAttempt).where(RecoveryAttempt.username == username)
    )

    return user


def create_reset_token(db: Session, user_id: str) -> tuple[PasswordResetToken, str]:
    """Create a password reset token. Returns (token_record, raw_token)."""
    raw_token = _generate_reset_token()
    token_hash = _hash_token(raw_token)

    expires_at = _now_utc() + timedelta(hours=RESET_TOKEN_EXPIRY_HOURS)

    reset_token = PasswordResetToken(
        id=str(uuid4()),
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at.isoformat(timespec="seconds"),
        created_at=_now_iso(),
    )
    db.add(reset_token)
    db.flush()
    return reset_token, raw_token


def validate_reset_token(db: Session, token: str) -> Optional[User]:
    """Validate a reset token and return the associated user if valid."""
    token_hash = _hash_token(token)

    reset_token = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.expires_at > _now_iso(),
            PasswordResetToken.used_at.is_(None),
        )
    ).scalar_one_or_none()

    if not reset_token:
        return None

    user = db.get(User, reset_token.user_id)
    return user


def use_reset_token(db: Session, token: str, new_password: str) -> bool:
    """Use a reset token to change the password. Returns True on success."""
    token_hash = _hash_token(token)

    reset_token = db.execute(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.expires_at > _now_iso(),
            PasswordResetToken.used_at.is_(None),
        )
    ).scalar_one_or_none()

    if not reset_token:
        return False

    user = db.get(User, reset_token.user_id)
    if not user:
        return False

    # Update password
    user.password_hash = _hash_password(new_password)

    # Mark token as used
    reset_token.used_at = _now_iso()

    # Invalidate all existing sessions for this user
    invalidate_all_user_sessions(db, user.id)

    db.flush()
    return True


def change_password(db: Session, user_id: str, current_password: str, new_password: str) -> bool:
    """Change password for authenticated user. Returns True on success."""
    user = db.get(User, user_id)
    if not user:
        print(f"DEBUG: User not found for id {user_id}")
        return False

    if not _verify_password(current_password, user.password_hash):
        print(f"DEBUG: Password verification failed for user {user_id}")
        return False

    user.password_hash = _hash_password(new_password)
    user.updated_at = _now_iso() if hasattr(user, 'updated_at') else None

    # Invalidate all existing sessions for this user (security: password change should log out all sessions)
    print(f"DEBUG: Invalidating sessions for user {user_id}")
    count = invalidate_all_user_sessions(db, user_id)
    print(f"DEBUG: Invalidated {count} sessions")

    db.flush()
    return True


def update_recovery_key(db: Session, user_id: str, new_recovery_key: str) -> bool:
    """Update user's recovery key. Returns True on success."""
    user = db.get(User, user_id)
    if not user:
        return False

    user.recovery_key_hash = _hash_token(new_recovery_key)
    db.flush()
    return True


def admin_exists(db: Session) -> bool:
    """Check if any admin user exists."""
    return db.execute(
        select(User.id).where(User.is_admin == True).limit(1)
    ).scalar_one_or_none() is not None


def get_admin_user(db: Session) -> Optional[User]:
    """Get the admin user (first admin)."""
    return db.execute(
        select(User).where(User.is_admin == True).limit(1)
    ).scalar_one_or_none()