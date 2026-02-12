import random
import time
from dataclasses import dataclass
from typing import Callable, Optional, TypeVar


T = TypeVar("T")


@dataclass
class RetryConfig:
    max_attempts: int = 5
    base_delay_seconds: float = 0.25
    max_delay_seconds: float = 10.0
    jitter_ratio: float = 0.30


def _compute_sleep_seconds(attempt: int, config: RetryConfig) -> float:
    exponential = min(config.base_delay_seconds * (2 ** (attempt - 1)), config.max_delay_seconds)
    jitter_multiplier = 1 + random.uniform(0, config.jitter_ratio)
    return exponential * jitter_multiplier


def call_with_retry(
    operation_name: str,
    fn: Callable[[], T],
    is_retryable_exception: Callable[[Exception], bool],
    is_retryable_result: Optional[Callable[[T], bool]] = None,
    config: Optional[RetryConfig] = None,
) -> T:
    cfg = config or RetryConfig()
    last_exception: Optional[Exception] = None

    for attempt in range(1, cfg.max_attempts + 1):
        try:
            result = fn()
            if is_retryable_result and is_retryable_result(result):
                if attempt == cfg.max_attempts:
                    return result
                time.sleep(_compute_sleep_seconds(attempt, cfg))
                continue
            return result
        except Exception as exc:  # noqa: BLE001
            last_exception = exc
            if not is_retryable_exception(exc) or attempt == cfg.max_attempts:
                raise
            time.sleep(_compute_sleep_seconds(attempt, cfg))

    if last_exception:
        raise last_exception

    raise RuntimeError(f"Retry loop exhausted unexpectedly for {operation_name}")
