"""Tests for the catalog module."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from hcr_quick_viewer.viz_server import catalog


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    {"mouse_id": "782149", "plot_type": "intensity_violins", "s3_key": "ctl/hcr/qc/782149/intensity_violins.png", "has_pdf": False},
    {"mouse_id": "782149", "plot_type": "spot_count", "s3_key": "ctl/hcr/qc/782149/spot_count.png", "has_pdf": True},
    {"mouse_id": "783551", "plot_type": "intensity_violins", "s3_key": "ctl/hcr/qc/783551/intensity_violins.png", "has_pdf": False},
]


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure catalog cache is empty before each test."""
    catalog._catalog_cache.clear()
    yield
    catalog._catalog_cache.clear()


@pytest.fixture()
def sample_catalog():
    return pd.DataFrame(SAMPLE_ROWS)


# ---------------------------------------------------------------------------
# Unit tests — pure DataFrame helpers (no S3)
# ---------------------------------------------------------------------------

class TestKnownPlotTypes:
    def test_returns_sorted_unique(self, sample_catalog):
        result = catalog.known_plot_types(sample_catalog)
        assert result == ["intensity_violins", "spot_count"]

    def test_empty_catalog(self):
        assert catalog.known_plot_types(pd.DataFrame()) == []


class TestMiceInCatalog:
    def test_returns_sorted(self, sample_catalog):
        assert catalog.mice_in_catalog(sample_catalog) == ["782149", "783551"]

    def test_empty(self):
        assert catalog.mice_in_catalog(pd.DataFrame()) == []


class TestMiceForPlotType:
    def test_returns_matching_mice(self, sample_catalog):
        assert catalog.mice_for_plot_type(sample_catalog, "intensity_violins") == ["782149", "783551"]

    def test_single_match(self, sample_catalog):
        assert catalog.mice_for_plot_type(sample_catalog, "spot_count") == ["782149"]

    def test_unknown_type(self, sample_catalog):
        assert catalog.mice_for_plot_type(sample_catalog, "nonexistent") == []


class TestPlotTypesForMouse:
    def test_returns_types(self, sample_catalog):
        assert catalog.plot_types_for_mouse(sample_catalog, "782149") == ["intensity_violins", "spot_count"]

    def test_unknown_mouse(self, sample_catalog):
        assert catalog.plot_types_for_mouse(sample_catalog, "999999") == []


class TestHasPdf:
    def test_true(self, sample_catalog):
        assert catalog.has_pdf(sample_catalog, "782149", "spot_count") is True

    def test_false(self, sample_catalog):
        assert catalog.has_pdf(sample_catalog, "782149", "intensity_violins") is False

    def test_missing_row(self, sample_catalog):
        assert catalog.has_pdf(sample_catalog, "999999", "intensity_violins") is False


# ---------------------------------------------------------------------------
# Integration-style tests — mocked S3
# ---------------------------------------------------------------------------

class TestLoadCatalog:
    @patch.object(catalog, "_list_plots_from_s3", return_value=SAMPLE_ROWS)
    def test_returns_dataframe(self, mock_list):
        df = catalog.load_catalog()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        mock_list.assert_called_once()

    @patch.object(catalog, "_list_plots_from_s3", return_value=SAMPLE_ROWS)
    def test_caches_result(self, mock_list):
        df1 = catalog.load_catalog()
        df2 = catalog.load_catalog()
        # Should only call S3 once due to cache
        mock_list.assert_called_once()
        pd.testing.assert_frame_equal(df1, df2)


class TestRefresh:
    @patch.object(catalog, "_list_plots_from_s3", return_value=SAMPLE_ROWS)
    def test_clears_cache(self, mock_list):
        catalog.load_catalog()
        catalog.refresh()
        assert mock_list.call_count == 2
