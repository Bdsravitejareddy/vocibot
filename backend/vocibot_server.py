"""VociBot Enterprise server.

    vocibot-server serve      [--edition clinic-server|one-computer] [--data-dir DIR] [--host H] [--port P] [--no-https]
    vocibot-server provision  [--edition ...] [--data-dir DIR]      download speech models and the note model
    vocibot-server reset-admin-password --username NAME [--edition ...] [--data-dir DIR]

Both editions are the same program with different defaults:
  clinic-server  one PC serves every doctor's browser over HTTPS on the clinic network
  one-computer   a single shared PC; listens on this computer only
"""

from __future__ import annotations

import argparse
import multiprocessing
import os
from pathlib import Path
import secrets
import sys

EDITIONS = {
    "clinic-server": {"host": "0.0.0.0", "port": 8443, "https": True, "max_live_sessions": None},
    "one-computer": {"host": "127.0.0.1", "port": 8765, "https": False, "max_live_sessions": "1"},
}


def bundle_dir() -> Path:
    """Where bundled resources live: the PyInstaller folder, or the repository."""

    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def default_data_dir(edition: str) -> Path:
    if os.name == "nt":
        if edition == "clinic-server":
            return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "VociBot" / "clinic-server"
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "VociBot"
    return Path.home() / ".vocibot" / edition


def load_env_file(path: Path) -> None:
    """KEY=VALUE lines; real environment variables win."""

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def configure(edition: str, data_dir: Path, *, offline: bool) -> None:
    """Point every setting at the data folder before the app is imported."""

    data_dir.mkdir(parents=True, exist_ok=True)
    profile = data_dir / "vocibot.env"
    if not profile.exists():
        bundled = bundle_dir() / "profiles" / ("windows-16gb.env" if os.name == "nt" else "mac-apple-silicon.env")
        if bundled.is_file():
            profile.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
    if profile.exists():
        load_env_file(profile)
    defaults = {
        "AI_MODE": "local",
        "DATABASE_URL": f"sqlite:///{(data_dir / 'vocibot.sqlite').as_posix()}",
        "RECORDINGS_DIR": str(data_dir / "recordings"),
        "HF_HOME": str(data_dir / "models"),
        "WEB_ROOT": str(bundle_dir() / "web") if (bundle_dir() / "web" / "index.html").is_file() else str(bundle_dir() / "out"),
        "HF_HUB_DISABLE_TELEMETRY": "1",
    }
    if EDITIONS[edition]["max_live_sessions"]:
        defaults["MAX_LIVE_SESSIONS"] = EDITIONS[edition]["max_live_sessions"]
    if offline:
        defaults |= {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def serve(args: argparse.Namespace) -> None:
    edition = EDITIONS[args.edition]
    configure(args.edition, args.data_dir, offline=True)
    host = args.host or edition["host"]
    port = args.port or edition["port"]
    use_https = edition["https"] and not args.no_https
    ssl: dict[str, str] = {}
    if use_https:
        from app.certificates import ensure_certificates

        paths = ensure_certificates(args.data_dir / "certs")
        ssl = {"ssl_certfile": str(paths.server_cert), "ssl_keyfile": str(paths.server_key)}
        os.environ.setdefault("SESSION_COOKIE_SECURE", "true")
        os.environ.setdefault("CA_CERT_PATH", str(paths.ca_cert))
    import uvicorn

    scheme = "https" if use_https else "http"
    print(f"VociBot Enterprise ({args.edition}) serving {scheme}://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}  data: {args.data_dir}", flush=True)
    uvicorn.run("app.main:app", host=host, port=port, workers=1, log_level="info", proxy_headers=False, **ssl)


def provision(args: argparse.Namespace) -> None:
    configure(args.edition, args.data_dir, offline=False)
    from faster_whisper.utils import download_model
    import httpx

    from app.config import Settings

    settings = Settings()
    for model in dict.fromkeys(name for name in (settings.whisper_model, settings.final_whisper_model) if name):
        print(f"Downloading speech model {model} ...", flush=True)
        print(f"  ready: {download_model(model)}", flush=True)
    print(f"Pulling note model {settings.ollama_model} through Ollama ({settings.ollama_base_url}) ...", flush=True)
    try:
        with httpx.stream("POST", f"{settings.ollama_base_url}/api/pull", json={"model": settings.ollama_model}, timeout=None) as response:
            response.raise_for_status()
            last = ""
            for line in response.iter_lines():
                status = line.split('"status":"', 1)[-1].split('"', 1)[0] if '"status"' in line else ""
                if status and status != last:
                    print(f"  {status}", flush=True)
                    last = status
    except httpx.HTTPError as error:
        sys.exit(f"Ollama is not reachable ({error}). Install Ollama from https://ollama.com and run provision again.")
    print("Provisioning complete.", flush=True)


def reset_admin_password(args: argparse.Namespace) -> None:
    """Break-glass recovery when no administrator can sign in."""

    configure(args.edition, args.data_dir, offline=True)
    from sqlalchemy import select

    from app.db import Base, SessionLocal, engine, migrate_sqlite_schema
    from app.models import User
    from app.services.auth import log_event, set_password

    Base.metadata.create_all(bind=engine)
    migrate_sqlite_schema(engine)
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.username == args.username.strip().lower()))
        if user is None:
            sys.exit(f"No account named {args.username!r}.")
        temporary = f"reset-{secrets.token_urlsafe(9)}"
        set_password(session, user, temporary, must_change=True)
        user.is_active = True
        log_event(session, "password_reset", subject=user, via="command line")
        session.commit()
    print(f"Temporary password for {user.username}: {temporary}\nThey must choose a new password at their next sign-in.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="vocibot-server", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command")
    for name in ("serve", "provision", "reset-admin-password"):
        command = commands.add_parser(name)
        command.add_argument("--edition", choices=sorted(EDITIONS), default=os.environ.get("VOCIBOT_EDITION", "clinic-server"))
        command.add_argument("--data-dir", type=Path)
        if name == "serve":
            command.add_argument("--host")
            command.add_argument("--port", type=int)
            command.add_argument("--no-https", action="store_true", help="clinic-server only: serve plain HTTP (testing)")
        if name == "reset-admin-password":
            command.add_argument("--username", required=True)
    args = parser.parse_args(argv or sys.argv[1:] or ["serve"])
    if args.data_dir is None:
        args.data_dir = Path(os.environ["VOCIBOT_DATA_DIR"]) if os.environ.get("VOCIBOT_DATA_DIR") else default_data_dir(args.edition)
    {"serve": serve, "provision": provision, "reset-admin-password": reset_admin_password}[args.command](args)


if __name__ == "__main__":
    # Model libraries start multiprocessing helpers; in the frozen app a helper
    # re-executes this entry point and must not start a second server.
    multiprocessing.freeze_support()
    main()
