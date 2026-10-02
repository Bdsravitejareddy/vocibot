"""Accounts, sign-in sessions and the security event log."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import AuthSession, Consultation, Patient, SecurityEvent, User

ROLES = {"admin", "clinician"}
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
# scrypt cost: 16 MiB and ~50 ms per hash, deliberately slow for attackers.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
# Verified against when the username is unknown, so timing does not reveal it.
_DUMMY_HASH: str | None = None


class AuthError(Exception):
    """Sign-in or account operation refused; the message is safe to show."""


@dataclass(frozen=True)
class SignedIn:
    user: User
    token: str
    expires_at: datetime


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


# --- passwords -------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    encode = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${encode(salt)}${encode(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def check_password_policy(password: str, username: str) -> None:
    if len(password) < settings.password_min_length:
        raise AuthError(f"Password must be at least {settings.password_min_length} characters.")
    if password.lower() == username.lower():
        raise AuthError("Password must not be the same as the username.")


def normalise_username(username: str) -> str:
    value = username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(value):
        raise AuthError("Username must be 3-64 characters: letters, digits, dot, dash or underscore.")
    return value


# --- security log ----------------------------------------------------------

def log_event(session: Session, event: str, *, actor: User | None = None, subject: User | None = None, username: str | None = None, ip: str | None = None, **detail: object) -> None:
    session.add(SecurityEvent(event=event, actor_user_id=actor.id if actor else None, subject_user_id=subject.id if subject else None, username=username or (subject.username if subject else actor.username if actor else None), ip_address=ip, detail=detail))


# --- accounts --------------------------------------------------------------

def setup_required(session: Session) -> bool:
    return session.scalar(select(func.count()).select_from(User)) == 0


def create_user(session: Session, *, username: str, display_name: str, password: str, role: str = "clinician", must_change_password: bool = False, actor: User | None = None, ip: str | None = None) -> User:
    name = normalise_username(username)
    if role not in ROLES:
        raise AuthError(f"Role must be one of: {', '.join(sorted(ROLES))}.")
    if not display_name.strip():
        raise AuthError("Display name is required.")
    check_password_policy(password, name)
    if session.scalar(select(User).where(User.username == name)) is not None:
        raise AuthError("That username is already taken.")
    user = User(username=name, display_name=display_name.strip(), password_hash=hash_password(password), role=role, must_change_password=must_change_password)
    session.add(user)
    session.flush()
    log_event(session, "user_created", actor=actor, subject=user, ip=ip, role=role)
    return user


def bootstrap_admin(session: Session, *, username: str, display_name: str, password: str, ip: str | None = None) -> User:
    """Create the first administrator; refused once any account exists.

    Patients and consultations recorded before accounts existed are given
    to this administrator so no clinical data is left unowned.
    """

    if not setup_required(session):
        raise AuthError("Setup has already been completed.")
    admin = create_user(session, username=username, display_name=display_name, password=password, role="admin", ip=ip)
    for model in (Patient, Consultation):
        session.execute(update(model).where(model.owner_id.is_(None)).values(owner_id=admin.id))
    log_event(session, "setup_completed", actor=admin, ip=ip)
    session.commit()
    return admin


def set_password(session: Session, user: User, password: str, *, must_change: bool = False) -> None:
    check_password_policy(password, user.username)
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    user.must_change_password = must_change
    user.failed_login_count = 0
    user.locked_until = None
    revoke_user_sessions(session, user)


# --- sign-in ---------------------------------------------------------------

def authenticate(session: Session, username: str, password: str, *, ip: str | None = None, user_agent: str | None = None) -> SignedIn:
    """Check credentials and open a session; one generic message for every failure."""

    global _DUMMY_HASH
    failure = AuthError("Incorrect username or password.")
    name = username.strip().lower()
    user = session.scalar(select(User).where(User.username == name))
    if user is None:
        _DUMMY_HASH = _DUMMY_HASH or hash_password(secrets.token_hex(8))
        verify_password(password, _DUMMY_HASH)
        log_event(session, "login_failed", username=name[:64], ip=ip, reason="unknown_user")
        session.commit()
        raise failure
    now = utcnow()
    locked_until = _aware(user.locked_until)
    if locked_until and locked_until > now:
        log_event(session, "login_blocked", subject=user, ip=ip, reason="locked")
        session.commit()
        minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
        raise AuthError(f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}.")
    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_failures:
            user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
            log_event(session, "account_locked", subject=user, ip=ip, minutes=settings.login_lockout_minutes)
        log_event(session, "login_failed", subject=user, ip=ip, reason="bad_password")
        session.commit()
        raise failure
    if not user.is_active:
        log_event(session, "login_blocked", subject=user, ip=ip, reason="deactivated")
        session.commit()
        raise failure
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(hours=settings.session_absolute_hours)
    session.add(AuthSession(token_hash=_token_hash(token), user_id=user.id, created_at=now, last_seen_at=now, expires_at=expires_at, ip_address=ip, user_agent=(user_agent or "")[:255]))
    log_event(session, "login_succeeded", subject=user, ip=ip)
    session.commit()
    return SignedIn(user=user, token=token, expires_at=expires_at)


def resolve_session(session: Session, token: str | None) -> User | None:
    """The signed-in user for a cookie token, enforcing idle and absolute expiry."""

    if not token:
        return None
    record = session.get(AuthSession, _token_hash(token))
    if record is None:
        return None
    now = utcnow()
    idle_expired = _aware(record.last_seen_at) + timedelta(minutes=settings.session_idle_minutes) < now
    if idle_expired or _aware(record.expires_at) < now or not record.user.is_active:
        session.delete(record)
        session.commit()
        return None
    # Avoid a database write on every request; a minute's precision is enough.
    if now - _aware(record.last_seen_at) > timedelta(minutes=1):
        record.last_seen_at = now
        session.commit()
    return record.user


def sign_out(session: Session, token: str | None, *, ip: str | None = None) -> None:
    if not token:
        return
    record = session.get(AuthSession, _token_hash(token))
    if record is not None:
        log_event(session, "logout", subject=record.user, ip=ip)
        session.delete(record)
        session.commit()


def revoke_user_sessions(session: Session, user: User) -> None:
    for record in session.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        session.delete(record)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
