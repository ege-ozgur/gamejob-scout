"""Careers-source collectors.

Each collector knows one applicant tracking system. Both ATSs need the same two
concepts — a board URL and a source key — so the names are qualified here at the
package boundary, where the collision actually exists. Inside
``collectors.greenhouse`` and ``collectors.lever`` the short names are
unambiguous and stay as they are.
"""

from gamejob_scout.collectors.base import (
    CollectionResult,
    Collector,
    CollectorError,
    JobBoardFetcher,
)
from gamejob_scout.collectors.greenhouse import (
    GREENHOUSE_API_BASE,
    GreenhouseCollector,
)
from gamejob_scout.collectors.greenhouse import board_jobs_url as greenhouse_board_jobs_url
from gamejob_scout.collectors.greenhouse import make_source_key as greenhouse_source_key
from gamejob_scout.collectors.lever import (
    LEVER_API_BASE,
    LEVER_MAX_ID_LENGTH,
    LEVER_MAX_PAGES,
    LEVER_PAGE_SIZE,
    LeverCollector,
    compose_description,
)
from gamejob_scout.collectors.lever import board_url as lever_board_url
from gamejob_scout.collectors.lever import make_source_key as lever_source_key
from gamejob_scout.collectors.lever import postings_url as lever_postings_url

__all__ = [
    "GREENHOUSE_API_BASE",
    "LEVER_API_BASE",
    "LEVER_MAX_ID_LENGTH",
    "LEVER_MAX_PAGES",
    "LEVER_PAGE_SIZE",
    "CollectionResult",
    "Collector",
    "CollectorError",
    "GreenhouseCollector",
    "JobBoardFetcher",
    "LeverCollector",
    "compose_description",
    "greenhouse_board_jobs_url",
    "greenhouse_source_key",
    "lever_board_url",
    "lever_postings_url",
    "lever_source_key",
]
