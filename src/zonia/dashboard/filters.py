"""Which candidates the dashboard list shows."""

from dataclasses import dataclass

from zonia.domain.models import RecruiterOutcome, Status
from zonia.storage import ConversationRow


@dataclass
class Filters:
    """The list filters, as the URL gives them. None means "all"."""

    status: Status | None = None
    country: str | None = None
    zone: str | None = None  # a service zone, or OUTSIDE_ZONE
    availability: str | None = None
    schedule: str | None = None
    search: str | None = None  # part of the name, the phone or the case code

    @property
    def chosen(self) -> int:
        """How many of the five lists have a value. The search is not counted: it is always in sight."""
        return sum(v is not None for v in (self.status, self.country, self.zone, self.availability, self.schedule))

    def matches(self, c: ConversationRow) -> bool:
        f = c.fields
        return (
            (self.status is None or c.status == self.status)
            and (self.country is None or c.country == self.country)
            and (self.zone is None or f.service_zone == self.zone)
            and (self.availability is None or self.availability in (f.availability or []))
            and (self.schedule is None or self.schedule in (f.schedule or []))
            and (self.search is None or self._found(c))
        )

    def _found(self, c: ConversationRow) -> bool:
        needle = self.search.casefold()
        digits = "".join(ch for ch in needle if ch.isdigit())
        return (
            needle in (c.fields.full_name or "").casefold()
            or needle in c.case_code.casefold()
            or (len(digits) >= 3 and digits in (c.phone or ""))
        )


def to_call(c: ConversationRow) -> bool:
    """Qualified, and the recruiter has not reached the candidate yet: no outcome, or "No answer"."""
    return c.status == Status.QUALIFIED and c.outcome in (None, RecruiterOutcome.NO_ANSWER)
