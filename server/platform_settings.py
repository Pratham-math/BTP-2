"""Host-managed platform configuration; never returned wholesale to a client."""
import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv
from server.config import PROJECT_DIR


@dataclass
class PlatformSettings:
    database_url: str = field(default="", repr=False)
    supabase_url: str = ""
    supabase_public_key: str = ""
    origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    s3_endpoint: str = ""
    s3_bucket: str = ""
    s3_access_key: str = field(default="", repr=False)
    s3_secret_key: str = field(default="", repr=False)
    runner_url: str = ""
    runner_token: str = field(default="", repr=False)
    runner_language_id: int = 0
    runner_verified: bool = False
    local_demo_python: bool = False
    # Owner's explicit choice: tunnel users' Python runs on this laptop (not sandboxed).
    tunnel_demo_python: bool = False
    text_model: str = ""
    verifier_model: str = ""
    vision_model: str = ""
    google_oauth_verified: bool = False
    topic_sources: bool = False
    document_sources: bool = False
    vision_sources: bool = False
    youtube_sources: bool = False
    speculation_enabled: bool = False
    max_jobs_per_user: int = 3
    max_queue: int = 30
    daily_model_calls: int = 200
    max_upload_bytes: int = 25 * 1024 * 1024
    profile: str = "production"

    @property
    def local(self):
        return self.profile == "local"

    @property
    def demo_runner(self):
        return self.local and self.local_demo_python

    @property
    def runner_cache_key(self):
        return f"local-demo:{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}" if self.demo_runner else self.runner_language_id

    @classmethod
    def from_env(cls):
        load_dotenv(PROJECT_DIR / ".env")
        return cls(
            database_url=os.getenv("DATABASE_URL", ""),
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_public_key=os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
            origins=tuple(x.strip() for x in os.getenv("PLATFORM_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()),
            s3_endpoint=os.getenv("S3_ENDPOINT_URL", ""), s3_bucket=os.getenv("S3_BUCKET", ""),
            s3_access_key=os.getenv("S3_ACCESS_KEY_ID", ""), s3_secret_key=os.getenv("S3_SECRET_ACCESS_KEY", ""),
            runner_url=os.getenv("JUDGE0_URL", "").rstrip("/"), runner_token=os.getenv("JUDGE0_TOKEN", ""),
            runner_language_id=int(os.getenv("JUDGE0_PYTHON_LANGUAGE_ID", "0") or "0"),
            runner_verified=os.getenv("JUDGE0_ISOLATION_VERIFIED", "false").lower() == "true",
            local_demo_python=os.getenv("PLATFORM_LOCAL_DEMO_PYTHON", "false").lower() == "true",
            tunnel_demo_python=os.getenv("PLATFORM_TUNNEL_DEMO_PYTHON", "false").lower() == "true",
            text_model=os.getenv("PLATFORM_TEXT_MODEL", ""), verifier_model=os.getenv("PLATFORM_VERIFIER_MODEL", ""),
            vision_model=os.getenv("PLATFORM_VISION_MODEL", ""),
            google_oauth_verified=os.getenv("GOOGLE_OAUTH_VERIFIED", "false").lower() == "true",
            topic_sources=os.getenv("PLATFORM_ENABLE_TOPIC_SOURCES", "false").lower() == "true",
            document_sources=os.getenv("PLATFORM_ENABLE_DOCUMENT_SOURCES", "false").lower() == "true",
            vision_sources=os.getenv("PLATFORM_ENABLE_VISION_SOURCES", "false").lower() == "true",
            youtube_sources=os.getenv("PLATFORM_ENABLE_YOUTUBE_SOURCES", "false").lower() == "true",
            speculation_enabled=os.getenv("PLATFORM_SPECULATION_ENABLED", "false").lower() == "true",
            max_jobs_per_user=int(os.getenv("MAX_JOBS_PER_USER", "3")),
            max_queue=int(os.getenv("MAX_QUEUED_JOBS", "30")),
            daily_model_calls=int(os.getenv("DAILY_MODEL_CALL_LIMIT", "200")),
            profile=os.getenv("PLATFORM_PROFILE", "production").lower(),
        )

    def checks(self):
        return {
            "database": bool(self.database_url),
            "authentication": self.local or bool(self.supabase_url and self.supabase_public_key and self.google_oauth_verified),
            "private_storage": self.local or bool(self.s3_endpoint and self.s3_bucket and self.s3_access_key and self.s3_secret_key),
            "python_runner": self.demo_runner or bool(self.runner_url and self.runner_language_id and self.runner_verified),
            "generation_models": bool(self.text_model and self.verifier_model and (
                os.getenv("PLATFORM_TEXT_PROVIDER", "gemini") == "ollama" or os.getenv("GEMINI_API_KEY", "") not in {"", "put_your_key_here"}) and (
                os.getenv("PLATFORM_SPEECH_PROVIDER", "gemini") == "piper" or (os.getenv("PLATFORM_SPEECH_MODEL") and os.getenv("GEMINI_API_KEY", "") not in {"", "put_your_key_here"}))),
        }

    @property
    def extraction_model(self):
        return self.vision_model or (self.text_model if os.getenv("PLATFORM_TEXT_PROVIDER", "gemini") == "gemini" else "")

    def source_features(self):
        storage = self.checks()["private_storage"]
        vision = bool(self.extraction_model and os.getenv("GEMINI_API_KEY", "") not in {"", "put_your_key_here"})
        if self.local:
            return {"text": True, "topic": True, "document": True, "image": vision, "youtube": vision}
        return {"text": True, "topic": self.topic_sources,
                "document": self.document_sources and storage and os.getenv("DOCUMENT_SANDBOX_VERIFIED", "false").lower() == "true",
                "image": self.vision_sources and storage and vision,
                "youtube": self.youtube_sources and vision}
