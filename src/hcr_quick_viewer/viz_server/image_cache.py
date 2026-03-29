"""LRU in-memory cache for plot image bytes.

Bytes are fetched from S3 on demand and kept in a thread-safe LRU cache so
repeated views of the same plot don't re-download.
"""

from __future__ import annotations

import io
import threading
from concurrent.futures import ThreadPoolExecutor

import boto3
from botocore.exceptions import ClientError
from cachetools import LRUCache
from PIL import Image

_QC_S3_BUCKET: str = "aind-scratch-data"
_QC_S3_PREFIX: str = "ctl/hcr/qc"

_MAX_ENTRIES = 50
_THUMB_MAX_ENTRIES = 200
_THUMB_WIDTH = 200

_lock = threading.RLock()
_cache: LRUCache[str, bytes] = LRUCache(maxsize=_MAX_ENTRIES)

_thumb_lock = threading.RLock()
_thumb_cache: LRUCache[str, bytes] = LRUCache(maxsize=_THUMB_MAX_ENTRIES)


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
    with _thumb_lock:
        _thumb_cache.clear()


def _make_thumbnail(png_bytes: bytes, max_width: int = _THUMB_WIDTH) -> bytes:
    """Resize a PNG to *max_width* preserving aspect ratio."""
    img = Image.open(io.BytesIO(png_bytes))
    if img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def get_thumbnail_bytes(
    mouse_id: str,
    plot_type: str,
    bucket: str = _QC_S3_BUCKET,
    prefix: str = _QC_S3_PREFIX,
    max_width: int = _THUMB_WIDTH,
) -> bytes | None:
    """Return a small PNG thumbnail, or ``None`` if the plot is missing.

    Fetches the full PNG (via :func:`get_plot_bytes`) and resizes it.
    Thumbnails are cached separately in a larger LRU cache.
    """
    key = f"thumb:{mouse_id}/{plot_type}:{max_width}"

    with _thumb_lock:
        cached = _thumb_cache.get(key)
        if cached is not None:
            return cached

    full = get_plot_bytes(mouse_id, plot_type, fmt="png", bucket=bucket, prefix=prefix)
    if full is None:
        return None

    thumb = _make_thumbnail(full, max_width=max_width)

    with _thumb_lock:
        _thumb_cache[key] = thumb

    return thumb


def prefetch_thumbnails(
    mouse_id: str,
    plot_types: list[str],
    *,
    bucket: str = _QC_S3_BUCKET,
    prefix: str = _QC_S3_PREFIX,
    max_width: int = _THUMB_WIDTH,
    max_workers: int = 8,
) -> dict[str, bytes | None]:
    """Fetch thumbnails for *plot_types* in parallel.

    Returns a ``{plot_type: thumb_bytes_or_None}`` dict.  Already-cached
    thumbnails are returned immediately; only cache misses hit S3.
    """
    results: dict[str, bytes | None] = {}
    to_fetch: list[str] = []

    for pt in plot_types:
        key = f"thumb:{mouse_id}/{pt}:{max_width}"
        with _thumb_lock:
            cached = _thumb_cache.get(key)
        if cached is not None:
            results[pt] = cached
        else:
            to_fetch.append(pt)

    if not to_fetch:
        return results

    def _fetch_one(pt: str) -> tuple[str, bytes | None]:
        return pt, get_thumbnail_bytes(
            mouse_id, pt, bucket=bucket, prefix=prefix, max_width=max_width,
        )

    with ThreadPoolExecutor(max_workers=min(max_workers, len(to_fetch))) as pool:
        for pt, thumb in pool.map(lambda p: _fetch_one(p), to_fetch):
            results[pt] = thumb

    return results
