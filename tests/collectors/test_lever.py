"""The Lever collector: mapping, composition, pagination, and sanitized warnings.

Lever paginates, so the fake fetcher here serves a *sequence* of bodies and records
the URLs it was asked for — that is how the `skip` progression gets asserted. The
end-to-end tests at the bottom go through the real `HttpFetcher` with respx.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import pytest
import respx

from gamejob_scout.collectors import (
    LEVER_MAX_ID_LENGTH,
    LEVER_MAX_PAGES,
    LEVER_PAGE_SIZE,
    CollectionResult,
    Collector,
    CollectorError,
    LeverCollector,
    compose_description,
    lever_board_url,
    lever_postings_url,
    lever_source_key,
)
from gamejob_scout.domain import ATSKind, Company
from gamejob_scout.http import FetchedDocument, HttpStatusError, RobotsDisallowedError
from tests.collectors.test_greenhouse import NOT_A_SLUG
from tests.factories import DISCOVERED_AT, make_company
from tests.http.conftest import ALLOW_ALL, DISALLOW_ALL, FakeClock, make_fetcher

FIXTURES: Final = Path(__file__).parent / "fixtures" / "lever"

SITE: Final = "examplestudio"
BOARD_URL: Final = "https://api.lever.co/v0/postings/examplestudio?mode=json"
ROBOTS_URL: Final = "https://api.lever.co/robots.txt"
SOURCE_KEY: Final = "example-studio-lever-examplestudio"

ROBOTS_WITH_CRAWL_DELAY: Final = "User-agent: *\nAllow: /\nCrawl-delay: 1\n"

FIRST_ID: Final = "79b732cb-96d7-4792-b7bb-be5c48fa2218"
SECOND_ID: Final = "c1d2e3f4-a5b6-4788-9900-112233445566"

MISSING: Final = object()
"""Sentinel for a key that should be absent entirely rather than set to None."""


def page_url(skip: int) -> str:
    return f"https://api.lever.co/v0/postings/{SITE}?mode=json&skip={skip}&limit={LEVER_PAGE_SIZE}"


class FakeFetcher:
    """Serves a queue of bodies and remembers every URL it was asked for.

    No cast is needed: this satisfies `JobBoardFetcher` structurally, which is the
    whole point of that protocol.
    """

    def __init__(self, *bodies: str) -> None:
        self.bodies = list(bodies)
        self.requested: list[str] = []

    def get(self, url: str) -> FetchedDocument:
        self.requested.append(url)
        body = self.bodies.pop(0) if self.bodies else "[]"
        return FetchedDocument(url=url, status_code=200, headers={}, text=body)


def load_fixture(fixture_name: str) -> str:
    return (FIXTURES / f"{fixture_name}.json").read_text(encoding="utf-8")


def make_collector(fetcher: FakeFetcher, **company_overrides: Any) -> LeverCollector:
    defaults: dict[str, Any] = {"ats": ATSKind.LEVER, "ats_identifier": SITE}
    return LeverCollector(fetcher, make_company(**{**defaults, **company_overrides}))


def collect_bodies(*bodies: str, **company_overrides: Any) -> CollectionResult:
    fetcher = FakeFetcher(*bodies)
    return make_collector(fetcher, **company_overrides).collect(discovered_at=DISCOVERED_AT)


def collect_fixture(fixture_name: str, **company_overrides: Any) -> CollectionResult:
    return collect_bodies(load_fixture(fixture_name), **company_overrides)


def collect_payload(payload: object, **company_overrides: Any) -> CollectionResult:
    return collect_bodies(json.dumps(payload), **company_overrides)


def a_posting(**overrides: Any) -> dict[str, Any]:
    """A posting shaped like the real API returns them."""
    posting: dict[str, Any] = {
        "id": SECOND_ID,
        "text": "Junior Technical Artist",
        "createdAt": 1784531218896,
        "categories": {"location": "Remote - Europe"},
        "description": "<div>Art pipeline work.</div>",
        "lists": [],
        "additional": "",
        "hostedUrl": f"https://example.com/{SITE}/{SECOND_ID}",
    }
    posting.update(overrides)
    return posting


def postings(count: int, *, start: int = 0) -> list[dict[str, Any]]:
    """`count` distinct postings, numbered so their IDs are predictable."""
    return [a_posting(id=f"id-{start + n:04d}") for n in range(count)]


if TYPE_CHECKING:

    def _static_conformance(collector: LeverCollector) -> Collector:
        """Checked by mypy, never executed, constructs nothing."""
        return collector


# -- URLs and identity -----------------------------------------------------


def test_the_board_url_is_canonical() -> None:
    """No skip or limit, so provenance reads the same however many pages a run needed."""
    assert lever_board_url(SITE) == BOARD_URL


def test_the_postings_url_carries_pagination() -> None:
    assert lever_postings_url(SITE, skip=40, limit=20) == (
        f"https://api.lever.co/v0/postings/{SITE}?mode=json&skip=40&limit=20"
    )


def test_the_postings_url_defaults_to_a_full_page() -> None:
    assert lever_postings_url(SITE) == page_url(0)


@pytest.mark.parametrize("site", NOT_A_SLUG)
def test_the_url_helpers_refuse_a_site_that_is_not_a_slug(site: str) -> None:
    """Path-shaped tokens matter most: refusing them keeps a bad site out of a URL."""
    with pytest.raises(ValueError, match="lever site"):
        lever_board_url(site)
    with pytest.raises(ValueError, match="lever site"):
        lever_postings_url(site)


@pytest.mark.parametrize(
    ("skip", "limit"),
    [
        (-1, LEVER_PAGE_SIZE),
        (0, 0),
        (0, LEVER_PAGE_SIZE + 1),
        (True, LEVER_PAGE_SIZE),
        (False, LEVER_PAGE_SIZE),
        (0, True),
        (0, False),
        (1.5, LEVER_PAGE_SIZE),
        (0, 1.5),
    ],
)
def test_the_postings_url_validates_its_pagination(skip: Any, limit: Any) -> None:
    """It is public, so it cannot be laxer than the collector's own loop."""
    # A deliberate alternation: the message names whichever argument was wrong.
    with pytest.raises(ValueError, match=r"skip|limit"):
        lever_postings_url(SITE, skip=skip, limit=limit)


@pytest.mark.parametrize(
    ("skip", "limit"),
    [(0, 1), (0, LEVER_PAGE_SIZE), (999, 50)],
)
def test_the_postings_url_accepts_the_boundaries(skip: int, limit: int) -> None:
    assert f"skip={skip}&limit={limit}" in lever_postings_url(SITE, skip=skip, limit=limit)


def test_the_source_key_includes_the_site() -> None:
    """Two Lever sites for one company must not collide."""
    assert lever_source_key(make_company(ats=ATSKind.LEVER, ats_identifier=SITE)) == SOURCE_KEY
    assert lever_source_key(make_company(ats=ATSKind.LEVER, ats_identifier="second")) == (
        "example-studio-lever-second"
    )


def test_the_source_key_helper_refuses_another_ats() -> None:
    with pytest.raises(ValueError, match="not 'lever'"):
        lever_source_key(make_company(ats=ATSKind.GREENHOUSE, ats_identifier=SITE))


def test_the_source_key_helper_refuses_a_missing_site() -> None:
    """Company forbids this, so the guard is checked past that validator."""
    company = Company.model_construct(
        key="example-studio",
        name="Example Studio",
        ats=ATSKind.LEVER,
        ats_identifier=None,
    )

    with pytest.raises(ValueError, match="no ats_identifier"):
        lever_source_key(company)


def test_the_source_key_helper_refuses_a_blank_site() -> None:
    company = Company.model_construct(
        key="example-studio",
        name="Example Studio",
        ats=ATSKind.LEVER,
        ats_identifier="",
    )

    with pytest.raises(ValueError, match="lever site"):
        lever_source_key(company)


def test_the_source_key_helper_validates_what_it_derived() -> None:
    company = Company.model_construct(
        key="Bad Key",
        name="Example Studio",
        ats=ATSKind.LEVER,
        ats_identifier=SITE,
    )

    with pytest.raises(ValueError, match="source key"):
        lever_source_key(company)


def test_a_collector_reports_its_identity() -> None:
    collector = make_collector(FakeFetcher())

    assert collector.source_key == SOURCE_KEY
    assert collector.company_key == "example-studio"
    assert collector.source is ATSKind.LEVER


def test_an_explicit_source_key_is_honoured() -> None:
    collector = LeverCollector(
        FakeFetcher(),
        make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        source_key="example-studio-emea-board",
    )

    assert collector.source_key == "example-studio-emea-board"


def test_an_explicit_source_key_must_still_be_a_slug() -> None:
    with pytest.raises(ValueError, match="source key"):
        LeverCollector(
            FakeFetcher(),
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
            source_key="Not A Slug",
        )


def test_a_company_on_another_ats_is_refused() -> None:
    with pytest.raises(ValueError, match="not 'lever'"):
        make_collector(FakeFetcher(), ats=ATSKind.GREENHOUSE, ats_identifier=SITE)


def test_the_collector_satisfies_the_protocol() -> None:
    assert isinstance(make_collector(FakeFetcher()), Collector)


# -- mapping ---------------------------------------------------------------


def test_a_board_maps_every_posting() -> None:
    result = collect_fixture("board_two_postings")

    assert result.found == 2
    assert len(result.listings) == 2
    assert result.warnings == ()


def test_each_field_comes_from_the_right_place() -> None:
    listing = collect_fixture("board_two_postings").listings[0]

    assert listing.source is ATSKind.LEVER
    assert listing.source_key == SOURCE_KEY
    assert str(listing.source_url) == BOARD_URL
    assert listing.external_id == FIRST_ID
    assert listing.company_key == "example-studio"
    assert listing.title == "Gameplay Programmer"
    assert listing.location_raw == "Kadikoy, Istanbul"
    assert listing.discovered_at == DISCOVERED_AT


def test_the_application_url_is_the_posting_page_not_the_form() -> None:
    """applyUrl is ignored: a person should read the role before a form."""
    listing = collect_fixture("board_two_postings").listings[0]

    assert str(listing.application_url) == f"https://example.com/{SITE}/{FIRST_ID}"
    assert not str(listing.application_url).endswith("/apply")


def test_the_identity_is_the_source_key_and_the_posting_id() -> None:
    listing = collect_fixture("board_two_postings").listings[0]

    assert listing.id == f"{SOURCE_KEY}:{FIRST_ID}"


def test_the_company_name_comes_from_our_configuration() -> None:
    result = collect_fixture("board_two_postings", name="Renamed Studio")

    assert result.listings[0].company_name == "Renamed Studio"


def test_an_absent_location_becomes_none() -> None:
    result = collect_payload([a_posting(categories={})])

    assert result.listings[0].location_raw is None


def test_a_missing_categories_object_becomes_none() -> None:
    result = collect_payload([a_posting(categories=None)])

    assert result.listings[0].location_raw is None


def test_an_empty_board_is_not_a_failure() -> None:
    result = collect_fixture("board_empty")

    assert result.found == 0
    assert result.listings == ()
    assert result.warnings == ()


# -- no publication timestamp ---------------------------------------------


def test_published_at_is_always_none() -> None:
    """Lever publishes no publication timestamp, and createdAt is not one."""
    result = collect_fixture("board_two_postings")

    assert all(listing.published_at is None for listing in result.listings)


def test_created_at_is_not_smuggled_into_any_field() -> None:
    """The fixture carries createdAt, so this pins the decision rather than luck."""
    payload = json.loads(load_fixture("board_two_postings"))
    assert payload[0]["createdAt"] == 1766401978539, "fixture must still carry createdAt"

    listing = collect_fixture("board_two_postings").listings[0]
    created = datetime.fromtimestamp(1766401978539 / 1000, UTC)

    assert listing.published_at is None
    assert listing.discovered_at != created


# -- description composition ----------------------------------------------


def test_a_description_with_lists_and_additional_is_composed_in_order() -> None:
    listing = collect_fixture("board_two_postings").listings[0]
    body = listing.description_raw

    assert body.startswith("<div>We are looking for a Gameplay Programmer")
    assert body.index("Responsibilities") < body.index("Requirements")
    assert body.index("Requirements") < body.index("We review every application")
    assert "<ul>\n<li>Build and maintain gameplay systems</li>" in body


def test_requirements_survive_when_they_live_only_in_lists() -> None:
    """The real board did this on every posting; `description` alone loses them."""
    listing = collect_fixture("board_only_lists").listings[0]

    assert "Strong C++ and debugging skills" in listing.description_raw
    assert "<h3>Requirements</h3>" in listing.description_raw


def test_a_description_without_lists_is_left_alone() -> None:
    listing = collect_fixture("board_no_lists").listings[0]

    assert listing.description_raw == "<div>Gameplay systems work in C++.</div>"


def test_nothing_is_unescaped() -> None:
    """An ampersand in the company's own text must survive as they wrote it."""
    listing = collect_fixture("board_two_postings").listings[0]

    assert "tools &amp; pipelines" in listing.description_raw


def test_a_list_name_is_html_escaped() -> None:
    """An unescaped & or < in a list name would produce broken markup."""
    posting = a_posting(lists=[{"text": "R&D <tools>", "content": "<li>Work</li>"}])

    body = compose_description(posting)

    assert "<h3>R&amp;D &lt;tools&gt;</h3>" in body
    assert "<h3>R&D <tools></h3>" not in body


def test_a_list_with_blank_content_is_skipped() -> None:
    posting = a_posting(
        lists=[
            {"text": "Requirements", "content": "   "},
            {"text": "Perks", "content": "<li>A</li>"},
        ],
    )

    body = compose_description(posting)

    assert "Requirements" not in body
    assert "<h3>Perks</h3>" in body


def test_a_list_without_a_name_keeps_its_items() -> None:
    posting = a_posting(lists=[{"text": "", "content": "<li>Ship features</li>"}])

    body = compose_description(posting)

    assert "<h3>" not in body
    assert "<section><ul><li>Ship features</li></ul></section>" in body


def test_a_malformed_list_entry_is_ignored() -> None:
    posting = a_posting(lists=["not an object", {"text": "Perks", "content": "<li>A</li>"}])

    assert compose_description(posting).count("<section>") == 1


def test_composition_is_byte_stable() -> None:
    """A stable composition is what keeps the content hash meaningful."""
    posting = a_posting(lists=[{"text": "Requirements", "content": "<li>C++</li>"}])

    assert compose_description(posting) == compose_description(dict(posting))


def test_identical_postings_hash_identically() -> None:
    first = collect_fixture("board_two_postings").listings[0]
    second = collect_fixture("board_two_postings").listings[0]

    assert first.content_hash == second.content_hash


def test_a_posting_with_no_description_anywhere_is_skipped() -> None:
    result = collect_fixture("board_blank_description")

    assert result.found == 1
    assert result.listings == ()
    assert result.warnings == (
        f"posting at index 0 (id {FIRST_ID}): no description content in any field",
    )


# -- id validation ---------------------------------------------------------


@pytest.mark.parametrize(
    "posting_id",
    [
        FIRST_ID,
        "12345",
        "abc-DEF_123",
        "x",
        "a" * LEVER_MAX_ID_LENGTH,
    ],
    ids=["uuid", "numeric", "mixed_case_underscore", "single_char", "max_length"],
)
def test_an_opaque_id_is_accepted_verbatim(posting_id: str) -> None:
    """Lever documents only "a unique posting ID", so the shape is not constrained."""
    result = collect_payload([a_posting(id=posting_id)])

    assert result.listings[0].external_id == posting_id
    assert result.warnings == ()


def test_valid_non_uuid_ids_all_map() -> None:
    result = collect_fixture("board_opaque_ids")

    assert result.found == 3
    assert [listing.external_id for listing in result.listings] == ["12345", "abc-DEF_123", "x"]
    assert result.warnings == ()


@pytest.mark.parametrize(
    "bad_id",
    [
        MISSING,
        None,
        12345,
        1.5,
        True,
        False,
        ["a"],
        {"a": 1},
        "",
        "   ",
        "a:b",
        "a b",
        "a\tb",
        "a\nb",
        "a\x00b",
        "a" * (LEVER_MAX_ID_LENGTH + 1),
    ],
    ids=[
        "missing",
        "null",
        "int",
        "float",
        "true",
        "false",
        "list",
        "object",
        "blank",
        "whitespace",
        "colon",
        "space",
        "tab",
        "newline",
        "control",
        "too_long",
    ],
)
def test_an_unsafe_id_skips_only_that_posting(bad_id: object) -> None:
    """external_id becomes half of a persisted primary key, so it is checked first."""
    broken = a_posting()
    if bad_id is MISSING:
        del broken["id"]
    else:
        broken["id"] = bad_id

    result = collect_payload([broken, a_posting(id=FIRST_ID)])

    assert result.found == 2, "the board still returned two entries"
    assert len(result.listings) == 1
    assert result.listings[0].external_id == FIRST_ID
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("posting at index 0: unusable 'id'")


@pytest.mark.parametrize("bad_id", ["a:b", "a b", "a" * 200, {"a": 1}, 12345])
def test_a_rejected_id_is_never_echoed_back(bad_id: object) -> None:
    result = collect_payload([a_posting(id=bad_id)])

    assert len(result.warnings) == 1
    assert str(bad_id) not in result.warnings[0]


def test_a_duplicate_id_is_kept_once() -> None:
    result = collect_payload([a_posting(id=FIRST_ID), a_posting(id=FIRST_ID)])

    assert result.found == 2
    assert len(result.listings) == 1
    assert result.warnings == (
        f"posting at index 1 (id {FIRST_ID}): duplicate id, keeping the first occurrence",
    )


# -- postings that cannot be mapped ---------------------------------------


def test_one_unusable_posting_does_not_cost_the_others() -> None:
    result = collect_fixture("board_partial")

    assert result.found == 2
    assert len(result.listings) == 1
    assert result.warnings == (f"posting at index 1 (id {SECOND_ID}): missing or blank 'text'",)


@pytest.mark.parametrize("field", ["text", "hostedUrl"])
def test_a_missing_required_field_skips_only_that_posting(field: str) -> None:
    result = collect_payload([a_posting(**{field: None}), a_posting(id=FIRST_ID)])

    assert result.found == 2
    assert len(result.listings) == 1
    assert result.warnings == (f"posting at index 0 (id {SECOND_ID}): missing or blank {field!r}",)


def test_an_entry_that_is_not_an_object_is_skipped() -> None:
    result = collect_payload(["not a posting", a_posting()])

    assert result.found == 2
    assert len(result.listings) == 1
    assert result.warnings == ("posting at index 0: entry was not an object",)


def test_a_posting_the_model_rejects_is_skipped() -> None:
    result = collect_fixture("board_unmappable")

    assert result.found == 2
    assert len(result.listings) == 1
    assert len(result.warnings) == 1
    assert "application_url" in result.warnings[0]


# -- warnings never quote the payload -------------------------------------


def test_a_failing_posting_never_leaks_its_description() -> None:
    """Pydantic's own error text embeds input_value, which would be the job ad."""
    result = collect_fixture("board_unmappable")
    everything = " ".join(result.warnings)

    assert "DESCRIPTIONMARKER" not in everything
    assert "URLMARKER" not in everything
    assert "input_value" not in everything


def test_a_failing_posting_still_says_which_one_it_was() -> None:
    result = collect_fixture("board_unmappable")

    assert result.warnings[0] == (
        f"posting at index 1 (id {SECOND_ID}): invalid application_url (url_parsing)"
    )


def test_a_long_description_is_not_copied_into_a_blank_field_warning() -> None:
    marker = "LEAKMARKER" + "x" * 200
    result = collect_payload([a_posting(text="   ", description=f"<div>{marker}</div>")])

    assert "LEAKMARKER" not in " ".join(result.warnings)


# -- pagination ------------------------------------------------------------


def test_a_short_board_still_confirms_the_end() -> None:
    """`limit` means "at most N", so a short page proves nothing on its own."""
    fetcher = FakeFetcher(json.dumps(postings(2)), "[]")
    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert result.found == 2
    assert fetcher.requested == [page_url(0), page_url(2)]


def test_an_empty_board_needs_one_request() -> None:
    fetcher = FakeFetcher("[]")
    make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert fetcher.requested == [page_url(0)]


def test_a_full_page_is_followed_by_another() -> None:
    fetcher = FakeFetcher(json.dumps(postings(LEVER_PAGE_SIZE)), "[]")
    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert result.found == LEVER_PAGE_SIZE
    assert fetcher.requested == [page_url(0), page_url(LEVER_PAGE_SIZE)]


def test_skip_advances_by_the_count_actually_returned() -> None:
    """Not by the requested limit, which the API never promises to fill."""
    fetcher = FakeFetcher(
        json.dumps(postings(LEVER_PAGE_SIZE)),
        json.dumps(postings(7, start=500)),
        "[]",
    )
    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert result.found == LEVER_PAGE_SIZE + 7
    assert fetcher.requested == [
        page_url(0),
        page_url(LEVER_PAGE_SIZE),
        page_url(LEVER_PAGE_SIZE + 7),
    ]
    assert result.warnings == ()


def test_the_page_bound_stops_the_loop_and_says_so() -> None:
    bodies = [json.dumps(postings(LEVER_PAGE_SIZE, start=n * 100)) for n in range(LEVER_MAX_PAGES)]
    fetcher = FakeFetcher(*bodies)

    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert len(fetcher.requested) == LEVER_MAX_PAGES
    assert result.found == LEVER_MAX_PAGES * LEVER_PAGE_SIZE
    assert result.warnings == (
        f"stopped after {LEVER_MAX_PAGES} pages; collection may be incomplete",
    )


def test_a_board_that_ignores_skip_is_caught() -> None:
    """Without this guard a repeated page would loop to the page bound."""
    same = json.dumps(postings(3))
    fetcher = FakeFetcher(same, same, same)

    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert len(fetcher.requested) == 2, "stopped as soon as the repeat was seen"
    assert result.found == 3
    assert len(result.listings) == 3
    assert result.warnings == ("board repeated a page of postings; stopping pagination",)


def test_a_page_of_unusable_ids_does_not_stop_pagination() -> None:
    """The regression guard for the vacuous-subset trap.

    A page whose IDs all fail validation yields an empty set of validated IDs, and
    an empty set is a subset of anything — so a naive `page_ids <= seen` check
    would stop here and silently truncate the board.
    """
    bad_page = json.dumps([a_posting(id=None), a_posting(id="a:b")])
    good_page = json.dumps(postings(2, start=900))
    fetcher = FakeFetcher(bad_page, good_page, "[]")

    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert len(fetcher.requested) == 3, "the loop continued past the unusable page"
    assert result.found == 4
    assert len(result.listings) == 2, "the later page's postings were still collected"
    assert len(result.warnings) == 2, "each bad posting was reported individually"
    assert all("unusable 'id'" in warning for warning in result.warnings)


def test_indexes_keep_counting_across_pages() -> None:
    fetcher = FakeFetcher(
        json.dumps(postings(2)),
        json.dumps([a_posting(id="a:b")]),
        "[]",
    )

    result = make_collector(fetcher).collect(discovered_at=DISCOVERED_AT)

    assert result.warnings == (
        "posting at index 2: unusable 'id' (contains whitespace, a colon, or a control character)",
    )


# -- responses that cannot be used at all ---------------------------------


def test_a_body_that_is_not_json() -> None:
    with pytest.raises(CollectorError, match="not valid JSON"):
        collect_bodies("<html>maintenance</html>")


@pytest.mark.parametrize("payload", [{"jobs": []}, "text", 12, None, True])
def test_a_body_that_is_not_an_array(payload: object) -> None:
    """Lever returns a bare array; an envelope means something changed."""
    with pytest.raises(CollectorError, match="not a JSON array"):
        collect_payload(payload)


def test_a_later_page_that_is_not_an_array() -> None:
    with pytest.raises(CollectorError, match="not a JSON array"):
        collect_bodies(json.dumps(postings(LEVER_PAGE_SIZE)), '{"jobs": []}')


def test_a_collector_error_names_its_source() -> None:
    with pytest.raises(CollectorError) as caught:
        collect_bodies("not json")

    assert caught.value.source_key == SOURCE_KEY


# -- through the real HTTP layer -------------------------------------------


def test_a_board_read_through_the_real_fetcher(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    """Lever asks for Crawl-delay: 1, which our default interval already matches."""
    router.get(ROBOTS_URL).respond(200, text=ROBOTS_WITH_CRAWL_DELAY)
    first = router.get(page_url(0)).respond(200, text=load_fixture("board_two_postings"))
    second = router.get(page_url(2)).respond(200, text="[]")

    with make_fetcher(clock) as fetcher:
        result = LeverCollector(
            fetcher,
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        ).collect(discovered_at=DISCOVERED_AT)

    assert len(result.listings) == 2
    assert first.call_count == 1
    assert second.call_count == 1
    assert clock.sleeps == [1.0, 1.0], "robots, then each page, spaced by one second"


def test_a_two_page_board_end_to_end(router: respx.MockRouter, clock: FakeClock) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(page_url(0)).respond(200, text=json.dumps(postings(LEVER_PAGE_SIZE)))
    router.get(page_url(LEVER_PAGE_SIZE)).respond(200, text=json.dumps(postings(3, start=900)))
    router.get(page_url(LEVER_PAGE_SIZE + 3)).respond(200, text="[]")

    with make_fetcher(clock) as fetcher:
        result = LeverCollector(
            fetcher,
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        ).collect(discovered_at=DISCOVERED_AT)

    assert result.found == LEVER_PAGE_SIZE + 3
    assert len(router.calls) == 4, "robots plus three pages"


def test_robots_denial_reaches_the_caller(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=DISALLOW_ALL)
    page = router.get(page_url(0)).respond(200, text="[]")

    with make_fetcher(clock) as fetcher, pytest.raises(RobotsDisallowedError):
        LeverCollector(
            fetcher,
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        ).collect(discovered_at=DISCOVERED_AT)

    assert not page.called


def test_an_unknown_site_reaches_the_caller(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(page_url(0)).respond(404)

    with make_fetcher(clock) as fetcher, pytest.raises(HttpStatusError) as caught:
        LeverCollector(
            fetcher,
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        ).collect(discovered_at=DISCOVERED_AT)

    assert caught.value.status_code == 404


def test_the_hosted_board_host_is_never_requested(
    router: respx.MockRouter,
    clock: FakeClock,
) -> None:
    """jobs.lever.co robots disallows AI crawlers; we only talk to the API."""
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(page_url(0)).respond(200, text=load_fixture("board_two_postings"))
    router.get(page_url(2)).respond(200, text="[]")
    hosted = router.get(url__startswith="https://jobs.lever.co").respond(200, text="[]")

    with make_fetcher(clock) as fetcher:
        LeverCollector(
            fetcher,
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        ).collect(discovered_at=DISCOVERED_AT)

    assert not hosted.called
    for call in router.calls:
        assert "jobs.lever.co" not in str(call.request.url)


def test_the_user_agent_identifies_us(router: respx.MockRouter, clock: FakeClock) -> None:
    router.get(ROBOTS_URL).respond(200, text=ALLOW_ALL)
    router.get(page_url(0)).respond(200, text="[]")

    with make_fetcher(clock) as fetcher:
        LeverCollector(
            fetcher,
            make_company(ats=ATSKind.LEVER, ats_identifier=SITE),
        ).collect(discovered_at=DISCOVERED_AT)

    for call in router.calls:
        assert "gamejob-scout" in call.request.headers["user-agent"]
