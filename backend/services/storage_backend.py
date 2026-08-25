"""
Pluggable storage backend for generated map image files.

Local disk remains the default storage backend.

When MAP_STORAGE_BACKEND=s3:
- Generated map files are uploaded to a private S3 bucket.
- A stable S3 URL is stored in MongoDB.
- A temporary presigned URL is generated when the image is sent
  to the frontend.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


STORAGE_BACKEND = os.getenv(
    "MAP_STORAGE_BACKEND",
    "local",
).strip().lower()

AWS_S3_BUCKET = os.getenv(
    "AWS_S3_BUCKET",
    "",
).strip()

AWS_REGION = os.getenv(
    "AWS_REGION",
    "",
).strip()

AWS_ACCESS_KEY_ID = os.getenv(
    "AWS_ACCESS_KEY_ID",
    "",
).strip()

AWS_SECRET_ACCESS_KEY = os.getenv(
    "AWS_SECRET_ACCESS_KEY",
    "",
).strip()


_s3_client = None


def is_s3_enabled() -> bool:
    """
    Returns True when S3 is configured as the map storage backend.
    """

    return STORAGE_BACKEND == "s3"


def _get_s3_client():
    """
    Creates and caches the boto3 S3 client.

    Local development may use explicit AWS credentials.

    On ECS, explicit credentials are not required because boto3
    automatically obtains temporary credentials from the ECS Task Role.
    """

    global _s3_client

    if _s3_client is not None:
        return _s3_client

    if not AWS_S3_BUCKET:
        raise ValueError(
            "MAP_STORAGE_BACKEND=s3 but AWS_S3_BUCKET is not set."
        )

    try:
        import boto3
        from botocore.config import Config
    except ImportError as error:
        raise ValueError(
            "MAP_STORAGE_BACKEND=s3 requires the boto3 package."
        ) from error

    client_kwargs = {
        "config": Config(
            signature_version="s3v4",
            s3={
                "addressing_style": "virtual",
            },
        ),
    }

    if AWS_REGION:
        client_kwargs["region_name"] = AWS_REGION

    # Explicit credentials are used only during local development.
    # On ECS, boto3 automatically uses the ECS Task Role.
    if AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY:
        client_kwargs["aws_access_key_id"] = (
            AWS_ACCESS_KEY_ID
        )
        client_kwargs["aws_secret_access_key"] = (
            AWS_SECRET_ACCESS_KEY
        )

    _s3_client = boto3.client(
        "s3",
        **client_kwargs,
    )

    return _s3_client


def _public_s3_url(
    object_key: str,
) -> str:
    """
    Creates a stable S3 URL to store in MongoDB.

    The bucket remains private. Before the URL is sent to the
    frontend, it is converted into a temporary presigned URL.
    """

    if AWS_REGION and AWS_REGION != "us-east-1":
        return (
            f"https://{AWS_S3_BUCKET}."
            f"s3.{AWS_REGION}.amazonaws.com/"
            f"{object_key}"
        )

    return (
        f"https://{AWS_S3_BUCKET}."
        f"s3.amazonaws.com/"
        f"{object_key}"
    )


def _extract_s3_object_key(
    stored_url: str,
) -> Optional[str]:
    """
    Extracts an S3 object key from supported URL formats:

    - /uploads/maps/source/map.png
    - s3://bucket-name/uploads/maps/source/map.png
    - https://bucket-name.s3.region.amazonaws.com/key
    - https://s3.region.amazonaws.com/bucket-name/key
    """

    cleaned_url = stored_url.strip()

    if not cleaned_url:
        return None

    # Relative local-style URL.
    #
    # Example:
    # /uploads/maps/source/map.png
    if "://" not in cleaned_url:
        object_key = unquote(
            cleaned_url.lstrip("/")
        )

        if object_key.startswith("uploads/maps/"):
            return object_key

        return None

    parsed_url = urlparse(cleaned_url)

    # S3 URL.
    #
    # Example:
    # s3://bucket-name/uploads/maps/source/map.png
    if parsed_url.scheme == "s3":
        if parsed_url.netloc != AWS_S3_BUCKET:
            return None

        object_key = unquote(
            parsed_url.path.lstrip("/")
        )

        return object_key or None

    if parsed_url.scheme not in {
        "http",
        "https",
    }:
        return None

    hostname = (
        parsed_url.hostname or ""
    ).lower()

    bucket_name = AWS_S3_BUCKET.lower()

    # Virtual-hosted S3 URL.
    #
    # Examples:
    # bucket.s3.amazonaws.com/key
    # bucket.s3.eu-central-1.amazonaws.com/key
    is_virtual_hosted_url = (
        hostname == f"{bucket_name}.s3.amazonaws.com"
        or (
            hostname.startswith(
                f"{bucket_name}.s3."
            )
            and hostname.endswith(
                ".amazonaws.com"
            )
        )
    )

    if is_virtual_hosted_url:
        object_key = unquote(
            parsed_url.path.lstrip("/")
        )

        return object_key or None

    # Path-style S3 URL.
    #
    # Examples:
    # s3.amazonaws.com/bucket/key
    # s3.eu-central-1.amazonaws.com/bucket/key
    is_path_style_url = (
        hostname == "s3.amazonaws.com"
        or (
            hostname.startswith("s3.")
            and hostname.endswith(
                ".amazonaws.com"
            )
        )
    )

    if is_path_style_url:
        full_path = unquote(
            parsed_url.path.lstrip("/")
        )

        bucket_prefix = (
            f"{AWS_S3_BUCKET}/"
        )

        if full_path.startswith(
            bucket_prefix
        ):
            object_key = full_path[
                len(bucket_prefix):
            ]

            return object_key or None

    return None


def resolve_generated_file_url(
    stored_url: Optional[str],
) -> Optional[str]:
    """
    Converts a stored private S3 URL into a temporary presigned URL
    that the browser can open.

    Local URLs and unrelated external URLs are returned unchanged.
    """

    if not stored_url:
        return stored_url

    if not is_s3_enabled():
        return stored_url

    object_key = _extract_s3_object_key(
        stored_url
    )

    if not object_key:
        return stored_url

    try:
        client = _get_s3_client()

        return client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": AWS_S3_BUCKET,
                "Key": object_key,
            },
            ExpiresIn=3600,
        )

    except Exception as error:
        print(
            "S3 presigned URL generation failed "
            f"for {object_key}: {error}"
        )

        return stored_url


def sync_generated_file(
    local_path: Path,
    local_url: str,
) -> str:
    """
    Uploads a generated map image to S3 when S3 storage is enabled.

    Returns:
    - The original local URL in local mode.
    - A stable S3 URL in S3 mode.
    """

    if not is_s3_enabled():
        return local_url

    if not local_path.exists():
        return local_url

    object_key = local_url.lstrip("/")

    try:
        client = _get_s3_client()

        client.upload_file(
            str(local_path),
            AWS_S3_BUCKET,
            object_key,
        )

        return _public_s3_url(
            object_key
        )

    except Exception as error:
        print(
            f"S3 sync failed for {object_key}, "
            f"keeping local URL: {error}"
        )

        return local_url


def ensure_generated_file_local(
    stored_url: Optional[str],
    local_path: Path,
) -> bool:
    """
    Ensures that a generated map file exists on local disk.

    This is needed on ECS because the container filesystem is
    temporary and local generated files may disappear after a
    container restart.

    Returns True when:
    - The local file already exists.
    - The file was successfully restored from S3.

    Returns False when:
    - S3 storage is disabled.
    - No stored URL is available.
    - The URL does not belong to the configured bucket.
    - The S3 download fails.
    """

    if local_path.exists():
        return True

    if not is_s3_enabled():
        return False

    if not stored_url:
        return False

    object_key = _extract_s3_object_key(
        stored_url
    )

    if not object_key:
        return False

    try:
        local_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        client = _get_s3_client()

        client.download_file(
            AWS_S3_BUCKET,
            object_key,
            str(local_path),
        )

        return local_path.exists()

    except Exception as error:
        print(
            f"S3 download failed for "
            f"{object_key}: {error}"
        )

        # Remove an incomplete local file that may have been
        # created before the S3 download failed.
        try:
            local_path.unlink(
                missing_ok=True
            )
        except Exception:
            pass

        return False


def delete_generated_file(
    stored_url: Optional[str],
) -> None:
    """
    Deletes the S3 copy of a generated map file.

    Local URLs and URLs that do not belong to the configured S3
    bucket are ignored.
    """

    if not is_s3_enabled():
        return

    if not stored_url:
        return

    object_key = _extract_s3_object_key(
        stored_url
    )

    if not object_key:
        return

    try:
        client = _get_s3_client()

        client.delete_object(
            Bucket=AWS_S3_BUCKET,
            Key=object_key,
        )

    except Exception as error:
        print(
            f"S3 delete failed for "
            f"{object_key}: {error}"
        )