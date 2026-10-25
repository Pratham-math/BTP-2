"""Supabase identity verification and per-request authorization."""
from dataclasses import dataclass
from uuid import UUID

import httpx
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from server.database import Course, Curriculum, Lesson, Membership, Profile


@dataclass(frozen=True)
class Actor:
    id: str
    email: str
    display_name: str
    session_id: str | None = None


class SupabaseVerifier:
    def __init__(self, settings):
        self.settings = settings
        self.jwks = jwt.PyJWKClient(settings.supabase_url + "/auth/v1/.well-known/jwks.json", cache_jwk_set=True, lifespan=300, timeout=10) if settings.supabase_url else None

    def __call__(self, token):
        if not self.settings.supabase_url:
            raise HTTPException(503, "Configure Supabase authentication on the host.")
        try:
            key = self.jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256", "ES256"],
                                audience="authenticated", issuer=self.settings.supabase_url + "/auth/v1",
                                options={"require": ["exp", "iat", "sub", "aud", "iss", "session_id"]}, leeway=15)
            user_id = str(UUID(claims["sub"]))
            session_id = str(UUID(claims["session_id"]))
            # The narrow DB function below rejects revoked sessions and deleted
            # users on every request, without an extra Auth HTTP round trip.
            metadata = claims.get("user_metadata") or {}
            if not isinstance(metadata, dict):
                metadata = {}
            return Actor(user_id, str(claims.get("email", ""))[:320], str(metadata.get("full_name", "Learner"))[:120], session_id)
        except HTTPException:
            raise
        except (httpx.RequestError, jwt.PyJWKClientConnectionError):
            raise HTTPException(503, "The authentication service is temporarily unavailable.") from None
        except (jwt.PyJWTError, httpx.HTTPStatusError, ValueError, TypeError, AttributeError, KeyError):
            raise HTTPException(401, "Your session is invalid or expired. Sign in again.", headers={"WWW-Authenticate": "Bearer"}) from None


def get_db(request: Request):
    if request.app.state.db is None:
        raise HTTPException(503, "Configure DATABASE_URL and apply platform migrations.")
    with request.app.state.db() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise


bearer = HTTPBearer(auto_error=False)


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db, scope="function")):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    actor = request.app.state.verify_token(credentials.credentials)
    request.app.state.limiter.check(actor.id, request.method not in {"GET", "HEAD", "OPTIONS"})
    if actor.session_id:
        exists = db.scalar(text("SELECT public.btp2_session_active(CAST(:sid AS uuid), CAST(:uid AS uuid))"),
                           {"sid": actor.session_id, "uid": actor.id})
        if not exists:
            raise HTTPException(401, "This sign-in session was revoked. Sign in again.")
    # Serializing this user's mutations prevents a request that started before
    # account erasure from committing new private data after cleanup.
    profile = (db.scalar(select(Profile).where(Profile.id == actor.id).with_for_update())
        if request.method not in {"GET", "HEAD", "OPTIONS"} else db.get(Profile, actor.id))
    if profile is None:
        # Only the student default is accepted from an authenticated identity.
        profile = Profile(id=actor.id, email=actor.email, display_name=actor.display_name)
        db.add(profile)
        db.flush()
    if not profile.active:
        raise HTTPException(403, "This account has been disabled.")
    return profile


def own_course(db, user, course_id):
    course = db.get(Course, course_id)
    if not course or course.owner_id != user.id:
        raise HTTPException(404, "Course not found.")
    return course


def enrolled(db, user_id, course_id):
    return db.scalar(select(Membership).where(Membership.course_id == course_id, Membership.user_id == user_id, Membership.active.is_(True))) is not None


def lesson_access(db, user, lesson_id, *, edit=False, curriculum=None):
    lesson = db.get(Lesson, lesson_id)
    if not lesson or lesson.retired:
        raise HTTPException(404, "Lesson not found.")
    if lesson.owner_id == user.id:
        return lesson
    if lesson.course_id:
        course = db.get(Course, lesson.course_id)
        if course.owner_id == user.id:
            return lesson
        if not edit and curriculum and curriculum.publication == "published" and enrolled(db, user.id, lesson.course_id):
            return lesson
    raise HTTPException(404, "Lesson not found.")


def curriculum_access(db, user, curriculum_id, *, edit=False):
    curriculum = db.scalar(select(Curriculum).where(Curriculum.id == curriculum_id).with_for_update()) if edit else db.get(Curriculum, curriculum_id)
    if not curriculum:
        raise HTTPException(404, "Lesson version not found.")
    lesson_access(db, user, curriculum.lesson_id, edit=edit, curriculum=curriculum)
    return curriculum
