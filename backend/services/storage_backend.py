"""
Pluggable storage backend for generated map image files.

Local disk (backend/uploads/maps/...) remains the default and requires no
configuration — this is exactly the existing behavior from before this
module existed. Setting MAP_STORAGE_BACKEND=s3 in backend/.env (plus the
AWS_* variables) switches to uploading the same files to an S3 bucket and
returning S3 URLs instead, without changing anything else in the map
processing pipeline or the frontend-facing MapResponse fields
(source_image_url / display_image_url stay plain URL strings either way).

boto3 is only imported when S3 mode is actually selected, so local-disk
development never requires the AWS SDK to be installed.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

STORAGE_BACKEND = os.getenv("MAP_STORAGE_BACKEND", "local").strip().lower()

AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "").strip()
AWS_REGION = os.getenv("AWS_REGION", "").strip()
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()

_s3_client = None


def is_s3_enabled() -> bool:
    return STORAGE_BACKEND == "s3"


def _get_s3_client():
    global _s3_client

    if _s3_client is not None:
        return _s3_client

    if not AWS_S3_BUCKET:
        raise ValueError(
            "MAP_STORAGE_BACKEND=s3 but AWS_S3_BUCKET is not set in .env"
        )

    try:
        import boto3
    except ImportError as error:
        raise ValueError(
            "MAP_STORAGE_BACKEND=s3 requires the boto3 package "
            "(pip install boto3)."
        ) from error

    client_kwargs = {}

    if AWS_REGION:
        client_kwargs["region_name"] = AWS_REGION

    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = AWS_ACCESS_KEY_ID
        client_kwargs["aws_secret_access_key"] = AWS_SECRET_ACCESS_KEY

    _s3_client = boto3.client("s3", **client_kwargs)
    return _s3_client


def _public_s3_url(object_key: str) -> str:
    if AWS_REGION and AWS_REGION != "us-east-1":
        return f"https://{AWS_S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com/{object_key}"

    return f"https://{AWS_S3_BUCKET}.s3.amazonaws.com/{object_key}"


def sync_generated_file(local_path: Path, local_url: str) -> str:
    """
    Called right after map_image_service writes a source/display PNG to
    local disk. In local mode this is a no-op that returns the same URL
    the frontend already used. In S3 mode it additionally uploads the
    file and returns the S3 URL instead, so the returned value is always
    the URL that should be stored on the Map document.
    """

    if not is_s3_enabled():
        return local_url

    if not local_path.exists():
        return local_url

    object_key = local_url.lstrip("/")

    try:
        client = _get_s3_client()
        client.upload_file(str(local_path), AWS_S3_BUCKET, object_key)
        return _public_s3_url(object_key)
    except Exception as error:
        # Never let a storage-sync failure break map upload/processing —
        # local disk already has a valid copy and the local URL still
        # works because /uploads is always mounted regardless of backend.
        print(f"S3 sync failed for {object_key}, keeping local URL: {error}")
        return local_url


def delete_generated_file(local_url: Optional[str]) -> None:
    """
    Best-effort deletion of the S3 copy of a generated file. No-op in
    local mode (local file deletion is already handled by
    map_image_service.delete_file_safely).
    """

    if not is_s3_enabled() or not local_url:
        return

    object_key = local_url.lstrip("/")

    try:
        client = _get_s3_client()
        client.delete_object(Bucket=AWS_S3_BUCKET, Key=object_key)
    except Exception as error:
        print(f"S3 delete failed for {object_key}: {error}")
