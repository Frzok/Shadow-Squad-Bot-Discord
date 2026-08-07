"""Date helpers for temporarily pausing automatic raid announcements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class RaidVacation:
    start: date
    end: date

    def includes(self, value: date) -> bool:
        return self.start <= value <= self.end


def parse_user_date(value: str) -> date:
    """Parse a user-facing date in DD.MM.YYYY or ISO format."""
    for format_string in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), format_string).date()
        except ValueError:
            continue
    raise ValueError("Используйте дату в формате ДД.ММ.ГГГГ")


def vacation_from_state(
    start_value: str | None,
    end_value: str | None,
) -> RaidVacation | None:
    """Return a valid saved vacation period, or None for absent/bad state."""
    if not start_value or not end_value:
        return None
    try:
        period = RaidVacation(
            start=date.fromisoformat(start_value),
            end=date.fromisoformat(end_value),
        )
    except ValueError:
        return None
    return period if period.start <= period.end else None
