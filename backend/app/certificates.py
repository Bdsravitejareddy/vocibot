"""A clinic-local certificate authority and server certificate for HTTPS.

Browsers only allow microphone access over HTTPS on a network, so the
clinic server needs a certificate. Without a public domain, VociBot creates
its own small certificate authority (CA) once; each doctor's device installs
the CA certificate (served at /ca.crt) and then trusts the server. The server
certificate is renewed automatically before it expires.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import socket


@dataclass(frozen=True)
class CertificatePaths:
    ca_cert: Path
    server_cert: Path
    server_key: Path


def local_names() -> tuple[list[str], list[str]]:
    """DNS names and IP addresses this machine is reached by on the clinic network."""

    hostname = socket.gethostname()
    names = sorted({hostname, hostname.split(".")[0], f"{hostname.split('.')[0]}.local", "localhost"})
    addresses = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            addresses.add(info[4][0])
    except socket.gaierror:
        pass
    try:
        # The address used to reach other machines (no packet is sent).
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return names, sorted(addresses)


def ensure_certificates(directory: Path, *, renew_within_days: int = 30) -> CertificatePaths:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    directory.mkdir(parents=True, exist_ok=True)
    paths = CertificatePaths(directory / "vocibot-ca.crt", directory / "server.crt", directory / "server.key")
    ca_key_path = directory / "vocibot-ca.key"
    now = datetime.now(timezone.utc)

    if paths.ca_cert.is_file() and ca_key_path.is_file():
        ca_key = serialization.load_pem_private_key(ca_key_path.read_bytes(), password=None)
        ca_cert = x509.load_pem_x509_certificate(paths.ca_cert.read_bytes())
    else:
        ca_key = ec.generate_private_key(ec.SECP256R1())
        ca_name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VociBot clinic"), x509.NameAttribute(NameOID.COMMON_NAME, f"VociBot local CA ({socket.gethostname()})")])
        ca_cert = (
            x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True, content_commitment=False, key_encipherment=False, data_encipherment=False, key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
            .sign(ca_key, hashes.SHA256())
        )
        ca_key_path.write_bytes(ca_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        paths.ca_cert.write_bytes(ca_cert.public_bytes(serialization.Encoding.PEM))
        _restrict(ca_key_path)

    names, addresses = local_names()
    if paths.server_cert.is_file() and paths.server_key.is_file():
        current = x509.load_pem_x509_certificate(paths.server_cert.read_bytes())
        san = current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        covers = set(names) <= set(san.get_values_for_type(x509.DNSName)) and {ipaddress.ip_address(a) for a in addresses} <= set(san.get_values_for_type(x509.IPAddress))
        if covers and current.not_valid_after_utc - now > timedelta(days=renew_within_days):
            return paths

    key = ec.generate_private_key(ec.SECP256R1())
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "VociBot clinic"), x509.NameAttribute(NameOID.COMMON_NAME, names[0])]))
        .issuer_name(ca_cert.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        # 397 days: within browser limits for server certificates.
        .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=397))
        .add_extension(x509.SubjectAlternativeName([*(x509.DNSName(name) for name in names), *(x509.IPAddress(ipaddress.ip_address(address)) for address in addresses)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    paths.server_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    paths.server_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _restrict(paths.server_key)
    return paths


def _restrict(path: Path) -> None:
    try:
        path.chmod(0o600)
    except OSError:
        pass
