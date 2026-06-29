"""
staff_hub_serve.py - Wave Staff Hub supervisor.

Keeps the public site (https://wavedropmaps.pages.dev) alive on this PC with a
FREE quick tunnel, whose URL rotates on restart. This supervisor makes that
rotation invisible:

  1. Starts Flask (web_api.py) on :5000.
  2. Starts a Cloudflare quick tunnel to :5000 and reads the random
     https://<words>.trycloudflare.com URL it prints.
  3. If that URL differs from what's baked into cloudflare_pages/_worker.js,
     rewrites the worker and `wrangler pages deploy`s it.
  4. Keeps reading the tunnel's stdout in a background thread. If cloudflared
     reconnects and prints a new URL, it is deployed immediately.
  5. Every 2 minutes, DNS-checks the deployed URL. If it's dead (tunnel rotated
     without the process dying), force-restarts cloudflared and redeployes.

Run it directly (python staff_hub_serve.py) or via restart_staff_hub.ps1.
Ctrl+C to stop.

NOTE: logs are intentionally ASCII-only - the Windows console is cp1252 and
crashes on emoji/box-drawing chars.
"""

import os
import re
import sys
import time
import signal
import shutil
import socket
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / '.env')

PORT_FILE = BASE_DIR / 'staff_hub_port.txt'
CANDIDATE_PORTS = (5000, 5002, 5003)


def _port_listening(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def _lifetime_ok(port, secret):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/api/lifetime')
    if secret:
        req.add_header('X-API-Key', secret)
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        return e.code == 200
    except Exception:
        return False


def resolve_port():
    """Pick Flask port. If :5000 is held by a stale Session-0 process (lifetime 404), use :5002."""
    secret = os.getenv('STAFF_HUB_SECRET', '')
    if not _port_listening(5000):
        return 5000
    if _lifetime_ok(5000, secret):
        log(':5000 already serves /api/lifetime — reusing')
        return 5000
    for port in CANDIDATE_PORTS[1:]:
        if not _port_listening(port):
            log(f'stale Flask on :5000 (lifetime missing) — using :{port}')
            return port
    log('WARNING: candidate ports busy — forcing :5002')
    return 5002


SITES = [
    {'project': 'wavedropmaps', 'dir': BASE_DIR / 'cloudflare_pages',
     'worker': BASE_DIR / 'cloudflare_pages' / '_worker.js'},
    {'project': 'wave-logging', 'dir': BASE_DIR / 'cloudflare_pages_logging',
     'worker': BASE_DIR / 'cloudflare_pages_logging' / '_worker.js'},
]

CF_TOKEN   = os.getenv('CLOUDFLARE_API_TOKEN', '')
CF_ACCOUNT = os.getenv('CLOUDFLARE_ACCOUNT_ID', '')

CLOUDFLARED = r'C:\Program Files (x86)\cloudflared\cloudflared.exe'
if not Path(CLOUDFLARED).exists():
    CLOUDFLARED = shutil.which('cloudflared') or CLOUDFLARED

URL_RE         = re.compile(r'https://[a-z0-9-]+\.trycloudflare\.com')
TUNNEL_LINE_RE = re.compile(r"const TUNNEL_URL = '([^']*)';")


def log(msg):
    line = f"[staff-hub] {time.strftime('%H:%M:%S')}  {msg}"
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode('ascii', 'replace').decode('ascii'), flush=True)


PORT = resolve_port()


def _worker_url(site):
    try:
        m = TUNNEL_LINE_RE.search(site['worker'].read_text(encoding='utf-8'))
        return m.group(1) if m else None
    except Exception:
        return None


def _set_worker_url(site, url):
    text = site['worker'].read_text(encoding='utf-8')
    new  = TUNNEL_LINE_RE.sub(f"const TUNNEL_URL = '{url}';", text, count=1)
    site['worker'].write_text(new, encoding='utf-8', newline='\n')


def _deploy(site):
    env = dict(os.environ, CLOUDFLARE_API_TOKEN=CF_TOKEN, CLOUDFLARE_ACCOUNT_ID=CF_ACCOUNT)
    cmd = ['npx', '--yes', 'wrangler@latest', 'pages', 'deploy', str(site['dir']),
           '--project-name', site['project'], '--branch', 'main', '--commit-dirty=true']
    log(f"deploying {site['project']} ...")
    r = subprocess.run(' '.join(f'"{c}"' if ' ' in c else c for c in cmd),
                       env=env, shell=True, cwd=str(BASE_DIR),
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode == 0:
        log(f"{site['project']} deployed OK")
    else:
        log(f"{site['project']} deploy FAILED (rc={r.returncode}): {(r.stderr or '').strip()[-300:]}")
    return r.returncode == 0


def sync_worker(url):
    for site in SITES:
        if not site['worker'].exists():
            continue
        if url == _worker_url(site):
            log(f"{site['project']}: tunnel URL unchanged - no redeploy")
            continue
        log(f"{site['project']}: new tunnel URL {url} - updating + deploying")
        _set_worker_url(site, url)
        _deploy(site)


def _tunnel_alive(url):
    if not url:
        return False
    try:
        host = url.replace('https://', '').split('/')[0]
        socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
        return True
    except OSError:
        return False


# Shared: latest URL seen in cloudflared stdout.
_current_url = [None]
_url_lock    = threading.Lock()


def _read_tunnel_stdout(proc):
    for line in proc.stdout:
        m = URL_RE.search(line)
        if m:
            with _url_lock:
                _current_url[0] = m.group(0)
        if proc.poll() is not None:
            break


def start_flask():
    log('starting Flask (web_api.py) on :%d' % PORT)
    env = dict(os.environ, STAFF_HUB_PORT=str(PORT))
    return subprocess.Popen([sys.executable, str(BASE_DIR / 'web_api.py')],
                            cwd=str(BASE_DIR), env=env)


def start_tunnel():
    log('starting Cloudflare quick tunnel ...')
    proc = subprocess.Popen(
        [CLOUDFLARED, 'tunnel', '--url', f'http://localhost:{PORT}'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1)

    with _url_lock:
        _current_url[0] = None

    # Block until URL appears (up to 40s).
    url      = None
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        m = URL_RE.search(line)
        if m:
            url = m.group(0)
            with _url_lock:
                _current_url[0] = url
            break

    # Keep reading stdout so URL rotations are detected.
    threading.Thread(target=_read_tunnel_stdout, args=(proc,), daemon=True).start()
    return proc, url


def main():
    if not CF_TOKEN or not CF_ACCOUNT:
        log('ERROR: CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID missing from .env')
        sys.exit(1)

    PORT_FILE.write_text(str(PORT), encoding='utf-8')
    log('wrote active port %d -> %s' % (PORT, PORT_FILE.name))

    flask_proc  = start_flask()
    time.sleep(2)
    tunnel_proc, url = start_tunnel()
    if url:
        try:
            sync_worker(url)
        except Exception as e:
            log(f'sync_worker error (non-fatal): {e}')
    else:
        log('WARNING: tunnel did not report a URL within 40s')

    deployed_url      = url
    last_health_check = time.monotonic()
    HEALTH_INTERVAL   = 120  # DNS check every 2 minutes

    try:
        while True:
            time.sleep(5)

            # Flask watchdog
            if flask_proc.poll() is not None:
                log('Flask exited - restarting')
                flask_proc = start_flask()
                time.sleep(2)

            # Tunnel process watchdog
            if tunnel_proc.poll() is not None:
                log('tunnel exited - restarting (URL will rotate)')
                tunnel_proc, url = start_tunnel()
                if url:
                    try:
                        sync_worker(url)
                        deployed_url = url
                    except Exception as e:
                        log(f'sync_worker error (non-fatal): {e}')
                continue

            # Detect URL rotation (cloudflared reconnected with new URL mid-process)
            with _url_lock:
                latest = _current_url[0]
            if latest and latest != deployed_url:
                log(f'tunnel URL rotated to {latest} - redeploying')
                try:
                    sync_worker(latest)
                    deployed_url = latest
                except Exception as e:
                    log(f'sync_worker error (non-fatal): {e}')

            # DNS health check — catches dead URLs the process-poll misses
            now = time.monotonic()
            if now - last_health_check >= HEALTH_INTERVAL:
                last_health_check = now
                if deployed_url and not _tunnel_alive(deployed_url):
                    log(f'tunnel DNS dead for {deployed_url} - force-restarting')
                    try:
                        tunnel_proc.terminate()
                    except Exception:
                        pass
                    time.sleep(2)
                    tunnel_proc, url = start_tunnel()
                    if url:
                        try:
                            sync_worker(url)
                            deployed_url = url
                        except Exception as e:
                            log(f'sync_worker error after health-restart (non-fatal): {e}')

    except KeyboardInterrupt:
        log('shutting down (Ctrl+C)')
        for p in (tunnel_proc, flask_proc):
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                pass


if __name__ == '__main__':
    main()
