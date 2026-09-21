import base64
import hashlib
import os
import shutil
from pathlib import Path

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from app.config import EncryptionConfig


class IntegrityError(Exception):
    """Raised when SHA-256 checksum verification fails during restore."""
    pass


class EncryptionService:
    """
    AES-256-CBC encryption/decryption for backup files.

    Wire-format for encrypted data:
        [ 16-byte random IV ] [ AES-256-CBC ciphertext (PKCS7 padded) ]
        .--. .-

    When disabled (encryption.enabled: false), encrypt() and decrypt()
    are transparent pass-throughs and no .enc suffix is appended to filenames.
    """

    BLOCK_SIZE = 16  # AES block size in bytes
    IV_SIZE = 16     # IV length in bytes

    def __init__(self, config: EncryptionConfig) -> None:
        self.enabled = config.enabled
        self._key: bytes | None = None

        if self.enabled:
            try:
                raw_key = base64.b64decode(config.key)
            except Exception as e:
                raise ValueError(f"Encryption key is not valid base64: {e}")

            if len(raw_key) != 32:
                raise ValueError(
                    f"Encryption key must decode to exactly 32 bytes (got {len(raw_key)}). "
                    "Generate a valid key with: openssl rand -base64 32"
                )
            self._key = raw_key

    # ------------------------------------------------------------------
    # encrypt() / decrypt()
    # ------------------------------------------------------------------

    def encrypt(self, data: bytes) -> bytes:
        """
        Encrypt data with AES-256-CBC.
        Returns: IV (16 bytes) + ciphertext.
        Pass-through when encryption is disabled.
        """
        if not self.enabled:
            return data

        iv = os.urandom(self.IV_SIZE)
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        return iv + cipher.encrypt(pad(data, self.BLOCK_SIZE))

    def decrypt(self, data: bytes) -> bytes:
        """
        Decrypt AES-256-CBC data.
        Expects: IV (first 16 bytes) + ciphertext.
        Pass-through when encryption is disabled.
        """
        if not self.enabled:
            return data

        iv = data[:self.IV_SIZE]
        ciphertext = data[self.IV_SIZE:]
        cipher = AES.new(self._key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(ciphertext), self.BLOCK_SIZE)

    # ------------------------------------------------------------------
    # Filename extension helper
    # ------------------------------------------------------------------

    def get_extension(self) -> str:
        """Return '.enc' when encryption is enabled, '' otherwise."""
        return ".enc" if self.enabled else ""

    # ------------------------------------------------------------------
    # SHA-256 checksum helpers (static  no key required)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_checksum(data: bytes) -> str:
        """Return the hex-encoded SHA-256 hash of data."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def verify_checksum(data: bytes, expected_hex: str) -> bool:
        """Return True if SHA-256(data) matches expected_hex, False otherwise."""
        return hashlib.sha256(data).hexdigest() == expected_hex

    # ------------------------------------------------------------------
    # Streaming encrypt / decrypt / checksum (constant memory footprint)
    # ------------------------------------------------------------------

    _CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB per chunk

    def encrypt_stream(
        self,
        input_path: Path,
        output_path: Path,
        chunk_size: int = _CHUNK_SIZE,
    ) -> None:
        """
        Stream-encrypt input_path → output_path using AES-256-CBC.

        Wire-format: [ 16-byte random IV ] [ PKCS7-padded AES-CBC ciphertext ]

        Memory footprint: at most two chunks + cipher overhead at any time.
        When encryption is disabled, copies input to output as-is.
        """
        if not self.enabled:
            shutil.copy2(input_path, output_path)
            return

        iv = os.urandom(self.IV_SIZE)
        cipher = AES.new(self._key, AES.MODE_CBC, iv)

        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            f_out.write(iv)
            prev: bytes | None = None
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    # End of file: encrypt prev with PKCS7 padding (handles empty file too)
                    last = prev if prev is not None else b""
                    f_out.write(cipher.encrypt(pad(last, self.BLOCK_SIZE)))
                    break
                if prev is not None:
                    # prev is not the last chunk  chunk_size is a multiple of BLOCK_SIZE
                    f_out.write(cipher.encrypt(prev))
                prev = chunk

    def decrypt_stream(
        self,
        input_path: Path,
        output_path: Path,
        chunk_size: int = _CHUNK_SIZE,
    ) -> None:
        """
        Stream-decrypt input_path → output_path (reverses encrypt_stream).

        Reads the 16-byte IV from the first bytes of input_path.
        Memory footprint: at most two chunks at any time.
        When encryption is disabled, copies input to output as-is.
        """
        if not self.enabled:
            shutil.copy2(input_path, output_path)
            return

        with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
            iv = f_in.read(self.IV_SIZE)
            cipher = AES.new(self._key, AES.MODE_CBC, iv)
            prev: bytes | None = None
            while True:
                chunk = f_in.read(chunk_size)
                if not chunk:
                    # End of file: unpad and write prev (the last ciphertext chunk)
                    if prev is not None:
                        f_out.write(unpad(cipher.decrypt(prev), self.BLOCK_SIZE))
                    break
                if prev is not None:
                    # prev is not the last chunk  write without unpadding
                    f_out.write(cipher.decrypt(prev))
                prev = chunk

    @staticmethod
    def compute_checksum_stream(
        path: Path,
        chunk_size: int = _CHUNK_SIZE,
    ) -> str:
        """
        Compute SHA-256 of a file incrementally without loading it into memory.
        Returns the hex digest string.
        """
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
