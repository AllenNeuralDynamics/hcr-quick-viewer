"""TTL-cached S3 catalog for QC plots.

Wraps ``aind_hcr_qc.utils.s3_qc.list_plots`` with a time-based cache so the
expensive S3 listing is shared across all Panel sessions and only refreshed
periodically.
"""

from __future__ import annotations

import os
import threading
from typing import Any

import boto3
import json
import pandas as pd
from botocore.exceptions import ClientError
from cachetools import TTLCache

_QC_S3_BUCKET: str = "aind-scratch-data"
_QC_S3_PREFIX: str = "ctl/hcr/qc"

_TTL_SECONDS = int(os.environ.get("QC_CATALOG_TTL_SECONDS", "300"))

_lock = threading.RLock()
_catalog_cache: TTLCache[str, pd.DataFrame] = TTLCache(maxsize=1, ttl=_TTL_SECONDS)
_CACHE_KEY = "catalog"


# ---------------------------------------------------------------------------
# S3 helpers (inlined so we don't depend on aind-hcr-qc at runtime)
# ---------------------------------------------------------------------------

def _s3_key(mouse_id: str, plot_type: str, ext: str) -> str:
    return f"{_QC_S3_PREFIX}/{mouse_id}/{plot_type}.{ext}"


def _list_plots_from_s3(
    bucket: str = _QC_S3_BUCKET,
    prefix: str = _QC_S3_PREFIX,
) -> list[dict[str, Any]]:
    """List all QC plots under *prefix*, returning one dict per PNG."""
    s3 = boto3.client("s3")
    results: list[dict[str, Any]] = []

    paginator = s3.get_paginator("list_objects_v2")

    # Enumerate mouse folders
    mouse_pages = paginator.paginate(Bucket=bucket, Prefix=prefix + "/", Delimiter="/")
    for page in mouse_pages:
        for cp in page.get("CommonPrefixes", []):
            mouse_prefix = cp["Prefix"]
            mouse_id = mouse_prefix.rstrip("/").split("/")[-1]
            if mouse_id.startswith("_"):
                continue

            # List objects in mouse folder
            all_keys: list[str] = []
            plot_pages = paginator.paginate(Bucket=bucket, Prefix=mouse_prefix)
            for ppage in plot_pages:
                for obj in ppage.get("Contents", []):
                    all_keys.append(obj["Key"])

            # Group by base name
            png_types = set()
            pdf_types = set()
            for key in all_keys:
                fname = key.split("/")[-1]
                if fname.endswith(".png"):
                    png_types.add(fname[:-4])
                elif fname.endswith(".pdf"):
                    pdf_types.add(fname[:-4])

            for plot_type in sorted(png_types):
                results.append({
                    "mouse_id": mouse_id,
                    "plot_type": plot_type,
                    "s3_key": f"{mouse_prefix}{plot_type}.png",
                    "has_pdf": plot_type in pdf_types,
                })

    return sorted(results, key=lambda r: (r["mouse_id"], r["plot_type"]))


def _load_metadata_from_s3(
    mouse_id: str,
    plot_type: str,
    bucket: str = _QC_S3_BUCKET,
) -> dict | None:
    """Fetch the JSON sidecar for a plot.  Returns None if missing."""
    s3 = boto3.client("s3")
    key = _s3_key(mouse_id, plot_type, "json")
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(resp["Body"].read())
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_catalog(bucket: str = _QC_S3_BUCKET) -> pd.DataFrame:
    """Return the catalog DataFrame, refreshing from S3 if TTL expired.

    Columns: ``mouse_id``, ``plot_type``, ``s3_key``, ``has_pdf``.
    """
    with _lock:
        cached = _catalog_cache.get(_CACHE_KEY)
        if cached is not None:
            return cached

        rows = _list_plots_from_s3(bucket=bucket)
        df = pd.DataFrame(rows, columns=["mouse_id", "plot_type", "s3_key", "has_pdf"])
        _catalog_cache[_CACHE_KEY] = df
        return df


def refresh() -> pd.DataFrame:
    """Force-refresh the catalog from S3."""
    with _lock:
        _catalog_cache.clear()
    return load_catalog()


def known_plot_types(catalog: pd.DataFrame) -> list[str]:
    """Return the sorted union of all plot types seen across all mice."""
    if catalog.empty:
        return []
    return sorted(catalog["plot_type"].unique().tolist())


def mice_in_catalog(catalog: pd.DataFrame) -> list[str]:
    """Return the sorted list of mouse IDs in the catalog."""
    if catalog.empty:
        return []
    return sorted(catalog["mouse_id"].unique().tolist())


def mice_for_plot_type(catalog: pd.DataFrame, plot_type: str) -> list[str]:
    """Return mouse IDs that have a specific plot type."""
    if catalog.empty:
        return []
    mask = catalog["plot_type"] == plot_type
    return sorted(catalog.loc[mask, "mouse_id"].unique().tolist())


def plot_types_for_mouse(catalog: pd.DataFrame, mouse_id: str) -> list[str]:
    """Return the plot types available for a given mouse."""
    if catalog.empty:
        return []
    mask = catalog["mouse_id"] == mouse_id
    return sorted(catalog.loc[mask, "plot_type"].unique().tolist())


def has_pdf(catalog: pd.DataFrame, mouse_id: str, plot_type: str) -> bool:
    """Check whether a PDF exists for a given (mouse, plot_type)."""
    mask = (catalog["mouse_id"] == mouse_id) & (catalog["plot_type"] == plot_type)
    rows = catalog.loc[mask]
    if rows.empty:
        return False
    return bool(rows.iloc[0]["has_pdf"])


def load_plot_metadata(mouse_id: str, plot_type: str) -> dict | None:
    """Fetch the JSON sidecar for a plot."""
    return _load_metadata_from_s3(mouse_id, plot_type)
