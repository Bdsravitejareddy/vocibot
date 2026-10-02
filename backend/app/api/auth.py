from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..models import SecurityEvent, User
from ..services.auth import AuthError, authenticate, bootstrap_admin, create_user, log_event, resolve_session, revoke_user_sessions, set_password, setup_required, sign_out, verify_password

router = APIRouter(tags=["auth"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SetupRequest(Credentials):
    display_name: str = Field(min_length=1, max_length=120)


class NewUser(SetupRequest):
    role: str = "clinician"
    must_change_password: bool = True


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=1, max_length=256)
    must_change_password: bool = True


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def current_user(request: Request, session: Session = Depends(get_session)) -> User:
    user = resolve_session(session, request.cookies.get(settings.session_cookie_name))
    if user is None:
        raise HTTPException(status_code=401, detail="Please sign in.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


def public_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_active": user.is_active,
        "must_change_password": user.must_change_password,
        "created_at": user.created_at.isoformat(),
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "locked": bool(user.locked_until),
    }


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_absolute_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _sign_in(session: Session, request: Request, response: Response, username: str, password: str) -> dict:
    try:
        signed_in = authenticate(session, username, password, ip=client_ip(request), user_agent=request.headers.get("user-agent"))
    except AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    _set_cookie(response, signed_in.token)
    return {"user": public_user(signed_in.user)}


@router.get("/api/auth/status")
def status(request: Request, session: Session = Depends(get_session)) -> dict:
    user = resolve_session(session, request.cookies.get(settings.session_cookie_name))
    return {"setup_required": setup_required(session), "user": public_user(user) if user else None}


@router.post("/api/auth/setup")
def setup(payload: SetupRequest, request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    try:
        bootstrap_admin(session, username=payload.username, display_name=payload.display_name, password=payload.password, ip=client_ip(request))
    except AuthError as error:
        session.rollback()
        raise HTTPException(status_code=409 if "already" in str(error) else 422, detail=str(error)) from error
    return _sign_in(session, request, response, payload.username, payload.password)


@router.post("/api/auth/login")
def login(payload: Credentials, request: Request, response: Response, session: Session = Depends(get_session)) -> dict:
    return _sign_in(session, request, response, payload.username, payload.password)


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = Depends(get_session)) -> None:
    sign_out(session, request.cookies.get(settings.session_cookie_name), ip=client_ip(request))
    response.delete_cookie(settings.session_cookie_name, path="/")


@router.get("/api/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"user": public_user(user)}


@router.post("/api/auth/password", status_code=204)
def change_password(payload: PasswordChange, request: Request, response: Response, user: User = Depends(current_user), session: Session = Depends(get_session)) -> None:
    user = session.merge(user)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=403, detail="Current password is incorrect.")
    try:
        set_password(session, user, payload.new_password)
    except AuthError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    log_event(session, "password_changed", actor=user, subject=user, ip=client_ip(request))
    session.commit()
    # Changing the password signs out every browser, including this one.
    response.delete_cookie(settings.session_cookie_name, path="/")


# --- administration --------------------------------------------------------

@router.get("/api/admin/users")
def list_users(_admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> list[dict]:
    return [public_user(user) for user in session.scalars(select(User).order_by(User.username))]


@router.post("/api/admin/users", status_code=201)
def add_user(payload: NewUser, request: Request, admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> dict:
    try:
        user = create_user(session, username=payload.username, display_name=payload.display_name, password=payload.password, role=payload.role, must_change_password=payload.must_change_password, actor=admin, ip=client_ip(request))
    except AuthError as error:
        session.rollback()
        raise HTTPException(status_code=409 if "taken" in str(error) else 422, detail=str(error)) from error
    session.commit()
    return public_user(user)


@router.patch("/api/admin/users/{user_id}")
def edit_user(user_id: str, payload: UserUpdate, request: Request, admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> dict:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.id == admin.id and (payload.is_active is False or payload.role not in (None, "admin")):
        raise HTTPException(status_code=409, detail="You cannot deactivate or demote your own account.")
    changes: dict[str, object] = {}
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip()
        changes["display_name"] = user.display_name
    if payload.role is not None:
        if payload.role not in {"admin", "clinician"}:
            raise HTTPException(status_code=422, detail="Role must be admin or clinician.")
        user.role = payload.role
        changes["role"] = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
        changes["is_active"] = payload.is_active
        if not payload.is_active:
            revoke_user_sessions(session, user)
    log_event(session, "user_updated", actor=admin, subject=user, ip=client_ip(request), **changes)
    session.commit()
    return public_user(user)


@router.post("/api/admin/users/{user_id}/reset-password", status_code=204)
def reset_password(user_id: str, payload: PasswordReset, request: Request, admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> None:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        set_password(session, user, payload.new_password, must_change=payload.must_change_password)
    except AuthError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    log_event(session, "password_reset", actor=admin, subject=user, ip=client_ip(request))
    session.commit()


@router.get("/api/admin/security-events")
def security_events(limit: int = 200, _admin: User = Depends(require_admin), session: Session = Depends(get_session)) -> list[dict]:
    events = session.scalars(select(SecurityEvent).order_by(SecurityEvent.occurred_at.desc()).limit(min(max(limit, 1), 1000)))
    return [{"id": item.id, "occurred_at": item.occurred_at.isoformat(), "event": item.event, "username": item.username, "actor_user_id": item.actor_user_id, "subject_user_id": item.subject_user_id, "ip_address": item.ip_address, "detail": item.detail} for item in events]
