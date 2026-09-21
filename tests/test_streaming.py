"""
Tests for Phase 15 streaming pipeline:
  - encrypt_stream / decrypt_stream roundtrip (20 MB)
  - compute_checksum_stream accuracy
  - passthrough (copy) when encryption disabled
  - S3 write_stream uses upload_fileobj, not put_object
  - 100 MB pipeline stays within bounded RAM
"""
import base64
import hashlib
import os
import tempfile
import tracemalloc
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import EncryptionConfig, S3StorageConfig
from app.encryption import EncryptionService
from app.storage.s3 import S3Storage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_enc(enabled: bool = True) -> EncryptionService:
    if enabled:
        key = base64.b64encode(os.urandom(32)).decode()
        cfg = EncryptionConfig(enabled=True, key=key)
    else:
        cfg = EncryptionConfig(enabled=False)
    return EncryptionService(cfg)


# ---------------------------------------------------------------------------
# Test 1  encrypt_stream / decrypt_stream roundtrip
# ---------------------------------------------------------------------------

def test_stream_roundtrip_20mb():
    """Streaming encrypt then decrypt returns the original 20 MB payload."""
    plaintext = os.urandom(20 * 1024 * 1024)
    enc = _make_enc(enabled=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        raw = Path(tmpdir) / "raw"
        enc_file = Path(tmpdir) / "enc"
        dec = Path(tmpdir) / "dec"

        raw.write_bytes(plaintext)
        enc.encrypt_stream(raw, enc_file)
        enc.decrypt_stream(enc_file, dec)

        assert dec.read_bytes() == plaintext


# ---------------------------------------------------------------------------
# Test 2  compute_checksum_stream accuracy
# ---------------------------------------------------------------------------

def test_checksum_stream_matches_hashlib():
    """compute_checksum_stream returns the same hex digest as hashlib.sha256."""
    data = os.urandom(5 * 1024 * 1024)  # 5 MB

    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "data"
        p.write_bytes(data)

        expected = hashlib.sha256(data).hexdigest()
        actual = EncryptionService.compute_checksum_stream(p)

        assert actual == expected


# ---------------------------------------------------------------------------
# Test 3  passthrough when encryption is disabled
# ---------------------------------------------------------------------------

def test_encrypt_stream_disabled_is_copy():
    """When encryption is disabled, encrypt_stream produces an identical copy."""
    data = os.urandom(1 * 1024 * 1024)  # 1 MB
    enc = _make_enc(enabled=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "src"
        dst = Path(tmpdir) / "dst"
        src.write_bytes(data)

        enc.encrypt_stream(src, dst)

        assert dst.read_bytes() == data


# ---------------------------------------------------------------------------
# Test 4  S3 write_stream uses upload_fileobj (multipart), not put_object
# ---------------------------------------------------------------------------

def test_s3_write_stream_uses_upload_fileobj():
    """S3Storage.write_stream calls upload_fileobj (multipart), not put_object."""
    cfg = S3StorageConfig(
        bucket="test-bucket",
        region="us-east-1",
        prefix="raven/",
        access_key="AKID",
        secret_key="secret",
    )

    with patch("app.storage.s3.boto3.client") as mock_boto3_client:
        mock_s3 = MagicMock()
        mock_boto3_client.return_value = mock_s3

        storage = S3Storage(cfg)

        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "backup.enc"
            src.write_bytes(b"fake encrypted data")

            storage.write_stream("mybackup.enc", src)

        mock_s3.upload_fileobj.assert_called_once()
        mock_s3.put_object.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5  100 MB streaming pipeline: peak RAM stays below 64 MB
# ---------------------------------------------------------------------------

def test_streaming_pipeline_bounded_ram_100mb():
    """
    Streaming encrypt + checksum of a 100 MB file must keep
    peak Python-tracked RAM under 64 MB (2 × 8 MB chunks + overhead).
    """
    data = os.urandom(100 * 1024 * 1024)  # 100 MB
    enc = _make_enc(enabled=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        raw = Path(tmpdir) / "raw"
        enc_file = Path(tmpdir) / "enc"
        raw.write_bytes(data)
        del data  # release the 100 MB before measuring

        tracemalloc.start()
        tracemalloc.clear_traces()

        enc.encrypt_stream(raw, enc_file)
        EncryptionService.compute_checksum_stream(enc_file)

        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    max_allowed_bytes = 64 * 1024 * 1024  # 64 MB
    assert peak < max_allowed_bytes, (
        f"Peak RAM {peak / (1024 * 1024):.1f} MB exceeded "
        f"{max_allowed_bytes // (1024 * 1024)} MB limit"
    )
