from unittest.mock import MagicMock, patch

from worker.app import _emit_metric


def test_emit_metric_swallows_cloudwatch_errors() -> None:
    fake_cloudwatch = MagicMock()
    fake_cloudwatch.put_metric_data.side_effect = RuntimeError("cloudwatch unavailable")

    with patch("worker.app._cloudwatch", fake_cloudwatch):
        with patch("worker.app.logger") as mock_logger:
            _emit_metric("reviews_success", 1)

    mock_logger.warning.assert_called_once()
