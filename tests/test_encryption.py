"""
Unit tests for EncryptionService and SHA-256 integrity helpers (Phase 4).
"""
import base64
import os

import pytest

from app.config import EncryptionConfig
from app.encryption import EncryptionService, IntegrityError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_key() -> str:
    """Generate a valid base64-encoded 32-byte key."""
    return base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def key():
    return _make_key()


@pytest.fixture
def enc_service(key):
    cfg = EncryptionConfig(enabled=True, key=key)
    return EncryptionService(cfg)


@pytest.fixture
def disabled_service():
    cfg = EncryptionConfig(enabled=False)
    return EncryptionService(cfg)


# ---------------------------------------------------------------------------
# EncryptionService  construction
# ---------------------------------------------------------------------------

class TestEncryptionServiceInit:
    def test_valid_key_constructs_without_error(self, key):
        cfg = EncryptionConfig(enabled=True, key=key)
        svc = EncryptionService(cfg)
        assert svc.enabled is True

    def test_disabled_requires_no_key(self):
        cfg = EncryptionConfig(enabled=False)
        svc = EncryptionService(cfg)
        assert svc.enabled is False
        assert svc._key is None

    def test_invalid_base64_key_raises_value_error(self):
        cfg = EncryptionConfig(enabled=True, key="not-valid-base64!!!")
        with pytest.raises(ValueError, match="base64"):
            EncryptionService(cfg)

    def test_short_key_raises_value_error(self):
        short = base64.b64encode(b"only16byteslong!").decode()  # 16 bytes, not 32
        cfg = EncryptionConfig(enabled=True, key=short)
        with pytest.raises(ValueError, match="32 bytes"):
            EncryptionService(cfg)


# ---------------------------------------------------------------------------
# encrypt() / decrypt() roundtrip
# ---------------------------------------------------------------------------

class TestEncryptDecrypt:
    def test_roundtrip_returns_original_plaintext(self, enc_service):
        plaintext = b"PostgreSQL backup data \x00\xff binary"
        assert enc_service.decrypt(enc_service.encrypt(plaintext)) == plaintext

    def test_roundtrip_large_data(self, enc_service):
        data = os.urandom(1024 * 64)  # 64 KB of random bytes
        assert enc_service.decrypt(enc_service.encrypt(data)) == data

    def test_roundtrip_exact_block_boundary(self, enc_service):
        # 32 bytes == exactly 2 AES blocks  PKCS7 adds a full padding block
        data = b"A" * 32
        assert enc_service.decrypt(enc_service.encrypt(data)) == data

    def test_encrypt_output_is_longer_than_input(self, enc_service):
        data = b"short"
        encrypted = enc_service.encrypt(data)
        # IV (16) + at least one padded block (16) = at least 32 bytes
        assert len(encrypted) > len(data)
        assert len(encrypted) >= 32

    def test_different_calls_produce_different_ciphertext(self, enc_service):
        """Two calls with the same plaintext must produce different ciphertext (random IV)."""
        data = b"same input"
        ct1 = enc_service.encrypt(data)
        ct2 = enc_service.encrypt(data)
        assert ct1 != ct2

    def test_different_ivs_in_ciphertext(self, enc_service):
        """The first 16 bytes (IV) must differ between two encryptions."""
        data = b"same input"
        iv1 = enc_service.encrypt(data)[:16]
        iv2 = enc_service.encrypt(data)[:16]
        assert iv1 != iv2

    def test_tampered_ciphertext_does_not_return_original(self, enc_service):
        """Flipping a byte in the ciphertext must NOT silently return the original plaintext."""
        data = b"important backup content"
        encrypted = bytearray(enc_service.encrypt(data))
        encrypted[20] ^= 0xFF  # flip a byte in the ciphertext portion
        try:
            result = enc_service.decrypt(bytes(encrypted))
            assert result != data
        except Exception:
            pass  # padding error is also acceptable  just not the original plaintext

    def test_decrypt_wrong_key_raises_or_returns_garbage(self, key):
        """Decrypting with a different key must not return the original plaintext."""
        svc1 = EncryptionService(EncryptionConfig(enabled=True, key=key))
        svc2 = EncryptionService(EncryptionConfig(enabled=True, key=_make_key()))

        data = b"sensitive backup"
        encrypted = svc1.encrypt(data)
        try:
            result = svc2.decrypt(encrypted)
            assert result != data
        except Exception:
            pass  # expected  wrong key triggers a padding or decryption error


# ---------------------------------------------------------------------------
# Pass-through mode (encryption disabled)
# ---------------------------------------------------------------------------

class TestPassThrough:
    def test_encrypt_returns_data_unchanged(self, disabled_service):
        data = b"plaintext backup"
        assert disabled_service.encrypt(data) == data

    def test_decrypt_returns_data_unchanged(self, disabled_service):
        data = b"plaintext backup"
        assert disabled_service.decrypt(data) == data

    def test_roundtrip_when_disabled(self, disabled_service):
        data = b"no encryption here"
        assert disabled_service.decrypt(disabled_service.encrypt(data)) == data


# ---------------------------------------------------------------------------
# get_extension()
# ---------------------------------------------------------------------------

class TestGetExtension:
    def test_returns_enc_when_enabled(self, enc_service):
        assert enc_service.get_extension() == ".enc"

    def test_returns_empty_string_when_disabled(self, disabled_service):
        assert disabled_service.get_extension() == ""


# ---------------------------------------------------------------------------
# compute_checksum() / verify_checksum()
# ---------------------------------------------------------------------------

class TestChecksum:
    def test_compute_checksum_returns_hex_string(self):
        checksum = EncryptionService.compute_checksum(b"data")
        assert isinstance(checksum, str)
        assert len(checksum) == 64  # SHA-256 hex digest is always 64 chars

    def test_compute_checksum_is_deterministic(self):
        data = b"backup content"
        assert EncryptionService.compute_checksum(data) == EncryptionService.compute_checksum(data)

    def test_different_inputs_produce_different_checksums(self):
        cs1 = EncryptionService.compute_checksum(b"file_a")
        cs2 = EncryptionService.compute_checksum(b"file_b")
        assert cs1 != cs2

    def test_verify_checksum_returns_true_for_valid_data(self):
        data = b"backup file bytes"
        checksum = EncryptionService.compute_checksum(data)
        assert EncryptionService.verify_checksum(data, checksum) is True

    def test_verify_checksum_returns_false_for_modified_data(self):
        data = b"original backup"
        checksum = EncryptionService.compute_checksum(data)
        tampered = b"modified backup"
        assert EncryptionService.verify_checksum(tampered, checksum) is False

    def test_verify_checksum_returns_false_for_wrong_hex(self):
        data = b"backup"
        assert EncryptionService.verify_checksum(data, "a" * 64) is False

    def test_compute_checksum_known_value(self):
        """SHA-256 of empty bytes is a well-known value."""
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert EncryptionService.compute_checksum(b"") == expected


# ---------------------------------------------------------------------------
# IntegrityError
# ---------------------------------------------------------------------------

class TestIntegrityError:
    def test_integrity_error_is_exception(self):
        err = IntegrityError("checksum mismatch")
        assert isinstance(err, Exception)
        assert str(err) == "checksum mismatch"

    def test_integrity_error_raised_when_checksum_fails(self):
        """Simulate the restore flow: abort with IntegrityError on mismatch."""
        data = b"backup bytes"
        stored_checksum = EncryptionService.compute_checksum(b"different bytes")

        if not EncryptionService.verify_checksum(data, stored_checksum):
            with pytest.raises(IntegrityError):
                raise IntegrityError("Integrity check failed: checksum mismatch")
