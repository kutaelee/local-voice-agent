from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate-private-ca.py"


def _run_generator(tmp_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    allowed_root = tmp_path / "tls"
    allowed_root.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["LVA_CA_KEY_PASSWORD"] = "test-only-password-with-32-characters"
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--allowed-root",
            str(allowed_root),
            "--output-dir",
            str(allowed_root / "test-deployment"),
            "--deployment-name",
            "test-deployment",
            *arguments,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


class GeneratePrivateCaTests(unittest.TestCase):
    def test_generates_matching_private_ca_and_server_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            tmp_path = Path(temporary_directory)
            result = _run_generator(
                tmp_path,
                "--dns-name",
                "voice-agent.home.arpa",
                "--ip-address",
                "192.168.50.20",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            output_dir = tmp_path / "tls" / "test-deployment"
            manifest = json.loads((output_dir / "manifest.json").read_text())
            self.assertEqual(
                manifest["subject_alternative_names"],
                {
                    "dns": ["voice-agent.home.arpa"],
                    "ip": ["192.168.50.20"],
                },
            )
            self.assertTrue(manifest["root_ca"]["private_key_encrypted"])
            self.assertFalse(manifest["server"]["private_key_encrypted"])

            root_certificate = x509.load_pem_x509_certificate(
                (output_dir / "root-ca.pem").read_bytes()
            )
            server_certificate = x509.load_pem_x509_certificate(
                (output_dir / "server-cert.pem").read_bytes()
            )
            root_public_key = root_certificate.public_key()
            root_public_key.verify(
                server_certificate.signature,
                server_certificate.tbs_certificate_bytes,
                server_certificate.signature_algorithm_parameters,
                server_certificate.signature_hash_algorithm,
            )
            san = server_certificate.extensions.get_extension_for_class(
                x509.SubjectAlternativeName
            ).value
            self.assertEqual(
                san.get_values_for_type(x509.DNSName),
                ["voice-agent.home.arpa"],
            )
            self.assertEqual(
                [
                    str(value)
                    for value in san.get_values_for_type(x509.IPAddress)
                ],
                ["192.168.50.20"],
            )
            eku = server_certificate.extensions.get_extension_for_class(
                x509.ExtendedKeyUsage
            ).value
            self.assertIn(ExtendedKeyUsageOID.SERVER_AUTH, eku)

            serialization.load_pem_private_key(
                (output_dir / "root-ca-key.pem").read_bytes(),
                password=b"test-only-password-with-32-characters",
            )
            serialization.load_pem_private_key(
                (output_dir / "server-key.pem").read_bytes(),
                password=None,
            )

    def test_refuses_existing_output_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            tmp_path = Path(temporary_directory)
            first = _run_generator(tmp_path, "--ip-address", "10.20.30.40")
            self.assertEqual(first.returncode, 0, first.stderr)
            second = _run_generator(tmp_path, "--ip-address", "10.20.30.40")
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("Refusing to overwrite", second.stderr)

    def test_refuses_public_ip_and_wildcard_dns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            tmp_path = Path(temporary_directory)
            public_ip = _run_generator(tmp_path, "--ip-address", "8.8.8.8")
            self.assertNotEqual(public_ip.returncode, 0)
            self.assertIn("Only private IP SANs are allowed", public_ip.stderr)

            reserved_ip_root = tmp_path / "reserved"
            reserved_ip = _run_generator(
                reserved_ip_root,
                "--ip-address",
                "192.0.2.1",
            )
            self.assertNotEqual(reserved_ip.returncode, 0)
            self.assertIn("Only private IP SANs are allowed", reserved_ip.stderr)

            wildcard_root = tmp_path / "wildcard"
            wildcard_dns = _run_generator(
                wildcard_root,
                "--dns-name",
                "*.home.arpa",
            )
            self.assertNotEqual(wildcard_dns.returncode, 0)
            self.assertIn("Invalid DNS name", wildcard_dns.stderr)


if __name__ == "__main__":
    unittest.main()
