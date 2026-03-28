"""Tests for the image_cache module."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from hcr_quick_viewer.viz_server import image_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    image_cache.clear()
    yield
    image_cache.clear()


class TestGetPlotBytes:
    @patch("hcr_quick_viewer.viz_server.image_cache.boto3")
    def test_returns_bytes_on_hit(self, mock_boto3):
        fake_body = MagicMock()
        fake_body.read.return_value = b"PNG_DATA"
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": fake_body}
        mock_boto3.client.return_value = mock_s3

        result = image_cache.get_plot_bytes("m1", "violins")
        assert result == b"PNG_DATA"
        mock_s3.get_object.assert_called_once()

    @patch("hcr_quick_viewer.viz_server.image_cache.boto3")
    def test_caches_after_first_fetch(self, mock_boto3):
        fake_body = MagicMock()
        fake_body.read.return_value = b"PNG_DATA"
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": fake_body}
        mock_boto3.client.return_value = mock_s3

        image_cache.get_plot_bytes("m1", "violins")
        image_cache.get_plot_bytes("m1", "violins")
        # Should only fetch from S3 once
        assert mock_s3.get_object.call_count == 1

    @patch("hcr_quick_viewer.viz_server.image_cache.boto3")
    def test_returns_none_on_404(self, mock_boto3):
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "not found"}},
            "GetObject",
        )
        mock_boto3.client.return_value = mock_s3

        result = image_cache.get_plot_bytes("m1", "missing_plot")
        assert result is None


def _make_png(width: int = 800, height: int = 600) -> bytes:
    """Create a minimal valid PNG in memory."""
    img = Image.new("RGB", (width, height), color="red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestMakeThumbnail:
    def test_resizes_wide_image(self):
        png = _make_png(800, 600)
        thumb = image_cache._make_thumbnail(png, max_width=200)
        img = Image.open(io.BytesIO(thumb))
        assert img.width == 200
        assert img.height == 150  # aspect ratio preserved

    def test_skips_small_image(self):
        png = _make_png(100, 80)
        thumb = image_cache._make_thumbnail(png, max_width=200)
        img = Image.open(io.BytesIO(thumb))
        assert img.width == 100  # no upscaling


class TestGetThumbnailBytes:
    @patch("hcr_quick_viewer.viz_server.image_cache.boto3")
    def test_returns_thumbnail(self, mock_boto3):
        png = _make_png(800, 600)
        fake_body = MagicMock()
        fake_body.read.return_value = png
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": fake_body}
        mock_boto3.client.return_value = mock_s3

        thumb = image_cache.get_thumbnail_bytes("m1", "violins")
        assert thumb is not None
        img = Image.open(io.BytesIO(thumb))
        assert img.width == 200

    @patch("hcr_quick_viewer.viz_server.image_cache.boto3")
    def test_returns_none_for_missing(self, mock_boto3):
        from botocore.exceptions import ClientError

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "not found"}},
            "GetObject",
        )
        mock_boto3.client.return_value = mock_s3

        assert image_cache.get_thumbnail_bytes("m1", "missing") is None

    @patch("hcr_quick_viewer.viz_server.image_cache.boto3")
    def test_caches_thumbnail(self, mock_boto3):
        png = _make_png(800, 600)
        fake_body = MagicMock()
        fake_body.read.return_value = png
        mock_s3 = MagicMock()
        mock_s3.get_object.return_value = {"Body": fake_body}
        mock_boto3.client.return_value = mock_s3

        image_cache.get_thumbnail_bytes("m1", "violins")
        image_cache.get_thumbnail_bytes("m1", "violins")
        # Full image fetched once, thumbnail generated once
        assert mock_s3.get_object.call_count == 1
