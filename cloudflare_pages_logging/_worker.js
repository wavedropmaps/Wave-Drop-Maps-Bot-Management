// ============================================================================
// wave-logging.pages.dev front door — Discord-OAuth gated, MANAGEMENT-ROLE only.
// ============================================================================
// "Login with Discord" -> allowed ONLY if the user holds the Management role in
// the Staff Hub guild. Enforced at the Cloudflare edge. Proxies to the PC's
// Flask under /logging (the Wave-Logging dashboard + its local data mirror).
//
// GO-LIVE secrets on THIS Pages project: DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET
// (same bot app as the hub), SESSION_SECRET (its own random value).
// Discord OAuth2 redirect to register: https://wave-logging.pages.dev/__auth/callback
// ============================================================================

// Supervisor-managed line — keep this exact format (staff_hub_serve.py rewrites it).
const TUNNEL_URL = 'https://joshua-appreciated-send-apt.trycloudflare.com';

const SITE_ORIGIN = 'https://wave-logging.pages.dev';
const REDIRECT_URI = SITE_ORIGIN + '/__auth/callback';
const UPSTREAM_PREFIX = '/logging';                 // Flask namespace for the dashboard

const STAFF_GUILD_ID = '1041450125391835186';
const REQUIRED_ROLE_ID = '1041582103927726170';     // "Management" in the Staff Hub guild

const SESSION_COOKIE = 'wlog_session';
const STATE_COOKIE = 'wlog_oauth_state';
const SESSION_TTL = 60 * 60 * 24 * 30;              // 30 days
const GATE_ENFORCED = true;                          // fail closed if secrets missing
const MIN_SECRET_LEN = 32;

const OPEN_PATHS = new Set(['/__auth/login', '/__auth/callback', '/__auth/logout', '/__auth/password']);

const MAINTENANCE_HTML = `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wave Logging — offline</title>
<style>body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}.card{max-width:420px;padding:2rem}h1{font-size:1.5rem}p{color:#8b949e;line-height:1.5}.w{font-size:3rem}</style></head>
<body><div class="card"><div class="w">📊</div><h1>Wave Logging is offline</h1>
<p>The dashboard runs from the team machine — it'll be back once that's online again.</p></div></body></html>`;

export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        if (url.pathname === '/ping') return json({ status: 'ok' });

        const secretOk = env.SESSION_SECRET && env.SESSION_SECRET.length >= MIN_SECRET_LEN;
        const configured = env.DISCORD_CLIENT_ID && env.DISCORD_CLIENT_SECRET && secretOk;

        if (GATE_ENFORCED && !configured) {
            return new Response(MAINTENANCE_HTML, {
                status: 503,
                headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' },
            });
        }

        if (configured) {
            if (url.pathname === '/__auth/login') return startLogin(env);
            if (url.pathname === '/__auth/callback') return handleCallback(request, env, url);
            if (url.pathname === '/__auth/password') return handlePassword(request, env);
            if (url.pathname === '/__auth/logout') {
                return redirect('/__auth/login', [`${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`]);
            }
            if (!OPEN_PATHS.has(url.pathname)) {
                const sess = await verifySession(getCookie(request, SESSION_COOKIE), env.SESSION_SECRET);
                if (!sess) {
                    if (url.pathname.startsWith('/data/') || url.pathname.startsWith('/api/')) {
                        return json({ error: 'unauthorized' }, 401);
                    }
                    return loginPage();
                }
            }
        }

        return proxy(request, url, configured, env.STAFF_HUB_SECRET);
    }
};

async function proxy(request, url, gated, secret) {
    const target = TUNNEL_URL + UPSTREAM_PREFIX + url.pathname + url.search;
    try {
        const upstream = await fetch(buildUpstreamRequest(request, target, gated, secret));
        const resp = new Response(upstream.body, upstream);
        if (gated) resp.headers.set('Cache-Control', 'private, no-store');
        return resp;
    } catch (err) {
        return new Response(MAINTENANCE_HTML, {
            status: 503,
            headers: { 'content-type': 'text/html; charset=utf-8', 'retry-after': '120', 'cache-control': 'no-store' },
        });
    }
}

function buildUpstreamRequest(request, target, gated, secret) {
    const headers = new Headers(request.headers);
    if (gated) {
        const stripped = stripWlogCookies(headers.get('Cookie'));
        if (stripped) headers.set('Cookie', stripped); else headers.delete('Cookie');
    }
    headers.delete('X-API-Key');                 // never let a client smuggle their own
    if (secret) headers.set('X-API-Key', secret);
    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD') init.body = request.body;
    return new Request(target, init);
}

function stripWlogCookies(cookieHeader) {
    if (!cookieHeader) return '';
    return cookieHeader.split(';').map(s => s.trim())
        .filter(c => { const n = c.split('=')[0].trim(); return n !== SESSION_COOKIE && n !== STATE_COOKIE; })
        .join('; ');
}

function startLogin(env) {
    const state = randB64(16);
    const auth = 'https://discord.com/oauth2/authorize'
        + `?client_id=${encodeURIComponent(env.DISCORD_CLIENT_ID)}`
        + `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}`
        + '&response_type=code'
        + `&scope=${encodeURIComponent('identify guilds.members.read')}`
        + `&state=${state}`;
    return redirect(auth, [`${STATE_COOKIE}=${state}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600`]);
}

async function handleCallback(request, env, url) {
    const code = url.searchParams.get('code');
    const state = url.searchParams.get('state');
    const cookieState = getCookie(request, STATE_COOKIE);
    if (!code || !state || !cookieState || !timingSafeEqual(state, cookieState)) {
        return deny('Login failed (state mismatch). Please try again.', 400, true);
    }

    const tokRes = await fetch('https://discord.com/api/oauth2/token', {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
            client_id: env.DISCORD_CLIENT_ID,
            client_secret: env.DISCORD_CLIENT_SECRET,
            grant_type: 'authorization_code',
            code,
            redirect_uri: REDIRECT_URI,
        }),
    });
    if (!tokRes.ok) return deny('Discord login failed. Please try again.', 502, true);
    const tok = await tokRes.json();
    if (!tok.access_token) return deny('Discord login failed. Please try again.', 502, true);

    // Read the user's member object (incl. roles) in the staff guild.
    const mRes = await fetch(`https://discord.com/api/users/@me/guilds/${STAFF_GUILD_ID}/member`, {
        headers: { Authorization: `Bearer ${tok.access_token}` },
    });
    if (mRes.status === 404) return deny('Access denied — you are not in the staff server.', 403, false);
    if (!mRes.ok) return deny('Could not verify your roles. Please try again.', 502, true);
    const member = await mRes.json();
    const hasRole = Array.isArray(member.roles) && member.roles.includes(REQUIRED_ROLE_ID);
    if (!hasRole) return deny('Access denied — the logging dashboard is for Management only.', 403, false);

    const uid = (member.user && member.user.id) || 'unknown';
    const token = await signSession({ uid: String(uid), exp: Math.floor(Date.now() / 1000) + SESSION_TTL }, env.SESSION_SECRET);
    return redirect('/', [
        `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_TTL}`,
        `${STATE_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`,
    ]);
}

// In-memory brute-force guard: 5 attempts per IP per 5 minutes.
const _pwAttempts = new Map();
const PW_MAX = 5;
const PW_WINDOW = 5 * 60 * 1000;

function checkRateLimit(ip) {
    const now = Date.now();
    let entry = _pwAttempts.get(ip);
    if (!entry || now - entry.start > PW_WINDOW) {
        entry = { count: 0, start: now };
        _pwAttempts.set(ip, entry);
    }
    entry.count++;
    return entry.count > PW_MAX;
}

async function handlePassword(request, env) {
    if (request.method !== 'POST') return deny('Method not allowed.', 405, false);
    if (!env.SITE_PASSWORD || env.SITE_PASSWORD.length < 1) return deny('Password login is not configured.', 503, false);

    const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
    if (checkRateLimit(ip)) {
        return deny('Too many attempts. Please wait 5 minutes and try again.', 429, false);
    }

    let body;
    try { body = await request.formData(); } catch (e) { return deny('Bad request.', 400, true); }
    const submitted = body.get('password') || '';

    if (!timingSafeEqual(submitted, env.SITE_PASSWORD)) {
        return deny('Wrong password. <a style="color:#58a6ff" href="/">Try again</a>.', 403, false);
    }

    const token = await signSession(
        { uid: 'password_user', exp: Math.floor(Date.now() / 1000) + SESSION_TTL },
        env.SESSION_SECRET,
    );
    return redirect('/', [
        `${SESSION_COOKIE}=${token}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_TTL}`,
    ]);
}

// ---- helpers ----------------------------------------------------------------

function redirect(location, cookies) {
    const h = new Headers({ 'Location': location });
    for (const c of (cookies || [])) h.append('Set-Cookie', c);
    return new Response(null, { status: 302, headers: h });
}

function json(obj, status = 200) {
    return new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json' } });
}

function deny(message, status, retry) {
    const link = retry ? '<p><a style="color:#58a6ff" href="/__auth/login">Try again</a></p>' : '';
    const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Wave Logging</title>
<style>body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}.card{max-width:440px;padding:2rem}h1{font-size:1.5rem}p{color:#8b949e;line-height:1.5}.w{font-size:3rem}</style></head>
<body><div class="card"><div class="w">🔒</div><h1>Wave Logging</h1><p>${message}</p>${link}</div></body></html>`;
    return new Response(html, { status, headers: { 'content-type': 'text/html; charset=utf-8' } });
}

function loginPage() {
    const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Wave Logging</title>
<style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:1.5rem}.card{max-width:430px}.logo{font-size:3.2rem;margin-bottom:.4rem}h1{font-size:1.8rem;font-weight:800;letter-spacing:.03em;color:#58a6ff;margin-bottom:.6rem}p{color:#8b949e;line-height:1.55;margin-bottom:1.6rem}.btn{display:inline-flex;align-items:center;gap:.6rem;background:#5865F2;color:#fff;text-decoration:none;font-weight:600;padding:.9rem 1.7rem;border-radius:11px;font-size:1.05rem}.btn:hover{background:#4752c4}.divider{display:flex;align-items:center;gap:.8rem;margin:1.4rem 0;color:#484f58;font-size:.85rem}.divider::before,.divider::after{content:'';flex:1;height:1px;background:#21262d}form{display:flex;gap:.5rem}input[type=password]{flex:1;background:#161b22;border:1px solid #30363d;border-radius:8px;color:#e6edf3;padding:.7rem 1rem;font-size:.95rem;outline:none;transition:border-color .15s}input[type=password]:focus{border-color:#58a6ff}input[type=password]::placeholder{color:#484f58}button[type=submit]{background:#21262d;border:1px solid #30363d;border-radius:8px;color:#e6edf3;font-weight:600;padding:.7rem 1.1rem;font-size:.95rem;cursor:pointer;transition:background .15s}button[type=submit]:hover{background:#30363d}.note{margin-top:1.2rem;font-size:.8rem;color:#6e7681}</style></head>
<style>.logo-wrap{position:relative;display:inline-block;margin-bottom:.4rem}.logo{cursor:pointer;user-select:none;display:inline-block;transition:transform .1s;-webkit-tap-highlight-color:transparent}.logo.holding{transform:scale(.9)}#pw-ring{width:5rem;height:5rem;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none}#pw-ring circle{fill:none;stroke:#58a6ff;stroke-width:2.5;stroke-dasharray:100;stroke-dashoffset:100;transform:rotate(-90deg);transform-origin:50% 50%}#pw-section{display:none;animation:fadeIn .3s ease}@keyframes fadeIn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}</style>
<body><div class="card">
<div class="logo-wrap">
  <div class="logo" id="logo">📊</div>
  <svg id="pw-ring" viewBox="0 0 36 36"><circle cx="18" cy="18" r="15.9"/></svg>
</div>
<h1>WAVE LOGGING</h1>
<p>Internal logging dashboard — <b>Management only</b>. Log in with Discord to continue.</p>
<a class="btn" href="/__auth/login">Login with Discord</a>
<div id="pw-section">
<div class="divider">or</div>
<form method="POST" action="/__auth/password">
  <input type="password" name="password" placeholder="Enter password" autocomplete="current-password" required>
  <button type="submit">Go</button>
</form>
</div>
<div class="note">You'll need the Management role to get in.</div>
</div>
<script>
var logo=document.getElementById('logo'),ring=document.querySelector('#pw-ring circle'),sec=document.getElementById('pw-section'),HOLD=1500,t=null,r=null,s=null;
function go(e){e.preventDefault();if(sec.style.display==='block')return;logo.classList.add('holding');s=performance.now();(function tick(){var p=Math.min((performance.now()-s)/HOLD,1);ring.style.strokeDashoffset=100-p*100;if(p<1)r=requestAnimationFrame(tick);}());t=setTimeout(function(){sec.style.display='block';reset();sec.querySelector('input').focus();},HOLD);}
function reset(){logo.classList.remove('holding');clearTimeout(t);t=null;cancelAnimationFrame(r);r=null;s=null;ring.style.strokeDashoffset=100;}
logo.addEventListener('mousedown',go);logo.addEventListener('touchstart',go,{passive:false});
logo.addEventListener('mouseup',reset);logo.addEventListener('mouseleave',reset);logo.addEventListener('touchend',reset);logo.addEventListener('touchcancel',reset);
</script>
</body></html>`;
    return new Response(html, { status: 200, headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
}

function getCookie(request, name) {
    const h = request.headers.get('Cookie') || '';
    for (const part of h.split(';')) {
        const idx = part.indexOf('=');
        if (idx === -1) continue;
        if (part.slice(0, idx).trim() === name) {
            try { return decodeURIComponent(part.slice(idx + 1).trim()); } catch (e) { return null; }
        }
    }
    return null;
}

function bytesToB64url(bytes) {
    let s = '';
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function b64urlToBytes(str) {
    str = str.replace(/-/g, '+').replace(/_/g, '/');
    while (str.length % 4) str += '=';
    const bin = atob(str);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
}

function randB64(n) {
    const b = new Uint8Array(n);
    crypto.getRandomValues(b);
    return bytesToB64url(b);
}

async function hmacKey(secret) {
    return crypto.subtle.importKey('raw', new TextEncoder().encode(secret),
        { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']);
}

async function signSession(payloadObj, secret) {
    const payload = bytesToB64url(new TextEncoder().encode(JSON.stringify(payloadObj)));
    const key = await hmacKey(secret);
    const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload)));
    return payload + '.' + bytesToB64url(sig);
}

async function verifySession(token, secret) {
    if (!token || token.indexOf('.') === -1) return null;
    const dot = token.lastIndexOf('.');
    const payload = token.slice(0, dot);
    const sig = token.slice(dot + 1);
    try {
        const key = await hmacKey(secret);
        const ok = await crypto.subtle.verify('HMAC', key, b64urlToBytes(sig), new TextEncoder().encode(payload));
        if (!ok) return null;
        const data = JSON.parse(new TextDecoder().decode(b64urlToBytes(payload)));
        if (!data || typeof data.exp !== 'number' || data.exp < Math.floor(Date.now() / 1000)) return null;
        return data;
    } catch (e) {
        return null;
    }
}

function timingSafeEqual(a, b) {
    if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
    let diff = 0;
    for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
}
