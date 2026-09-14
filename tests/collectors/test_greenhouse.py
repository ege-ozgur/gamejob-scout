"""The Greenhouse collector: mapping, sanitized warnings, and failure behaviour.

Most tests hand the collector a canned :class:`FetchedDocument` rather than
standing up a mock transport — that is exactly what `FetchedDocument` was added
for in milestone 1.3. The handful of end-to-end tests at the bottom go through
the real `HttpFetcher` with respx, to prove the collector behaves inside the
responsible HTTP layer rather than only beside it.
"""

import html
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

import pytest
import respx

from gamejob_scout.collectors import (
    CollectionResult,
    Collector,
    CollectorError,
    GreenhouseCollector,
    board_jobs_url,
    make_source_key,
)
from gamejob_scout.domain import ATSKind, Company
from gamejob_scout.http import FetchedDocument, HttpFetcher, HttpStatusError, RobotsDisallowedError
from tests.factories import DISCOVERED_AT, make_company
from tests.http.conftest import ALLOW_ALL, DISALLOW_ALL, FakeClock, make_fetcher

FIXTURES: Final = Path(__file__).parent / "fixtures" / "greenhouse"

BOARD_URL: Final = "https://boards-api.greenhouse.io/v1/boards/examplestudio/jobs?content=true"
ROBOTS_URL: Final = "https://boards-api.greenhouse.io/robots.txt"
SINGLE_JOB_URL: Final = "https://boards-api.greenhouse.io/v1/boards/examplestudio/jobs/4968083003"

SOURCE_KEY: Final = "example-studio-greenhouse-examplestudio"

MISSING: Final = object()
"""Sentinel for a key that should be absent entirely rather than set to None."""


class FakeFetcher:
    """Hands back one canned body and remembers what it was asked for."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.requested: list[str] = []

    def get(self, url: str) -> FetchedDocument:
        self.requested.append(url)
        return FetchedDocument(url=url, status_code=200, headers={}, text=self.text)


def load_fixture(fixture_name: str) -> str:
    return (FIXTURES / f"{fixture_name}.json").read_text(encoding="utf-8")


def make_collector(fetcher: FakeFetcher, **company_overrides: Any) -> GreenhouseCollector:
    # The collector wants the real fetcher type; the fake satisfies the only
    # method it actually calls.
    return GreenhouseCollector(
        cast(HttpFetcher, fetcher),
        make_company(**company_overrides),
    )


def collect_body(body: str, **company_overrides: Any) -> CollectionResult:
    return make_collector(FakeFetcher(body), **company_overrides).collect(
        discovered_at=DISCOVERED_AT,
    )


def collect_fixture(fixture_name: str, **company_overrides: Any) -> CollectionResult:
    return collect_body(load_fixture(fixture_name), **company_overrides)


def collect_payload(payload: object) -> CollectionResult:
    return collect_body(json.dumps(payload))


def a_job(**overrides: Any) -> dict[str, Any]:
    """A posting shaped like the real API returns them."""
    job: dict[str, Any] = {
        "id": 5095371003,
        "title": "Junior Technical Artist",
        "location": {"name": "Remote - Europe"},
        "absolute_url": "https://example.com/examplestudio/jobs/5095371003",
        "first_published": "2026-06-30T08:00:00-04:00",
        "content": "&lt;p&gt;Art pipeline work.&lt;/p&gt;",
    }
    job.update(overrides)
    return job


if TYPE_CHECKING:

    def _static_conformance(collector: GreenhouseCollector) -> Collector:
        """Checked by mypy, never executed, constructs nothing."""
        return collector


# -- identity and construction --------------------------------------------


def test_the_board_url_asks_for_content() -> None:
    assert board_jobs_url("examplestudio") == BOARD_URL


def test_the_source_key_includes_the_board() -> None:
    """Two boards for one company on one ATS must not collide."""
    assert make_source_key(make_company()) == SOURCE_KEY
    assert make_source_key(make_company(ats_identifier="secondboard")) == (
        "example-studio-greenhouse-secondboard"
    )


NOT_A_SLUG = [
    "",
    "   ",
    "Example",
    "EXAMPLE",
    "example studio",
    "example_studio",
    "ex--ample",
    "-example",
    "example-",
    "exam.ple",
    "ex/ample",
    "../../etc",
]


@pytest.mark.parametrize("token", NOT_A_SLUG)
def test_the_board_url_refuses_a_token_that_is_not_a_slug(token: str) -> None:
    """The helper is exported, so it cannot be laxer than the constructor.

    The path-shaped entries matter most: refusing them is what keeps a bad token
    from being interpolated into somebody else's URL.
    """
    with pytest.raises(ValueError, match="board token"):
        board_jobs_url(token)


def test_the_source_key_helper_refuses_another_ats() -> None:
    with pytest.raises(ValueError, match="not 'greenhouse'"):
        make_source_key(make_company(ats=ATSKind.LEVER, ats_identifier="examplestudio"))


def test_the_source_key_helper_refuses_a_missing_board_token() -> None:
    """Company forbids this, so the guard is checked past that validator."""
    company = Company.model_construct(
        key="example-studio",
        name="Example Studio",
        ats=ATSKind.GREENHOUSE,
        ats_identifier=None,
    )

    with pytest.raises(ValueError, match="no ats_identifier"):
        make_source_key(company)


@pytest.mark.parametrize("token", ["Example_Studio", "example studio", "ex/ample"])
def test_the_source_key_helper_refuses_a_token_that_is_not_a_slug(token: str) -> None:
    """A blank token is absent from this list because Company rejects it first."""
    with pytest.raises(ValueError, match="board token"):
        make_source_key(make_company(ats_identifier=token))


def test_the_source_key_helper_refuses_a_blank_token_reaching_it_anyway() -> None:
    company = Company.model_construct(
        key="example-studio",
        name="Example Studio",
        ats=ATSKind.GREENHOUSE,
        ats_identifier="",
    )

    with pytest.raises(ValueError, match="board token"):
        make_source_key(company)


def test_the_source_key_helper_validates_what_it_derived() -> None:
    """Defensive: two valid slugs always compose into a valid one.

    Reaching this needs a Company built past its own validator, but the check
    is what makes the helper safe to trust rather than safe by coincidence.
    """
    company = Company.model_construct(
        key="Bad Key",
        name="Example Studio",
        ats=ATSKind.GREENHOUSE,
        ats_identifier="examplestudio",
    )

    with pytest.raises(ValueError, match="source key"):
        make_source_key(company)


def test_a_collector_reports_its_identity() -> None:
    collector = make_collector(FakeFetcher("{}"))

    assert collector.source_key == SOURCE_KEY
    assert collector.company_key == "example-studio"
    assert collector.source is ATSKind.GREENHOUSE


def test_an_explicit_source_key_is_honoured() -> None:
    collector = GreenhouseCollector(
        cast(HttpFetcher, FakeFetcher("{}")),
        make_company(),
        source_key="example-studio-emea-board",
    )

    assert collector.source_key == "example-studio-emea-board"


def test_a_company_on_another_ats_is_refused() -> None:
    with pytest.raises(ValueError, match="not 'greenhouse'"):
        make_collector(FakeFetcher("{}"), ats=ATSKind.LEVER, ats_identifier="examplestudio")


def test_a_company_without_a_board_token_is_refused() -> None:
    """Company already forbids this, so the guard is checked past that validator."""
    company = Company.model_construct(
        key="example-studio",
        name="Example Studio",
        ats=ATSKind.GREENHOUSE,
        ats_identifier=None,
    )

    with pytest.raises(ValueError, match="no ats_identifier"):
        GreenhouseCollector(cast(HttpFetcher, FakeFetcher("{}")), company)


@pytest.mark.parametrize("token", ["Example_Studio", "example studio", "EXAMPLE", "ex--ample"])
def test_a_board_token_that_is_not_slug_safe_is_refused(token: str) -> None:
    with pytest.raises(ValueError, match="board token"):
        make_collector(FakeFetcher("{}"), ats_identifier=token)


def test_an_explicit_source_key_must_still_be_a_slug() -> None:
    with pytest.raises(ValueError, match="source key"):
        GreenhouseCollector(
            cast(HttpFetcher, FakeFetcher("{}")),
            make_company(),
            source_key="Not A Slug",
        )


def test_the_collector_satisfies_the_protocol() -> None:
    assert isinstance(make_collector(FakeFetcher("{}")), Collector)


# -- mapping ---------------------------------------------------------------


def test_a_board_maps_every_posting() -> None:
    result = collect_fixture("board_two_jobs")

    assert result.found == 2
    assert len(result.listings) == 2
    assert result.warnings == ()


def test_each_field_comes_from_the_right_place() -> None:
    listing = collect_fixture("board_two_jobs").listings[0]

    assert listing.source is ATSKind.GREENHOUSE
    assert listing.source_key == SOURCE_KEY
    assert str(listing.source_url) == BOARD_URL
    assert listing.external_id == "4968083003"
    assert listing.company_key == "example-studio"
    assert listing.title == "Gameplay Programmer"
    assert str(listing.application_url) == ("https://example.com/examplestudio/jobs/4968083003")
    assert listing.discovered_at == DISCOVERED_AT


def test_the_job_post_id_becomes_the_external_id_as_a_string() -> None:
    """`id` is an int in the payload and differs from `internal_job_id`."""
    listing = collect_fixture("board_two_jobs").listings[0]

    assert listing.external_id == "4968083003"
    assert isinstance(listing.external_id, str)


def test_the_identity_is_the_source_key_and_the_external_id() -> None:
    listing = collect_fixture("board_two_jobs").listings[0]

    assert listing.id == f"{SOURCE_KEY}:4968083003"


def test_the_description_is_decoded_exactly_once() -> None:
    listing = collect_fixture("board_two_jobs").listings[0]

    assert listing.description_raw.startswith("<p><strong>About the role</strong></p>")
    # The company's own text contains an ampersand, which survives one decode.
    assert "tools &amp; pipelines" in listing.description_raw


def test_decoding_twice_would_corrupt_the_company_text() -> None:
    """Pins why 'exactly once' is stated rather than assumed to be harmless."""
    listing = collect_fixture("board_two_jobs").listings[0]
    twice = html.unescape(listing.description_raw)

    assert twice != listing.description_raw
    assert "tools & pipelines" in twice


def test_the_publication_date_is_converted_to_utc() -> None:
    """The API sends an offset, not UTC."""
    listing = collect_fixture("board_two_jobs").listings[0]

    assert listing.published_at == datetime(2026, 2, 11, 17, 55, 28, tzinfo=UTC)
    assert listing.published_at is not None
    assert listing.published_at.tzinfo == UTC


def test_the_location_is_kept_exactly_as_published() -> None:
    """Sorting out inconsistent real-world spellings is the normalizer's job.

    The dotless and dotted i here are the point of the test, not a typo: real
    boards publish Turkish place names and the collector must not touch them.
    """
    listing = collect_fixture("board_two_jobs").listings[0]

    assert listing.location_raw == "Kadıköy, İstanbul"  # noqa: RUF001


def test_the_company_name_comes_from_our_configuration() -> None:
    """The board also sends one, but ours is what we monitor it under."""
    result = collect_fixture("board_two_jobs", name="Renamed Studio")

    assert result.listings[0].company_name == "Renamed Studio"


def test_an_empty_board_is_not_a_failure() -> None:
    result = collect_fixture("board_empty")

    assert result.found == 0
    assert result.listings == ()
    assert result.warnings == ()


def test_absent_optional_fields_become_none() -> None:
    listing = collect_fixture("board_minimal_fields").listings[0]

    assert listing.published_at is None
    assert listing.location_raw is None


def test_the_board_is_requested_once_and_nothing_else_is() -> None:
    """No N+1 follow-up to the single-job endpoint."""
    fetcher = FakeFetcher(load_fixture("board_two_jobs"))
    make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert fetcher.requested == [BOARD_URL]


# -- postings that cannot be mapped ---------------------------------------


def test_one_unusable_posting_does_not_cost_the_others() -> None:
    result = collect_fixture("board_partial")

    assert result.found == 2
    assert len(result.listings) == 1
    assert len(result.warnings) == 1
    assert "content" in result.warnings[0]


@pytest.mark.parametrize("field", ["title", "content", "absolute_url"])
def test_a_missing_required_field_skips_only_that_posting(field: str) -> None:
    payload = {"jobs": [a_job(**{field: None}), a_job(id=4968083003)], "meta": {"total": 2}}

    result = collect_payload(payload)

    assert result.found == 2
    assert len(result.listings) == 1
    assert result.warnings == (f"job at index 0 (id 5095371003): missing or blank '{field}'",)


def test_an_entry_that_is_not_an_object_is_skipped() -> None:
    result = collect_payload({"jobs": ["not a job", a_job()], "meta": {"total": 2}})

    assert result.found == 2
    assert len(result.listings) == 1
    assert result.warnings == ("job at index 0: entry was not an object",)


def test_a_posting_the_model_rejects_is_skipped() -> None:
    result = collect_fixture("board_unmappable_job")

    assert result.found == 2
    assert len(result.listings) == 1
    assert len(result.warnings) == 1
    assert "application_url" in result.warnings[0]


def test_an_unusable_publication_date_keeps_the_posting() -> None:
    """Losing an optional date is not worth losing the job over."""
    result = collect_payload({"jobs": [a_job(first_published="not a date")], "meta": {"total": 1}})

    assert len(result.listings) == 1
    assert result.listings[0].published_at is None
    assert result.warnings == (
        "job at index 0 (id 5095371003): unusable 'first_published', continuing without it",
    )


def test_a_naive_publication_date_is_not_invented_into_a_timezone() -> None:
    result = collect_payload(
        {"jobs": [a_job(first_published="2026-06-30T08:00:00")], "meta": {"total": 1}},
    )

    assert result.listings[0].published_at is None


# -- id validation ---------------------------------------------------------


@pytest.mark.parametrize(
    "bad_id",
    [MISSING, None, "5095371003", 12.0, 3.7, True, False, [1, 2], {"a": 1}, 0, -5],
    ids=[
        "missing",
        "null",
        "string",
        "float_whole",
        "float",
        "true",
        "false",
        "list",
        "object",
        "zero",
        "negative",
    ],
)
def test_only_a_positive_integer_id_is_accepted(bad_id: object) -> None:
    """A blind str() here would persist 'None' or 'True' as a job's identity."""
    broken = a_job()
    if bad_id is MISSING:
        del broken["id"]
    else:
        broken["id"] = bad_id

    result = collect_payload({"jobs": [broken, a_job(id=4968083003)], "meta": {"total": 2}})

    assert result.found == 2, "the board still returned two entries"
    assert len(result.listings) == 1
    assert result.listings[0].external_id == "4968083003"
    assert result.warnings == ("job at index 0: unusable 'id'",)


@pytest.mark.parametrize("bad_id", ["5095371003", True, -5, {"a": 1}])
def test_a_rejected_id_is_never_echoed_back(bad_id: object) -> None:
    """An id that failed validation is untrusted payload, so it is not repeated."""
    result = collect_payload({"jobs": [a_job(id=bad_id)], "meta": {"total": 1}})

    assert result.warnings == ("job at index 0: unusable 'id'",)
    assert str(bad_id) not in result.warnings[0]


def test_a_positive_integer_id_is_accepted() -> None:
    result = collect_payload({"jobs": [a_job(id=1)], "meta": {"total": 1}})

    assert result.listings[0].external_id == "1"
    assert result.warnings == ()


# -- warnings never quote the payload -------------------------------------


def test_a_failing_posting_never_leaks_its_description() -> None:
    """Pydantic's own error text embeds input_value, which would be the job ad."""
    result = collect_fixture("board_unmappable_job")
    everything = " ".join(result.warnings)

    assert "DESCRIPTIONMARKER" not in everything
    assert "URLMARKER" not in everything
    assert "input_value" not in everything


def test_a_failing_posting_still_says_which_one_it_was() -> None:
    """Sanitized is not the same as useless."""
    result = collect_fixture("board_unmappable_job")

    assert result.warnings[0] == (
        "job at index 1 (id 5095371003): invalid application_url (url_parsing)"
    )


def test_a_long_description_is_not_copied_into_a_blank_field_warning() -> None:
    marker = "LEAKMARKER" + "x" * 200
    payload = {"jobs": [a_job(title="   ", content=marker)], "meta": {"total": 1}}

    result = collect_payload(payload)

    assert "LEAKMARKER" not in " ".join(result.warnings)


# -- meta ------------------------------------------------------------------


def test_a_correct_total_says_nothing() -> None:
    assert collect_fixture("board_two_jobs").warnings == ()


def test_an_absent_meta_says_nothing() -> None:
    """meta is optional metadata, not something the mapping depends on."""
    assert collect_fixture("board_no_meta").warnings == ()


def test_a_meta_without_a_total_says_nothing() -> None:
    result = collect_payload({"jobs": [a_job()], "meta": {"something_else": 1}})

    assert result.warnings == ()
    assert len(result.listings) == 1


def test_a_meta_that_is_not_an_object_warns() -> None:
    result = collect_fixture("board_bad_meta")

    assert result.warnings == ("board response 'meta' was not an object",)
    assert len(result.listings) == 1, "mapping still continues"


@pytest.mark.parametrize("total", ["1", 1.0, 1.5, -1, True, False, None, [1], {"n": 1}])
def test_a_total_that_is_not_a_non_negative_integer_warns(total: object) -> None:
    result = collect_payload({"jobs": [a_job()], "meta": {"total": total}})

    assert result.warnings == ("board response 'meta.total' was not a non-negative integer",)
    assert len(result.listings) == 1


def test_a_total_that_disagrees_with_the_payload_warns() -> None:
    """The first sign of Greenhouse introducing pagination would look like this."""
    result = collect_fixture("board_total_mismatch")

    assert result.warnings == ("board reported 7 jobs but returned 1",)
    assert len(result.listings) == 1


def test_a_total_of_zero_on_an_empty_board_is_fine() -> None:
    assert collect_payload({"jobs": [], "meta": {"total": 0}}).warnings == ()


# -- responses that cannot be used at all ---------------------------------


def test_a_body_that_is_not_json() -> None:
    with pytest.raises(CollectorError, match="not valid JSON"):
        collect_body("<html>maintenance</html>")


@pytest.mark.parametrize("payload", [[], "text", 12, None, True])
def test_a_body_that_is_not_an_object(payload: object) -> None:
    with pytest.raises(CollectorError, match="not a JSON object"):
        collect_payload(payload)


def test_a_response_without_a_jobs_array() -> None:
    with pytest.raises(CollectorError, match="no 'jobs' array"):
        collect_payload({"meta": {"total": 0}})


@pytest.mark.parametrize("jobs", ["", 0, {"a": 1}, None])
def test_a_jobs_field_that_is_not_an_array(jobs: object) -> None:
    with pytest.raises(CollectorError, match="'jobs' was not an array"):
        collect_payload({"jobs": jobs})


def test_a_collector_error_names_its_source() -> None:
    with pytest.raises(CollectorError) as caught:
        collect_body("not json")

    assert caught.value.source_key == SOURCE_KEY


# -- through the real HTTP layer -------------------------------------------


def test_a_board_read_through_the_real_fetcher(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    board = router.get(BOARD_URL).respond(200, text=load_fixture("board_two_jobs"))
    single = router.get(SINGLE_JOB_URL).respond(200, text="{}")

    with make_fetcher(clock) as fetcher:
        result = GreenhouseCollector(fetcher, make_company()).collect(discovered_at=DISCOVERED_AT)

    assert len(result.listings) == 2
    assert board.call_count == 1
    assert not single.called, "no N+1 follow-up on individual postings"


def test_robots_denial_reaches_the_caller(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    """Collectors do not swallow their own failures."""
    router.get(ROBOTS_URL).respond(200, text=DISALLOW_ALL)
    board = router.get(BOARD_URL).respond(200, text=load_fixture("board_two_jobs"))

    with make_fetcher(clock) as fetcher, pytest.raises(RobotsDisallowedError):
        GreenhouseCollector(fetcher, make_company()).collect(discovered_at=DISCOVERED_AT)

    assert not board.called


def test_an_unknown_board_token_reaches_the_caller(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(BOARD_URL).respond(404)

    with make_fetcher(clock) as fetcher, pytest.raises(HttpStatusError) as caught:
        GreenhouseCollector(fetcher, make_company()).collect(discovered_at=DISCOVERED_AT)

    assert caught.value.status_code == 404


def test_the_user_agent_identifies_us_to_the_board(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(BOARD_URL).respond(200, text=load_fixture("board_two_jobs"))

    with make_fetcher(clock) as fetcher:
        GreenhouseCollector(fetcher, make_company()).collect(discovered_at=DISCOVERED_AT)

    for call in router.calls:
        assert "gamejob-scout" in call.request.headers["user-agent"]
