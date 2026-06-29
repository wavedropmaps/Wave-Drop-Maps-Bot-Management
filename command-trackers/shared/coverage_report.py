"""Helpers wiring coverage audit into tracker report generators."""

from __future__ import annotations

from metrics import (
    audit_day_coverage,
    compute_day_totals_for_days,
    first_seen_dates,
    recent_entrants,
    series_with_first_seen,
)


def prepare_coverage_context(
    history: list[dict],
    by_day: dict,
    active_names: list[str],
    roster_added: dict[str, str] | None = None,
    entrant_within_days: int = 30,
) -> dict:
    first_seen = first_seen_dates(history, roster_added=roster_added)
    audit = audit_day_coverage(by_day, active_names, first_seen)
    chart_dates = audit["complete_days"] if audit["complete_days"] else audit["all_dates"]
    day_totals = compute_day_totals_for_days(by_day, chart_dates, active_names, first_seen)
    entrants = recent_entrants(first_seen, entrant_within_days)
    return {
        "first_seen": first_seen,
        "audit": audit,
        "chart_dates": chart_dates,
        "day_totals": day_totals,
        "entrants": entrants,
    }


__all__ = [
    "prepare_coverage_context",
    "series_with_first_seen",
]
