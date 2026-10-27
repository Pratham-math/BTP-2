"""Local-profile accounts and signed object downloads. Mounted only when local."""
import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.auth import get_db
from server.database import LocalCredential, Profile, new_id
from server.local_services import check_password, hash_password, issue_token

router = APIRouter(prefix="/api/local")
DB = Annotated[Session, Depends(get_db, scope="function")]


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    login: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=200)


class Register(Login):
    name: str = Field(min_length=1, max_length=120)


def session(profile):
    return {"token": issue_token(profile.id, profile.email, profile.display_name), "user": {"id": profile.id}}


@router.post("/register", status_code=201)
def register(body: Register, db: DB):
    login = body.login.lower()
    if db.scalar(select(LocalCredential).where(LocalCredential.login == login)):
        raise HTTPException(409, "An account with this login already exists. Sign in instead.")
    # The first local account administers this installation; later ones are students.
    first = not db.scalar(select(func.count()).select_from(Profile))
    profile = Profile(id=new_id(), email=login, display_name=body.name, privilege="administrator" if first else "student")
    db.add(profile)
    db.flush()
    db.add(LocalCredential(profile_id=profile.id, login=login, password_hash=hash_password(body.password)))
    return session(profile)


@router.post("/login")
def login(body: Login, db: DB):
    credential = db.scalar(select(LocalCredential).where(LocalCredential.login == body.login.lower()))
    if not credential or not check_password(body.password, credential.password_hash):
        raise HTTPException(401, "Login or password is incorrect.")
    profile = db.get(Profile, credential.profile_id)
    if not profile.active:
        raise HTTPException(403, "This account has been disabled.")
    return session(profile)


@router.get("/objects/{key:path}")
def signed_object(key: str, expires: int, signature: str, request: Request):
    objects = request.app.state.objects
    if expires < time.time() or not hmac.compare_digest(signature, objects.signature(key, expires)):
        raise HTTPException(403, "This media link expired. Reload to renew it.")
    try:
        path = objects.path(key)
    except ValueError:
        raise HTTPException(404, "Not found.") from None
    if not path.is_file():
        raise HTTPException(404, "Not found.")
    # Stored types can come from an upload's client header: serve only known-safe
    # media inline; anything else downloads in a sandbox and can never run as HTML.
    stored = path.with_name(path.name + ".mime")
    mime = stored.read_text(encoding="ascii").strip() if stored.exists() else ""
    headers = {"Cache-Control": "private, max-age=300", "Content-Security-Policy": "sandbox", "X-Content-Type-Options": "nosniff"}
    if mime not in INLINE_TYPES:
        mime = "application/octet-stream"
        headers["Content-Disposition"] = "attachment"
    return FileResponse(path, media_type=mime, headers=headers)


INLINE_TYPES = {"audio/mp4", "video/mp4", "text/vtt", "image/png", "image/jpeg", "application/pdf"}
