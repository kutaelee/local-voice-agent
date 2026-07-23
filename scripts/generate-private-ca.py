#!/usr/bin/env python3
"""Generate a private debug CA and one LAN server certificate.

This tool is intentionally strict:
- output must be beneath the canonical runtime TLS root;
- the deployment directory must not already exist;
- wildcard DNS names are rejected;
- the CA key is encrypted with a password supplied only through the process
  environment.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


CANONICAL_TLS_ROOT = Path("/mnt/e/Data/LocalVoiceAgent/tls")
CANONICAL_RUNTIME_ROOT = CANONICAL_TLS_ROOT.parent
DEPLOYMENT_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
DNS_LABEL_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
PRIVATE_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
PRIVATE_IPV6_NETWORK = ipaddress.ip_network("fc00::/7")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="New deployment directory beneath E:\\Data\\LocalVoiceAgent\\tls",
    )
    parser.add_argument(
        "--deployment-name",
        required=True,
        help="Lowercase identifier used in certificate subjects",
    )
    parser.add_argument("--dns-name", action="append", default=[])
    parser.add_argument("--ip-address", action="append", default=[])
    parser.add_argument(
        "--allowed-root",
        type=Path,
        default=CANONICAL_TLS_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args()


def _validated_dns_name(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if not candidate or len(candidate) > 253 or "*" in candidate:
        raise ValueError(f"Invalid DNS name: {value!r}")
    labels = candidate.split(".")
    if any(not DNS_LABEL_PATTERN.fullmatch(label) for label in labels):
        raise ValueError(f"Invalid DNS name: {value!r}")
    return candidate


def _validated_private_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(value)
    allowed = (
        address.version == 4
        and any(address in network for network in PRIVATE_IPV4_NETWORKS)
    ) or (address.version == 6 and address in PRIVATE_IPV6_NETWORK)
    if not allowed:
        raise ValueError(f"Only private IP SANs are allowed: {value!r}")
    if address.is_loopback or address.is_link_local or address.is_unspecified:
        raise ValueError(f"Loopback, link-local, and unspecified SANs are rejected: {value!r}")
    return address


def _write_new(path: Path, contents: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    os.chmod(path, mode)


def _sha256(contents: bytes) -> str:
    return hashlib.sha256(contents).hexdigest()


def main() -> int:
    args = _parse_args()
    if not DEPLOYMENT_PATTERN.fullmatch(args.deployment_name):
        raise ValueError("deployment-name must be a lowercase DNS-label-style identifier")

    configured_root = args.allowed_root.expanduser()
    if not configured_root.is_absolute():
        raise ValueError("allowed-root must be absolute")
    if not configured_root.exists():
        if configured_root != CANONICAL_TLS_ROOT:
            raise FileNotFoundError(f"Allowed root is unavailable: {configured_root}")
        canonical_runtime_root = CANONICAL_RUNTIME_ROOT.resolve(strict=True)
        if configured_root.parent.resolve(strict=True) != canonical_runtime_root:
            raise ValueError("Canonical TLS root parent did not resolve as expected")
        configured_root.mkdir(mode=0o700)
    allowed_root = configured_root.resolve(strict=True)
    output_dir = args.output_dir.expanduser()
    if not output_dir.is_absolute():
        raise ValueError("output-dir must be absolute")
    resolved_parent = output_dir.parent.resolve(strict=True)
    if resolved_parent != allowed_root:
        raise ValueError(f"output-dir must be a direct child of {allowed_root}")
    if output_dir.exists():
        raise FileExistsError(f"Refusing to overwrite existing output directory: {output_dir}")

    dns_names = sorted({_validated_dns_name(value) for value in args.dns_name})
    ip_addresses = sorted(
        {_validated_private_ip(value) for value in args.ip_address},
        key=lambda address: (address.version, address.packed),
    )
    if not dns_names and not ip_addresses:
        raise ValueError("At least one --dns-name or --ip-address is required")

    password = os.environ.get("LVA_CA_KEY_PASSWORD")
    if password is None or len(password) < 20:
        raise ValueError("LVA_CA_KEY_PASSWORD must contain at least 20 characters")
    password_bytes = password.encode("utf-8")

    output_dir.mkdir(mode=0o700)
    os.chmod(output_dir, 0o700)

    now = datetime.now(UTC)
    not_before = now - timedelta(minutes=5)
    ca_not_after = now + timedelta(days=3650)
    server_not_after = now + timedelta(days=825)

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    ca_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Voice Agent"),
            x509.NameAttribute(
                NameOID.COMMON_NAME,
                f"Local Voice Agent {args.deployment_name} Debug Root",
            ),
        ]
    )
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_subject)
        .issuer_name(ca_subject)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(ca_not_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    common_name = dns_names[0] if dns_names else str(ip_addresses[0])
    server_subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Local Voice Agent"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ]
    )
    san_entries: list[x509.GeneralName] = [
        *(x509.DNSName(name) for name in dns_names),
        *(x509.IPAddress(address) for address in ip_addresses),
    ]
    server_certificate = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_subject)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(server_not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(server_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    root_certificate_pem = ca_certificate.public_bytes(serialization.Encoding.PEM)
    root_key_pem = ca_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password_bytes),
    )
    server_certificate_pem = server_certificate.public_bytes(serialization.Encoding.PEM)
    server_key_pem = server_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    _write_new(output_dir / "root-ca.pem", root_certificate_pem, 0o644)
    _write_new(output_dir / "root-ca-key.pem", root_key_pem, 0o600)
    _write_new(output_dir / "server-cert.pem", server_certificate_pem, 0o644)
    _write_new(output_dir / "server-key.pem", server_key_pem, 0o600)

    manifest = {
        "schema_version": "1.0",
        "deployment_name": args.deployment_name,
        "generated_at": now.isoformat(),
        "generator": {
            "cryptography": __import__("cryptography").__version__,
            "python": sys.version.split()[0],
        },
        "subject_alternative_names": {
            "dns": dns_names,
            "ip": [str(address) for address in ip_addresses],
        },
        "root_ca": {
            "certificate_file": "root-ca.pem",
            "certificate_sha256": _sha256(root_certificate_pem),
            "certificate_fingerprint_sha256": ca_certificate.fingerprint(
                hashes.SHA256()
            ).hex(),
            "private_key_file": "root-ca-key.pem",
            "private_key_encrypted": True,
            "not_after": ca_not_after.isoformat(),
        },
        "server": {
            "certificate_file": "server-cert.pem",
            "certificate_sha256": _sha256(server_certificate_pem),
            "certificate_fingerprint_sha256": server_certificate.fingerprint(
                hashes.SHA256()
            ).hex(),
            "private_key_file": "server-key.pem",
            "private_key_encrypted": False,
            "not_after": server_not_after.isoformat(),
        },
        "android_scope": "debug_only_user_installed_ca",
        "private_key_protection": (
            "windows_acl_wrapper_required"
            if output_dir.as_posix().startswith("/mnt/")
            else "posix_mode_0600_verified"
        ),
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    _write_new(output_dir / "manifest.json", manifest_bytes, 0o644)

    if not output_dir.as_posix().startswith("/mnt/"):
        for key_path in (output_dir / "root-ca-key.pem", output_dir / "server-key.pem"):
            if stat.S_IMODE(key_path.stat().st_mode) & 0o077:
                raise PermissionError(
                    f"Private key permissions are too broad: {key_path}"
                )

    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
