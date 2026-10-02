from datetime import datetime, timedelta, timezone
import ipaddress
import subprocess
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID

from app.certificates import ensure_certificates, local_names

BACKEND = Path(__file__).resolve().parents[1]


def test_clinic_https_certificate_is_signed_by_the_local_ca_and_covers_this_machine(tmp_path) -> None:
    paths = ensure_certificates(tmp_path)
    ca = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
    server = x509.load_pem_x509_certificate(paths.server_cert.read_bytes())

    assert server.issuer == ca.subject
    ca.public_key().verify(server.signature, server.tbs_certificate_bytes, ec.ECDSA(server.signature_hash_algorithm))  # raises if not signed by the CA
    names, addresses = local_names()
    san = server.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert set(names) <= set(san.get_values_for_type(x509.DNSName))
    assert {ipaddress.ip_address(a) for a in addresses} <= set(san.get_values_for_type(x509.IPAddress))
    assert ExtendedKeyUsageOID.SERVER_AUTH in server.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert server.not_valid_after_utc - datetime.now(timezone.utc) <= timedelta(days=398)
    assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is True


def test_certificates_are_reused_and_renewed_only_when_close_to_expiry(tmp_path) -> None:
    first = ensure_certificates(tmp_path)
    original_ca, original_server = first.ca_cert.read_bytes(), first.server_cert.read_bytes()

    ensure_certificates(tmp_path)
    assert first.server_cert.read_bytes() == original_server

    ensure_certificates(tmp_path, renew_within_days=400)  # everything counts as expiring
    assert first.server_cert.read_bytes() != original_server
    assert first.ca_cert.read_bytes() == original_ca  # devices keep trusting the same CA


def test_reset_admin_password_command_issues_a_temporary_password(tmp_path) -> None:
    import os

    env = {**os.environ, "VOCIBOT_DATA_DIR": str(tmp_path), "AI_MODE": "demo", "PYTHONPATH": str(BACKEND)}
    env.pop("DATABASE_URL", None)
    env.pop("RECORDINGS_DIR", None)
    setup = "from app.db import Base, SessionLocal, engine, migrate_sqlite_schema\nfrom app.services.auth import bootstrap_admin\nBase.metadata.create_all(bind=engine); migrate_sqlite_schema(engine)\nwith SessionLocal() as s: bootstrap_admin(s, username='chief', display_name='Chief', password='original-password')"
    prelude = f"import sys; sys.argv=['x']; from pathlib import Path; import vocibot_server as v; v.configure('one-computer', Path({str(tmp_path)!r}), offline=True)\n"
    subprocess.run([sys.executable, "-c", prelude + setup], cwd=BACKEND, env=env, check=True)

    result = subprocess.run([sys.executable, "vocibot_server.py", "reset-admin-password", "--edition", "one-computer", "--username", "Chief"], cwd=BACKEND, env=env, capture_output=True, text=True, check=True)
    temporary = result.stdout.split("Temporary password for chief: ")[1].split()[0]

    check = prelude + f"from app.db import SessionLocal\nfrom app.services.auth import authenticate\nwith SessionLocal() as s:\n    signed = authenticate(s, 'chief', {temporary!r})\n    print(signed.user.must_change_password)"
    assert subprocess.run([sys.executable, "-c", check], cwd=BACKEND, env=env, capture_output=True, text=True, check=True).stdout.strip() == "True"
