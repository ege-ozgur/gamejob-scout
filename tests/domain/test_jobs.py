"""Identity and change detection for job listings.

Three properties matter most here and each has an explicit test:

* a listing survives a round trip through JSON unchanged;
* a wrong stored ID is rejected;
* a wrong stored content hash is rejected.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gamejob_scout.domain import HASHED_FIELDS, JobListing, make_job_id
from tests.factories import PUBLISHED_AT, make_job_listing

DERIVED_FIELDS_ADDED_IN_1_6 = [
    "description",
    "location",
    "workplace_type",
    "experience_level",
    "years_required_min",
    "years_required_max",
]


def test_round_trips_through_json() -> None:
    job = make_job_listing()

    assert JobListing.model_validate(job.model_dump(mode="json")) == job


def test_a_wrong_stored_id_is_rejected() -> None:
    payload = make_job_listing().model_dump(mode="json")
    payload["id"] = "greenhouse:example-studio:12345"

    with pytest.raises(ValidationError, match="id must be"):
        JobListing.model_validate(payload)


def test_a_wrong_stored_content_hash_is_rejected() -> None:
    payload = make_job_listing().model_dump(mode="json")
    payload["content_hash"] = "0" * 64

    with pytest.raises(ValidationError, match="content_hash does not match"):
        JobListing.model_validate(payload)


def test_a_malformed_content_hash_is_rejected() -> None:
    payload = make_job_listing().model_dump(mode="json")
    payload["content_hash"] = "not-a-digest"

    with pytest.raises(ValidationError, match="content_hash"):
        JobListing.model_validate(payload)


def test_the_same_posting_always_gets_the_same_identity() -> None:
    first = make_job_listing()
    second = make_job_listing()

    assert first.id == second.id
    assert first.content_hash == second.content_hash


def test_the_id_is_built_from_the_source_and_its_own_job_id() -> None:
    job = make_job_listing()

    assert job.id == "example-studio-greenhouse:12345"
    assert job.id == make_job_id(job.source_key, job.external_id)


def test_the_hash_is_a_lowercase_sha256_digest() -> None:
    digest = make_job_listing().content_hash

    assert len(digest) == 64
    assert digest == digest.lower()
    assert set(digest) <= set("0123456789abcdef")


def test_hashed_fields_are_pinned() -> None:
    """Adding a field to the model must not silently change every stored hash."""
    assert HASHED_FIELDS == (
        "title",
        "location_raw",
        "description_raw",
        "published_at",
        "application_url",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("discovered_at", datetime(2027, 1, 1, 0, 0, tzinfo=UTC)),
        ("company_name", "Example Studio (EMEA)"),
        ("source_url", "https://example.com/boards/examplestudio-eu"),
        ("company_key", "example-studio-eu"),
    ],
)
def test_the_hash_ignores_anything_we_did_not_get_from_the_posting(
    field: str,
    value: object,
) -> None:
    """Re-crawling, or renaming a company in our own config, is not an edit."""
    assert make_job_listing(**{field: value}).content_hash == make_job_listing().content_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "Senior Gameplay Programmer"),
        ("location_raw", "Ankara, Turkey"),
        ("description_raw", "<p>Work on rendering systems.</p>"),
        ("published_at", datetime(2026, 9, 2, 12, 30, tzinfo=UTC)),
        ("application_url", "https://example.com/jobs/12345/apply-now"),
    ],
)
def test_the_hash_follows_what_the_company_published(field: str, value: object) -> None:
    assert make_job_listing(**{field: value}).content_hash != make_job_listing().content_hash


def test_dropping_the_location_changes_the_hash() -> None:
    assert make_job_listing(location_raw=None).content_hash != make_job_listing().content_hash


def test_the_raw_description_is_stored_as_supplied() -> None:
    html = '<div class="content"><ul><li>Ship gameplay features</li></ul></div>'
    job = make_job_listing(description_raw=html)

    assert job.description_raw == html


def test_the_raw_description_keeps_its_outer_whitespace() -> None:
    """Source truth is stored character for character, padding included."""
    padded = " \n<div>Role</div>\t "
    job = make_job_listing(description_raw=padded)

    assert job.description_raw == padded
    assert JobListing.model_validate(job.model_dump(mode="json")).description_raw == padded


def test_outer_whitespace_alone_changes_the_content_hash() -> None:
    """If the posting's bytes changed, the hash changes. We do not decide what counts."""
    bare = make_job_listing(description_raw="<div>Role</div>")
    padded = make_job_listing(description_raw=" \n<div>Role</div>\t ")

    assert bare.content_hash != padded.content_hash


@pytest.mark.parametrize("blank", ["", "   ", "\n\t "])
def test_a_blank_raw_description_is_still_rejected(blank: str) -> None:
    with pytest.raises(ValidationError, match="description_raw"):
        make_job_listing(description_raw=blank)


@pytest.mark.parametrize("name", DERIVED_FIELDS_ADDED_IN_1_6)
def test_derived_fields_do_not_exist_yet(name: str) -> None:
    """They arrive in milestone 1.6, together with the normalizer that fills them."""
    assert name not in JobListing.model_fields


def test_a_scheduled_future_posting_is_accepted() -> None:
    future = datetime(2099, 1, 1, 0, 0, tzinfo=UTC)

    assert make_job_listing(published_at=future).published_at == future


def test_published_at_is_optional() -> None:
    assert make_job_listing(published_at=None).published_at is None


def test_timestamps_are_converted_to_utc() -> None:
    job = make_job_listing(published_at="2026-09-01T15:30:00+03:00")

    assert job.published_at == PUBLISHED_AT


def test_a_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="discovered_at"):
        make_job_listing(discovered_at=datetime(2026, 9, 11, 8, 1))


@pytest.mark.parametrize("field", ["external_id", "title", "company_name"])
def test_required_text_cannot_be_blank(field: str) -> None:
    with pytest.raises(ValidationError, match=field):
        make_job_listing(**{field: "   "})


def test_the_application_url_must_be_a_real_url() -> None:
    with pytest.raises(ValidationError, match="application_url"):
        make_job_listing(application_url="/jobs/12345/apply")


def test_the_source_key_must_be_a_slug() -> None:
    with pytest.raises(ValidationError, match="source_key"):
        make_job_listing(source_key="Example Studio Greenhouse")
