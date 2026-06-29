"""
Generate a self-contained HTML report from the snapshot database.
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
from db import init_db, get_history, get_latest_per_server, get_predictions, get_active_servers, get_roster_added_by_name, DATA_DIR
from report_fragments import RED_FLAGS_CSS, TABLE_EXPAND_JS, donut_renorm_js, small_multiples_js, coverage_banner_html
from market_report_extras import enrich_market_rows, market_extras
from metrics import build_normalized_heatmap, series_with_first_seen
from coverage_report import prepare_coverage_context

WAVE_SERVER = "Wave Free Dropmaps"

REPORTS_DIR = DATA_DIR / "reports"

COLORS = [
    "#4A9EFF","#7C5CFF","#3FB68B","#E8A23B",
    "#E5484D","#5BCEDA","#F472B6","#60A5FA",
    "#FBBF24","#34D399","#FB923C","#F87171",
]


def fmt_ts(ts):
    if not ts: return "—"
    return ts[:16].replace("T", " ") + " UTC"


def build_report(days=90, open_browser=True):
    init_db()
    latest  = get_latest_per_server()
    history = get_history(days)
    preds   = get_predictions()

    if not latest:
        print("No data yet. Run a collect first.")
        sys.exit(1)

    # ── Index data ────────────────────────────────────────────────────────────
    current_members = {r["name"]: r["member_count"] or 0 for r in latest}
    current_total   = sum(current_members.values()) or 1

    by_server_day: dict = defaultdict(dict)
    by_server_day_online: dict = defaultdict(dict)
    by_day: dict = defaultdict(dict)
    for row in history:
        day = row["captured_at"][:10]
        name = row["name"]
        by_day[day][name] = row
        by_server_day[name][day]        = row["member_count"] or 0
        by_server_day_online[name][day] = row["online_count"] or 0

    all_dates    = sorted({row["captured_at"][:10] for row in history})
    active_names = [s["name"] for s in get_active_servers()]
    server_names = active_names or sorted(by_server_day.keys())

    cov = prepare_coverage_context(
        history, by_day, server_names, roster_added=get_roster_added_by_name()
    )
    first_seen = cov["first_seen"]
    complete_days = set(cov["audit"]["complete_days"])
    coverage_html = coverage_banner_html(cov["audit"], cov["entrants"])
    day_totals = cov["day_totals"]

    day_server: dict = defaultdict(dict)
    for day, srv_map in by_day.items():
        if day in complete_days:
            for name, row in srv_map.items():
                if row.get("member_count") is not None:
                    day_server[day][name] = row["member_count"]

    all_hist_days = sorted(day_totals.keys())

    # ── Growth helpers ────────────────────────────────────────────────────────
    def nearest_day_before(target: str):
        for d in reversed(all_hist_days):
            if d <= target: return d
        return None

    def growth_stats(name, days_back):
        target  = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        old_day = nearest_day_before(target)
        if not old_day: return None, None, None
        old_m = day_server[old_day].get(name)
        if not old_m: return None, None, None
        old_total = day_totals.get(old_day) or 1
        cur = current_members.get(name, 0)
        delta  = cur - old_m
        pct    = round(delta / old_m * 100, 2)
        s_delta= round(cur/current_total*100 - old_m/old_total*100, 2)
        return delta, pct, s_delta

    def members_per_day(name):
        d7, _, _ = growth_stats(name, 7)
        return round(d7 / 7, 1) if d7 is not None else None

    def linear_projection(name, forward_days=30):
        day_latest = {}
        for row in history:
            if row["name"] != name or not row["member_count"]:
                continue
            day = row["captured_at"][:10]
            day_latest[day] = row["member_count"]

        pts = sorted(day_latest.items())
        if len(pts) < 2: return None

        d0 = datetime.fromisoformat(pts[0][0])
        xs = [(datetime.fromisoformat(d) - d0).days for d, _ in pts]
        ys = [v for _, v in pts]

        if xs[-1] == 0: return None

        n  = len(xs)
        xm, ym = sum(xs)/n, sum(ys)/n
        num = sum((xs[i]-xm)*(ys[i]-ym) for i in range(n))
        den = sum((xs[i]-xm)**2 for i in range(n))
        if den == 0: return None
        slope = num / den
        return max(0, round(ys[-1] + slope * forward_days))

    def acceleration(name):
        d7  = nearest_day_before((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"))
        d14 = nearest_day_before((datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d"))
        if not d7 or not d14: return None
        m_now = current_members.get(name, 0)
        m_7   = by_server_day[name].get(d7)
        m_14  = by_server_day[name].get(d14)
        if m_7 is None or m_14 is None: return None
        return round((m_now - m_7) / 7 - (m_7 - m_14) / 7, 1)

    def eng_trend(name):
        d30 = nearest_day_before((datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"))
        if not d30: return None
        m_now = current_members.get(name, 0)
        o_now = (latest_by_name.get(name) or {}).get("online_count") or 0
        m_30  = by_server_day[name].get(d30)
        o_30  = by_server_day_online[name].get(d30)
        if not m_30 or not o_30: return None
        return round(o_now / m_now * 100 - o_30 / m_30 * 100, 1) if m_now else None

    # ── Market rank (Wave's rank now vs 7d ago) ───────────────────────────────
    latest_by_name = {r["name"]: r for r in latest}
    sorted_now     = sorted(current_members.items(), key=lambda x: x[1], reverse=True)
    wave_rank_now  = next((i+1 for i,(n,_) in enumerate(sorted_now) if n==WAVE_SERVER), None)
    d7_ago_rank    = nearest_day_before((datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"))
    mc_7d          = {n: by_server_day[n].get(d7_ago_rank, 0) for n in server_names} if d7_ago_rank else {}
    wave_rank_7d   = next((i+1 for i,(n,_) in enumerate(sorted(mc_7d.items(), key=lambda x: x[1], reverse=True)) if n==WAVE_SERVER), None) if mc_7d else None
    rank_delta     = (wave_rank_7d - wave_rank_now) if wave_rank_now and wave_rank_7d else None
    rank_sub       = (f"↑{rank_delta} from last week" if rank_delta and rank_delta>0 else (f"↓{abs(rank_delta)} from last week" if rank_delta and rank_delta<0 else "same as last week")) if rank_delta is not None else "not enough history"

    # ── Convergence ETA ───────────────────────────────────────────────────────
    wave_mc_val  = current_members.get(WAVE_SERVER, 0)
    wave_mpd_val = members_per_day(WAVE_SERVER) or 0
    convergence  = []
    for r in latest:
        name = r["name"]
        if name == WAVE_SERVER: continue
        comp_mc  = current_members.get(name, 0)
        comp_mpd = members_per_day(name) or 0
        gap      = wave_mc_val - comp_mc
        rel_vel  = wave_mpd_val - comp_mpd
        if gap <= 0:
            convergence.append({"name": name, "status": "ahead",   "gap": -gap,  "eta": None, "rel_vel": rel_vel})
        elif rel_vel < -0.1:
            convergence.append({"name": name, "status": "catching","gap": gap,    "eta": round(gap/abs(rel_vel)), "rel_vel": rel_vel})
        else:
            convergence.append({"name": name, "status": "safe",    "gap": gap,    "eta": None, "rel_vel": rel_vel})
    convergence.sort(key=lambda x: ({"ahead":0,"catching":1,"safe":2}[x["status"]], x.get("eta") or 99999))

    # Fastest accelerating competitor
    comp_accels   = [(r["name"], acceleration(r["name"])) for r in latest if r["name"] != WAVE_SERVER]
    comp_accels   = [(n,a) for n,a in comp_accels if a is not None]
    fastest_accel = max(comp_accels, key=lambda x: x[1]) if comp_accels else None
    closest_threat = next((c for c in convergence if c["status"] in ("ahead","catching")), None)

    conv_cards_html = ""
    for c in convergence:
        if c["status"] == "ahead":
            icon, cls = "🚨", "threat-ahead"
            detail = f'Ahead of Wave by <b>{c["gap"]:,}</b> members · rel. velocity: <span class="{"pos" if c["rel_vel"]>0 else "neg"}">{c["rel_vel"]:+.1f}/day</span>'
        elif c["status"] == "catching":
            icon, cls = "⚠️", "threat-catching"
            detail = f'Gap: <b>{c["gap"]:,}</b> members · gaining <b>{abs(c["rel_vel"]):.1f}/day</b> on Wave · ETA: <b>~{c["eta"]} days</b>'
        else:
            icon, cls = "✅", "threat-safe"
            detail = f'Gap: <b>{c["gap"]:,}</b> members · Wave pulling ahead at <b>+{c["rel_vel"]:.1f}/day</b>'
        conv_cards_html += f'<div class="conv-card {cls}"><span class="conv-icon">{icon}</span><div><div class="conv-name">{c["name"]}</div><div class="conv-detail">{detail}</div></div></div>\n'

    # ── Predictions index ─────────────────────────────────────────────────────
    pred_by_server: dict = {}
    for p in preds:
        if p["name"] not in pred_by_server:
            pred_by_server[p["name"]] = p

    # ── Chart datasets ────────────────────────────────────────────────────────
    pie_labels = [r["name"] for r in latest]
    pie_values = [r["member_count"] or 0 for r in latest]
    pie_colors = COLORS[:len(pie_labels)]

    line_datasets = []
    for i, name in enumerate(server_names):
        series = series_with_first_seen(by_server_day, name, all_dates, first_seen)
        line_datasets.append({"label":name,"data":series,
            "borderColor":COLORS[i%len(COLORS)],
            "backgroundColor":COLORS[i%len(COLORS)]+"1f",
            "tension":0.4,"fill":False,"spanGaps":True,
            "pointRadius":0,"pointHoverRadius":4,"borderWidth":2})

    stacked_datasets = []
    for i, name in enumerate(server_names):
        series = []
        for d in all_dates:
            m = by_server_day[name].get(d)
            t = day_totals.get(d)
            series.append(round(m / t * 100, 2) if d in complete_days and t and m else None)
        stacked_datasets.append({"label":name,"data":series,
            "_raw":[by_server_day[name].get(d) if d in complete_days else None for d in all_dates],
            "borderColor":COLORS[i%len(COLORS)],
            "backgroundColor":COLORS[i%len(COLORS)]+"55",
            "tension":0.4,"fill":True,"spanGaps":True,
            "pointRadius":0,"pointHoverRadius":4,"borderWidth":1.5})

    vel_datasets = []
    for i, name in enumerate(server_names):
        series = []
        for j, day in enumerate(all_dates):
            target = (datetime.fromisoformat(day) - timedelta(days=7)).strftime("%Y-%m-%d")
            old_day = next((d for d in reversed(all_dates[:j]) if d <= target), None)
            cur_m = by_server_day[name].get(day)
            old_m = by_server_day[name].get(old_day) if old_day else None
            if cur_m and old_m and old_m > 0:
                series.append(round((cur_m - old_m) / old_m * 100, 2))
            else:
                series.append(None)
        vel_datasets.append({"label":name,"data":series,
            "borderColor":COLORS[i%len(COLORS)],
            "backgroundColor":"transparent",
            "tension":0.4,"fill":False,"spanGaps":False,
            "pointRadius":0,"pointHoverRadius":4,"borderWidth":2})

    online_datasets = []
    for i, name in enumerate(server_names):
        series = [by_server_day_online[name].get(d) for d in all_dates]
        online_datasets.append({"label":name,"data":series,
            "borderColor":COLORS[i%len(COLORS)],
            "backgroundColor":COLORS[i%len(COLORS)]+"1f",
            "tension":0.4,"fill":False,"spanGaps":True,
            "pointRadius":0,"pointHoverRadius":4,"borderWidth":2})

    ratio_data = []
    for r in latest:
        m = r["member_count"] or 0
        o = r["online_count"] or 0
        ratio_data.append({"name":r["name"], "ratio": round(o/m*100,1) if m else 0})
    ratio_data.sort(key=lambda x: x["ratio"], reverse=True)

    rank_by: dict = defaultdict(dict)
    for row in history:
        dr = row.get("discovery_rank")
        if dr is not None:
            rank_by[row["name"]][row["captured_at"][:10]] = dr

    rank_datasets = []
    for i, name in enumerate(server_names):
        if not rank_by.get(name):
            continue
        series = [rank_by[name].get(d) for d in all_dates]
        if not any(s is not None for s in series):
            continue
        rank_datasets.append({
            "label": name, "data": series,
            "borderColor": COLORS[i % len(COLORS)],
            "backgroundColor": "transparent",
            "tension": 0.4, "fill": False, "spanGaps": True,
            "pointRadius": 2, "pointHoverRadius": 5, "borderWidth": 2,
        })

    eng_datasets = []
    for i, name in enumerate(server_names):
        series = []
        for d in all_dates:
            m = by_server_day[name].get(d)
            o = by_server_day_online[name].get(d)
            series.append(round(o/m*100, 1) if m and o else None)
        eng_datasets.append({"label":name,"data":series,
            "borderColor":COLORS[i%len(COLORS)],
            "backgroundColor":COLORS[i%len(COLORS)]+"1f",
            "tension":0.4,"fill":False,"spanGaps":True,"pointRadius":0,"pointHoverRadius":4,"borderWidth":2})

    new_server_cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    # ── Table rows ────────────────────────────────────────────────────────────
    table_rows = []
    for r in latest:
        name = r["name"]
        d7, p7, s7    = growth_stats(name, 7)
        d30, p30, s30 = growth_stats(name, 30)
        share  = round(current_members[name] / current_total * 100, 2)
        mpd    = members_per_day(name)
        proj   = linear_projection(name)
        online_pct = round((r["online_count"] or 0) / (r["member_count"] or 1) * 100, 1)

        p = pred_by_server.get(name)
        if p:
            if p["hit"] is None:
                pred_label = f'{p["predicted_members"]:,} by {p["target_date"]}'
                pred_status = "pending"
            elif p["hit"] == 1:
                pred_label = f'Hit {p["actual_members"]:,} (target {p["predicted_members"]:,})'
                pred_status = "hit"
            else:
                pred_label = f'Missed — got {p["actual_members"]:,} (target {p["predicted_members"]:,})'
                pred_status = "miss"
        else:
            pred_label, pred_status = "—", ""

        is_new = bool(first_seen.get(name, "") >= new_server_cutoff)
        row_dict = {
            "name":       name,
            "is_wave":    name == WAVE_SERVER,
            "is_us":      name == WAVE_SERVER,
            "is_new":     is_new,
            "tracked_since": first_seen.get(name),
            "members":    r["member_count"] or 0,
            "online":     r["online_count"] or 0,
            "online_pct": online_pct,
            "eng_trend":  eng_trend(name),
            "share":      share,
            "mpd":        mpd,
            "accel":      acceleration(name),
            "d7":         d7,
            "p7":         p7,
            "s7":         s7,
            "d30":        d30,
            "p30":        p30,
            "s30":        s30,
            "proj":       proj,
            "pred_label": pred_label,
            "pred_status":pred_status,
            "last_seen":  fmt_ts(r["captured_at"]),
            "captured_at": r.get("captured_at") or "",
        }
        if "discovery_rank" in r:
            row_dict["discovery_rank"] = r["discovery_rank"]
        table_rows.append(row_dict)

    hist_for_baseline = [
        {"name": r.get("name"), "member_count": r.get("member_count"), "online_count": r.get("online_count"), "captured_at": r.get("captured_at", "")}
        for r in history
    ]
    heatmap_matrix = build_normalized_heatmap(hist_for_baseline, all_dates, server_names)
    heatmap_dates = all_dates
    table_rows = enrich_market_rows(table_rows, by_server_day, day_totals, all_dates, current_total, hist_for_baseline)
    extras = market_extras(table_rows, WAVE_SERVER, rank_delta, preds, closest_threat, {"Wave Free Dropmaps"}, hist_for_baseline)

    total_oc        = sum(r["online_count"] or 0 for r in latest)
    total_members_all = sum(current_members.values())
    avg_online_pct  = round(total_oc / max(total_members_all, 1) * 100, 1)

    generated_at      = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    last_date         = all_dates[-1] if all_dates else "—"
    first_date        = all_dates[0]  if all_dates else "—"
    total_servers     = len(server_names)
    wave_mc_display   = f"{wave_mc_val:,}" if wave_mc_val else "—"

    rank_section_html = ""
    if rank_datasets:
        rank_section_html = """
<div class="card" style="margin-bottom:16px">
  <h2>Discovery Search Rank Over Time</h2>
  <h3>Lower rank = higher position on Discord Discover (Discover-scraped servers only)</h3>
  <div class="chart-tall"><canvas id="rankChart"></canvas></div>
</div>"""

    # ── HTML ──────────────────────────────────────────────────────────────────
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Drop Map Market Research — {last_date}</title>
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
  background:var(--accent);border-radius:2px;box-shadow:0 0 12px var(--accent);
}}
.topbar .pill{{
  padding:4px 10px;border-radius:6px;
  background:var(--panel-2);border:1px solid var(--border);
  color:var(--muted);font-size:12px;font-family:var(--mono);
  margin-left:auto;
}}
main{{padding:24px 20px;max-width:1500px;margin:0 auto}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:20px}}
.card{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:18px}}
.kpi{{padding:16px;min-width:0}}
.kpi .label{{color:var(--muted);text-transform:uppercase;font-size:10px;letter-spacing:.08em;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.kpi .value{{font-family:var(--mono);font-size:22px;font-weight:500;font-variant-numeric:tabular-nums;letter-spacing:-0.03em;margin-top:6px;line-height:1.1;color:var(--accent)}}
.kpi .sub{{color:var(--muted);font-size:11px;margin-top:4px}}
.row{{display:grid;gap:16px;margin-bottom:16px}}
.row.cols-2{{grid-template-columns:1fr 1fr}}
.row.full{{grid-template-columns:1fr}}
.card h2{{margin:0 0 14px;font-size:13px;font-weight:600;color:var(--text)}}
.card h3{{margin:0 0 4px;font-size:11px;font-weight:600;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}}
.chart-wrap{{position:relative;height:280px}}
.chart-tall{{position:relative;height:360px}}
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
.badge{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-family:var(--mono);font-weight:500}}
.badge-hit{{background:rgba(63,182,139,0.1);color:var(--good);border:1px solid rgba(63,182,139,0.3)}}
.badge-miss{{background:rgba(229,72,77,0.1);color:var(--bad);border:1px solid rgba(229,72,77,0.3)}}
.badge-pend{{background:rgba(74,158,255,0.08);color:var(--muted);border:1px solid var(--border)}}
.heatmap{{overflow-x:auto;padding-top:4px}}
.hm-row{{display:flex;align-items:center;gap:4px;margin-bottom:3px}}
.hm-label{{width:190px;min-width:190px;color:var(--muted);text-align:right;padding-right:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}}
.hm-cells{{display:flex;gap:2px}}
.hm-cell{{width:13px;height:13px;border-radius:3px;cursor:default;flex-shrink:0}}
.hm-dates{{display:flex;gap:2px;margin-left:200px;margin-bottom:6px}}
.hm-date{{width:13px;text-align:center;font-size:9px;color:var(--muted-2);transform:rotate(-60deg);transform-origin:bottom left;height:18px}}
hr.divider{{border:0;border-top:1px solid var(--border);margin:20px 0}}
.badge-wave{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-family:var(--mono);font-weight:500;background:rgba(74,158,255,0.08);color:var(--accent);border:1px solid rgba(74,158,255,0.3)}}
.badge-new{{display:inline-block;padding:2px 7px;border-radius:4px;font-size:11px;font-family:var(--mono);font-weight:500;background:rgba(63,182,139,0.1);color:var(--good);border:1px solid rgba(63,182,139,0.3)}}
.conv-grid{{display:grid;gap:10px}}
.conv-card{{display:flex;align-items:flex-start;gap:12px;padding:14px;border-radius:8px;border:1px solid var(--border)}}
.conv-card.threat-ahead{{background:rgba(229,72,77,0.06);border-color:rgba(229,72,77,0.25)}}
.conv-card.threat-catching{{background:rgba(232,162,59,0.06);border-color:rgba(232,162,59,0.25)}}
.conv-card.threat-safe{{background:rgba(63,182,139,0.06);border-color:rgba(63,182,139,0.2)}}
.conv-icon{{font-size:18px;line-height:1;padding-top:2px;flex-shrink:0}}
.conv-name{{font-weight:600;margin-bottom:4px}}
.conv-detail{{color:var(--muted);font-size:12px;line-height:1.5}}
@media(max-width:1100px){{.kpi-row{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:900px){{.row.cols-2{{grid-template-columns:1fr}}}}
@media(max-width:600px){{.kpi-row{{grid-template-columns:1fr}}}}
{RED_FLAGS_CSS}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">Drop Map Market Research</div>
  <div class="pill">{generated_at}</div>
</header>
{extras["threat_banner_html"]}
<main>
{coverage_html}
{extras["red_flags_html"]}

<div class="kpi-row">
  <div class="card kpi">
    <div class="label">Servers Tracked</div>
    <div class="value">{total_servers}</div>
    <div class="sub">{first_date} → {last_date}</div>
  </div>
  <div class="card kpi">
    <div class="label">Total Members (all)</div>
    <div class="value">{total_members_all:,}</div>
    <div class="sub">across all tracked servers</div>
  </div>
  <div class="card kpi">
    <div class="label">Wave Members</div>
    <div class="value">{wave_mc_display}</div>
    <div class="sub">Wave Free Dropmaps</div>
  </div>
  <div class="card kpi">
    <div class="label">Wave Market Rank</div>
    <div class="value" style="color:{'var(--good)' if wave_rank_now==1 else 'var(--warn)'}">{'#'+str(wave_rank_now) if wave_rank_now else '—'}</div>
    <div class="sub">{rank_sub}</div>
  </div>
</div>

<div class="kpi-row" style="margin-top:0">
  <div class="card kpi">
    <div class="label">Data Points</div>
    <div class="value">{len(history):,}</div>
    <div class="sub">total snapshots stored</div>
  </div>
  <div class="card kpi">
    <div class="label">{'⚠️ Closest Threat' if closest_threat else 'Competitive Position'}</div>
    <div class="value" style="font-size:14px;color:{'var(--bad)' if closest_threat and closest_threat['status']=='ahead' else ('var(--warn)' if closest_threat else 'var(--good)')}">
      {closest_threat['name'] if closest_threat else 'All clear'}</div>
    <div class="sub">{'Ahead by '+str(closest_threat['gap'])+' members' if closest_threat and closest_threat['status']=='ahead' else ('ETA ~'+str(closest_threat['eta'])+'d' if closest_threat and closest_threat.get('eta') else ('No competitors gaining' if not closest_threat else ''))}</div>
  </div>
  <div class="card kpi">
    <div class="label">Fastest Accelerating</div>
    <div class="value" style="font-size:14px;color:var(--warn)">{fastest_accel[0] if fastest_accel else '—'}</div>
    <div class="sub">{('+'+str(fastest_accel[1])+'/day accel') if fastest_accel and fastest_accel[1] is not None else 'Not enough history'}</div>
  </div>
  <div class="card kpi">
    <div class="label">Snapshot Window</div>
    <div class="value" style="font-size:13px;color:var(--muted);font-family:var(--mono);padding-top:4px">{first_date}<br>→ {last_date}</div>
    <div class="sub">{days}d window</div>
  </div>
</div>

<div class="kpi-row">
  <div class="card kpi">
    <div class="label">Wave Share Δ (7d)</div>
    <div class="value" style="color:{'var(--good)' if (extras.get('wave_share_delta_7d') or 0) >= 0 else 'var(--bad)'}">{extras.get('wave_share_delta_7d') if extras.get('wave_share_delta_7d') is not None else '—'}{('pp' if extras.get('wave_share_delta_7d') is not None else '')}</div>
    <div class="sub">share points vs 7 days ago</div>
  </div>
  <div class="card kpi">
    <div class="label">Market HHI</div>
    <div class="value" style="font-size:16px">{extras['hhi']['hhi'] if extras['hhi']['hhi'] is not None else '—'}</div>
    <div class="sub">{extras['hhi']['label']}</div>
  </div>
  <div class="card kpi">
    <div class="label">Growth Capture (7d)</div>
    <div class="value" style="font-size:12px;line-height:1.3;padding-top:4px">{extras['capture_text']}</div>
    <div class="sub">who won incremental growth</div>
  </div>
  <div class="card kpi">
    <div class="label">Prediction Scorecard</div>
    <div class="value" style="font-size:14px">{extras['pred_text']}</div>
    <div class="sub">Wave 30-day targets</div>
  </div>
</div>

<div class="kpi-row">
  <div class="card kpi">
    <div class="label">Wave Boost Health</div>
    <div class="value" style="font-size:13px">{extras['boost_text']}</div>
    <div class="sub">from guild-dash snapshot</div>
  </div>
  <div class="card kpi">
    <div class="label">Online Metrics</div>
    <div class="value" style="font-size:12px;color:var(--muted)">{extras['norm_note']}</div>
    <div class="sub">avg raw {avg_online_pct}% online now</div>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h2>Market Share (current)</h2>
    <h3>Share of total members by server</h3>
    <div class="chart-wrap"><canvas id="pieChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Online Engagement Ratio</h2>
    <h3>Online members as a % of total members</h3>
    <div class="chart-wrap"><canvas id="ratioChart"></canvas></div>
  </div>
</div>

<div class="row full">
  <div class="card">
    <h2>Member Growth Over Time</h2>
    <h3>Per-server mini charts (shared scale)</h3>
    <div class="multiples-grid" id="mcMultiples"></div>
  </div>
</div>

<div class="row">
  <div class="card">
    <h2>Online Activity Over Time</h2>
    <h3>Concurrent online members per server</h3>
    <div class="chart-tall"><canvas id="onlineChart"></canvas></div>
  </div>
</div>

<div class="row">
  <div class="card">
    <h2>Market Share Over Time</h2>
    <h3>Each server's % of total tracked members</h3>
    <div class="chart-tall"><canvas id="stackedChart"></canvas></div>
  </div>
</div>

<div class="row cols-2">
  <div class="card">
    <h2>Growth Velocity</h2>
    <h3>Week-over-week % growth rate per server</h3>
    <div class="chart-wrap"><canvas id="velChart"></canvas></div>
  </div>
  <div class="card">
    <h2>Engagement Trend Over Time</h2>
    <h3>Online % per server — rising = healthier community</h3>
    <div class="chart-wrap"><canvas id="engChart"></canvas></div>
  </div>
</div>

<div class="card" style="margin-bottom:16px">
  <h2>Server Summary</h2>
  <h3 style="margin-bottom:14px">Click any column header to sort · Accel = growth acceleration (members/day/day)</h3>
  <div class="table-toolbar"><button type="button" id="expandBtn">Show all columns</button></div>
  <div style="overflow-x:auto">
  <table id="mainTable" style="min-width:1200px">
    <thead><tr>
      <th data-col="name"            data-type="str">Server<span class="arr">↕</span></th>
      <th data-col="members"         data-type="num">Members<span class="arr">↕</span></th>
      <th data-col="share"           data-type="num">Share %<span class="arr">↕</span></th>
      <th data-col="s7"              data-type="num">Share Δ 7d<span class="arr">↕</span></th>
      <th data-col="d7"              data-type="num">7d Δ<span class="arr">↕</span></th>
      <th data-col="mpd"             data-type="num">Mem/Day<span class="arr">↕</span></th>
      <th data-col="discovery_rank"  data-type="num" class="col-advanced">Discovery<span class="arr">↕</span></th>
      <th data-col="online"          data-type="num" class="col-advanced">Online<span class="arr">↕</span></th>
      <th data-col="online_pct"      data-type="num" class="col-advanced">Online %<span class="arr">↕</span></th>
      <th data-col="eng_trend"       data-type="num" class="col-advanced">Eng. Trend<span class="arr">↕</span></th>
      <th data-col="accel"           data-type="num" class="col-advanced">Accel<span class="arr">↕</span></th>
      <th data-col="p7"              data-type="num" class="col-advanced">7d %<span class="arr">↕</span></th>
      <th data-col="d30"             data-type="num" class="col-advanced">30d Δ<span class="arr">↕</span></th>
      <th data-col="p30"             data-type="num" class="col-advanced">30d %<span class="arr">↕</span></th>
      <th data-col="s30"             data-type="num" class="col-advanced">Share Δ 30d<span class="arr">↕</span></th>
      <th data-col="proj"            data-type="num" class="col-advanced">Proj 30d<span class="arr">↕</span></th>
      <th data-col="last_seen"       data-type="str" class="col-advanced">Last Seen<span class="arr">↕</span></th>
    </tr></thead>
    <tbody id="tableBody"></tbody>
  </table>
  </div>
</div>

{rank_section_html}

<div class="card" style="margin-bottom:16px">
  <h2>Online Activity Heatmap</h2>
  <h3 style="margin-bottom:12px">Normalized toward 14:00 UTC · tooltip shows raw online count</h3>
  <div class="heatmap" id="heatmap"></div>
</div>

<div class="card" style="margin-bottom:16px">
  <h2>Convergence Analysis</h2>
  <h3 style="margin-bottom:14px">Wave Free Dropmaps vs each competitor at current growth rates</h3>
  <div class="conv-grid">
    {conv_cards_html}
  </div>
</div>

<div class="card">
  <h2>30-Day Predictions</h2>
  <h3 style="margin-bottom:14px">Auto-generated member count targets</h3>
  <div style="overflow-x:auto">
  <table style="min-width:700px">
    <thead><tr>
      <th>Server</th><th>Made On</th><th>Target Date</th>
      <th>Baseline</th><th>Predicted</th><th>Actual</th><th>Result</th>
    </tr></thead>
    <tbody id="predBody"></tbody>
  </table>
  </div>
</div>

<script>
const COLORS = {json.dumps(COLORS)};
const PIE_LABELS    = {json.dumps(pie_labels)};
const PIE_VALUES    = {json.dumps(pie_values)};
const PIE_COLORS    = {json.dumps(pie_colors)};
const LINE_LABELS   = {json.dumps(all_dates)};
const LINE_DS       = {json.dumps(line_datasets)};
const STACK_DS      = {json.dumps(stacked_datasets)};
const VEL_DS        = {json.dumps(vel_datasets)};
const ENG_DS        = {json.dumps(eng_datasets)};
const ONLINE_DS     = {json.dumps(online_datasets)};
const RATIO_DATA    = {json.dumps(ratio_data)};
const HM_DATA       = {json.dumps(heatmap_matrix)};
const HM_DATES      = {json.dumps(heatmap_dates)};
const RANK_DS       = {json.dumps(rank_datasets)};
const RAW_ROWS      = {json.dumps(table_rows)};
const PRED_DATA     = {json.dumps(preds)};

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
  x:{{ticks:{{...TICK,maxTicksLimit:14}},grid:GRID}},
  y:{{ticks:{{...TICK,callback:v=>v?.toLocaleString()}},grid:GRID}},
}};
const LEG = {{labels:{{color:'#8B98A6',font:{{size:11,family:"'Inter',sans-serif"}},usePointStyle:true,pointStyle:'line',boxWidth:20,padding:16}}}};

/* donut */
{donut_renorm_js('pieChart', 'PIE_LABELS', 'PIE_VALUES', 'PIE_COLORS')}

/* online engagement bar */
new Chart('ratioChart',{{type:'bar',
  data:{{
    labels:RATIO_DATA.map(r=>r.name),
    datasets:[{{label:'Online %',data:RATIO_DATA.map(r=>r.ratio),
      backgroundColor:RATIO_DATA.map((_,i)=>COLORS[i%COLORS.length]+'40'),
      borderColor:RATIO_DATA.map((_,i)=>COLORS[i%COLORS.length]),
      borderWidth:1,borderRadius:4}}]
  }},
  options:{{
    indexAxis:'y',responsive:true,maintainAspectRatio:false,
    plugins:{{legend:{{display:false}},tooltip:{{...TIP,callbacks:{{label:c=>` ${{c.parsed.x}}%`}}}}}},
    scales:{{x:{{ticks:{{...TICK,callback:v=>v+'%'}},grid:GRID}},y:{{ticks:{{color:'#8B98A6',font:{{size:11}}}},grid:{{color:'transparent'}}}}}}
  }}
}});

function mkLine(id, ds, extraOpts={{}}) {{
  new Chart(id, {{type:'line',
    data:{{labels:LINE_LABELS,datasets:ds}},
    options:{{
      responsive:true,maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{legend:LEG,tooltip:TIP}},
      scales:AXIS,...extraOpts,
    }}
  }});
}}

{small_multiples_js('mcMultiples', 'LINE_LABELS', 'LINE_DS')}
mkLine('onlineChart', ONLINE_DS);
function renormalizeShare(chart){{
  const ds=chart.data.datasets, labels=chart.data.labels;
  for(let i=0;i<labels.length;i++){{
    let total=0; const vis=[];
    ds.forEach((d,di)=>{{
      if(chart.getDatasetMeta(di).hidden)return;
      const raw=d._raw?d._raw[i]:null;
      if(raw!=null){{total+=raw;vis.push({{di,raw}});}}
    }});
    vis.forEach(({{di,raw}})=>{{ds[di].data[i]=total>0?Math.round(raw/total*10000)/100:null;}});
  }}
  chart.update();
}}
new Chart('stackedChart',{{type:'line',data:{{labels:LINE_LABELS,datasets:STACK_DS}},
  options:{{
    responsive:true,maintainAspectRatio:false,
    interaction:{{mode:'index',intersect:false}},
    plugins:{{
      legend:{{...LEG,onClick(e,item,legend){{
        const c=legend.chart, idx=item.datasetIndex;
        c.isDatasetVisible(idx)?c.hide(idx):c.show(idx);
        renormalizeShare(c);
      }}}},
      tooltip:{{...TIP,callbacks:{{label:c=>` ${{c.dataset.label}}: ${{c.parsed.y?.toFixed(1)}}%`}}}}
    }},
    scales:{{x:AXIS.x,y:{{stacked:true,min:0,max:100,ticks:{{...TICK,callback:v=>v+'%'}},grid:GRID}}}}
  }}
}});
mkLine('velChart',    VEL_DS,{{
  plugins:{{legend:LEG,tooltip:{{...TIP,callbacks:{{label:c=>` ${{c.dataset.label}}: ${{c.parsed.y?.toFixed(2)}}%`}}}}}},
  scales:{{x:AXIS.x,y:{{ticks:{{...TICK,callback:v=>v+'%'}},grid:GRID,afterDataLimits(s){{const r=Math.max(Math.abs(s.min),Math.abs(s.max),1);s.min=-r;s.max=r;}}}}}}
}});
mkLine('engChart',    ENG_DS,{{
  plugins:{{legend:LEG,tooltip:{{...TIP,callbacks:{{label:c=>` ${{c.dataset.label}}: ${{c.parsed.y?.toFixed(1)}}%`}}}}}},
  scales:{{x:AXIS.x,y:{{ticks:{{...TICK,callback:v=>v+'%'}},grid:GRID}}}}
}});

/* heatmap */
(function(){{
  const wrap=document.getElementById('heatmap');
  if(!HM_DATES.length){{wrap.innerHTML='<p style="color:var(--muted-2);padding:8px">Not enough data yet.</p>';return;}}
  const hdr=document.createElement('div');hdr.className='hm-dates';
  HM_DATES.forEach(d=>{{const el=document.createElement('div');el.className='hm-date';el.textContent=d.slice(5);hdr.appendChild(el);}});
  wrap.appendChild(hdr);
  HM_DATA.forEach(srv=>{{
    const row=document.createElement('div');row.className='hm-row';
    const lbl=document.createElement('div');lbl.className='hm-label';lbl.textContent=srv.name;row.appendChild(lbl);
    const cells=document.createElement('div');cells.className='hm-cells';
    srv.vals.forEach((v,i)=>{{
      const c=document.createElement('div');c.className='hm-cell';
      if(v===null||v===undefined){{c.style.background='#131922';}}
      else{{const t=v/srv.max;const raw=srv.raw_vals?srv.raw_vals[i]:v;c.style.background=`rgba(74,158,255,${{(.08+t*.65).toFixed(2)}})`;c.title=`${{srv.name}} · ${{HM_DATES[i]}}: ${{(raw??0).toLocaleString()}} online (norm display)`;}}
      cells.appendChild(c);
    }});
    row.appendChild(cells);wrap.appendChild(row);
  }});
}})();

/* discovery rank chart */
if(RANK_DS.length){{
  new Chart('rankChart',{{type:'line',data:{{labels:LINE_LABELS,datasets:RANK_DS}},
    options:{{
      responsive:true,maintainAspectRatio:false,
      interaction:{{mode:'index',intersect:false}},
      plugins:{{legend:LEG,tooltip:TIP}},
      scales:{{
        x:AXIS.x,
        y:{{reverse:true,min:1,ticks:{{...TICK,precision:0}},grid:GRID,title:{{display:true,text:'Discover rank (lower=better)',color:'#8B98A6'}}}}
      }}
    }}
  }});
}}

/* table */
let sortCol='members',sortDir=-1;
function fmtN(v,sfx='',dec=0){{
  if(v===null||v===undefined)return'<span class="dim">—</span>';
  const f=dec>0?Math.abs(v).toFixed(dec):Math.abs(v).toLocaleString();
  const sign=v>0?'+':v<0?'-':'';const cls=v>0?'pos':v<0?'neg':'';
  return cls?`<span class="${{cls}}">${{sign}}${{f}}${{sfx}}</span>`:`${{f}}${{sfx}}`;
}}
function renderTable(rows){{
  const sorted=[...rows].sort((a,b)=>{{
    const av=a[sortCol],bv=b[sortCol];
    if(av===null||av===undefined)return 1;if(bv===null||bv===undefined)return-1;
    return(typeof av==='string'?av.localeCompare(bv):av-bv)*sortDir;
  }});
  document.getElementById('tableBody').innerHTML=sorted.map(r=>{{
    const waveBadge = r.is_wave ? '<span class="badge badge-wave">us</span> ' : '';
    const newBadge  = r.is_new  ? `<span class="entrant-badge">since ${{r.tracked_since||'new'}}</span> ` : '';
    return`<tr>
      <td><b>${{r.name}}</b> ${{waveBadge}}${{newBadge}}</td>
      <td style="font-family:var(--mono)">${{r.members?r.members.toLocaleString():'—'}}</td>
      <td style="font-family:var(--mono)">${{r.share!=null?r.share.toFixed(2)+'%':'—'}}</td>
      <td style="font-family:var(--mono)">${{fmtN(r.s7,'pp',2)}}</td>
      <td style="font-family:var(--mono)">${{fmtN(r.d7)}}</td>
      <td style="font-family:var(--mono)">${{fmtN(r.mpd,'',1)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.discovery_rank!=null?'#'+r.discovery_rank:'<span class="dim">—</span>'}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.online?r.online.toLocaleString():'—'}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.online_pct!=null?r.online_pct.toFixed(1)+'%':'—'}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.eng_trend,'%',1)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.accel,'',1)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.p7,'%',2)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.d30)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.p30,'%',2)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{fmtN(r.s30,'pp',2)}}</td>
      <td class="col-advanced" style="font-family:var(--mono)">${{r.proj!=null?r.proj.toLocaleString():'—'}}</td>
      <td class="col-advanced" style="color:var(--muted-2);font-family:var(--mono);font-size:11px">${{r.last_seen}}</td>
    </tr>`;
  }}).join('');
}}
document.querySelectorAll('#mainTable th[data-col]').forEach(th=>{{
  th.addEventListener('click',()=>{{
    const col=th.dataset.col;sortDir=sortCol===col?-sortDir:-1;sortCol=col;
    document.querySelectorAll('#mainTable th').forEach(t=>{{t.classList.remove('sort-asc','sort-desc');t.querySelector('.arr').textContent='↕';}});
    th.classList.add(sortDir===-1?'sort-desc':'sort-asc');th.querySelector('.arr').textContent=sortDir===-1?'↓':'↑';
    renderTable(RAW_ROWS);
  }});
}});
renderTable(RAW_ROWS);
document.querySelector('#mainTable th[data-col="members"]').classList.add('sort-desc');
document.querySelector('#mainTable th[data-col="members"] .arr').textContent='↓';

/* predictions */
(function(){{
  const seen=new Set();
  const rows=PRED_DATA.filter(p=>{{if(seen.has(p.name))return false;seen.add(p.name);return true;}});
  document.getElementById('predBody').innerHTML=rows.map(p=>{{
    const badge=p.hit===null?`<span class="badge badge-pend">Pending · due ${{p.target_date}}</span>`
      :p.hit===1?`<span class="badge badge-hit">Hit</span>`:`<span class="badge badge-miss">Missed</span>`;
    const actual=p.actual_members!=null?p.actual_members.toLocaleString():'—';
    return`<tr><td><b>${{p.name}}</b></td>
      <td style="color:var(--muted-2);font-family:var(--mono);font-size:11px">${{p.predicted_at}}</td>
      <td style="font-family:var(--mono)">${{p.target_date}}</td>
      <td style="font-family:var(--mono)">${{p.members_at_prediction.toLocaleString()}}</td>
      <td style="font-family:var(--mono)">${{p.predicted_members.toLocaleString()}}</td>
      <td style="font-family:var(--mono)">${{actual}}</td>
      <td>${{badge}}</td></tr>`;
  }}).join('');
}})();
{TABLE_EXPAND_JS}
setupTableExpand('mainTable','expandBtn');
</script>
</main>
</body>
</html>"""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORTS_DIR / f"report_{last_date}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"Report saved: {out_path}")
    if open_browser:
        webbrowser.open(out_path.as_uri())
    return str(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90)
    args = parser.parse_args()
    build_report(args.days)
