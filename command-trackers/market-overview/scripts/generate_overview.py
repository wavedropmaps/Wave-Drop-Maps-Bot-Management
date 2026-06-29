"""
Executive cross-market overview — reads latest snapshots from all three tracker DBs.
No scraping. Generates overview_YYYY-MM-DD.html
"""

import json
import sqlite3
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[3]
SHARED = REPO / "command-trackers" / "shared"
sys.path.insert(0, str(SHARED))

from metrics import (  # noqa: E402
    GUILD_DROP_MAP_ID,
    GUILD_IMPROVEMENT_ID,
    cross_market_context,
    market_hhi,
    portfolio_split,
    read_guild_boost_snapshot,
)
from report_fragments import RED_FLAGS_CSS, red_flags_html  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REPORTS_DIR = DATA_DIR / "reports"


def _query(db_path: Path, sql: str, params=()):
    if not db_path.exists():
        return []
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _drop_map_summary():
    rows = _query(
        REPO / "command-trackers" / "drop-map-research" / "data" / "data.db",
        """
        SELECT s.name, sn.member_count, sn.captured_at
        FROM snapshots sn JOIN servers s ON s.id = sn.server_id
        WHERE sn.id IN (SELECT MAX(id) FROM snapshots GROUP BY server_id) AND s.active=1
        """,
    )
    if not rows:
        return None
    total = sum(r["member_count"] or 0 for r in rows) or 1
    wave = next((r for r in rows if r["name"] == "Wave Free Dropmaps"), None)
    if not wave:
        return None
    share = round((wave["member_count"] or 0) / total * 100, 2)
    rank = 1 + sum(1 for r in rows if (r["member_count"] or 0) > (wave["member_count"] or 0))
    shares = [(r["member_count"] or 0) / total * 100 for r in rows]
    return {"rank": rank, "share": share, "members": wave["member_count"], "hhi": market_hhi(shares), "tracked": len(rows)}


def _improvement_summary():
    rows = _query(
        REPO / "command-trackers" / "market-research" / "data" / "data.db",
        """
        SELECT s.name, s.is_us, sn.member_count
        FROM servers s
        LEFT JOIN snapshots sn ON sn.id = (
            SELECT id FROM snapshots WHERE server_key=s.key ORDER BY captured_at DESC LIMIT 1
        )
        WHERE s.active=1 AND sn.member_count IS NOT NULL
        """,
    )
    if not rows:
        return None
    total = sum(r["member_count"] for r in rows) or 1
    wave = next((r for r in rows if r.get("is_us")), None)
    if not wave:
        return None
    share = round(wave["member_count"] / total * 100, 2)
    rank = 1 + sum(1 for r in rows if r["member_count"] > wave["member_count"])
    shares = [r["member_count"] / total * 100 for r in rows]
    return {"rank": rank, "share": share, "members": wave["member_count"], "hhi": market_hhi(shares), "tracked": len(rows)}


def _guild_summary():
    rows = _query(
        REPO / "command-trackers" / "guild-stats" / "data" / "data.db",
        """
        SELECT g.guild_id, g.name, s.member_count, s.boost_tier, s.boost_count, s.channel_count
        FROM snapshots s JOIN guilds g ON g.guild_id = s.guild_id
        WHERE s.id IN (SELECT MAX(id) FROM snapshots GROUP BY guild_id)
        """,
    )
    return rows


def build_report(open_browser: bool = True) -> str:
    dm = _drop_map_summary()
    imp = _improvement_summary()
    guilds = _guild_summary()
    portfolio = portfolio_split([{"name": g["name"], "members": g["member_count"]} for g in guilds])

    flags = []
    dm_active = _query(
        REPO / "command-trackers" / "drop-map-research" / "data" / "data.db",
        "SELECT COUNT(*) as n FROM servers WHERE active=1",
    )
    imp_active = _query(
        REPO / "command-trackers" / "market-research" / "data" / "data.db",
        "SELECT COUNT(*) as n FROM servers WHERE active=1",
    )
    if dm and dm_active and dm["tracked"] < dm_active[0]["n"]:
        flags.append(f"Drop-map partial scan today ({dm['tracked']}/{dm_active[0]['n']} servers)")
    if imp and imp_active and imp["tracked"] < imp_active[0]["n"]:
        flags.append(f"Improvement market partial scan today ({imp['tracked']}/{imp_active[0]['n']} servers)")
    if dm and dm["share"] < 60:
        flags.append(f"Drop-map share below 60% ({dm['share']}%)")
    if imp and imp["share"] < 55:
        flags.append(f"Improvement cord share below 55% ({imp['share']}%)")

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    guild_cards = ""
    for g in guilds:
        ctx = cross_market_context(g["guild_id"]) or {}
        guild_cards += f"""
        <div class="card kpi">
          <div class="label">{g['name'][:40]}</div>
          <div class="value" style="font-size:16px">{g['member_count']:,}</div>
          <div class="sub">Tier {g.get('boost_tier')} · {g.get('boost_count')} boosts · {g.get('channel_count')} ch</div>
          <div class="sub">{ctx.get('market_label', 'market')}: #{ctx.get('rank', '—')} · {ctx.get('share', '—')}% share</div>
        </div>"""

    port_text = " · ".join(f"{p['name'][:20]} {p['pct']}%" for p in portfolio) if portfolio else "—"

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>Wave Market Overview — {today}</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{{--bg:#0A0E14;--panel:#0F1419;--border:#1F2630;--text:#E6EDF3;--muted:#8B98A6;--accent:#4A9EFF;--good:#3FB68B;--mono:'JetBrains Mono',monospace;--sans:'Inter',sans-serif}}
body{{background:var(--bg);color:var(--text);font-family:var(--sans);margin:0;padding:24px}}
h1{{font-size:18px;margin-bottom:8px}}
.meta{{color:var(--muted);font-size:12px;margin-bottom:20px}}
.kpi-row{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px;margin-bottom:20px}}
.card{{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:16px}}
.kpi .label{{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em}}
.kpi .value{{font-family:var(--mono);font-size:22px;color:var(--accent);margin-top:6px}}
.kpi .sub{{color:var(--muted);font-size:11px;margin-top:4px}}
.links a{{color:var(--accent);margin-right:16px;font-size:13px}}
{RED_FLAGS_CSS}
</style></head><body>
<h1>Wave Market Overview</h1>
<div class="meta">Generated {generated} · reads guild-dash + mktdash + rdropmap DBs (no live scrape)</div>
{red_flags_html(flags)}
<div class="kpi-row">
  <div class="card kpi">
    <div class="label">Drop Map Market</div>
    <div class="value">{'#' + str(dm['rank']) if dm else '—'}</div>
    <div class="sub">{f"{dm['share']}% share · HHI {dm['hhi']['hhi']} ({dm['hhi']['label']}) · {dm['tracked']} tracked" if dm else 'no data'}</div>
  </div>
  <div class="card kpi">
    <div class="label">Improvement Cord Market</div>
    <div class="value">{'#' + str(imp['rank']) if imp else '—'}</div>
    <div class="sub">{f"{imp['share']}% share · HHI {imp['hhi']['hhi']} ({imp['hhi']['label']}) · {imp['tracked']} tracked" if imp else 'no data'}</div>
  </div>
  <div class="card kpi">
    <div class="label">Wave Portfolio Split</div>
    <div class="value" style="font-size:13px;line-height:1.4">{port_text}</div>
    <div class="sub">combined Wave guild members</div>
  </div>
</div>
<h2 style="font-size:14px;margin:20px 0 12px">Guild Infrastructure</h2>
<div class="kpi-row">{guild_cards}</div>
<div class="links" style="margin-top:24px">
  <a href="../../guild-stats/data/reports/">guilddash reports</a>
  <a href="../../market-research/data/reports/">mktdash reports</a>
  <a href="../../drop-map-research/data/reports/">rdropmap reports</a>
</div>
</body></html>"""

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"overview_{today}.html"
    out.write_text(html, encoding="utf-8")
    print(f"Overview saved: {out}")
    if open_browser:
        webbrowser.open(out.as_uri())
    return str(out)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    build_report(open_browser=not args.no_browser)
