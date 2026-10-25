"""Read-only configured-service checks. Never print credentials or source content."""
import argparse
import json
import shutil
import re
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from server.database import make_engine
from server.platform_settings import PlatformSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-only", action="store_true")
    args = parser.parse_args()
    settings = PlatformSettings.from_env()
    result = {}
    if settings.database_url:
        engine = make_engine(settings.database_url)
        try:
            with engine.connect() as connection:
                row = connection.execute(text("SELECT current_user, (SELECT count(*) FROM public.profiles), public.btp2_session_active('00000000-0000-0000-0000-000000000000'::uuid,'00000000-0000-0000-0000-000000000000'::uuid)" )).first()
                result["database"] = {"connected": True, "application_and_session_access": True}
        except Exception as error:
            message = str(error).lower()
            category = next((code for fragment, code in [("certificate verify failed", "tls_certificate"), ("tenant or user not found", "pooler_tenant"),
                ("password authentication failed", "login_rejected"), ("failed to resolve", "dns"), ("permission denied", "role_permissions"),
                ("timeout", "network_timeout"), ("connection refused", "network_refused")] if fragment in message), "connection_failed")
            target = re.search(r"permission denied for (table|schema|column) ([a-z_]+)", message)
            result["database"] = {"connected": False, "error_type": type(error).__name__, "category": category,
                "permission_target": target.group(0) if target else None,
                "action": "Check the exact pooler host, role suffix, network and TLS certificate. Credentials are intentionally omitted."}
        finally:
            engine.dispose()
    else:
        result["database"] = {"connected": False, "action": "Set DATABASE_URL."}
    if not args.database_only:
        import httpx
        try:
            response = httpx.get(settings.supabase_url + "/auth/v1/settings", headers={"apikey": settings.supabase_public_key}, timeout=15)
            response.raise_for_status()
            result["google_oauth"] = {"enabled": response.json().get("external", {}).get("google", False)}
        except Exception as error:
            result["google_oauth"] = {"enabled": False, "error_type": type(error).__name__}
        result["configured"] = settings.checks()
        root = Path(__file__).resolve().parents[1]
        result["media_tools"] = {name: bool(shutil.which(name) or next((root / ".local" / "bin" / "ffmpeg").glob("*/bin/" + name + ".exe"), None)) for name in ("ffmpeg", "ffprobe")}
        docker = shutil.which("docker")
        result["media_tools"]["docker_cli"] = bool(docker)
        try:
            checked = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], timeout=10, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                **({"creationflags": subprocess.CREATE_NO_WINDOW} if sys.platform == "win32" else {})) if docker else None
            result["media_tools"]["docker_daemon"] = bool(checked and checked.returncode == 0)
        except (OSError, subprocess.TimeoutExpired):
            result["media_tools"]["docker_daemon"] = False
    destination = Path(__file__).resolve().parents[1] / ".run" / "platform-readiness.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["database"]["connected"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
