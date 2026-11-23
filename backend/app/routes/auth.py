"""Authentication routes for SFT Billing."""

from __future__ import annotations

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.session import get_db_session
from app.services.auth_service import (
    _decode_jwt,
    _now_utc,
    admin_exists,
    change_password,
    create_reset_token,
    create_session,
    create_user,
    get_admin_user,
    get_user_by_username,
    invalidate_all_user_sessions,
    invalidate_session,
    validate_reset_token,
    validate_session,
    normalize_mobile,
    verify_credentials,
    verify_mobile,
    verify_recovery_key,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
security = HTTPBearer(auto_error=False)


# --- Schemas ---

class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)
    remember: bool = False


class LoginResponse(BaseModel):
    token: str
    user: dict
    expires_in: int  # seconds


class FirstRunSetupRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    mobile: str = Field(min_length=10, max_length=20)
    password: str = Field(min_length=8, max_length=128)


class FirstRunSetupResponse(BaseModel):
    token: str
    user: dict
    recovery_key: str
    expires_in: int


class ForgotPasswordVerifyRequest(BaseModel):
    username: str = Field(min_length=1)
    recovery_key: str = Field(min_length=1)


class ForgotPasswordMobileRequest(BaseModel):
    mobile: str = Field(min_length=1, max_length=20)


class ForgotPasswordVerifyResponse(BaseModel):
    reset_token: str
    expires_in: int


class ForgotPasswordResetRequest(BaseModel):
    reset_token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class UserInfo(BaseModel):
    id: str
    username: str
    is_admin: bool
    created_at: str
    last_login_at: str | None = None


# --- Dependencies ---
# Plain `def` (not `async def`): session validation performs blocking SQLite I/O,
# so FastAPI must run these in its threadpool instead of the event loop.

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db_session),
) -> User:
    """Extract and validate the current user from the Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The token is a session token, not a JWT - validate it against the database
    user = validate_session(db, credentials.credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    db: Session = Depends(get_db_session),
) -> User | None:
    """Get current user if authenticated, otherwise None."""
    if not credentials:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


# --- Routes ---

@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    response: Response,
    db: Session = Depends(get_db_session),
):
    """Authenticate user and create session."""
    user = verify_credentials(db, request.username, request.password)
    if not user:
        # Same error for unknown user or wrong password (security)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    session, raw_token = create_session(db, user.id, remember=request.remember)

    # Update last login
    user.last_login_at = _now_utc().isoformat(timespec="seconds")
    db.flush()

    expires_in = int((datetime.fromisoformat(session.expires_at) - _now_utc()).total_seconds())

    return LoginResponse(
        token=raw_token,
        user={
            "id": user.id,
            "username": user.username,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        },
        expires_in=expires_in,
    )


@router.post("/logout")
def logout(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db_session),
):
    """Invalidate the current session."""
    invalidate_session(db, credentials.credentials)
    return {"ok": True}


@router.get("/me", response_model=UserInfo)
def get_current_user_info(
    user: User = Depends(get_current_user),
):
    """Get current authenticated user info."""
    return UserInfo(
        id=user.id,
        username=user.username,
        is_admin=user.is_admin,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
    )


@router.post("/first-run-setup", response_model=FirstRunSetupResponse)
def first_run_setup(
    request: FirstRunSetupRequest,
    db: Session = Depends(get_db_session),
):
    """Create the first administrator account. Only works if no admin exists."""
    if admin_exists(db):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Administrator account already exists",
        )

    if normalize_mobile(request.mobile) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a valid 10-digit mobile number.",
        )

    user, recovery_key = create_user(
        db,
        username=request.username.strip(),
        password=request.password,
        is_admin=True,
        mobile=request.mobile,
    )

    session, raw_token = create_session(db, user.id, remember=True)

    expires_in = int((datetime.fromisoformat(session.expires_at) - _now_utc()).total_seconds())

    return FirstRunSetupResponse(
        token=raw_token,
        user={
            "id": user.id,
            "username": user.username,
            "is_admin": user.is_admin,
            "created_at": user.created_at,
            "last_login_at": user.last_login_at,
        },
        recovery_key=recovery_key,
        expires_in=expires_in,
    )


@router.get("/first-run-status")
def first_run_status(db: Session = Depends(get_db_session)):
    """Check if first-run setup is needed."""
    return {"needs_setup": not admin_exists(db)}


@router.post("/forgot-password/verify", response_model=ForgotPasswordVerifyResponse)
def forgot_password_verify(
    request: ForgotPasswordVerifyRequest,
    db: Session = Depends(get_db_session),
):
    """Verify recovery key and issue a password reset token."""
    user = verify_recovery_key(db, request.username, request.recovery_key)
    if not user:
        # Same error for unknown user or wrong key (security)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or recovery key",
        )

    reset_token, raw_token = create_reset_token(db, user.id)

    expires_in = int((_now_utc() + timedelta(hours=1) - _now_utc()).total_seconds())

    return ForgotPasswordVerifyResponse(
        reset_token=raw_token,
        expires_in=expires_in,
    )


@router.post("/forgot-password/verify-mobile", response_model=ForgotPasswordVerifyResponse)
def forgot_password_verify_mobile(
    request: ForgotPasswordMobileRequest,
    db: Session = Depends(get_db_session),
):
    """Match the registered mobile number and issue a password reset token."""
    user = verify_mobile(db, request.mobile)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This mobile number is not registered.",
        )
    _, raw_token = create_reset_token(db, user.id)
    return ForgotPasswordVerifyResponse(reset_token=raw_token, expires_in=3600)


@router.post("/forgot-password/reset")
def forgot_password_reset(
    request: ForgotPasswordResetRequest,
    db: Session = Depends(get_db_session),
):
    """Reset password using a reset token."""
    success = use_reset_token(db, request.reset_token, request.new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token",
        )
    return {"ok": True}


# Need to import use_reset_token
from app.services.auth_service import use_reset_token  # noqa: E402


@router.post("/change-password")
def change_password_endpoint(
    request: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """Change password for authenticated user."""
    success = change_password(db, user.id, request.current_password, request.new_password)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    return {"ok": True}