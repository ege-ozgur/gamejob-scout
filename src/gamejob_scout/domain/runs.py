"""Reporting for an ingestion run.

One broken source must never end a run, so each source records its own outcome
in a :class:`SourceResult` and the :class:`RunReport` summarizes them.

Everything derived — durations, totals, the overall status — is a plain Python
property rather than a model field. Derived values therefore never get
serialized, which keeps these models round-trippable and makes it impossible for
a stored total to disagree with the sources it came from.
"""

from typing import Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from gamejob_scout.domain.enums import ATSKind, RunStatus
from gamejob_scout.domain.types import NonEmptyStr, Slug, UtcDatetime


class SourceResult(BaseModel):
    """What happened when we collected one careers source.

    ``source_key`` identifies the board, ``company_key`` the company that owns
    it. They are separate because one company may eventually run several boards,
    for example a regional ATS alongside a global one.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: Slug
    company_key: Slug
    source: ATSKind
    status: RunStatus
    started_at: UtcDatetime
    finished_at: UtcDatetime

    jobs_found: int = Field(default=0, ge=0)
    jobs_new: int = Field(default=0, ge=0)
    jobs_updated: int = Field(default=0, ge=0)
    jobs_unchanged: int = Field(default=0, ge=0)

    warnings: tuple[NonEmptyStr, ...] = ()
    """Recoverable failures: an unparseable posting, a truncated page of
    results, a row that would not persist. Not deduplicated — two identical
    warnings mean it happened twice."""

    message: str | None = None
    """Human-readable note. Required when the source failed or was skipped."""

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @model_validator(mode="after")
    def _check_outcome(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be earlier than started_at")

        accounted = self.jobs_new + self.jobs_updated + self.jobs_unchanged
        if accounted > self.jobs_found:
            raise ValueError(
                f"jobs_new + jobs_updated + jobs_unchanged ({accounted}) "
                f"cannot exceed jobs_found ({self.jobs_found})",
            )

        counts = (self.jobs_found, self.jobs_new, self.jobs_updated, self.jobs_unchanged)

        if self.status in (RunStatus.FAILED, RunStatus.SKIPPED):
            if self.message is None:
                raise ValueError(f"status {self.status.value!r} requires a message")
            if any(counts):
                raise ValueError(f"status {self.status.value!r} requires all counts to be zero")
        elif self.status is RunStatus.SUCCESS:
            if self.warnings:
                raise ValueError("status 'success' cannot carry warnings; use 'partial'")
            if self.message is not None:
                raise ValueError("status 'success' cannot carry a message; use 'partial'")
        elif not self.warnings and self.message is None:
            raise ValueError("status 'partial' requires warnings or a message explaining why")

        return self


class RunReport(BaseModel):
    """The outcome of one full ingestion run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: UUID = Field(default_factory=uuid4)
    started_at: UtcDatetime
    finished_at: UtcDatetime
    sources: tuple[SourceResult, ...] = ()

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    @property
    def status(self) -> RunStatus:
        """Overall outcome, derived from the sources we actually attempted.

        Skipped sources are ignored, except when everything was skipped: a run
        where nothing ran is not a success.
        """
        attempted = [source for source in self.sources if source.status is not RunStatus.SKIPPED]
        if not attempted:
            return RunStatus.SKIPPED

        outcomes = {source.status for source in attempted}
        if outcomes == {RunStatus.SUCCESS}:
            return RunStatus.SUCCESS
        if outcomes == {RunStatus.FAILED}:
            return RunStatus.FAILED
        return RunStatus.PARTIAL

    @property
    def jobs_found(self) -> int:
        return sum(source.jobs_found for source in self.sources)

    @property
    def jobs_new(self) -> int:
        return sum(source.jobs_new for source in self.sources)

    @property
    def jobs_updated(self) -> int:
        return sum(source.jobs_updated for source in self.sources)

    @property
    def jobs_unchanged(self) -> int:
        return sum(source.jobs_unchanged for source in self.sources)

    def _count_with_status(self, status: RunStatus) -> int:
        return sum(1 for source in self.sources if source.status is status)

    @property
    def sources_succeeded(self) -> int:
        return self._count_with_status(RunStatus.SUCCESS)

    @property
    def sources_partial(self) -> int:
        return self._count_with_status(RunStatus.PARTIAL)

    @property
    def sources_failed(self) -> int:
        return self._count_with_status(RunStatus.FAILED)

    @property
    def sources_skipped(self) -> int:
        return self._count_with_status(RunStatus.SKIPPED)

    @model_validator(mode="after")
    def _check_sources(self) -> Self:
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot be earlier than started_at")

        seen: set[str] = set()
        for source in self.sources:
            if source.source_key in seen:
                raise ValueError(f"duplicate source_key in run: {source.source_key!r}")
            seen.add(source.source_key)

            if source.started_at < self.started_at or source.finished_at > self.finished_at:
                raise ValueError(
                    f"source {source.source_key!r} ran outside the run's own time window",
                )

        return self
