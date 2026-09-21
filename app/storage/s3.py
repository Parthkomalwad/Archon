from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import ClientError

from app.config import S3StorageConfig
from app.logger import log
from app.storage.base import BaseStorage, StorageError


class S3Storage(BaseStorage):
    """
    AWS S3 storage backend.

    All objects are stored under a configurable prefix (default: 'archon/').
    The full S3 key is: {config.prefix}{filename}
    """

    def __init__(self, config: S3StorageConfig) -> None:
        self.bucket = config.bucket
        self.prefix = config.prefix
        self._client = boto3.client(
            "s3",
            region_name=config.region,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
        )

    def _key(self, filename: str) -> str:
        return f"{self.prefix}{filename}"

    # ------------------------------------------------------------------
    # write()
    # ------------------------------------------------------------------

    def write(self, filename: str, data: bytes) -> None:
        try:
            self._client.put_object(Bucket=self.bucket, Key=self._key(filename), Body=data)
        except ClientError as e:
            log.error("storage_write_failed", "S3 write failed", error=str(e))
            raise StorageError(f"S3 write failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # read()
    # ------------------------------------------------------------------

    def read(self, filename: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=self._key(filename))
            return response["Body"].read()
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise StorageError(f"File not found in S3: '{filename}'")
            log.error("storage_read_failed", "S3 read failed", error=str(e))
            raise StorageError(f"S3 read failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # list()
    # ------------------------------------------------------------------

    def list(self, prefix: str) -> list[dict]:
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            results = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self._key(prefix)):
                for obj in page.get("Contents", []):
                    # Strip the storage prefix to return bare filenames
                    name = obj["Key"][len(self.prefix):]
                    results.append({"filename": name, "size_bytes": obj["Size"]})
            return results
        except ClientError as e:
            log.error("storage_list_failed", "S3 list failed", error=str(e))
            raise StorageError(f"S3 list failed for prefix '{prefix}': {e}")

    # ------------------------------------------------------------------
    # delete()
    # ------------------------------------------------------------------

    def delete(self, filename: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._key(filename))
        except ClientError as e:
            log.error("storage_delete_failed", "S3 delete failed", error=str(e))
            raise StorageError(f"S3 delete failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # exists()
    # ------------------------------------------------------------------

    def exists(self, filename: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=self._key(filename))
            return True
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("404", "NoSuchKey"):
                return False
            log.error("storage_exists_failed", "S3 exists check failed", error=str(e))
            raise StorageError(f"S3 exists check failed for '{filename}': {e}")

    # ------------------------------------------------------------------
    # write_stream() / read_stream()
    # ------------------------------------------------------------------

    _TRANSFER_CFG = TransferConfig(
        multipart_threshold=8 * 1024 * 1024,
        multipart_chunksize=8 * 1024 * 1024,
    )

    def write_stream(self, filename: str, source_path: Path) -> None:
        try:
            with open(source_path, "rb") as f:
                self._client.upload_fileobj(
                    f, self.bucket, self._key(filename), Config=self._TRANSFER_CFG
                )
        except ClientError as e:
            log.error("storage_write_failed", "S3 write_stream failed", error=str(e))
            raise StorageError(f"S3 write_stream failed for '{filename}': {e}")

    def read_stream(self, filename: str, dest_path: Path) -> None:
        try:
            with open(dest_path, "wb") as f:
                self._client.download_fileobj(self.bucket, self._key(filename), f)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("NoSuchKey", "404"):
                raise StorageError(f"File not found in S3: '{filename}'")
            log.error("storage_read_failed", "S3 read_stream failed", error=str(e))
            raise StorageError(f"S3 read_stream failed for '{filename}': {e}")
