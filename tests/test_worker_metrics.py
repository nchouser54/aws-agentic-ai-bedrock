import logging
from unittest.mock import MagicMock, patch

import pytest

from worker.app import _emit_metric


def test_emit_metric_swallows_cloudwatch_errors(caplog: pytest.LogCaptureFixture) -> None:
    """_emit_metric must not propagate exceptions from CloudWatch, and must log a warning."""
    fake_cloudwatch = MagicMock()
    fake_cloudwatch.put_metric_data.side_effect = RuntimeError("cloudwatch unavailable")

    with patch("worker.app._cloudwatch", fake_cloudwatch):
        with caplog.at_level(logging.WARNING, logger="pr_review_worker"):
            _emit_metric("reviews_success", 1)

    assert any(
        "metric_emit_failed" in record.message
        for record in caplog.records
    ), f"Expected 'metric_emit_failed' warning; got: {[r.message for r in caplog.records]}"
