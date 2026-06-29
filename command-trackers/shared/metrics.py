"""
Shared metric helpers for guild-stats, market-research, and drop-map-research dashboards.
Pure Python — no HTML.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TRACKERS = REPO_ROOT / "command-trackers"

GUILD_DROP_MAP_ID = "988564962802810961"
GUILD_IMPROVEMENT_ID = "971731167621574666"

REF_HOUR_UTC = 14


def nearest_day_on_or_before(all_dates: list[str], target: str) -> str | None:
    for d in reversed(sorted(all_dates)):
        if d <= target:
            return d
    return None


def growth_delta(
    mc_by_name: dict[str, dict[str, int]],
    name: str,
    current: int,
    all_dates: list[str],
    days_back: int,
) -> tuple[int | None, float | None]:
    target = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    old_day = nearest_day_on_or_before(all_dates, target)
    if not old_day:
        return None, None
    old_v = mc_by_name.get(name, {}).get(old_day)
    if not old_v:
        return None, None
    delta = current - old_v
    pct = round(delta / old_v * 100, 2) if old_v else None
    return delta, pct


def share_at(mc_by_name: dict[str, dict[str, int]], day_totals: dict[str, int], name: str, day: str) -> float | None:
    total = day_totals.get(day)
    m = mc_by_name.get(name, {}).get(day)
    if not total or not m:
        return None
    return round(m / total * 100, 2)


def share_delta(cur_share: float | None, old_share: float | None) -> float | None:
    if cur_share is None or old_share is None:
        return None
    return round(cur_share - old_share, 2)


def growth_stats_with_share(
    name: str,
    current: int,
    current_total: int,
    mc_by_name: dict[str, dict[str, int]],
    day_totals: dict[str, int],
    all_dates: list[str],
    days_back: int,
) -> tuple[int | None, float | None, float | None]:
    delta, pct = growth_delta(mc_by_name, name, current, all_dates, days_back)
    target = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    old_day = nearest_day_on_or_before(all_dates, target)
    if not old_day:
        return delta, pct, None
    old_share = share_at(mc_by_name, day_totals, name, old_day)
    cur_share = round(current / current_total * 100, 2) if current_total else None
    s_delta = share_delta(cur_share, old_share)
    return delta, pct, s_delta


def members_per_day(mc_by_name: dict[str, dict[str, int]], name: str, current: int, all_dates: list[str]) -> float | None:
    d7, _ = growth_delta(mc_by_name, name, current, all_dates, 7)
    return round(d7 / 7, 1) if d7 is not None else None


def growth_capture(rows: list[dict[str, Any]], delta_key: str = "d7") -> dict[str, Any]:
    deltas = [(r.get("name"), r.get(delta_key)) for r in rows]
    deltas = [(n, d) for n, d in deltas if n is not None and d is not None]
    market_growth = sum(d for _, d in deltas)
    if market_growth == 0:
        return {"market_growth": 0, "captures": [], "top": None}
    captures = sorted(
        [{"name": n, "d7": d, "capture_pct": round(d / market_growth * 100, 1)} for n, d in deltas],
        key=lambda x: x["capture_pct"],
        reverse=True,
    )
    return {"market_growth": market_growth, "captures": captures, "top": captures[0] if captures else None}


def market_hhi(shares: list[float]) -> dict[str, Any]:
    if not shares:
        return {"hhi": None, "label": "—"}
    hhi = round(sum(s * s for s in shares), 0)
    if hhi >= 5000:
        label = "Highly concentrated"
    elif hhi >= 2500:
        label = "Moderately concentrated"
    else:
        label = "Fragmented"
    return {"hhi": hhi, "label": label}


def prediction_scorecard(preds: list[dict], wave_keys: set[str] | None = None) -> dict[str, Any]:
    wave_keys = wave_keys or set()

    def is_wave(p: dict) -> bool:
        if p.get("server_key") in wave_keys:
            return True
        if p.get("name") in wave_keys:
            return True
        if p.get("is_us"):
            return True
        return False

    def bucket(subset: list[dict]) -> dict:
        seen: set[str] = set()
        unique = []
        for p in subset:
            key = p.get("server_key") or p.get("name")
            if key in seen:
                continue
            seen.add(key)
            unique.append(p)
        hit = sum(1 for p in unique if p.get("hit") == 1)
        miss = sum(1 for p in unique if p.get("hit") == 0)
        pending = sum(1 for p in unique if p.get("hit") is None)
        resolved = hit + miss
        accuracy = round(hit / resolved * 100, 1) if resolved else None
        biases = []
        for p in unique:
            if p.get("hit") is not None and p.get("actual_members") and p.get("predicted_members"):
                biases.append(p["actual_members"] - p["predicted_members"])
        avg_bias = round(sum(biases) / len(biases), 1) if biases else None
        return {"hit": hit, "miss": miss, "pending": pending, "accuracy": accuracy, "avg_bias": avg_bias}

    wave_preds = [p for p in preds if is_wave(p)]
    return {"wave": bucket(wave_preds), "all": bucket(preds)}


def parse_snapshot_hour(captured_at: str) -> int:
    if not captured_at:
        return REF_HOUR_UTC
    if " UTC" in captured_at and "T" not in captured_at[:20]:
        parts = captured_at.split()
        if len(parts) >= 2 and ":" in parts[1]:
            try:
                return int(parts[1].split(":")[0])
            except ValueError:
                pass
    ts = captured_at.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts).hour
    except ValueError:
        return REF_HOUR_UTC


def hourly_online_baseline(history: list[dict], min_samples: int = 2) -> dict[int, float]:
    by_hour: dict[int, list[float]] = defaultdict(list)
    all_pcts: list[float] = []

    for row in history:
        m = row.get("member_count")
        o = row.get("online_count")
        if not m or o is None:
            continue
        pct = o / m * 100
        all_pcts.append(pct)
        hour = parse_snapshot_hour(row.get("captured_at", ""))
        by_hour[hour].append(pct)

    global_med = median(all_pcts) if all_pcts else 15.0
    baseline: dict[int, float] = {}
    for h in range(24):
        samples = by_hour.get(h, [])
        baseline[h] = median(samples) if len(samples) >= min_samples else global_med

    if baseline.get(REF_HOUR_UTC, 0) <= 0:
        baseline[REF_HOUR_UTC] = global_med or 15.0
    return baseline


def normalize_online_pct(
    raw_pct: float,
    snapshot_hour: int,
    baseline: dict[int, float],
    ref_hour: int = REF_HOUR_UTC,
) -> float:
    ref = baseline.get(ref_hour) or baseline.get(REF_HOUR_UTC) or raw_pct or 15.0
    snap = baseline.get(snapshot_hour) or ref
    if snap <= 0:
        return raw_pct
    return round(raw_pct * (ref / snap), 1)


def normalized_online_from_row(row: dict, baseline: dict[int, float]) -> float | None:
    m = row.get("member_count") or 0
    o = row.get("online_count")
    if not m or o is None:
        return None
    raw = o / m * 100
    hour = parse_snapshot_hour(row.get("captured_at", ""))
    return normalize_online_pct(raw, hour, baseline)


def compute_market_red_flags(
    table_rows: list[dict],
    wave_name: str,
    rank_delta: int | None,
    dead_invites: list[str] | None = None,
    share_delta_threshold: float = 0.5,
) -> list[str]:
    flags: list[str] = []
    dead_invites = dead_invites or []

    for r in table_rows:
        name = r.get("name", "")
        s7 = r.get("s7") if r.get("s7") is not None else r.get("share_delta_7d")
        if name == wave_name and s7 is not None and s7 < -share_delta_threshold:
            flags.append(f"{name} lost {abs(s7):.2f}pp share (7d)")
        mpd = r.get("mpd")
        if mpd is not None and mpd < 0 and name != wave_name:
            flags.append(f"{name}: {mpd:+.1f} members/day")

    if rank_delta is not None and rank_delta < 0:
        flags.append(f"{wave_name} dropped {abs(rank_delta)} rank(s) vs last week")

    for name in dead_invites:
        flags.append(f"{name}: invite dead — auto-removed")

    return flags


def compute_guild_red_flags(
    table_rows: list[dict],
    prev_by_name: dict[str, dict] | None = None,
) -> list[str]:
    flags: list[str] = []
    prev_by_name = prev_by_name or {}

    for r in table_rows:
        name = r.get("name", "")
        prev = prev_by_name.get(name, {})
        mpd = r.get("mpd")
        if mpd is not None and mpd < -10:
            flags.append(f"{name}: {mpd:+.1f} members/day")

        cur_tier = r.get("boost_tier")
        old_tier = prev.get("boost_tier")
        if cur_tier is not None and old_tier is not None and cur_tier < old_tier:
            flags.append(f"{name}: boost tier dropped Tier {old_tier} → Tier {cur_tier}")

        cur_ch = r.get("channel_count")
        old_ch = prev.get("channel_count")
        if cur_ch and old_ch and old_ch > 0:
            if (cur_ch - old_ch) / old_ch * 100 > 5:
                flags.append(f"{name}: +{cur_ch - old_ch} channels (7d) — possible bloat")

        eng = r.get("eng_trend_norm") or r.get("eng_trend")
        if eng is not None and eng < -2:
            flags.append(f"{name}: engagement down {abs(eng):.1f}pp (30d)")

    return flags


def guild_infra_metrics(row: dict) -> dict[str, float | int | None]:
    m = row.get("member_count") or row.get("members") or 0
    boosts = row.get("boost_count") or 0
    channels = row.get("channel_count")
    roles = row.get("role_count")
    if not m:
        return {"boosts_per_1k": None, "channels_per_1k": None, "roles": roles}
    return {
        "boosts_per_1k": round(boosts / m * 1000, 2),
        "channels_per_1k": round(channels / m * 1000, 2) if channels else None,
        "roles": roles,
    }


def portfolio_split(guild_rows: list[dict]) -> list[dict]:
    total = sum((r.get("member_count") or r.get("members") or 0) for r in guild_rows)
    if not total:
        return []
    out = []
    for r in guild_rows:
        m = r.get("member_count") or r.get("members") or 0
        out.append({"name": r.get("name"), "members": m, "pct": round(m / total * 100, 2)})
    return sorted(out, key=lambda x: x["members"], reverse=True)


def _read_drop_map_wave() -> dict | None:
    db = TRACKERS / "drop-map-research" / "data" / "data.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT s.name, sn.member_count
            FROM snapshots sn
            JOIN servers s ON s.id = sn.server_id
            WHERE sn.id IN (SELECT MAX(id) FROM snapshots GROUP BY server_id)
              AND s.active = 1
        """).fetchall()
        if not rows:
            return None
        data = [dict(r) for r in rows]
        total = sum(r["member_count"] or 0 for r in data) or 1
        wave = next((r for r in data if r["name"] == "Wave Free Dropmaps"), None)
        if not wave:
            return None
        share = round((wave["member_count"] or 0) / total * 100, 2)
        sorted_mc = sorted(data, key=lambda x: x["member_count"] or 0, reverse=True)
        rank = next(i + 1 for i, r in enumerate(sorted_mc) if r["name"] == "Wave Free Dropmaps")
        return {"rank": rank, "share": share, "members": wave["member_count"], "market_label": "drop-map market"}
    finally:
        conn.close()


def _read_mkt_research_wave() -> dict | None:
    db = TRACKERS / "market-research" / "data" / "data.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT s.name, s.key, s.is_us, sn.member_count
            FROM servers s
            LEFT JOIN snapshots sn ON sn.id = (
                SELECT id FROM snapshots WHERE server_key = s.key ORDER BY captured_at DESC LIMIT 1
            )
            WHERE s.active = 1
        """).fetchall()
        data = [dict(r) for r in rows if r["member_count"]]
        if not data:
            return None
        total = sum(r["member_count"] for r in data) or 1
        wave = next((r for r in data if r.get("is_us")), None)
        if not wave:
            return None
        share = round(wave["member_count"] / total * 100, 2)
        sorted_mc = sorted(data, key=lambda x: x["member_count"], reverse=True)
        rank = next(i + 1 for i, r in enumerate(sorted_mc) if r.get("is_us"))
        return {"rank": rank, "share": share, "members": wave["member_count"], "market_label": "improvement cord market"}
    finally:
        conn.close()


def cross_market_context(guild_id: str) -> dict | None:
    if guild_id == GUILD_DROP_MAP_ID:
        return _read_drop_map_wave()
    if guild_id == GUILD_IMPROVEMENT_ID:
        return _read_mkt_research_wave()
    return None


def read_guild_boost_snapshot(guild_id: str) -> dict | None:
    db = TRACKERS / "guild-stats" / "data" / "data.db"
    if not db.exists():
        return None
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT g.name, g.guild_id, s.boost_count, s.boost_tier, s.channel_count, s.role_count
            FROM snapshots s
            JOIN guilds g ON g.guild_id = s.guild_id
            WHERE s.guild_id = ?
            ORDER BY s.captured_at DESC LIMIT 1
        """, (guild_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def linear_projection_from_series(day_values: dict[str, int], forward_days: int = 30) -> int | None:
    pts = sorted(day_values.items())
    if len(pts) < 2:
        return None
    d0 = datetime.fromisoformat(pts[0][0])
    xs = [(datetime.fromisoformat(d) - d0).days for d, _ in pts]
    ys = [v for _, v in pts]
    n = len(xs)
    xm, ym = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - xm) * (ys[i] - ym) for i in range(n))
    den = sum((xs[i] - xm) ** 2 for i in range(n))
    if den == 0:
        return None
    slope = num / den
    return max(0, round(ys[-1] + slope * forward_days))


def acceleration_from_series(mc_by_name: dict[str, dict[str, int]], name: str, current: int, all_dates: list[str]) -> float | None:
    d7 = nearest_day_on_or_before(all_dates, (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"))
    d14 = nearest_day_on_or_before(all_dates, (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d"))
    if not d7 or not d14:
        return None
    m_7 = mc_by_name.get(name, {}).get(d7)
    m_14 = mc_by_name.get(name, {}).get(d14)
    if m_7 is None or m_14 is None:
        return None
    return round((current - m_7) / 7 - (m_7 - m_14) / 7, 1)


def count_snapshot_days_near_hour(history: list[dict], hour: int = REF_HOUR_UTC, tolerance: int = 1) -> int:
    days: set[str] = set()
    for row in history:
        ts = row.get("captured_at") or ""
        if not ts:
            continue
        h = parse_snapshot_hour(ts)
        if abs(h - hour) <= tolerance:
            days.add(ts[:10])
    return len(days)


def online_norm_note(history: list[dict], ref_hour: int = REF_HOUR_UTC, min_days: int = 7) -> str:
    n = count_snapshot_days_near_hour(history, ref_hour)
    if n >= min_days:
        return f"Online metrics normalized to {ref_hour}:00 UTC ({n} canonical snapshot days)."
    return (
        f"Online metrics partially time-adjusted toward {ref_hour}:00 UTC "
        f"({n}/{min_days} canonical days — accuracy improves as 14:05 UTC collects accumulate)."
    )


def build_normalized_heatmap(
    history: list[dict],
    all_dates: list[str],
    server_names: list[str],
) -> list[dict]:
    """Heatmap rows with normalized values for color; raw online in raw_vals."""
    baseline = hourly_online_baseline(history)
    online_by: dict[str, dict[str, tuple[int | None, int | None, str]]] = defaultdict(dict)
    for row in history:
        name = row.get("name")
        day = (row.get("captured_at") or "")[:10]
        if not name or not day:
            continue
        online_by[name][day] = (
            row.get("online_count"),
            row.get("member_count"),
            row.get("captured_at") or "",
        )

    matrix = []
    for name in server_names:
        norm_vals, raw_vals = [], []
        for d in all_dates:
            tup = online_by.get(name, {}).get(d)
            if not tup or tup[0] is None or not tup[1]:
                norm_vals.append(None)
                raw_vals.append(None)
                continue
            raw_o, members, ts = tup
            raw_pct = raw_o / members * 100
            hour = parse_snapshot_hour(ts)
            norm_o = round(members * normalize_online_pct(raw_pct, hour, baseline) / 100)
            norm_vals.append(norm_o)
            raw_vals.append(raw_o)
        max_v = max((v for v in norm_vals if v), default=1) or 1
        matrix.append({"name": name, "vals": norm_vals, "raw_vals": raw_vals, "max": max_v})
    return matrix


# ── Snapshot coverage (partial days + new entrants) ───────────────────────────

def first_seen_dates(
    history: list[dict],
    name_key: str = "name",
    date_key: str = "captured_at",
    roster_added: dict[str, str] | None = None,
) -> dict[str, str]:
    """Earliest snapshot day per entity; roster_added supplies pre-snapshot join dates."""
    first: dict[str, str] = {}
    for row in history:
        name = row.get(name_key)
        day = (row.get(date_key) or "")[:10]
        if not name or not day:
            continue
        if name not in first or day < first[name]:
            first[name] = day
    for name, added in (roster_added or {}).items():
        ad = (added or "")[:10]
        if not ad:
            continue
        if name not in first or ad < first[name]:
            first[name] = ad
    return first


def expected_entities_on_day(active_names: list[str], first_seen: dict[str, str], day: str) -> list[str]:
    return [n for n in active_names if first_seen.get(n, day) <= day]


def audit_day_coverage(
    by_day: dict[str, dict[str, dict]],
    active_names: list[str],
    first_seen: dict[str, str],
) -> dict[str, Any]:
    """Classify each day as complete or partial (missing expected entities)."""
    all_dates = sorted(by_day.keys())
    complete_days: list[str] = []
    incomplete_days: list[dict[str, Any]] = []

    for day in all_dates:
        expected = expected_entities_on_day(active_names, first_seen, day)
        if not expected:
            complete_days.append(day)
            continue
        missing = [
            n for n in expected
            if n not in by_day.get(day, {})
            or by_day[day][n].get("member_count") is None
        ]
        if missing:
            incomplete_days.append({
                "day": day,
                "present": len(expected) - len(missing),
                "expected": len(expected),
                "missing": missing,
            })
        else:
            complete_days.append(day)

    return {
        "all_dates": all_dates,
        "complete_days": complete_days,
        "incomplete_days": incomplete_days,
    }


def compute_day_totals_for_days(
    by_day: dict[str, dict[str, dict]],
    days: list[str],
    active_names: list[str],
    first_seen: dict[str, str],
    member_key: str = "member_count",
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for day in days:
        expected = expected_entities_on_day(active_names, first_seen, day)
        t = sum(
            (by_day.get(day, {}).get(n, {}).get(member_key) or 0)
            for n in expected
            if n in by_day.get(day, {})
        )
        if t:
            totals[day] = t
    return totals


def recent_entrants(first_seen: dict[str, str], within_days: int = 30) -> dict[str, str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).strftime("%Y-%m-%d")
    return {n: d for n, d in sorted(first_seen.items(), key=lambda x: x[1]) if d >= cutoff}


def series_with_first_seen(
    mc_by_name: dict[str, dict[str, int]],
    name: str,
    all_dates: list[str],
    first_seen: dict[str, str],
) -> list[int | None]:
    fs = first_seen.get(name)
    return [
        mc_by_name.get(name, {}).get(d) if fs and fs <= d else None
        for d in all_dates
    ]
