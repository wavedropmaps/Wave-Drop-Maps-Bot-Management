import os
import hmac
import json
import uuid
import sqlite3
import gzip
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
import requests as _requests
from flask import Flask, jsonify, send_from_directory, request, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv

load_dotenv(override=True)  # .env is source of truth; don't keep a stale inherited STAFF_HUB_SECRET

BASE_DIR = Path(__file__).resolve().parent

app = Flask(__name__, static_folder=str(BASE_DIR / 'website'), static_url_path='')

# Security: limit request size to 1MB (prevents memory exhaustion)
app.config['MAX_CONTENT_LENGTH'] = 1 * 1024 * 1024

# Rate limiting: use user ID if available, fall back to IP
def _rate_limit_key():
    uid = request.headers.get('X-Wave-User-Id', '').strip()
    return uid if uid else get_remote_address()

limiter = Limiter(
    app=app,
    key_func=_rate_limit_key,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

API_SECRET = os.getenv('STAFF_HUB_SECRET', '')

# Allowlist of data endpoints — only these are served from website/data/.
# An explicit allowlist beats sanitising input: zero path-traversal surface.
_API_PAGES = {
    'loot', 'surge', 'tips', 'duties', 'vbucks',
    'economy', 'daily_summary', 'session_history', 'events', 'team_hierarchy',
    'lifetime',
}

# Wave-Logging dashboard — static site + the bot's local data mirror.
# Served under /logging; fronted by wave-logging.pages.dev (role-gated worker).
_LOGGING_SITE = BASE_DIR / 'wave_logging_site'
_LOGGING_DATA = BASE_DIR / 'wave_logging_local' / 'data'


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')

    # Gzip compress HTML/CSS/JS if client supports it (most do)
    if 'gzip' in request.headers.get('Accept-Encoding', ''):
        if resp.content_type and any(t in resp.content_type for t in ['text/html', 'text/css', 'application/json', 'application/javascript', 'text/javascript']):
            try:
                buf = BytesIO()
                with gzip.GzipFile(fileobj=buf, mode='wb') as f:
                    f.write(resp.get_data())
                resp.set_data(buf.getvalue())
                resp.headers['Content-Encoding'] = 'gzip'
            except Exception:
                pass  # If compression fails, just serve uncompressed

    # Cache static assets (CSS, JS, images) for 24 hours; HTML only 1 hour for updates
    if resp.content_type:
        if any(t in resp.content_type for t in ['image/', 'application/javascript', 'text/css', 'font/']):
            resp.headers['Cache-Control'] = 'public, max-age=86400'
        elif 'text/html' in resp.content_type:
            resp.headers['Cache-Control'] = 'public, max-age=3600'

    return resp


# Edge gate -> origin trust. Only the Cloudflare worker knows STAFF_HUB_SECRET and
# attaches it as X-API-Key on every request it proxies. A request hitting the raw
# tunnel URL directly won't have it -> rejected here. /ping stays open for local
# health checks (no sensitive data). If the secret is unset we FAIL CLOSED (503)
# rather than silently serve the origin unauthenticated.
_PUBLIC_PATHS = {'/ping'}


@app.before_request
def _require_worker_secret():
    if request.path in _PUBLIC_PATHS:
        return None
    # Allow localhost access for local development
    if request.host.startswith('127.0.0.1') or request.host.startswith('localhost'):
        return None
    if not API_SECRET:
        return jsonify({'error': 'server not configured'}), 503
    if not hmac.compare_digest(request.headers.get('X-API-Key', ''), API_SECRET):
        return jsonify({'error': 'forbidden'}), 403
    return None


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/tips')
def api_tips():
    """Serve T&T data with tasks read LIVE from the DB (so inserts are instant)
    and leaderboard/duties from the bot-written static file."""
    data_dir = BASE_DIR / 'website' / 'data'
    static_path = data_dir / 'tips.json'

    # Start from the bot-written file if it exists (has leaderboard, duties, meta).
    base: dict = {}
    if static_path.exists():
        try:
            base = json.loads(static_path.read_text(encoding='utf-8'))
        except Exception:
            base = {}

    # Always override tasks with a live DB read.
    tasks = []
    try:
        with _tt_db() as conn:
            rows = conn.execute(
                "SELECT * FROM tt_tasks WHERE status != 'completed' ORDER BY created_at ASC"
            ).fetchall()
        for r in rows:
            t = dict(r)
            t['claimed_by_name'] = t.get('claimed_by_name') or (
                f"User {t['claimed_by']}" if t.get('claimed_by') else None)
            t['point_value'] = t.get('point_value') or t.get('base_points') or 1
            tasks.append(t)
    except Exception:
        pass

    base['tasks'] = tasks
    if '_meta' not in base:
        base['_meta'] = {}
    base['_meta']['last_updated'] = datetime.now(timezone.utc).isoformat()

    resp = jsonify(base)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/api/duty_needs')
def api_duty_needs():
    """Serve the latest duty config from the bot."""
    static_path = BASE_DIR / 'website' / 'data' / 'duty_needs.json'
    if static_path.exists():
        try:
            resp = Response(static_path.read_text(encoding='utf-8'), mimetype='application/json')
            resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            return resp
        except Exception:
            pass
    return jsonify({"error": "No duty config available yet"})


@app.route('/api/<page>')
def api_data(page):
    """Serve the live payload the bot writes to website/data/<page>.json.

    Generic on purpose: every leaderboard page fetches /api/<its-key> and we
    just drop a data/<key>.json file. No GitHub, no per-request DB load.
    """
    if page not in _API_PAGES:
        return jsonify({'error': 'not found'}), 404
    data_dir = BASE_DIR / 'website' / 'data'
    if not (data_dir / f'{page}.json').exists():
        return jsonify({'error': 'not found'}), 404
    resp = send_from_directory(str(data_dir), f'{page}.json', mimetype='application/json')
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/logging')
@app.route('/logging/')
def logging_index():
    return send_from_directory(str(_LOGGING_SITE), 'index.html')


@app.route('/logging/data/<path:p>')
def logging_data(p):
    # The dashboard's relative data/... fetches land here. send_from_directory is
    # traversal-safe; serve the bot's local mirror, never cached.
    resp = send_from_directory(str(_LOGGING_DATA), p)
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@app.route('/logging/<path:p>')
def logging_asset(p):
    return send_from_directory(str(_LOGGING_SITE), p)


@app.route('/ping')
def ping():
    return jsonify({'status': 'ok'})


# ── Remote DB query (used by Mac Claude via wave-db MCP) ───────────────────

_DB_QUERY_TOKEN = os.getenv('DB_QUERY_TOKEN', '')
_DB_PATHS = {
    'management':   BASE_DIR / 'bot_database.db',
    'logistics':    Path(r'C:\Users\kiere\Desktop\Wave Logistics Bot\bot.db'),
    'logistics-maps': Path(r'C:\Users\kiere\Desktop\Wave Logistics Bot\map_requests.db'),
}
_DB_QUERY_ALLOWLIST = {'SELECT', 'WITH', 'PRAGMA'}

@app.route('/api/db/query', methods=['POST'])
def db_query():
    if not _DB_QUERY_TOKEN:
        return jsonify({'error': 'not configured'}), 503
    auth = request.headers.get('Authorization', '')
    if not hmac.compare_digest(auth, f'Bearer {_DB_QUERY_TOKEN}'):
        return jsonify({'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    db   = body.get('db', 'management')
    sql  = (body.get('sql') or '').strip()
    if db not in _DB_PATHS:
        return jsonify({'error': f'unknown db, pick one of: {list(_DB_PATHS)}'}), 400
    if not sql:
        return jsonify({'error': 'sql required'}), 400
    first_word = sql.split()[0].upper()
    if first_word not in _DB_QUERY_ALLOWLIST:
        return jsonify({'error': 'only SELECT/WITH/PRAGMA allowed'}), 400
    db_path = _DB_PATHS[db]
    if not db_path.exists():
        return jsonify({'error': f'{db} db file not found'}), 404
    try:
        conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql).fetchall()
        conn.close()
        return jsonify({'db': db, 'rows': [dict(r) for r in rows], 'count': len(rows)})
    except sqlite3.OperationalError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        return jsonify({'error': 'db_error'}), 500


# ── T&T web-action helpers ─────────────────────────────────────────────────

def _tt_db():
    """Open a sync sqlite3 connection to the shared bot DB (WAL-safe concurrent writes)."""
    conn = sqlite3.connect(str(BASE_DIR / 'bot_database.db'), timeout=5)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.row_factory = sqlite3.Row
    return conn


def _wave_user_id():
    """Return the verified Discord user ID injected by the Cloudflare worker, or None."""
    uid = request.headers.get('X-Wave-User-Id', '').strip()
    try:
        return int(uid) if uid else None
    except (ValueError, TypeError):
        return None


@app.route('/api/tt/tasks')
def tt_tasks_live():
    """Live task list — polled every 10 s by the page so claims appear instantly."""
    tasks = []
    try:
        with _tt_db() as conn:
            rows = conn.execute(
                "SELECT * FROM tt_tasks WHERE status != 'completed' ORDER BY created_at ASC"
            ).fetchall()
        for r in rows:
            t = dict(r)
            if not t.get('claimed_by_name') and t.get('claimed_by'):
                t['claimed_by_name'] = f"User {t['claimed_by']}"
            t['point_value'] = t.get('point_value') or t.get('base_points') or 1
            tasks.append(t)
    except Exception:
        pass
    resp = jsonify({'tasks': tasks, 'ts': datetime.now(timezone.utc).isoformat()})
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@app.route('/api/me')
def api_me():
    uid   = request.headers.get('X-Wave-User-Id', '').strip()
    uname = request.headers.get('X-Wave-User-Name', '').strip()
    uav   = request.headers.get('X-Wave-User-Avatar', '').strip()
    utype = request.headers.get('X-Wave-User-Type', '').strip()
    raw_roles = request.headers.get('X-Wave-User-Roles', '').strip()
    avatar_url = f'https://cdn.discordapp.com/avatars/{uid}/{uav}.webp?animated=true&size=128' if uid and uav and uav.startswith('a_') else (f'https://cdn.discordapp.com/avatars/{uid}/{uav}.png?size=128' if uid and uav else None)
    roles = [r for r in raw_roles.split(',') if r]
    return jsonify({
        'user_id': uid or None,
        'display_name': uname or None,
        'avatar_url': avatar_url,
        'roles': roles,
        'user_type': utype or None
    })


_BOT_ADMIN_BASE = 'http://127.0.0.1:5001'

_HEAD_TT_ROLE_ID = '1286285354462085182'
_MANAGEMENT_ROLE_ID = '1041582103927726170'


def _admin_role_ids():
    """Return role ID strings for the current user.
    Tries live bot lookup first (reflects promotions instantly).
    Falls back to session header if bot is offline or times out."""
    uid = request.headers.get('X-Wave-User-Id', '').strip()
    if uid:
        try:
            resp = _requests.get(
                f'{_BOT_ADMIN_BASE}/admin/user/roles',
                params={'user_id': uid},
                headers={'X-API-Key': API_SECRET},
                timeout=2,
            )
            if resp.status_code == 200:
                return set(resp.json().get('role_ids', []))
        except Exception:
            pass
    # Fallback: session header (may be stale after promotions)
    raw = request.headers.get('X-Wave-User-Roles', '')
    return {r.strip() for r in raw.split(',') if r.strip()}


def _has_tt_admin(roles):
    return _MANAGEMENT_ROLE_ID in roles or _HEAD_TT_ROLE_ID in roles


@app.route('/api/admin/tt/cancel_task', methods=['POST'])
@limiter.limit("60 per minute")
def tt_admin_cancel_task():
    """Delete a T&T task from the admin panel (Flask-native; matches >removetttask)."""
    roles = _admin_role_ids()
    if not _has_tt_admin(roles):
        return jsonify({'error': 'forbidden'}), 403
    body = request.get_json(silent=True) or {}
    task_id = body.get('task_id')
    if task_id is None or str(task_id).strip() == '':
        return jsonify({'error': 'task_id required'}), 400
    try:
        task_id = int(task_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid task_id'}), 400
    try:
        with _tt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cur = conn.execute('DELETE FROM tt_tasks WHERE task_id=?', (task_id,))
            conn.commit()
        if cur.rowcount == 0:
            return jsonify({'error': 'task not found'}), 404
        return jsonify({'ok': True, 'task_id': task_id, 'status': 'deleted'})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/admin/<path:subpath>', methods=['GET', 'POST', 'DELETE'])
def api_admin_proxy(subpath):
    uid   = request.headers.get('X-Wave-User-Id', '')
    roles = ','.join(_admin_role_ids())  # live roles, falls back to session
    qs    = request.query_string.decode()
    try:
        fwd_headers = {'X-API-Key': API_SECRET, 'X-Wave-User-Id': uid,
                       'X-Wave-User-Roles': roles}
        content_type = request.headers.get('Content-Type', '')
        if content_type:
            fwd_headers['Content-Type'] = content_type
        upstream = _requests.request(
            method=request.method,
            url=f'{_BOT_ADMIN_BASE}/admin/{subpath}' + (f'?{qs}' if qs else ''),
            headers=fwd_headers,
            data=request.get_data(),
            timeout=30,
        )
        return Response(upstream.content, status=upstream.status_code,
                        content_type=upstream.headers.get('Content-Type', 'application/json'))
    except _requests.exceptions.ConnectionError:
        return jsonify({'error': 'bot_offline'}), 503
    except Exception:
        return jsonify({'error': 'proxy_error'}), 500


@app.route('/api/tt/tasks/<int:task_id>/claim', methods=['POST'])
@limiter.limit("30 per minute")
def tt_claim(task_id):
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    now = datetime.now(timezone.utc).isoformat()
    try:
        with _tt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cur = conn.execute(
                "UPDATE tt_tasks SET status='claimed', claimed_by=?, claimed_at=? "
                "WHERE task_id=? AND status='available'",
                (uid, now, task_id),
            )
            conn.commit()
        if cur.rowcount == 0:
            return jsonify({'error': 'not_available'}), 409
        return jsonify({'ok': True, 'task_id': task_id})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/tt/tasks/<int:task_id>/unclaim', methods=['POST'])
@limiter.limit("30 per minute")
def tt_unclaim(task_id):
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cur = conn.execute(
                "UPDATE tt_tasks SET status='available', claimed_by=NULL, claimed_at=NULL "
                "WHERE task_id=? AND claimed_by=? AND status='claimed'",
                (task_id, uid),
            )
            conn.commit()
        if cur.rowcount == 0:
            return jsonify({'error': 'not_found'}), 409
        return jsonify({'ok': True, 'task_id': task_id})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


# ── Wave Points shop endpoints ────────────────────────────────────────────────

# Mirror of SHOP_PRIZES in commands/wave_points_commands.py — kept in sync manually
_SHOP_PRIZES = {
    "Staff Promotions": [
        ("Trial Staff → Staff",          30),
        ("Staff → Support",              50),
        ("Support → Senior Support",    200),
        ("Senior Support → Admin",      350),
        ("Admin → Head Admin",          700),
        ("Head Admin → Management",     999),
        ("Instant Management",         5000),
    ],
    "Perks & Roles": [
        ("Wave Contributor",            450),
        ("Paid Priority",               400),
        ("Paid Promotions in Drop Map Announcements", 7500),
        ("Paid Promotions in Improvement Cord Announcements", 3000),
        ("VIP",                        5000),
    ],
    "In-Game Rewards": [
        ("Pro Drop Map",               700),
        ("Pro Loot Route",             400),
        ("Pro Surge Route",            200),
    ],
}
_ALL_PRIZES: dict[str, int] = {n: c for prizes in _SHOP_PRIZES.values() for n, c in prizes}


@app.route('/api/shop/role_names')
def shop_role_names():
    uid  = request.headers.get('X-Wave-User-Id', '').strip()
    roles = request.headers.get('X-Wave-User-Roles', '')
    try:
        r = _requests.get(
            f'{_BOT_ADMIN_BASE}/admin/user/role_names',
            headers={'X-API-Key': API_SECRET, 'X-Wave-User-Id': uid, 'X-Wave-User-Roles': roles},
            timeout=5,
        )
        if r.ok:
            return jsonify(r.json())
    except Exception:
        pass
    return jsonify({'role_names': []})


@app.route('/api/shop/balance')
def shop_balance():
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            row = conn.execute('SELECT points FROM wave_points WHERE user_id=?', (uid,)).fetchone()
        balance = row['points'] if row else 0
        return jsonify({'balance': balance, 'user_id': str(uid)})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/shop/redeem', methods=['POST'])
@limiter.limit("20 per minute")
def shop_redeem():
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    prize = data.get('prize', '').strip()
    if prize not in _ALL_PRIZES:
        return jsonify({'error': 'invalid_prize'}), 400
    cost = _ALL_PRIZES[prize]
    try:
        with _tt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT points FROM wave_points WHERE user_id=?', (uid,)).fetchone()
            balance = row['points'] if row else 0
            if balance < cost:
                conn.rollback()
                return jsonify({'error': 'insufficient_balance', 'balance': balance, 'cost': cost}), 400
            dup = conn.execute(
                "SELECT id FROM web_redemptions WHERE user_id=? AND prize=? AND status IN ('pending','processing')",
                (str(uid), prize),
            ).fetchone()
            if dup:
                conn.rollback()
                return jsonify({'id': dup['id'], 'status': 'pending', 'duplicate': True})
            rid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO web_redemptions(id, user_id, prize, cost, status, created_at) VALUES(?,?,?,?,?,?)",
                (rid, str(uid), prize, cost, 'pending', datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return jsonify({'id': rid, 'status': 'pending'})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/shop/status/<redemption_id>')
def shop_status(redemption_id):
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            row = conn.execute(
                'SELECT status, result_json FROM web_redemptions WHERE id=? AND user_id=?',
                (redemption_id, str(uid)),
            ).fetchone()
        if not row:
            return jsonify({'error': 'not_found'}), 404
        result = json.loads(row['result_json']) if row['result_json'] else None
        return jsonify({'status': row['status'], 'result': result})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


# ── VBucks shop endpoints ────────────────────────────────────────────────────

_VBUCKS_AMOUNTS = [800, 1000, 1500, 2000, 5000, 10000]
_VBUCKS_PRIZE_NAMES = {f"Redeem {n:,} VBucks": n for n in _VBUCKS_AMOUNTS}
WP_PER_100_VBUCKS = 50  # fixed: 50 WP = 100 VBucks
_VBUCKS_WP_COSTS = {n: n * WP_PER_100_VBUCKS // 100 for n in _VBUCKS_AMOUNTS}


def _ensure_vbucks_redemptions_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS web_vbucks_redemptions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            created_at TEXT NOT NULL,
            processed_at TEXT
        )
    """)
    conn.commit()


@app.route('/api/shop/vbucks_balance')
def shop_vbucks_balance():
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            rows = conn.execute(
                "SELECT duty_type, total_vbucks FROM vbucks WHERE user_id=? AND duty_type='main'",
                (str(uid),),
            ).fetchall()
        total = sum(r['total_vbucks'] for r in rows)
        by_wallet = {r['duty_type']: r['total_vbucks'] for r in rows}
        return jsonify({'total': total, 'wallets': by_wallet, 'user_id': str(uid)})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/shop/vbucks_redeem', methods=['POST'])
@limiter.limit("20 per minute")
def shop_vbucks_redeem():
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    prize = data.get('prize', '').strip()
    if prize not in _VBUCKS_PRIZE_NAMES:
        return jsonify({'error': 'invalid_prize'}), 400
    amount = _VBUCKS_PRIZE_NAMES[prize]
    cost_wp = _VBUCKS_WP_COSTS[amount]
    try:
        with _tt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            _ensure_vbucks_redemptions_table(conn)
            wp_row = conn.execute(
                'SELECT points FROM wave_points WHERE user_id=?', (uid,)
            ).fetchone()
            wp_balance = wp_row['points'] if wp_row else 0
            if wp_balance < cost_wp:
                conn.rollback()
                return jsonify({'error': 'insufficient_balance', 'balance': wp_balance, 'cost': cost_wp}), 400
            dup = conn.execute(
                "SELECT id FROM web_vbucks_redemptions WHERE user_id=? AND amount=? AND status IN ('pending','processing')",
                (str(uid), amount),
            ).fetchone()
            if dup:
                conn.rollback()
                return jsonify({'id': dup['id'], 'status': 'pending', 'duplicate': True})
            rid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO web_vbucks_redemptions(id,user_id,amount,status,created_at) VALUES(?,?,?,?,?)",
                (rid, str(uid), amount, 'pending', datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
        return jsonify({'id': rid, 'status': 'pending'})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/shop/vbucks_status/<redemption_id>')
def shop_vbucks_status(redemption_id):
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            _ensure_vbucks_redemptions_table(conn)
            row = conn.execute(
                'SELECT status, result_json FROM web_vbucks_redemptions WHERE id=? AND user_id=?',
                (redemption_id, str(uid)),
            ).fetchone()
        if not row:
            return jsonify({'error': 'not_found'}), 404
        result = json.loads(row['result_json']) if row['result_json'] else None
        return jsonify({'status': row['status'], 'result': result})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


# ── Bank Bonds endpoints ───────────────────────────────────────────────────

_BOND_TIERS = {7: 15.0, 14: 30.0, 30: 60.0, 60: 100.0}

import time as _time


def _ensure_web_bonds_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS web_bonds (
            id          TEXT PRIMARY KEY,
            user_id     TEXT NOT NULL,
            days        INTEGER NOT NULL,
            amount      INTEGER NOT NULL,
            status      TEXT NOT NULL DEFAULT 'pending',
            result_json TEXT,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL
        )
    """)
    conn.commit()


@app.route('/api/bonds/balance')
def bonds_balance():
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            wp_row = conn.execute('SELECT points FROM wave_points WHERE user_id=?', (uid,)).fetchone()
            bond_rows = conn.execute(
                'SELECT id, amount_locked, amount_payout, maturity_date FROM bank_bonds '
                'WHERE user_id=? AND status="ACTIVE" ORDER BY maturity_date ASC',
                (uid,)
            ).fetchall()
        wp = wp_row['points'] if wp_row else 0
        bonds = [{'id': r['id'], 'locked': r['amount_locked'],
                  'payout': r['amount_payout'], 'maturity': r['maturity_date']} for r in bond_rows]
        return jsonify({'wp': wp, 'bonds': bonds})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/bonds/buy', methods=['POST'])
@limiter.limit("20 per minute")
def bonds_buy():
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    body = request.get_json(silent=True) or {}
    days = body.get('days')
    amount = body.get('amount')
    if days not in _BOND_TIERS:
        return jsonify({'error': 'invalid_duration'}), 400
    try:
        amount = int(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({'error': 'invalid_amount'}), 400
    try:
        with _tt_db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            _ensure_web_bonds_table(conn)
            dup = conn.execute(
                "SELECT id FROM web_bonds WHERE user_id=? AND status IN ('pending','processing')",
                (str(uid),)
            ).fetchone()
            if dup:
                conn.rollback()
                return jsonify({'id': dup['id'], 'status': 'pending', 'duplicate': True})
            eid = str(uuid.uuid4())
            now = _time.time()
            conn.execute(
                'INSERT INTO web_bonds (id, user_id, days, amount, status, created_at, updated_at) '
                'VALUES (?, ?, ?, ?, ?, ?, ?)',
                (eid, str(uid), days, amount, 'pending', now, now)
            )
            conn.commit()
        return jsonify({'id': eid, 'status': 'pending'})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/bonds/status/<bond_id>')
def bonds_status(bond_id):
    uid = _wave_user_id()
    if not uid:
        return jsonify({'error': 'unauthorized'}), 401
    try:
        with _tt_db() as conn:
            _ensure_web_bonds_table(conn)
            row = conn.execute(
                'SELECT status, result_json FROM web_bonds WHERE id=? AND user_id=?',
                (bond_id, str(uid))
            ).fetchone()
        if not row:
            return jsonify({'error': 'not_found'}), 404
        result = None
        if row['result_json']:
            try:
                result = json.loads(row['result_json'])
            except Exception:
                pass
        return jsonify({'id': bond_id, 'status': row['status'], 'result': result})
    except Exception:
        return jsonify({'error': 'db_error'}), 500


# ─── WP Profile History Endpoints ───────────────────────────────────────────

def _wp_activity_rows(conn, user_id: str, limit: int = 100) -> list:
    """All logged WP balance changes for a user from bot_logs."""
    rows = conn.execute(
        """SELECT timestamp, details_json FROM bot_logs
           WHERE category='wave_points' AND action='points_changed'
           AND json_extract(target_json, '$.id') = ?
           ORDER BY timestamp DESC LIMIT ?""",
        (user_id, limit),
    ).fetchall()
    events = []
    for r in rows:
        try:
            details = json.loads(r['details_json'] or '{}')
        except json.JSONDecodeError:
            details = {}
        change = int(details.get('change', 0))
        reason = (details.get('reason') or '').strip()
        if not reason:
            reason = 'Wave Points spent' if change < 0 else 'Wave Points earned'
        events.append({
            'timestamp': r['timestamp'],
            'description': reason,
            'amount': change,
            'running_balance': int(details.get('balance_after', 0)),
        })
    return events


@app.route('/api/profile/wp_history')
def profile_wp_history():
    """Balance over time from bot_logs activity, with redemption fallback."""
    user_id = request.args.get('user_id', '').strip()
    if not user_id:
        return jsonify({'error': 'missing user_id'}), 400
    try:
        with _tt_db() as conn:
            row = conn.execute('SELECT points FROM wave_points WHERE user_id=?', (user_id,)).fetchone()
            balance = row['points'] if row else 0
            log_rows = conn.execute(
                """SELECT timestamp, details_json FROM bot_logs
                   WHERE category='wave_points' AND action='points_changed'
                   AND json_extract(target_json, '$.id') = ?
                   ORDER BY timestamp ASC""",
                (user_id,),
            ).fetchall()
        now = datetime.now(timezone.utc).isoformat()
        if log_rows:
            points = []
            for r in log_rows:
                try:
                    details = json.loads(r['details_json'] or '{}')
                except json.JSONDecodeError:
                    details = {}
                points.append({
                    'timestamp': r['timestamp'],
                    'balance': int(details.get('balance_after', 0)),
                })
            if not points or points[-1]['balance'] != balance:
                points.append({'timestamp': now, 'balance': balance})
            return jsonify(points)
        with _tt_db() as conn:
            redemptions = conn.execute(
                'SELECT cost, created_at FROM web_redemptions WHERE user_id=? AND status IN (\'completed\', \'success\') ORDER BY created_at ASC',
                (user_id,),
            ).fetchall()
        if not redemptions:
            return jsonify([{'timestamp': now, 'balance': balance}])
        total_spent = sum(r['cost'] for r in redemptions)
        points = []
        running = balance + total_spent
        for r in redemptions:
            points.append({'timestamp': r['created_at'], 'balance': running})
            running -= r['cost']
        points.append({'timestamp': now, 'balance': balance})
        return jsonify(points)
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/profile/wp_transactions')
def profile_wp_transactions():
    """Individual WP spend events from redemptions.
    Returns [{timestamp, description, amount, running_balance}] sorted descending.
    Falls back to a synthetic row if no transactions exist."""
    user_id = request.args.get('user_id', '').strip()
    if not user_id:
        return jsonify({'error': 'missing user_id'}), 400
    try:
        with _tt_db() as conn:
            row = conn.execute('SELECT points FROM wave_points WHERE user_id=?', (user_id,)).fetchone()
            balance = row['points'] if row else 0
            redemptions = conn.execute(
                'SELECT prize, cost, created_at FROM web_redemptions WHERE user_id=? AND status IN (\'completed\', \'success\') ORDER BY created_at DESC',
                (user_id,)
            ).fetchall()
        if not redemptions:
            now = datetime.now(timezone.utc).isoformat()
            return jsonify([{'timestamp': now, 'description': 'Current Balance', 'amount': 0, 'running_balance': balance}])
        # Build transaction list with running_balance working backward from current
        transactions = []
        running = balance
        for r in redemptions:
            transactions.append({
                'timestamp': r['created_at'],
                'description': f"Redeemed: {r['prize']}",
                'amount': -r['cost'],
                'running_balance': running
            })
            running += r['cost']
        return jsonify(transactions)
    except Exception:
        return jsonify({'error': 'db_error'}), 500


@app.route('/api/profile/wp_activity')
def profile_wp_activity():
    """Full WP activity ledger from bot_logs (earnings, penalties, shop, transfers).
    Returns [{timestamp, description, amount, running_balance}] sorted descending."""
    user_id = request.args.get('user_id', '').strip()
    if not user_id:
        return jsonify({'error': 'missing user_id'}), 400
    try:
        with _tt_db() as conn:
            events = _wp_activity_rows(conn, user_id)
        return jsonify(events)
    except Exception:
        return jsonify({'error': 'db_error'}), 500


if __name__ == '__main__':
    _port = int(os.getenv('STAFF_HUB_PORT', '5000'))
    app.run(host='127.0.0.1', port=_port, debug=False)
