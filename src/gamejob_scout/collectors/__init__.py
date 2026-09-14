"""Careers-source collectors.

Each collector knows one applicant tracking system. The Lever adapter arrives in
milestone 1.5.
"""

from gamejob_scout.collectors.base import CollectionResult, Collector, CollectorError
from gamejob_scout.collectors.greenhouse import (
    GREENHOUSE_API_BASE,
    GreenhouseCollector,
    board_jobs_url,
    make_source_key,
)

__all__ = [
    "GREENHOUSE_API_BASE",
    "CollectionResult",
    "Collector",
    "CollectorError",
    "GreenhouseCollector",
    "board_jobs_url",
    "make_source_key",
]
