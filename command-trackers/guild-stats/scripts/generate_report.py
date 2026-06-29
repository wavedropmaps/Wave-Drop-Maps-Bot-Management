"""
Generate a self-contained HTML dashboard from the guild-stats snapshot database.
Styled to exactly match the token dashboard UI (wavedropmaps token dashboard).
Saves to data/reports/report_YYYY-MM-DD.html.

Usage:
  python generate_report.py [--days 90]
"""

import sys, os, json, argparse, webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(__file__))
_SHARED = Path(__file__).resolve().parents[2] / "shared"
sys.path.insert(0, str(_SHARED))
from db import init_db, get_history, get_latest_per_guild, get_active_guilds, get_roster_added_by_name, DATA_DIR
from metrics import (
    portfolio_split,
    compute_guild_red_flags,
    hourly_online_baseline,
    normalize_online_pct,
    parse_snapshot_hour,
    cross_market_context,
    nearest_day_on_or_before,
    build_normalized_heatmap,
    online_norm_note,
    series_with_first_seen,
)
from coverage_report import prepare_coverage_context
from report_fragments import (
    RED_FLAGS_CSS,
    TABLE_EXPAND_JS,
    donut_renorm_js,
    small_multiples_js,
    red_flags_html,
    threat_banner_html,
    coverage_banner_html,
)

REPORTS_DIR = DATA_DIR / "reports"

COLORS = [
    "#4A9EFF", "#7C5CFF", "#3FB68B",
    "#E8A23B", "#E5484D", "#5BCEDA",
]


def fmt_ts(ts):
    if not ts: return "—"
    return ts[:16].replace("T", " ") + " UTC"


def build_report(days: int = 90, open_browser: bool = True) -> str:
    init_db()
    latest  = get_latest_per_guild()
    history = get_history(days)

    if not latest:
        print("No data yet. Run a collect first.")
        sys.exit(1)

    # ── Index data ─────────────────────────────────────────────────────────────
    guild_names   = [r["name"] for r in latest]
    current_mc    = {r["name"]: r["member_count"] or 0 for r in latest}
    current_oc    = {r["name"]: r["online_count"]  or 0 for r in latest}
    current_boost = {r["name"]: r["boost_count"]   or 0 for r in latest}
    current_tier  = {r["name"]: r["boost_tier"]    or 0 for r in latest}
    by_day: dict = defaultdict(dict)
    for row in history:
        day  = row["captured_at"][:10]
        name = row["name"]
        by_day[day][name] = row

    all_dates   = sorted(by_day.keys())
    active_names = [g["name"] for g in get_active_guilds()]
    all_guilds  = active_names or guild_names

    cov = prepare_coverage_context(
        history, by_day, all_guilds, roster_added=get_roster_added_by_name()
    )
    first_seen = cov["first_seen"]
    complete_days = set(cov["audit"]["complete_days"])
    coverage_html = coverage_banner_html(cov["audit"], cov["entrants"])

    mc_by:    dict = defaultdict(dict)
    oc_by:    dict = defaultdict(dict)
    boost_by: dict = defaultdict(dict)
    tier_by:  dict = defaultdict(dict)

    for day, guilds in by_day.items():
        for name, row in guilds.items():
            if row["member_count"] is not None:
                mc_by[name][day]    = row["member_count"]
            if row["online_count"]  is not None:
                oc_by[name][day]    = row["online_count"]
            if row["boost_count"]   is not None:
                boost_by[name][day] = row["boost_count"]
            if row["boost_tier"]    is not None:
                tier_by[name][day]  = row["boost_tier"]

    total_by_day = cov["day_totals"]

    baseline = hourly_online_baseline([
        {
            "name": r.get("name"),
            "member_count": r.get("member_count"),
            "online_count": r.get("online_count"),
            "captured_at": r.get("captured_at", ""),
        }
        for r in history
    ])
    hist_for_hm = [
        {"name": r.get("name"), "member_count": r.get("member_count"), "online_count": r.get("online_count"), "captured_at": r.get("captured_at", "")}
        for r in history
    ]
    heatmap_matrix = build_normalized_heatmap(hist_for_hm, all_dates, all_guilds)
    norm_note = online_norm_note(hist_for_hm)

    # ── Growth helpers ─────────────────────────────────────────────────────────
    def nearest_day_on_or_before_local(target: str):
        return nearest_day_on_or_before(all_dates, target)

    def growth(name: str, days_back: int):
        target  = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        old_day = nearest_day_on_or_before_local(target)
        if not old_day:
            return None, None
        old_v = mc_by[name].get(old_day)
        cur   = current_mc.get(name, 0)
        if not old_v:
            return None, None
        delta = cur - old_v
        pct   = round(delta / old_v * 100, 2)
        return delta, pct

    def linear_projection(name: str, forward_days: int = 30):
        pts = sorted(mc_by[name].items())
        if len(pts) < 2:
            return None
        d0 = datetime.fromisoformat(pts[0][0])
        xs = [(datetime.fromisoformat(d) - d0).days for d, _ in pts]
        ys = [v for _, v in pts]
        n  = len(xs)
        xm, ym = sum(xs)/n, sum(ys)/n
        num = sum((xs[i]-xm)*(ys[i]-ym) for i in range(n))
        den = sum((xs[i]-xm)**2 for i in range(n))
        if den == 0:
            return None
        slope = num / den
        return max(0, round(ys[-1] + slope * forward_days))

    def mpd(name: str):
        d7, _ = growth(name, 7)
        return round(d7 / 7, 1) if d7 is not None else None

    def eng_trend(name: str):
        target  = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
        old_day = nearest_day_on_or_before_local(target)
        if not old_day:
            return None
        old_row = by_day.get(old_day, {}).get(name)
        if not old_row:
            return None
        m_now = current_mc.get(name, 0)
        o_now = current_oc.get(name, 0)
        m_old = old_row.get("member_count") or 0
        o_old = old_row.get("online_count")
        if not m_old or o_old is None or not m_now:
            return None
        return round(o_now / m_now * 100 - o_old / m_old * 100, 1)

    # ── Portfolio donut + 7d-ago baseline for red flags ────────────────────────
    portfolio   = portfolio_split(latest)
    pie_labels  = [p["name"] for p in portfolio]
    pie_values  = [p["members"] for p in portfolio]
    pie_colors  = COLORS[:len(pie_labels)]

    d7_target = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    d7_day    = nearest_day_on_or_before_local(d7_target)
    prev_by_name: dict[str, dict] = {}
    if d7_day:
        for name in all_guilds:
            row = by_day.get(d7_day, {}).get(name)
            if row:
                prev_by_name[name] = {
                    "boost_tier":    row.get("boost_tier"),
                    "channel_count": row.get("channel_count"),
                }

    # ── Summary stat card values ───────────────────────────────────────────────
    total_members = sum(current_mc.values())
    total_online  = sum(current_oc.values())
    total_boosts  = sum(current_boost.values())
    online_pct    = round(total_online / total_members * 100, 1) if total_members else 0

    all_d7   = [growth(n, 7)[0]  for n in all_guilds]
    total_d7 = sum(v for v in all_d7 if v is not None)

    def sign_str(v):
        if v is None: return "—"
        return f"+{v:,}" if v >= 0 else f"{v:,}"

    guild_banner = threat_banner_html(
        f"<b>Portfolio:</b> {total_members:,} members · {sign_str(total_d7)} past 7d",
        css_class="guild-banner",
    )

    # ── Cross-market context cards ─────────────────────────────────────────────
    cross_cards_html = ""
    for r in latest:
        ctx = cross_market_context(r["guild_id"])
        if not ctx:
            continue
        cross_cards_html += (
            f'<div class="cross-card">'
            f'<div class="label">{r["name"]} — {ctx["market_label"]}</div>'
            f'<div class="val">#{ctx["rank"]} · {ctx["share"]}% share · '
            f'{(ctx["members"] or 0):,} members</div>'
            f'</div>\n'
        )

    # ── Chart datasets ─────────────────────────────────────────────────────────
    mc_datasets = []
    for i, name in enumerate(all_guilds):
        series = series_with_first_seen(mc_by, name, all_dates, first_seen)
        mc_datasets.append({
            "label": name, "data": series,
            "borderColor": COLORS[i % len(COLORS)],
            "backgroundColor": COLORS[i % len(COLORS)] + "1f",
            "tension": 0.4, "fill": False, "spanGaps": True,
            "pointRadius": 0, "pointHoverRadius": 4, "borderWidth": 2,
        })

    total_series = [
        total_by_day.get(d) if d in complete_days else None
        for d in all_dates
    ]
    total_dataset = [{
        "label": "Combined", "data": total_series,
        "borderColor": "#4A9EFF",
        "backgroundColor": "#4A9EFF1f",
        "tension": 0.4, "fill": True, "spanGaps": True,
        "pointRadius": 0, "pointHoverRadius": 4, "borderWidth": 2.5,
    }]

    oc_datasets = []
    for i, name in enumerate(all_guilds):
        series = [oc_by[name].get(d) for d in all_dates]
        oc_datasets.append({
            "label": name, "data": series,
            "borderColor": COLORS[i % len(COLORS)],
            "backgroundColor": COLORS[i % len(COLORS)] + "1f",
            "tension": 0.4, "fill": False, "spanGaps": True,
            "pointRadius": 0, "pointHoverRadius": 4, "borderWidth": 2,
        })

    boost_datasets = []
    for i, name in enumerate(all_guilds):
        series = [boost_by[name].get(d) for d in all_dates]
        boost_datasets.append({
            "label": name, "data": series,
            "borderColor": COLORS[i % len(COLORS)],
            "backgroundColor": COLORS[i % len(COLORS)] + "40",
            "tension": 0.4, "fill": True, "spanGaps": True,
            "pointRadius": 0, "pointHoverRadius": 4, "borderWidth": 1.5,
        })

    vel_datasets = []
    for i, name in enumerate(all_guilds):
        series = []
        for j, day in enumerate(all_dates):
            target  = (datetime.fromisoformat(day) - timedelta(days=7)).strftime("%Y-%m-%d")
            old_day = next((d for d in reversed(all_dates[:j]) if d <= target), None)
            cur_m = mc_by[name].get(day)
            old_m = mc_by[name].get(old_day) if old_day else None
            if cur_m and old_m and old_m > 0:
                series.append(round((cur_m - old_m) / old_m * 100, 2))
            else:
                series.append(None)
        vel_datasets.append({
            "label": name, "data": series,
            "borderColor": COLORS[i % len(COLORS)],
            "backgroundColor": "transparent",
            "tension": 0.4, "fill": False, "spanGaps": False,
            "pointRadius": 0, "pointHoverRadius": 4, "borderWidth": 2,
        })

    online_ratio_data = []
    for r in latest:
        m = r["member_count"] or 0
        o = r["online_count"]  or 0
        raw = round(o / m * 100, 1) if m else 0
        hour = parse_snapshot_hour(r.get("captured_at", ""))
        online_ratio_data.append({
            "name": r["name"],
            "ratio": normalize_online_pct(raw, hour, baseline),
        })

    # ── Table rows ─────────────────────────────────────────────────────────────
    table_rows = []
    for r in latest:
        name     = r["name"]
        d7, p7   = growth(name, 7)
        d30, p30 = growth(name, 30)
        proj     = linear_projection(name)
        m_per_d  = mpd(name)
        m        = r["member_count"] or 0
        o        = r["online_count"] or 0
        raw_op   = round(o / m * 100, 1) if m else 0
        hour     = parse_snapshot_hour(r.get("captured_at", ""))
        op       = normalize_online_pct(raw_op, hour, baseline)
        gid      = r["guild_id"]
        ctx      = cross_market_context(gid)
        market_share = ctx["share"] if ctx else None

        table_rows.append({
            "name":          name,
            "guild_id":      gid,
            "members":       m,
            "online":        o,
            "online_pct":    op,
            "boost_count":   r["boost_count"]   or 0,
            "boost_tier":    r["boost_tier"]     or 0,
            "channel_count": r["channel_count"],
            "role_count":    r["role_count"],
            "mpd":           m_per_d,
            "d7":            d7,
            "p7":            p7,
            "d30":           d30,
            "p30":           p30,
            "proj":          proj,
            "market_share":  market_share,
            "eng_trend":     eng_trend(name),
            "last_seen":     fmt_ts(r["captured_at"]),
        })

    red_flags = compute_guild_red_flags(table_rows, prev_by_name)
    flags_html = red_flags_html(red_flags)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    first_date   = all_dates[0]  if all_dates else "—"
    last_date    = all_dates[-1] if all_dates else "—"

    # ── HTML ───────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Wave Guild Stats — {last_date}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
:root{{
  --bg:#0A0E14;--panel:#0F1419;--panel-2:#131922;
  --border:#1F2630;--border-2:#283040;
  --text:#E6EDF3;--muted:#8B98A6;--muted-2:#5A6573;
  --accent:#4A9EFF;--accent-2:#7C5CFF;
  --good:#3FB68B;--warn:#E8A23B;--bad:#E5484D;
  --mono:'JetBrains Mono',ui-monospace,SFMono-Regular,Consolas,monospace;
  --sans:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{
  background:var(--bg);color:var(--text);
  font-family:var(--sans);font-size:13px;line-height:1.55;
  -webkit-font-smoothing:antialiased;min-height:100vh;
}}
header.topbar{{
  display:flex;align-items:center;gap:16px;padding:10px 20px;
  border-bottom:1px solid var(--border);
  background:linear-gradient(180deg,var(--panel) 0%,var(--bg) 100%);
  position:sticky;top:0;z-index:10;
  backdrop-filter:saturate(180%) blur(8px);
}}
.topbar .brand{{
  font-weight:600;letter-spacing:-0.01em;font-size:14px;
  display:flex;align-items:center;gap:8px;
}}
.topbar .brand::before{{
  content:"";display:inline-block;width:8px;height:8px;
  background:var(--good);border-radius:2px;box-shadow:0 0 12px var(--good);
}}
.topbar .pill{{
  padding:4px 10px;border-radius:6px;
  background:var(--panel-2);border:1px solid var(--border);
  color:var(--muted);font-size:12px;font-family:var(--mono);
  margin-left:auto;
}}
main{{padding:24px 20px;max-width:1400px;margin:0 auto}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px}}
.card{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:18px}}
.kpi{{padding:16px;min-width:0}}
.kpi .label{{color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.08em;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.kpi .value{{font-family:var(--mono);font-size:22px;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:-0.03em;margin-top:6px;line-height:1.1;color:var(--accent)}}
.kpi .delta{{font-family:var(--mono);font-size:12px;margin-top:4px}}
.kpi .sub{{color:var(--muted);font-size:11px;margin-top:4px}}
.row{{display:grid;gap:16px;margin-bottom:16px}}
.row.cols-2{{grid-template-columns:1fr 1fr}}
.card h2{{margin:0 0 14px;font-size:13px;font-weight:600;color:var(--text)}}
.card h3{{margin:0 0 4px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}
.chart-wrap{{position:relative;height:280px}}
.chart-tall{{position:relative;height:340px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--border)}}
th{{color:var(--muted);font-weight:600;text-transform:uppercase;font-size:10px;letter-spacing:.06em;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{color:var(--text)}}
th .arr{{margin-left:3px;opacity:.3;font-size:.65em}}
th.sort-asc .arr,th.sort-desc .arr{{opacity:1;color:var(--accent)}}
tbody tr{{transition:background 100ms}}
tbody tr:hover{{background:var(--panel-2)}}
td{{color:var(--text);white-space:nowrap}}
.pos{{color:var(--good)}}.neg{{color:var(--bad)}}.dim{{color:var(--muted-2)}}
.tier{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-family:var(--mono);font-weight:500}}
.tier-0{{background:rgba(74,158,255,0.05);color:var(--muted-2)}}
.tier-1{{background:rgba(63,182,139,0.1);color:var(--good);border:1px solid rgba(63,182,139,0.3)}}
.tier-2{{background:rgba(74,158,255,0.1);color:var(--accent);border:1px solid rgba(74,158,255,0.3)}}
.tier-3{{background:rgba(124,92,255,0.1);color:var(--accent-2);border:1px solid rgba(124,92,255,0.3)}}
.heatmap{{overflow-x:auto}}
.hm-row{{display:flex;align-items:center;gap:4px;margin-bottom:3px}}
.hm-label{{width:180px;min-width:180px;color:var(--muted);text-align:right;padding-right:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}}
.hm-cells{{display:flex;gap:2px}}
.hm-cell{{width:14px;height:14px;border-radius:3px;cursor:default;flex-shrink:0}}
.hm-dates{{display:flex;gap:2px;margin-left:184px;margin-bottom:4px}}
.hm-date{{width:14px;text-align:center;font-size:9px;color:var(--muted-2);transform:rotate(-60deg);transform-origin:bottom left;height:20px}}
@media(max-width:900px){{.kpi-row{{grid-template-columns:1fr 1fr}}.row.cols-2{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.kpi-row{{grid-template-columns:1fr}}}}
{RED_FLAGS_CSS}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">Wave Guild Stats</div>
  <div class="pill">{generated_at}</div>
</header>
{guild_banner}
<main>
{coverage_html}
{flags_html}

<div class="kpi-row">
  <div class="card kpi">
    <div class="label">Total Members</div>
    <div class="value">{total_members:,}</div>
    <div class="delta {'pos' if total_d7 >= 0 else 'neg'}">{sign_str(total_d7)} past 7d</div>
  </div>
  <div class="card kpi">
    <div class="label">Online Now</div>
    <div class="value" style="color:var(--good)">{total_online:,}</div>
    <div class="sub">{online_pct}% of total</div>
  </div>
  <div class="card kpi">
    <div class="label">Total Boosts</div>
    <div class="value" style="color:var(--warn)">{total_boosts}</div>
    <div class="sub">across {len(all_guilds)} servers</div>
  </div>
  <div class="card kpi">
    <div class="label">Snapshot Window</div>
    <div class="value" style="font-size:13px;color:var(--muted);font-family:var(--mono);padding-top:4px">{first_date}<br>→ {last_date}</div>
    <div class="sub">{days}d window</div>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h2>Portfolio Split</h2>
    <h3>Member share across Wave servers</h3>
    <div class="chart-wrap"><canvas id="pieChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Cross-Market Position</h2>
    <h3>Wave rank in each tracked competitor market</h3>
    {cross_cards_html if cross_cards_html else '<p class="dim" style="font-size:12px">No cross-market data yet.</p>'}
  </div>
</div>

<div class="row">
  <div class="card">
    <h2>Member Count Over Time — Per Server</h2>
    <h3>Shared-scale mini charts</h3>
    <div class="multiples-grid" id="mcMultiples"></div>
    <p class="norm-note">{norm_note}</p>
  </div>
</div>

<div class="row">
  <div class="card">
    <h2>Combined Total Members Over Time</h2>
    <div class="chart-wrap"><canvas id="totalChart"></canvas></div>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h2>Online Count Over Time</h2>
    <div class="chart-wrap"><canvas id="ocChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Online Ratio (% of members online)</h2>
    <div class="chart-wrap"><canvas id="ratioChart"></canvas></div>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h2>Boost Count Over Time</h2>
    <div class="chart-wrap"><canvas id="boostChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Growth Velocity (week-over-week %)</h2>
    <div class="chart-wrap"><canvas id="velChart"></canvas></div>
  </div>
</div>

<div class="card" style="margin-bottom:16px">
  <h2>Server Summary</h2>
  <div class="table-toolbar"><button type="button" id="expandBtn">Show all columns</button></div>
  <div style="overflow-x:auto">
  <table id="summaryTable" style="min-width:900px">
    <thead><tr>
      <th data-col="name"          data-type="str">Guild           <span class="arr">↕</span></th>
      <th data-col="members"       data-type="num">Members         <span class="arr">↕</span></th>
      <th data-col="online_pct"    data-type="num">Online %        <span class="arr">↕</span></th>
      <th data-col="boost_count"   data-type="num">Boosts          <span class="arr">↕</span></th>
      <th data-col="d7"            data-type="num">7d Δ            <span class="arr">↕</span></th>
      <th data-col="mpd"           data-type="num">Mem/Day         <span class="arr">↕</span></th>
      <th data-col="boost_tier"    data-type="num" class="col-advanced">Tier            <span class="arr">↕</span></th>
      <th data-col="channel_count" data-type="num" class="col-advanced">Channels        <span class="arr">↕</span></th>
      <th data-col="role_count"    data-type="num" class="col-advanced">Roles           <span class="arr">↕</span></th>
      <th data-col="d30"           data-type="num" class="col-advanced">30d Δ           <span class="arr">↕</span></th>
      <th data-col="proj"          data-type="num" class="col-advanced">Proj. 30d       <span class="arr">↕</span></th>
      <th data-col="market_share"  data-type="num" class="col-advanced">Market Share    <span class="arr">↕</span></th>
      <th data-col="last_seen"     data-type="str" class="col-advanced">Last Snapshot   <span class="arr">↕</span></th>
    </tr></thead>
    <tbody id="tableBody"></tbody>
  </table>
  </div>
</div>

<div class="card">
  <h2>Online Activity Heatmap</h2>
  <div style="margin-bottom:12px;font-size:11px;color:var(--muted-2)">Darker = more online</div>
  <div class="heatmap" id="heatmap"></div>
</div>

<script>
const COLORS  = {json.dumps(COLORS)};
const PIE_LABELS = {json.dumps(pie_labels)};
const PIE_VALUES = {json.dumps(pie_values)};
const PIE_COLORS = {json.dumps(pie_colors)};
const DATES   = {json.dumps(all_dates)};
const MC_DS   = {json.dumps(mc_datasets)};
const TOT_DS  = {json.dumps(total_dataset)};
const OC_DS   = {json.dumps(oc_datasets)};
const VEL_DS  = {json.dumps(vel_datasets)};
const BOOST_DS= {json.dumps(boost_datasets)};
const RATIO   = {json.dumps(online_ratio_data)};
const HM_DATA = {json.dumps(heatmap_matrix)};
const HM_DATES= {json.dumps(all_dates)};
const RAW_ROWS= {json.dumps(table_rows)};

const GRID = {{color:'#1F2630'}};
const TICK = {{color:'#8B98A6',font:{{size:11,family:"'JetBrains Mono',monospace"}}}};
const TIP  = {{
  backgroundColor:'#0F1419',borderColor:'#283040',borderWidth:1,
  titleColor:'#E6EDF3',bodyColor:'#8B98A6',
  titleFont:{{family:"'Inter',sans-serif",size:12}},
  bodyFont:{{family:"'JetBrains Mono',monospace",size:12}},
  padding:{{x:12,y:8}},
}};
const AXIS = {{
  x:{{ticks:{{...TICK,maxTicksLimit:16}},grid:GRID}},
  y:{{ticks:{{...TICK,callback:v=>v?.toLocaleString()}},grid:GRID}},
}};
const LEG = {{labels:{{color:'#8B98A6',font:{{size:11,family:"'Inter',sans-serif"}},usePointStyle:true,pointStyle:'line',boxWidth:20,padding:16}}}};

function mkLine(id, ds, extraOpts={{}}) {{
  new Chart(id, {{type:'line',
    data:{{labels:DATES,datasets:ds}},
    options:{{
      responsive:true,maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{legend:LEG,tooltip:TIP}},
      scales:AXIS,...extraOpts,
    }}
  }});
}}

{donut_renorm_js('pieChart', 'PIE_LABELS', 'PIE_VALUES', 'PIE_COLORS')}
{small_multiples_js('mcMultiples', 'DATES', 'MC_DS')}
mkLine('totalChart',TOT_DS);
mkLine('ocChart',   OC_DS);
mkLine('boostChart',BOOST_DS);
mkLine('velChart',  VEL_DS, {{
  plugins:{{legend:LEG,tooltip:{{...TIP,callbacks:{{label:c=>` ${{c.dataset.label}}: ${{c.parsed.y?.toFixed(2)}}%`}}}}}},
  scales:{{x:AXIS.x,y:{{ticks:{{...TICK,callback:v=>v+'%'}},grid:GRID,afterDataLimits(s){{const r=Math.max(Math.abs(s.min),Math.abs(s.max),1);s.min=-r;s.max=r;}}}}}}
}});

new Chart('ratioChart',{{type:'bar',
  data:{{
    labels: RATIO.map(r=>r.name),
    datasets:[{{
      label:'Online %',
      data: RATIO.map(r=>r.ratio),
      backgroundColor: RATIO.map((_,i)=>COLORS[i%COLORS.length]+'40'),
      borderColor: RATIO.map((_,i)=>COLORS[i%COLORS.length]),
      borderWidth:1,borderRadius:4,
    }}]
  }},
  options:{{
    indexAxis:'y',responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}},tooltip:{{...TIP,callbacks:{{label:c=>` ${{c.parsed.x.toFixed(1)}}%`}}}}}},
    scales:{{
      x:{{ticks:{{...TICK,callback:v=>v+'%'}},grid:GRID}},
      y:{{ticks:{{color:'#8B98A6',font:{{size:11}}}},grid:{{color:'transparent'}}}},
    }}
  }}
}});

// Heatmap
(function(){{
  const wrap = document.getElementById('heatmap');
  if(!HM_DATES.length){{wrap.innerHTML='<p style="color:var(--muted-2);padding:8px">Not enough data yet.</p>';return;}}
  const hdr = document.createElement('div'); hdr.className='hm-dates';
  HM_DATES.forEach(d=>{{
    const el=document.createElement('div'); el.className='hm-date'; el.textContent=d.slice(5); hdr.appendChild(el);
  }});
  wrap.appendChild(hdr);
  HM_DATA.forEach(srv=>{{
    const row=document.createElement('div'); row.className='hm-row';
    const lbl=document.createElement('div'); lbl.className='hm-label'; lbl.textContent=srv.name; row.appendChild(lbl);
    const cells=document.createElement('div'); cells.className='hm-cells';
    srv.vals.forEach((v,i)=>{{
      const c=document.createElement('div'); c.className='hm-cell';
      if(v==null){{ c.style.background='#131922'; }}
      else{{
        const intensity=v/srv.max;
        c.style.background=`rgba(74,158,255,${{(.08+intensity*.65).toFixed(2)}})`;
        c.title=`${{srv.name}} · ${{HM_DATES[i]}}: ${{v.toLocaleString()}} online (norm)${{srv.raw_vals&&srv.raw_vals[i]!=null?` · raw ${{srv.raw_vals[i].toLocaleString()}}`:''}}`;
      }}
      cells.appendChild(c);
    }});
    row.appendChild(cells); wrap.appendChild(row);
  }});
}})();

// Table
const TIER_LABELS = ['None','Level 1','Level 2','Level 3'];
const TIER_CSS    = ['tier-0','tier-1','tier-2','tier-3'];
let sortCol='members', sortDir=-1;

function fmtN(v, sfx='', dec=0) {{
  if(v===null||v===undefined) return '<span class="dim">—</span>';
  const abs = dec>0 ? Math.abs(v).toFixed(dec) : Math.abs(v).toLocaleString();
  const sign = v>0?'+':v<0?'-':'';
  const cls  = v>0?'pos':v<0?'neg':'';
  return cls ? `<span class="${{cls}}">${{sign}}${{abs}}${{sfx}}</span>` : `${{abs}}${{sfx}}`;
}}

function renderTable(rows) {{
  const sorted = [...rows].sort((a,b)=>{{
    const av=a[sortCol], bv=b[sortCol];
    if(av==null) return 1; if(bv==null) return -1;
    return (typeof av==='string' ? av.localeCompare(bv) : av-bv)*sortDir;
  }});
  document.getElementById('tableBody').innerHTML = sorted.map(r=>{{
    const tier = r.boost_tier ?? 0;
    return `<tr>
      <td><b>${{r.name}}</b></td>
      <td style="font-family:var(--mono)">${{r.members?r.members.toLocaleString():'—'}}</td>
      <td style="font-family:var(--mono)">${{r.online_pct!=null?r.online_pct.toFixed(1)+'%':'—'}}</td>
      <td style="font-family:var(--mono)">${{r.boost_count??'—'}}</td>
      <td style="font-family:var(--mono)">${{fmtN(r.d7)}}</td>
      <td style="font-family:var(--mono)">${{fmtN(r.mpd,'',1)}}</td>
      <td class="col-advanced"><span class="tier ${{TIER_CSS[tier]}}">${{TIER_LABELS[tier]}}</span></td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.channel_count??'<span class="dim">—</span>'}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.role_count??'<span class="dim">—</span>'}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.d30)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.proj!=null?r.proj.toLocaleString():'<span class="dim">—</span>'}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.market_share!=null?r.market_share.toFixed(2)+'%':'<span class="dim">—</span>'}}</td>
      <td class="col-advanced" style="color:var(--muted-2);font-family:var(--mono);font-size:11px">${{r.last_seen}}</td>
    </tr>`;
  }}).join('');
}}

document.querySelectorAll('#summaryTable th[data-col]').forEach(th=>{{
  th.addEventListener('click',()=>{{
    const col=th.dataset.col;
    sortDir = sortCol===col ? -sortDir : -1;
    sortCol = col;
    document.querySelectorAll('#summaryTable th').forEach(t=>{{
      t.classList.remove('sort-asc','sort-desc');
      t.querySelector('.arr').textContent='↕';
    }});
    th.classList.add(sortDir===-1?'sort-desc':'sort-asc');
    th.querySelector('.arr').textContent = sortDir===-1?'↓':'↑';
    renderTable(RAW_ROWS);
  }});
}});
renderTable(RAW_ROWS);
const dflt = document.querySelector('#summaryTable th[data-col="members"]');
dflt.classList.add('sort-desc'); dflt.querySelector('.arr').textContent='↓';
{TABLE_EXPAND_JS}
setupTableExpand('summaryTable','expandBtn');
</script>
</main>
</body>
</html>"""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"report_{last_date}.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report saved: {out}")
    if open_browser:
        webbrowser.open(out.as_uri())
    return str(out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    build_report(args.days)
