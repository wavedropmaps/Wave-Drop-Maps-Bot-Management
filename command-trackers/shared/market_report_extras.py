"""Extra KPI / flag computations injected into market dashboard reports."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_SHARED = Path(__file__).resolve().parent
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from metrics import (  # noqa: E402
    GUILD_DROP_MAP_ID,
    GUILD_IMPROVEMENT_ID,
    growth_capture,
    growth_stats_with_share,
    hourly_online_baseline,
    market_hhi,
    compute_market_red_flags,
    normalized_online_from_row,
    parse_snapshot_hour,
    normalize_online_pct,
    prediction_scorecard,
    read_guild_boost_snapshot,
    online_norm_note,
)
from report_fragments import red_flags_html, threat_banner_html  # noqa: E402


def enrich_market_rows(
    table_rows: list[dict],
    mc_by: dict,
    day_totals: dict,
    all_dates: list[str],
    current_total: int,
    history: list[dict],
) -> list[dict]:
    baseline = hourly_online_baseline(history)
    for r in table_rows:
        name = r["name"]
        cur = r.get("members") or 0
        _, _, s7 = growth_stats_with_share(name, cur, current_total, mc_by, day_totals, all_dates, 7)
        _, _, s30 = growth_stats_with_share(name, cur, current_total, mc_by, day_totals, all_dates, 30)
        r["s7"] = s7
        r["s30"] = s30
        r["share_delta_7d"] = s7
        if r.get("online") is not None and cur:
            raw_pct = r["online"] / cur * 100
            ts = r.get("captured_at") or r.get("last_seen", "")
            hour = parse_snapshot_hour(ts)
            r["online_pct_norm"] = normalize_online_pct(raw_pct, hour, baseline)
    return table_rows


def market_extras(
    table_rows: list[dict],
    wave_name: str,
    rank_delta: int | None,
    preds: list[dict],
    closest_threat: dict | None,
    wave_keys: set[str] | None = None,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    shares = [r.get("share") or 0 for r in table_rows]
    hhi = market_hhi(shares)
    capture = growth_capture(table_rows)
    pred = prediction_scorecard(preds, wave_keys or {wave_name, "wave"})

    wave_row = next((r for r in table_rows if r.get("is_us") or r.get("name") == wave_name), None)
    wave_s7 = (wave_row or {}).get("s7")

    capture_text = "—"
    if capture["top"] and capture["market_growth"]:
        top = capture["top"]
        capture_text = (
            f'{top["name"]} captured {top["capture_pct"]}% of '
            f'{capture["market_growth"]:+,} market growth (7d)'
        )

    pred_wave = pred["wave"]
    pred_text = "—"
    if pred_wave["accuracy"] is not None:
        pred_text = f'{pred_wave["hit"]}/{pred_wave["hit"] + pred_wave["miss"]} hit · {pred_wave["accuracy"]}%'

    threat_text = ""
    if closest_threat:
        if closest_threat.get("status") == "ahead":
            threat_text = (
                f'<b>Threat:</b> {closest_threat["name"]} is ahead by '
                f'{closest_threat["gap"]:,} members'
            )
        elif closest_threat.get("eta"):
            threat_text = (
                f'<b>Closest catch:</b> {closest_threat["name"]} · '
                f'ETA ~{closest_threat["eta"]} days at current pace'
            )

    flags = compute_market_red_flags(table_rows, wave_name, rank_delta)

    boost_guild = GUILD_IMPROVEMENT_ID
    if wave_name and "drop" in wave_name.lower():
        boost_guild = GUILD_DROP_MAP_ID
    boost = read_guild_boost_snapshot(boost_guild)
    boost_text = "—"
    if boost:
        boost_text = f'Tier {boost.get("boost_tier")} · {boost.get("boost_count")} boosts · {boost.get("channel_count")} ch'

    return {
        "hhi": hhi,
        "capture_text": capture_text,
        "pred_text": pred_text,
        "wave_share_delta_7d": wave_s7,
        "boost_text": boost_text,
        "red_flags_html": red_flags_html(flags),
        "threat_banner_html": threat_banner_html(threat_text),
        "norm_note": online_norm_note(history or []),
    }
