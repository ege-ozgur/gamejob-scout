"""The candidate side of matching.

:class:`CandidateProfile` deliberately holds no identifying information. A name
is not needed to decide whether a job fits, and this model is the payload that
later phases hand to a language model, so the less it carries the better. If the
dashboard ever needs a display name it belongs in UI configuration, outside this
model.
"""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from gamejob_scout.domain.enums import ExperienceLevel, WorkplaceType
from gamejob_scout.domain.types import NonEmptyStr, StringTuple

_DEFAULT_WORKPLACE_TYPES = (WorkplaceType.HYBRID, WorkplaceType.ON_SITE, WorkplaceType.REMOTE)


class Education(BaseModel):
    """One completed or in-progress qualification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    degree: NonEmptyStr
    field_of_study: NonEmptyStr
    institution: NonEmptyStr
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)


class Project(BaseModel):
    """One portfolio or course project worth showing to an employer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: NonEmptyStr
    summary: NonEmptyStr
    technologies: StringTuple = ()
    url: HttpUrl | None = None


class CandidateProfile(BaseModel):
    """What the candidate is looking for and what they bring to it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    headline: str | None = None

    target_roles: StringTuple
    excluded_roles: StringTuple = ()
    experience_level: ExperienceLevel
    years_of_experience: float = Field(default=0.0, ge=0.0, le=60.0)

    preferred_locations: StringTuple = ()
    acceptable_workplace_types: tuple[WorkplaceType, ...] = _DEFAULT_WORKPLACE_TYPES
    prefers_remote: bool = False
    authorized_to_work_in: StringTuple = ()
    willing_to_relocate: bool = False

    skills: StringTuple = ()
    programming_languages: StringTuple = ()
    game_engines: StringTuple = ()
    industries: StringTuple = ()

    education: tuple[Education, ...] = ()
    projects: tuple[Project, ...] = ()

    @field_validator("acceptable_workplace_types", mode="after")
    @classmethod
    def _dedupe_workplace_types(cls, value: tuple[WorkplaceType, ...]) -> tuple[WorkplaceType, ...]:
        """Remove duplicates and impose a stable order so output is predictable."""
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def _check_role_preferences(self) -> Self:
        """Reject a profile that cannot express a usable search.

        Both cases here mean the profile is self-contradictory or empty, which is
        worth failing on. Ordinary untidiness (duplicates, stray whitespace) is
        cleaned up silently instead.
        """
        if not self.target_roles:
            raise ValueError("target_roles must contain at least one role")

        if not self.acceptable_workplace_types:
            raise ValueError("acceptable_workplace_types must contain at least one value")

        targets = {role.casefold() for role in self.target_roles}
        overlap = sorted(role for role in self.excluded_roles if role.casefold() in targets)
        if overlap:
            raise ValueError(
                f"roles cannot be both targeted and excluded: {', '.join(overlap)}",
            )

        return self
