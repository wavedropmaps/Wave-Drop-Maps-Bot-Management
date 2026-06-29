// ============================================================================
// wavedropmaps.pages.dev front door — Discord-OAuth GATED  (STAGED, NOT LIVE)
// ============================================================================
// Access rule: "Login with Discord" -> allowed ONLY if the user is a member of
// the Wave Drop Maps Staff Hub guild. Enforced at the Cloudflare edge, so
// unauthenticated requests never reach the PC/tunnel.
//
// GO-LIVE (when you're back at the PC, after pasting me Client ID + Secret):
//   1. Set these on the Pages project (Settings > Variables, or wrangler):
//        DISCORD_CLIENT_ID       (plain var)
//        DISCORD_CLIENT_SECRET   (SECRET / encrypted)
//        SESSION_SECRET          (SECRET — long random string; I'll generate one)
//   2. In the Discord Developer Portal > your app > OAuth2 > Redirects, add:
//        https://wavedropmaps.pages.dev/__auth/callback
//   3. Replace _worker.js with this file and deploy.
//
// SAFE ROLLOUT: until the three env vars are set, this behaves exactly like the
// current open proxy — so deploying it early can't lock anyone out.
// ============================================================================

// Supervisor-managed line — keep this exact format (staff_hub_serve.py rewrites it).
const TUNNEL_URL = 'https://joshua-appreciated-send-apt.trycloudflare.com';

// Fixed, must equal the redirect registered in Discord (prevents Host-header
// spoofing / OAuth-hijack via a forged origin).
const SITE_ORIGIN = 'https://wavedropmaps.pages.dev';
const REDIRECT_URI = SITE_ORIGIN + '/__auth/callback';

const STAFF_GUILD_ID = '1041450125391835186';
const TRAINEE_GUILD_ID = '1405570493691596820';
const SESSION_COOKIE = 'wsh_session';
const STATE_COOKIE = 'wsh_oauth_state';
const SESSION_TTL = 60 * 60 * 24 * 30; // 30 days (seconds)

// Flip to true at GO-LIVE: a missing/weak secret then FAILS CLOSED (503) instead
// of silently serving the private site unauthenticated. Keep false while staging.
const GATE_ENFORCED = true;
const MIN_SECRET_LEN = 32;

// Paths reachable WITHOUT a session (the login dance + a health check).
const OPEN_PATHS = new Set(['/__auth/login', '/__auth/callback', '/__auth/logout', '/__auth/password', '/ping', '/preview.png', '/api/db/query']);

const MAINTENANCE_HTML = `<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wave Staff Hub — temporarily offline</title>
<style>body{font-family:system-ui,-apple-system,sans-serif;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}.card{max-width:420px;padding:2rem}h1{font-size:1.6rem;margin:0 0 .5rem}p{color:#8b949e;line-height:1.5}.wave{font-size:3rem}</style></head>
<body><div class="card"><div class="wave">🌊</div><h1>Wave Staff Hub is offline</h1>
<p>The hub is temporarily unavailable. It runs from the team machine — it'll be back once that's online again.</p></div></body></html>`;

export default {
    async fetch(request, env) {
        const url = new URL(request.url);

        const secretOk = env.SESSION_SECRET && env.SESSION_SECRET.length >= MIN_SECRET_LEN;
        const configured = env.DISCORD_CLIENT_ID && env.DISCORD_CLIENT_SECRET && secretOk;

        let userId = null, userRoles = [], userName = '', userAv = '', userType = '';

        // Fail CLOSED in production: refuse to serve the private site if the gate
        // isn't fully configured, rather than silently proxying it unauthenticated.
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
                    if (url.pathname.startsWith('/api/')) return json({ error: 'unauthorized' }, 401);
                    return loginPage();
                }
                userId    = sess.uid;
                userRoles = sess.roles || [];
                userName  = sess.uname || '';
                userAv    = sess.uav   || '';
                userType  = sess.type  || 'staff';
            }
        }

        return proxy(request, url, configured, env.STAFF_HUB_SECRET, userId, userRoles, userName, userAv, userType);
    }
};

async function proxy(request, url, gated, secret, userId, userRoles, userName, userAv, userType) {
    const target = TUNNEL_URL + url.pathname + url.search;
    try {
        const upstream = await fetch(buildUpstreamRequest(request, target, gated, secret, userId, userRoles, userName, userAv, userType));
        const resp = new Response(upstream.body, upstream);
        if (url.pathname === '/preview.png') {
            // Short TTL so Discord/scrapers re-fetch within a day — no version bumps needed.
            resp.headers.set('Cache-Control', 'public, max-age=86400, must-revalidate');
        } else if (gated) {
            // Private, authed content — never let a shared cache (Cloudflare's edge)
            // store it and serve it to another / an unauthenticated visitor.
            resp.headers.set('Cache-Control', 'private, no-store');
        }
        return resp;
    } catch (err) {
        return new Response(MAINTENANCE_HTML, {
            status: 503,
            headers: { 'content-type': 'text/html; charset=utf-8', 'retry-after': '120', 'cache-control': 'no-store' },
        });
    }
}

// Build the upstream request. When gated, strip the session/state cookies so the
// edge-only session token is never forwarded to the tunnel / Flask. ALWAYS attach
// the shared secret (X-API-Key) so Flask can prove the request came from this
// worker, not from someone who found the raw tunnel URL. Strip any client-supplied
// X-API-Key first so a caller can never smuggle their own.
function buildUpstreamRequest(request, target, gated, secret, userId, userRoles, userName, userAv, userType) {
    const headers = new Headers(request.headers);
    if (gated) {
        const stripped = stripWshCookies(headers.get('Cookie'));
        if (stripped) headers.set('Cookie', stripped); else headers.delete('Cookie');
    }
    headers.delete('X-API-Key');
    if (secret) headers.set('X-API-Key', secret);
    // Strip any client-supplied identity headers then inject worker-verified ones.
    headers.delete('X-Wave-User-Id');
    headers.delete('X-Wave-User-Name');
    headers.delete('X-Wave-User-Avatar');
    headers.delete('X-Wave-User-Roles');
    headers.delete('X-Wave-User-Type');
    if (userId)   headers.set('X-Wave-User-Id',     String(userId));
    if (userName) headers.set('X-Wave-User-Name',   String(userName));
    if (userAv)   headers.set('X-Wave-User-Avatar', String(userAv));
    if (userRoles && userRoles.length) headers.set('X-Wave-User-Roles', userRoles.join(','));
    if (userType) headers.set('X-Wave-User-Type',   String(userType));
    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD') init.body = request.body;
    return new Request(target, init);
}

function stripWshCookies(cookieHeader) {
    if (!cookieHeader) return '';
    return cookieHeader.split(';')
        .map(s => s.trim())
        .filter(c => {
            const n = c.split('=')[0].trim();
            return n !== SESSION_COOKIE && n !== STATE_COOKIE;
        })
        .join('; ');
}

function startLogin(env) {
    const state = randB64(16);
    const auth = 'https://discord.com/oauth2/authorize'
        + `?client_id=${encodeURIComponent(env.DISCORD_CLIENT_ID)}`
        + `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}`
        + '&response_type=code'
        + `&scope=${encodeURIComponent('identify guilds guilds.members.read')}`
        + `&state=${state}`;
    return redirect(auth, [`${STATE_COOKIE}=${state}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600`]);
}

async function handleCallback(request, env, url) {
    const code = url.searchParams.get('code');
    const state = url.searchParams.get('state');
    const cookieState = getCookie(request, STATE_COOKIE);
    // CSRF: the state in the URL must match the one we set in the (HttpOnly) cookie.
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

    const gRes = await fetch('https://discord.com/api/users/@me/guilds', {
        headers: { Authorization: `Bearer ${tok.access_token}` },
    });
    if (!gRes.ok) return deny('Could not verify your Discord servers. Please try again.', 502, true);
    const guilds = await gRes.json();
    let primaryGuildId = STAFF_GUILD_ID;
    const isStaff = Array.isArray(guilds) && guilds.some(g => g && g.id === STAFF_GUILD_ID);
    const isTrainee = Array.isArray(guilds) && guilds.some(g => g && g.id === TRAINEE_GUILD_ID);
    
    if (!isStaff && !isTrainee) {
        return deny('Access denied — the Wave Staff Hub is for staff and trainees only.', 403, false);
    }
    
    if (!isStaff && isTrainee) {
        primaryGuildId = TRAINEE_GUILD_ID;
    }

    const uRes = await fetch('https://discord.com/api/users/@me', {
        headers: { Authorization: `Bearer ${tok.access_token}` },
    });
    const user = uRes.ok ? await uRes.json() : {};

    let memberRoles = [];
    try {
        const mRes = await fetch(`https://discord.com/api/users/@me/guilds/${primaryGuildId}/member`, {
            headers: { Authorization: `Bearer ${tok.access_token}` },
        });
        if (mRes.ok) { const m = await mRes.json(); memberRoles = Array.isArray(m.roles) ? m.roles : []; }
    } catch (_) {}

    const token = await signSession(
        {
            uid:   String(user.id || 'unknown'),
            uname: String(user.global_name || user.username || ''),
            uav:   String(user.avatar || ''),
            roles: memberRoles,
            type:  isStaff ? 'staff' : 'trainee',
            exp:   Math.floor(Date.now() / 1000) + SESSION_TTL,
        },
        env.SESSION_SECRET,
    );
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

// ---- helpers ---------------------------------------------------------------

function redirect(location, cookies) {
    const h = new Headers({ 'Location': location });
    for (const c of (cookies || [])) h.append('Set-Cookie', c);
    return new Response(null, { status: 302, headers: h });
}

function json(obj, status = 200) {
    return new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json' } });
}

// Public, branded "Login with Discord" landing page shown to unauthenticated
// visitors. Carries OpenGraph/Twitter preview tags so Discord/social unfurls show
// the Wave Staff Hub card (the gate would otherwise block the preview crawler).
// No sensitive data — safe to serve pre-auth.
function loginPage() {
    const html = `<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wave Staff Hub</title>
<meta property="og:type" content="website">
<meta property="og:site_name" content="Wave Staff Hub">
<meta property="og:title" content="Wave Staff Hub">
<meta property="og:description" content="Unified Wave staff hub. Staff Sheet archive, Lifetime Activity, Weekly Activity leaderboard, and Wave Economy 2.0 — all in one place.">
<meta property="og:image" content="${SITE_ORIGIN}/preview.png?v=4">
<meta property="og:url" content="${SITE_ORIGIN}/">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Wave Staff Hub">
<meta name="twitter:description" content="Staff access only — log in with Discord.">
<meta name="twitter:image" content="${SITE_ORIGIN}/preview.png?v=4">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:#0d1117;color:#e6edf3;min-height:100vh;display:flex;align-items:center;justify-content:center;text-align:center;padding:1.5rem}
.card{max-width:430px}
.logo-wrap{position:relative;display:inline-block;margin-bottom:.4rem}
.logo{font-size:3.5rem;cursor:pointer;user-select:none;display:inline-block;transition:transform .1s;-webkit-tap-highlight-color:transparent}
.logo.holding{transform:scale(.9)}
#pw-ring{width:5rem;height:5rem;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);pointer-events:none}
#pw-ring circle{fill:none;stroke:#58a6ff;stroke-width:2.5;stroke-dasharray:100;stroke-dashoffset:100;transform:rotate(-90deg);transform-origin:50% 50%}
h1{font-size:2rem;font-weight:800;letter-spacing:.04em;background:linear-gradient(90deg,#58a6ff,#bc8cff);-webkit-background-clip:text;background-clip:text;color:transparent;margin-bottom:.7rem}
p{color:#8b949e;line-height:1.55;margin-bottom:1.7rem}
.btn{display:inline-flex;align-items:center;gap:.6rem;background:#5865F2;color:#fff;text-decoration:none;font-weight:600;padding:.9rem 1.7rem;border-radius:11px;font-size:1.05rem;transition:background .15s}
.btn:hover{background:#4752c4}
.divider{display:flex;align-items:center;gap:.8rem;margin:1.4rem 0;color:#484f58;font-size:.85rem}.divider::before,.divider::after{content:'';flex:1;height:1px;background:#21262d}
form{display:flex;gap:.5rem;margin-top:0}
input[type=password]{flex:1;background:#161b22;border:1px solid #30363d;border-radius:8px;color:#e6edf3;padding:.7rem 1rem;font-size:.95rem;outline:none;transition:border-color .15s}
input[type=password]:focus{border-color:#58a6ff}
input[type=password]::placeholder{color:#484f58}
button[type=submit]{background:#21262d;border:1px solid #30363d;border-radius:8px;color:#e6edf3;font-weight:600;padding:.7rem 1.1rem;font-size:.95rem;cursor:pointer;transition:background .15s}
button[type=submit]:hover{background:#30363d}
.note{margin-top:1.2rem;font-size:.8rem;color:#6e7681}
#pw-section{display:none;animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}
</style></head>
<body><div class="card">
<div class="logo-wrap">
  <div class="logo" id="logo">🌊</div>
  <svg id="pw-ring" viewBox="0 0 36 36"><circle cx="18" cy="18" r="15.9"/></svg>
</div>
<h1>WAVE STAFF HUB</h1>
<p>This hub is for Wave Drop Maps staff. Log in with Discord to continue.</p>
<a class="btn" href="/__auth/login">
<svg width="22" height="22" viewBox="0 0 24 24" fill="#fff"><path d="M20.3 4.4A19.8 19.8 0 0 0 15.4 3l-.2.5c2.1.5 3.1 1.3 4.2 2.1A13 13 0 0 0 12 4.4c-2.6 0-5 .6-7.4 1.2 1.1-.8 2.1-1.6 4.2-2.1L8.6 3a19.8 19.8 0 0 0-4.9 1.4C1 8.3.3 12.1.6 15.9a19.9 19.9 0 0 0 6 3l.8-1.3c-.7-.3-1.3-.6-2-1l.5-.4a14.2 14.2 0 0 0 12.2 0l.5.4c-.6.4-1.3.7-2 1l.8 1.3a19.9 19.9 0 0 0 6-3c.4-4.5-.7-8.3-3.4-11.5ZM8.5 13.7c-1 0-1.7-.9-1.7-2s.7-2 1.7-2 1.8.9 1.7 2c0 1.1-.8 2-1.7 2Zm7 0c-1 0-1.7-.9-1.7-2s.7-2 1.7-2 1.8.9 1.7 2c0 1.1-.8 2-1.7 2Z"/></svg>
Login with Discord
</a>
<div id="pw-section">
<div class="divider">or</div>
<form method="POST" action="/__auth/password">
  <input type="password" name="password" placeholder="Enter password" autocomplete="current-password" required>
  <button type="submit">Go</button>
</form>
</div>
<div class="note">Not staff? You won't be able to access the hub.</div>
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

function deny(message, status, retry) {
    const link = retry ? '<p><a style="color:#58a6ff" href="/__auth/login">Try again</a></p>' : '';
    const html = `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Wave Staff Hub</title>
<style>body{font-family:system-ui,sans-serif;background:#0d1117;color:#e6edf3;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}.card{max-width:440px;padding:2rem}h1{font-size:1.5rem}p{color:#8b949e;line-height:1.5}.w{font-size:3rem}</style></head>
<body><div class="card"><div class="w">🔒</div><h1>Wave Staff Hub</h1><p>${message}</p>${link}</div></body></html>`;
    return new Response(html, { status, headers: { 'content-type': 'text/html; charset=utf-8' } });
}

function getCookie(request, name) {
    const h = request.headers.get('Cookie') || '';
    for (const part of h.split(';')) {
        const idx = part.indexOf('=');
        if (idx === -1) continue;
        if (part.slice(0, idx).trim() === name) {
            // Tolerate a malformed cookie value rather than throwing a 500 (self-DoS).
            try { return decodeURIComponent(part.slice(idx + 1).trim()); }
            catch (e) { return null; }
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
    return crypto.subtle.importKey(
        'raw', new TextEncoder().encode(secret),
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

// Constant-time string compare (avoids leaking the state via timing).
function timingSafeEqual(a, b) {
    if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
    let diff = 0;
    for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return diff === 0;
}
