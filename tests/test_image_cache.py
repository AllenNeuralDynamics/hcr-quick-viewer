"""Tests for the image_cache module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
