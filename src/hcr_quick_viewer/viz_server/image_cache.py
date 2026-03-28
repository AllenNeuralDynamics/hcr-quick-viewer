"""LRU in-memory cache for plot image bytes.

Bytes are fetched from S3 on demand and kept in a thread-safe LRU cache so
repeated views of the same plot don't re-download.
"""

from __future__ import annotations

import threading

import boto3
from botocore.exceptions import ClientError
from cachetools import LRUCache

_QC_S3_BUCKET: str = "aind-scratch-data"
_QC_S3_PREFIX: str = "ctl/hcr/qc"

_MAX_ENTRIES = 50
_lock = threading.RLock()
_cache: LRUCache[str, bytes] = LRUCache(maxsize=_MAX_ENTRIES)


def _cache_key(mouse_id: str, plot_type: str, fmt: str) -> str:
    return f"{mouse_id}/{plot_type}.{fmt}"


def get_plot_bytes(
    mouse_id: str,
    plot_type: str,
    fmt: str = "png",
    bucket: str = _QC_S3_BUCKET,
    prefix: str = _QC_S3_PREFIX,
) -> bytes | None:
    """Return the raw bytes of a plot image, or ``None`` if missing.

    Results are cached in an LRU cache (up to *_MAX_ENTRIES* items).

    Parameters
    ----------
    mouse_id:
        Subject identifier.
    plot_type:
        Short plot identifier.
    fmt:
        ``"png"`` or ``"pdf"``.
    bucket:
        S3 bucket name.
    prefix:
        S3 key prefix.
    """
    key = _cache_key(mouse_id, plot_type, fmt)

    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    # Fetch outside the lock to avoid blocking other threads
    s3 = boto3.client("s3")
    s3_key = f"{prefix}/{mouse_id}/{plot_type}.{fmt}"
    try:
        resp = s3.get_object(Bucket=bucket, Key=s3_key)
        data: bytes = resp["Body"].read()
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise

    with _lock:
        _cache[key] = data

    return data


def clear() -> None:
    """Drop all cached entries."""
    with _lock:
        _cache.clear()
