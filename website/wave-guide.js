/* ════════════════════════════════════════════════════════════════════════
   Wave Staff Hub — Shared "? GUIDE" widget
   ----------------------------------------------------------------------------
   Drop  <script src="wave-guide.js"></script>  before </body> on any board
   page. The widget auto-detects the page from its filename and renders a
   pinned "? GUIDE" button (top-right) that opens a slide-in explainer panel.

   To add / edit a board's guide, edit the BOARDS object below. One file =
   every board's help content. Nothing here touches the bot or its JSON data.
   ════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  /* ── SPA hash → filename map (index.html uses hash routing) ────────────── */
  const HASH_MAP = {
    economy:  "economy.html",
    activity: "activity_leaderboard.html",
    loot:     "loot_routes_leaderboard.html",
    surge:    "surge_routes_leaderboard.html",
    tips:     "tips_tricks_leaderboard.html",
    events:   "events.html",
    sheet:    "staff_sheet.html",
    hub:      "index.html",
    team:     "team.html",
    "duty-needs": "duty_needs.html"
  };

  /* ── Per-board content registry (keyed by page filename) ───────────────── */
  const BOARDS = {

    /* ───────────────────  STAFF HUB (home / index)  ────────────────────── */
    "index.html": {
      title: "The Wave Staff Hub",
      sub: "What everything is",
      accent: "#00d4ff",
      rgb: "0,212,255",
      html: `
        <div class="wg-hub">
        <p class="wg-intro">Welcome to the <b>Wave Staff Hub</b> — one link for everything Wave. Use the top nav to move between sections; here's what each one is and how it all ties together. Tap any heading to jump straight there. 👇</p>

        <h2 class="wg-h2">🧭 The Sections</h2>

        <div class="wg-map" style="border-color:#00ff88">
          <div class="wg-map-head" style="color:#00ff88"><a href="#economy" style="color:inherit;text-decoration:none">💰 Wave Shop →</a></div>
          <div class="wg-map-desc">The full <b>economy</b> — earn Wave Points, grow them in the <b>Central Bank</b> (bonds, weekly lottery), send P2P, and spend in the <b>shop</b> on promotions, perks &amp; in-game rewards including VBucks prizes.</div>
        </div>
        <div class="wg-map" style="border-color:#ff4d4d">
          <div class="wg-map-head" style="color:#ff4d4d"><a href="#activity" style="color:inherit;text-decoration:none">⚔️ Activity →</a></div>
          <div class="wg-map-desc">Your <b>weekly activity report</b>, three tabs: <b>General Staff</b> (messages, days active, mod commands &amp; a 0–100 Rank Total), <b>Map Request</b> (requests handled, performance rank &amp; Wave Points awards), and <b>Lifetime</b> (all-time totals for Messages, Mod Commands, Reviews &amp; Map Requests). Weekly resets every Sunday — consistency is everything.</div>
        </div>
        <div class="wg-map" style="border-color:#00d4ff">
          <div class="wg-map-head" style="color:#00d4ff"><a href="#events" style="color:inherit;text-decoration:none">🎉 Events →</a></div>
          <div class="wg-map-desc"><b>Weekly Challenges</b> (5 at week start + 2 mid-week Difficulty-10 Mayhem, up to 100 WP each — first to finish wins), surprise <b>Power Hours</b> (activity earns bonus WP, 50% chance of 2× Double), and the all-time winners leaderboard.</div>
        </div>
        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080"><a href="#loot" style="color:inherit;text-decoration:none">🗺️ Loot Routes →</a></div>
          <div class="wg-map-desc">The <b>route rotation</b> board — earn <b>Wave Points</b> for finishing routes fast, stack role multipliers, and chase the <b>33% Lucky Map</b> 2× bonus.</div>
        </div>
        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF"><a href="#surge" style="color:inherit;text-decoration:none">⚡ Surge Routes →</a></div>
          <div class="wg-map-desc">The surge-route equivalent of Loot Routes — its own rotation, <b>Wave Points</b>, shop and <b>6% Lucky Map</b> bonus. Separate from Loot but works the same way.</div>
        </div>
        <div class="wg-map" style="border-color:#a855f7">
          <div class="wg-map-head" style="color:#a855f7"><a href="#tips" style="color:inherit;text-decoration:none">🎯 Tips &amp; Tricks →</a></div>
          <div class="wg-map-desc">Claim and complete <b>content tasks</b> across 9 duty types (Spawns, Surge, Creative, Pro Notes &amp; more), climb the leaderboard, and spend what you earn in its shop.</div>
        </div>

        <h2 class="wg-h2">🔗 How It All Connects</h2>
        <p class="wg-p">Show up &amp; do your <b>duties</b> → climb the <b>Weekly</b> board and grow your <b>Lifetime</b> totals → that pays out <b>Wave Points</b> → grow them in the <b>Bank</b> or spend them in the <b>Shop</b> → unlock roles and rewards. <b>Events</b>, <b>Loot</b>, <b>Surge</b> &amp; <b>Tips</b> are extra ways to earn on top. It's all one loop. 🔁</p>

        <div class="wg-note">💡 Every section has its own <b>❓ GUIDE</b> button in the top-right — open it there for the full breakdown: exact points, tiers, rewards &amp; commands.</div>

        <p class="wg-outro">One hub, everything Wave. Bookmark it and check back often. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
        </div>
      `
    },

    /* ───────────────────────  AVAILABLE DUTIES  ────────────────────────── */
    "duty_needs.html": {
      title: "Available Duties",
      sub: "How to Apply",
      accent: "#a855f7",
      rgb: "168,85,247",
      html: `
        <p class="wg-intro">Looking to join the team or pick up a new role? This board shows exactly what positions we're currently hiring for and how urgently we need them.</p>

        <h2 class="wg-h2">📝 How to Apply</h2>
        <p class="wg-p">If you want to apply for an open duty or have any questions about the requirements, <b>please DM Fruss</b> directly.</p>
        
        <h2 class="wg-h2">📖 Role Descriptions</h2>
        <p class="wg-p">Not sure what a specific duty actually involves? Head over to the <code class="wg-cmd">#roles-explained</code> channel in the Discord server. It breaks down the exact responsibilities for every single role.</p>

        <h2 class="wg-h2">🎓 Training</h2>
        <p class="wg-outro"><b>No prior experience is needed for any of these duties.</b> You will be fully trained from scratch. You legitimately need nothing but an internet connection and a willingness to learn.</p>
      `
    },

    /* ─────────────────────────  ECONOMY  ───────────────────────────────── */
    "economy.html": {
      title: "Wave Point Economy",
      sub: "Complete Guide",
      accent: "#00ff88",
      rgb: "0,255,136",
      html: `
        <p class="wg-intro">Welcome to the <b>Wave Point Economy</b> — a full ecosystem built around our drop maps, loot routes, and community contributions. We've got a Central Bank with Bonds and a weekly Lottery, P2P trading, and a full shop.</p>

        <h2 class="wg-h2">💎 1 · Earning Wave Points</h2>

        <h3 class="wg-h3">📊 Weekly Rank 100 Bonus</h3>
        <p class="wg-p">Hit a <b>Perfect 100 Rank Total</b> on the Weekly board → <b>+30 WP</b>. Below 100 = nothing.</p>

        <h3 class="wg-h3">🎯 Weekly Staff Challenges</h3>
        <ul class="wg-ul">
          <li><b>Week Start:</b> 5 challenges drop (messages, requests, modlog, proof reviews + 1 extra)</li>
          <li><b>Mid-Week Mayhem:</b> 2 brutal Difficulty-10 challenges</li>
          <li>First to complete wins <b>difficulty × 10 WP</b> (up to <b>100 WP</b> each)</li>
        </ul>

        <h3 class="wg-h3">🎯 Daily Map Reviewer Challenges</h3>
        <p class="wg-p">One-winner race per day:</p>
        <ul class="wg-ul">
          <li>🟢 <b>Easy</b> ~20–30 WP — Early Bird, High Roller, Cleanup Crew, Variety Hour, Lone Wolf</li>
          <li>🟡 <b>Medium</b> ~40–75 WP — Stack King, Volume Sprint, Mini Marathon, Lucky 7, The Twelve</li>
          <li>🔴 <b>Hard</b> ~100–175 WP — Marathon Leader, Diamond Run, Full Spectrum, Burst Mode</li>
        </ul>

        <h3 class="wg-h3">⏳ Power Hour</h3>
        <p class="wg-p">Rolls every hour — <b>10%</b> chance at peak (13:00–21:00 UTC), <b>5%</b> off-peak. Lasts 1 hour.</p>
        <ul class="wg-ul">
          <li>📨 Every 10 messages → +1 WP <span class="wg-dim">(capped 50/session)</span></li>
          <li>👤 Every 5 role duties → +1 WP</li>
          <li>🗺️ Every 1 map request → +1 WP</li>
          <li>🛡️ Every 2 mod commands → +1 WP</li>
        </ul>
        <div class="wg-note">⚡⚡ <b>50% chance</b> any Power Hour becomes a <b>Double Power Hour</b> — all points 2×!</div>

        <h3 class="wg-h3">🗺️ Loot Routes</h3>
        <p class="wg-p">Complete loot routes to earn <b>Wave Points directly</b> — awarded automatically on completion.</p>

        <h3 class="wg-h3">⚡ Surge Routes</h3>
        <p class="wg-p">Complete surge routes to earn <b>Wave Points directly</b> — awarded automatically on completion.</p>

        <h2 class="wg-h2">🏦 2 · The Central Bank</h2>

        <h3 class="wg-h3">💰 Tiered Daily Interest</h3>
        <p class="wg-p">Every day at midnight UTC your Wave Points earn automatic interest — no command needed.</p>
        <table class="wg-table">
          <tr><th>Balance</th><th>APR</th><th>Daily (example)</th></tr>
          <tr><td>≥ 1 000 WP</td><td class="base">15%</td><td class="wg-dim">1000 WP → +0.41 WP/day</td></tr>
          <tr><td>≥ 500 WP</td><td class="base">10%</td><td class="wg-dim">500 WP → +0.14 WP/day</td></tr>
          <tr><td>≥ 250 WP</td><td class="base">7%</td><td class="wg-dim">250 WP → +0.05 WP/day</td></tr>
          <tr><td>≥ 50 WP</td><td class="base">5%</td><td class="wg-dim">50 WP → +0.01 WP/day</td></tr>
        </table>
        <p class="wg-p wg-dim">Payout = <code>round(balance × APR / 365)</code>. You'll get a DM each time interest is paid.</p>

        <h3 class="wg-h3">🔒 Bank Bonds — Guaranteed Returns</h3>
        <p class="wg-p"><code class="wg-cmd">&gt;buybond &lt;days&gt; &lt;amount&gt;</code> locks WP for a fixed term at a guaranteed return. <code class="wg-cmd">&gt;mybonds</code> checks your active bonds.</p>
        <table class="wg-table">
          <tr><th>Duration</th><th>Return</th></tr>
          <tr><td>7 days</td><td class="base">+15%</td></tr>
          <tr><td>14 days</td><td class="base">+30%</td></tr>
          <tr><td>30 days</td><td class="base">+60%</td></tr>
          <tr><td>60 days</td><td class="base">+100%</td></tr>
        </table>

        <h3 class="wg-h3">🎰 Wave Lottery</h3>
        <p class="wg-p"><code class="wg-cmd">&gt;buylottery</code> — 5 WP per ticket. Every ticket adds 5 WP to the pot (+50 WP Bank subsidy). Winner takes the <b>entire pot</b>. Draw: <b>Sunday midnight UTC</b>.</p>

        <h3 class="wg-h3">🤝 P2P Trading</h3>
        <p class="wg-p"><code class="wg-cmd">&gt;pay @User &lt;amount&gt; wp</code> — send Wave Points to another user. <b>10% tax</b> to the Bank.</p>

        <h2 class="wg-h2">🎁 3 · Spending Wave Points</h2>
        <p class="wg-p"><code class="wg-cmd">&gt;wavepointshop</code> to browse • <code class="wg-cmd">&gt;wavepointsredeem</code> to claim.</p>

        <h3 class="wg-h3">📈 Staff Promotions</h3>
        <div class="wg-reward"><span>Trial Staff → Staff</span><span class="cost">30</span></div>
        <div class="wg-reward"><span>Staff → Support</span><span class="cost">50</span></div>
        <div class="wg-reward"><span>Support → Senior Support</span><span class="cost">200</span></div>
        <div class="wg-reward"><span>Senior Support → Admin</span><span class="cost">350</span></div>
        <div class="wg-reward"><span>Admin → Head Admin</span><span class="cost">700</span></div>
        <div class="wg-reward"><span>Head Admin → Management *</span><span class="cost">999</span></div>
        <div class="wg-reward"><span>⚡ Instant Management</span><span class="cost">5,000</span></div>
        <div class="wg-note">* Management requires 4+ weeks as Head Admin.</div>

        <h3 class="wg-h3">🎖️ Perks &amp; Roles</h3>
        <div class="wg-reward"><span>Wave Contributor</span><span class="cost">450</span></div>
        <div class="wg-reward"><span>Paid Priority</span><span class="cost">400</span></div>
        <div class="wg-reward"><span>Paid Promos in Drop Map Announcements</span><span class="cost">7,500</span></div>
        <div class="wg-reward"><span>Paid Promos in Improvement Cord Announcements</span><span class="cost">3,000</span></div>
        <div class="wg-reward"><span>VIP</span><span class="cost">5,000</span></div>

        <h3 class="wg-h3">🗺️ In-Game Rewards</h3>
        <div class="wg-reward"><span>Pro Surge Route</span><span class="cost">200</span></div>
        <div class="wg-reward"><span>Pro Loot Route</span><span class="cost">400</span></div>
        <div class="wg-reward"><span>Pro Drop Map</span><span class="cost">700</span></div>

        <h2 class="wg-h2">📜 Command Cheat Sheet</h2>
        <ul class="wg-ul">
          <li><b>Wave Points:</b> <code class="wg-cmd">&gt;wp</code> <code class="wg-cmd">&gt;wpleaderboard</code> <code class="wg-cmd">&gt;wavepointshop</code> <code class="wg-cmd">&gt;wavepointsredeem</code></li>
          <li><b>VBucks:</b> <code class="wg-cmd">&gt;vbucks</code></li>
          <li><b>Central Bank:</b> <code class="wg-cmd">&gt;buybond &lt;amt&gt;</code> <code class="wg-cmd">&gt;mybonds</code> <code class="wg-cmd">&gt;buylottery</code></li>
          <li><b>P2P:</b> <code class="wg-cmd">&gt;pay @User &lt;amt&gt; wp</code></li>
        </ul>

        <p class="wg-outro">Keep grinding the maps, smashing duties, and invest those points — bonds pay massive, the lottery's only 5 WP a ticket, and the shop is packed with rewards. Let's make some waves. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
      `
    },

    /* ───────────────────────  STAFF SHEET  ─────────────────────────────── */
    "staff_sheet.html": {
      title: "The Staff Sheet",
      sub: "Weekly Activity Report",
      accent: "#00d4ff",
      rgb: "0,212,255",
      html: `
        <p class="wg-intro">The Staff Sheet is a Google document holding the data and statistics on how you performed that week. These sheets are used to make decisions on <b>promotions and demotions</b>.</p>

        <h2 class="wg-h2">📋 Meaning of Each Column</h2>
        <ul class="wg-ul">
          <li><b>Staff</b> — the name of the staff member.</li>
          <li><b>Role</b> — the roles the staff member holds.</li>
          <li><b>Messages sent since (date)</b> — how many messages you've sent since that date in the general chat of the <b>Drop Map server</b>.</li>
          <li><b>Days of the week active</b> — how many days you were active in the week (6/7, 7/7, etc).</li>
          <li><b>Rank — Messages</b> — a percentage score based on how many messages you've sent.</li>
          <li><b>Rank — Days of Week</b> — a percentage score based on how many days you were active.</li>
          <li><b>Rank — Total</b> — your overall percentage score, based on your activity and total points.</li>
          <li><b>Points from Improvement cord</b> — how many messages you've sent since that date in the general chat of the <b>Improvement server</b>.</li>
        </ul>

        <h2 class="wg-h2">📈 How to Improve Your Ranking</h2>

        <h3 class="wg-h3">💬 Send messages &amp; stay active</h3>
        <div class="wg-links">
          <a class="wg-link" target="_blank" rel="noopener" href="https://discord.com/channels/988564962802810961/1301478991097630730"><span class="wg-ico">#</span> General Chat — Server 1</a>
          <a class="wg-link" target="_blank" rel="noopener" href="https://discord.com/channels/971731167621574666/1301482403751133264"><span class="wg-ico">#</span> General Chat — Server 2</a>
        </div>

        <h3 class="wg-h3">👀 Monitor these channels</h3>
        <div class="wg-links">
          <a class="wg-link" target="_blank" rel="noopener" href="https://discord.com/channels/988564962802810961/1210768660101210192"><span class="wg-ico">#</span> Monitor — Server 1</a>
          <a class="wg-link" target="_blank" rel="noopener" href="https://discord.com/channels/971731167621574666/1131536957151924265"><span class="wg-ico">#</span> Monitor — Server 2</a>
        </div>
        <p class="wg-p wg-dim">…and other channels, too!</p>

        <h3 class="wg-h3">🔼 Bump the server</h3>
        <p class="wg-p">Use <code class="wg-cmd">/bump</code> in:</p>
        <div class="wg-links">
          <a class="wg-link" target="_blank" rel="noopener" href="https://discord.com/channels/988564962802810961/1301479034898616340"><span class="wg-ico">#</span> Bump — Server 1</a>
          <a class="wg-link" target="_blank" rel="noopener" href="https://discord.com/channels/971731167621574666/1301482490971815936"><span class="wg-ico">#</span> Bump — Server 2</a>
        </div>

        <h2 class="wg-h2">📌 Notes</h2>
        <ul class="wg-ul">
          <li>Staff sheets come out during <b>Saturday / Sunday</b> (depending on your timezone).</li>
        </ul>

        <div class="wg-note">❓ Still have doubts, enquiries, or don't understand something? <b>DM the Staff Sheet admin</b> on Discord <span class="wg-dim">(user ID 987843990734905414)</span>.</div>
      `
    },

    /* ─────────────  LIFETIME / POWER SCORE  (milestones.html)  ──────────── */
    "milestones.html": {
      title: "Lifetime Activity",
      sub: "Power Score · Badges",
      accent: "#ffd93d",
      rgb: "255,217,61",
      html: `
        <p class="wg-intro">This board ranks every staff member by their <b>Power Score</b> — the total badge points earned across all four tracked duties, for as long as they've been on the team. It's your all-time hall of grind.</p>

        <h2 class="wg-h2">⭐ How Power Score Works</h2>
        <p class="wg-p">Every duty you complete earns <b>badges</b>. Each badge is worth points, and higher tiers are worth far more. Your Power Score is the sum of every badge you hold, across all four duties.</p>
        <table class="wg-table">
          <tr><th>Badge</th><th>Worth</th></tr>
          <tr><td>🥉 Bronze</td><td class="base">1 pt</td></tr>
          <tr><td>🥈 Silver</td><td class="base">2 pts</td></tr>
          <tr><td>🥇 Gold</td><td class="base">4 pts</td></tr>
          <tr><td>⭐ Legend</td><td class="base">8 pts</td></tr>
          <tr><td>👑 God</td><td class="base">16 pts</td></tr>
        </table>

        <h2 class="wg-h2">🎖️ The Four Duties &amp; Badge Thresholds</h2>
        <p class="wg-p">Each duty has its own targets — hit the count, earn the badge:</p>
        <div class="wg-duty">
          <div class="wg-duty-head">⚔️ Messages <span class="wg-dim">— messages sent in the server</span></div>
          <div class="wg-tiers"><span>🥉 1,000</span><span>🥈 3,000</span><span>🥇 8,000</span><span>⭐ 10,000</span><span>👑 50,000</span></div>
        </div>
        <div class="wg-duty">
          <div class="wg-duty-head">🗺️ Map Request Helper <span class="wg-dim">— help process map requests</span></div>
          <div class="wg-tiers"><span>🥉 250</span><span>🥈 750</span><span>🥇 2,000</span><span>⭐ 2,500</span><span>👑 12,500</span></div>
        </div>
        <div class="wg-duty">
          <div class="wg-duty-head">📋 Mod Commands <span class="wg-dim">— commands run to keep the community safe</span></div>
          <div class="wg-tiers"><span>🥉 50</span><span>🥈 200</span><span>🥇 500</span><span>⭐ 1,000</span><span>👑 10,000</span></div>
        </div>

        <h2 class="wg-h2">🏆 Power Tiers &amp; Rewards</h2>
        <p class="wg-p">Your <b>total</b> Power Points unlock an overall rank — the badge shown next to your name — plus Discord roles in the Staff Hub and a one-time Wave Point bonus:</p>
        <table class="wg-table">
          <tr><th>Tier</th><th>Power Pts</th><th>Reward</th></tr>
          <tr><td>🥉 Bronze</td><td>4+</td><td class="base">+20 WP</td></tr>
          <tr><td>🥈 Silver</td><td>8+</td><td class="base">+50 WP</td></tr>
          <tr><td>🥇 Gold</td><td>16+</td><td class="base">+100 WP</td></tr>
          <tr><td>⭐ Legend</td><td>32+</td><td class="base">+300 WP</td></tr>
          <tr><td>👑 God</td><td>64+</td><td class="base">+500 WP</td></tr>
        </table>

        <h2 class="wg-h2">🔎 Tabs &amp; Views</h2>
        <ul class="wg-ul">
          <li><b>All</b> — the overall Power Score ranking.</li>
          <li><b>Messages / Map Request Helper / Mod Commands</b> — zoom into a single duty.</li>
          <li><b>Rising</b> — who's climbing the fastest right now.</li>
          <li><b>Hall of Fame</b> — the legends sitting on God-tier badges.</li>
        </ul>
        <p class="wg-p wg-dim">Tip: press keys <b>1–7</b> to flip between tabs instantly.</p>

        <h2 class="wg-h2">🖱️ Profiles &amp; Compare</h2>
        <ul class="wg-ul">
          <li>Click any row to open that person's full <b>profile</b> — every duty, badge &amp; tier.</li>
          <li>Inside a profile, hit <b>⚔ Compare</b>, then click a second person to put the two side-by-side.</li>
          <li>Use the <b>search bar</b> to find anyone, and the <b>tier filter</b> (Bronze → God) to narrow the board.</li>
        </ul>

        <p class="wg-outro">Every message, every duty, every day adds up. Pick a lane, chase the next badge, and watch your Power Score climb. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
      `
    },

    /* ──────────────  ACTIVITY  (activity_leaderboard.html)  ─────────── */
    "activity_leaderboard.html": {
      title: "Weekly Activity",
      sub: "How the Weekly Board Works",
      accent: "#ff4d4d",
      rgb: "255,77,77",
      pages: [
        /* ── GENERAL STAFF tab ── */
        {
          id: "general", label: "💬 General Staff",
          html: `
            <p class="wg-intro">Your live weekly scoreboard. The <b>General Staff</b> tab ranks everyone by their overall <b>Rank Total</b> for the week. It all resets every Sunday (UTC) — the countdown at the top shows exactly when. A slow week never haunts you; a big week puts you on top.</p>

            <h2 class="wg-h2">📊 The Columns</h2>
            <table class="wg-table">
              <tr><th>Column</th><th>What It Means</th></tr>
              <tr><td>💬 Messages</td><td>Messages sent across the community servers this week</td></tr>
              <tr><td>📅 Days Active</td><td>How many days (out of 7) you showed up</td></tr>
              <tr><td>⚙️ Mod Cmds</td><td>Moderation commands you ran this week</td></tr>
              <tr><td class="base">🏆 Rank Total</td><td class="base">Your overall weekly score, 0–100</td></tr>
            </table>

            <h2 class="wg-h2">🎨 Rank Total Colours</h2>
            <div class="wg-tiers">
              <span>🥇 100 = perfect</span><span>🔵 80+</span><span>🟢 60+</span><span>🟡 40+</span><span>🔴 under 40</span>
            </div>
            <div class="wg-note">💡 Hit a perfect <b>100 Rank Total</b> and you earn <b>+30 Wave Points</b> for the week.</div>

            <h2 class="wg-h2">🌴 Away</h2>
            <p class="wg-p">Members on <b>Away</b> / <b>Strike Immunity Away</b> show a coloured dot and are exempt from weekly penalties.</p>

            <p class="wg-p wg-dim">Click any row to open that member's full profile.</p>
            <p class="wg-outro">Fresh slate every week. Show up, stay consistent, and own the top of the board. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
          `
        },

        /* ── MAP REQUEST tab ── */
        {
          id: "req", label: "🗺️ Map Request",
          html: `
            <p class="wg-intro">The <b>Map Request</b> tab ranks the map-request duty team by how many requests they handled this week — and pays out <b>Wave Points</b> to the top performers.</p>

            <h2 class="wg-h2">📊 The Columns</h2>
            <table class="wg-table">
              <tr><th>Column</th><th>What It Means</th></tr>
              <tr><td>🗺️ Requests</td><td>Map requests you handled this week</td></tr>
              <tr><td>⭐ Performance</td><td>Your rank band (see below)</td></tr>
              <tr><td class="base">💰 Wave Points</td><td class="base">What you earned (or lost) this week</td></tr>
            </table>

            <h2 class="wg-h2">⭐ Performance Ranks (Full Week)</h2>
            <table class="wg-table">
              <tr><th>Rank</th><th>Requests</th></tr>
              <tr><td>🌟 Great</td><td class="base">41+</td></tr>
              <tr><td>⭐ Very Good</td><td>21 – 40</td></tr>
              <tr><td>✅ Good</td><td>10 – 20</td></tr>
              <tr><td>❌ Bad</td><td>9 or below</td></tr>
            </table>

            <h2 class="wg-h2">💰 Weekly Wave Points Awards</h2>
            <div class="wg-reward"><span>🥇 1st place</span><span class="cost">150 WP</span></div>
            <div class="wg-reward"><span>🥈 2nd place</span><span class="cost">100 WP</span></div>
            <div class="wg-note">You must reach at least <b>Good (10+)</b> to be eligible for an award.</div>



            <h2 class="wg-h2">⚠️ Bad Penalty</h2>
            <ul class="wg-ul">
              <li>A ❌ <b>Bad</b> week costs you <b>−40 Wave Points</b></li>
              <li>Hit <b>0</b> total and your duty role is <b>auto-removed</b> from all servers</li>
              <li>You'll get a DM explaining what happened</li>
              <li>🌴 <b>Away</b> / <b>Strike Immunity Away</b> = fully exempt</li>
            </ul>

            <div class="wg-note">🗓️ Awards &amp; penalties apply on the <b>Full Week</b> report only — mid-week is a warning, nothing is awarded or deducted.</div>
            <p class="wg-outro">Hit your numbers and cash out. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
          `
        },
      ]
    },

    /* ─────────────────────  LOOT ROUTES  ───────────────────────────────── */
    "loot_routes_leaderboard.html": {
      title: "Loot Routes",
      sub: "Tabs & System Overview",
      accent: "#FF0080",
      rgb: "255,0,128",
      html: `
        <p class="wg-intro">Everything you need to know about the Loot Route system — from earning points to making your route. Click any tab name below to jump straight to it.</p>

        <h2 class="wg-h2">📑 What Each Tab Is</h2>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('leaderboard',null);">📊 Leaderboard →</div>
          <div class="wg-map-desc">Your live rankings by total loot route points. Updates automatically as routes are completed.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('earn',null);">⚡ How to Earn Points →</div>
          <div class="wg-map-desc">Full breakdown of the points tiers — the faster you complete, the more you earn. Also covers role multipliers (Head Loot Routes = 2×, Inspector = 1.5×) and the 33% Lucky Map bonus.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('rotation',null);">🔄 Rotation Queue →</div>
          <div class="wg-map-desc">See where everyone sits in the queue. You are auto-assigned the next available map when it's your turn.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('shop',null);">🛍️ Shop / Prizes →</div>
          <div class="wg-map-desc">Spend your points on rewards — VBucks, roles, paid priority routes, and more.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('lucky',null);">🍀 Lucky Maps →</div>
          <div class="wg-map-desc">A 33% chance your assigned map is a Lucky Map, giving 2× points on completion.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('stats',null);">📈 Stats &amp; Graphs →</div>
          <div class="wg-map-desc">Visual charts showing completion trends, team performance over time, and personal stats.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('colours',null);">🎨 Colour Code →</div>
          <div class="wg-map-desc">The official colour codes you must use when marking your route on fortnite.gg. Using wrong colours = asked to redo.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('checklist',null);">📋 Checklist →</div>
          <div class="wg-map-desc">Step-by-step checklist for creating your route correctly — from marking materials in-game to submitting for review.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('howto',null);">🗺️ How to Make a Loot Route →</div>
          <div class="wg-map-desc">Full written guide covering every step: assignment, building your route on fortnite.gg, colour codes, and submitting.</div>
        </div>

        <div class="wg-map" style="border-color:#FF0080">
          <div class="wg-map-head" style="color:#FF0080;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('team',null);">👥 How the Team Operates →</div>
          <div class="wg-map-desc">The rotation system, team roles, and how maps are assigned and verified.</div>
        </div>

        <div class="wg-note">⏱️ The clock starts the moment you're assigned — complete fast for max points.</div>
      `
    },

    "events.html": {
      title: "Events",
      sub: "Challenges · Power Hour · Leaderboard",
      accent: "#00d4ff",
      rgb: "0,212,255",
      html: `
        <p class="wg-intro">The <b>Events</b> board is your live feed of every active way to earn bonus Wave Points outside your normal duties — timed challenges, surprise Power Hours, and the all-time winners leaderboard. This page updates itself automatically.</p>

        <h2 class="wg-h2">🎯 Weekly Staff Challenges</h2>
        <p class="wg-p">A fresh set of challenges drops each week — first to hit the target wins the Wave Points. No second place.</p>
        <ul class="wg-ul">
          <li><b>Week start:</b> 5 challenges go live (messages, requests, modlog, proof reviews + 1 extra)</li>
          <li><b>Mid-Week Mayhem:</b> 2 brutal Difficulty-10 challenges drop</li>
          <li>Reward = difficulty × 10 — up to <b>100 WP</b> per challenge</li>
        </ul>
        <div class="wg-note">🏁 First to complete claims the reward — keep an eye on the board and move fast.</div>

        <h2 class="wg-h2">⏳ Power Hours</h2>
        <p class="wg-p">A Power Hour can fire <b>every hour</b> — <b>10%</b> chance at peak (13:00–21:00 UTC), <b>5%</b> off-peak. When one's live, your activity earns bonus WP for 60 minutes:</p>
        <ul class="wg-ul">
          <li>📨 Every 10 messages → +1 WP <span class="wg-dim">(capped 50/session)</span></li>
          <li>👤 Every 5 role duties → +1 WP</li>
          <li>🗺️ Every 1 map request → +1 WP</li>
          <li>🛡️ Every 2 mod commands → +1 WP</li>
        </ul>
        <div class="wg-note">⚡⚡ <b>50% chance</b> any Power Hour becomes a <b>Double Power Hour</b> — all points 2×!</div>

        <h2 class="wg-h2">🏆 The Leaderboard</h2>
        <p class="wg-p">The all-time ranking of challenge winners. Every challenge you win adds to your total and climbs you up the board.</p>

        <h2 class="wg-h2">📊 Reading the Board</h2>
        <ul class="wg-ul">
          <li><b>Challenges</b> — what's live now, with status badges (Active / Upcoming / Ended)</li>
          <li><b>Power Hours</b> — current/recent windows and their multiplier</li>
          <li><b>Leaderboard</b> — top challenge winners by points</li>
        </ul>

        <p class="wg-outro">Stay ready — challenges and Power Hours reward whoever shows up first. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
      `
    },

    "surge_routes_leaderboard.html": {
      title: "Surge Routes",
      sub: "Tabs & System Overview",
      accent: "#00C8FF",
      rgb: "0,200,255",
      html: `
        <p class="wg-intro">Everything you need to know about the Surge Route system — from earning points to making your route. Click any tab name below to jump straight to it.</p>

        <h2 class="wg-h2">📑 What Each Tab Is</h2>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('leaderboard',null);">📊 Leaderboard →</div>
          <div class="wg-map-desc">Your live rankings by total surge route points. Updates automatically as routes are completed.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('earn',null);">⚡ How to Earn Points →</div>
          <div class="wg-map-desc">Full breakdown of the points tiers — the faster you complete, the more you earn. Also covers role multipliers and the 6% Lucky Map bonus.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('rotation',null);">🔄 Rotation Queue →</div>
          <div class="wg-map-desc">See where everyone sits in the queue. You are auto-assigned the next available map when it's your turn.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('shop',null);">🛍️ Shop / Prizes →</div>
          <div class="wg-map-desc">Spend your points on rewards — VBucks, roles, paid priority routes, and more.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('lucky',null);">🍀 Lucky Maps →</div>
          <div class="wg-map-desc">A 6% chance your assigned map is a Lucky Map, giving 2× points on completion.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('stats',null);">📈 Stats &amp; Graphs →</div>
          <div class="wg-map-desc">Visual charts showing completion trends, team performance over time, and personal stats.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('colours',null);">🎨 Colour Code →</div>
          <div class="wg-map-desc">The official colour codes you must use when marking your surge route. Using wrong colours = asked to redo.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('checklist',null);">📋 Checklist →</div>
          <div class="wg-map-desc">Step-by-step checklist for creating your surge route correctly — from marking in-game to submitting for review.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('howto',null);">⚡ How to Make a Surge Route →</div>
          <div class="wg-map-desc">Training video, colour code guide, and quiz — complete all three before being added to the rotation.</div>
        </div>

        <div class="wg-map" style="border-color:#00C8FF">
          <div class="wg-map-head" style="color:#00C8FF;cursor:pointer;" onclick="document.querySelector('.wg-panel').classList.remove('open');document.querySelector('.wg-backdrop').classList.remove('open');document.body.style.overflow='';switchTab('team',null);">👥 How the Team Operates →</div>
          <div class="wg-map-desc">The rotation system, team roles, and how maps are assigned and verified.</div>
        </div>

        <div class="wg-note">⏱️ The clock starts the moment you're assigned — complete fast for max points.</div>
      `
    },

    /* ─────────────────────  TEAM HIERARCHY  ────────────────────────────── */
    "team.html": {
      title: "Team Hierarchy",
      sub: "Roles & Structure",
      accent: "#00d4ff",
      rgb: "0,212,255",
      html: `
        <p class="wg-intro">This page shows the <b>Wave leadership structure</b> — who holds each key role across the three branches. Data is pulled live from Discord and refreshes automatically.</p>

        <h2 class="wg-h2">🏛️ The Three Branches</h2>

        <div class="wg-map" style="border-color:#ba55d3">
          <div class="wg-map-head" style="color:#ba55d3">💜 Human Resources (Head Staff)</div>
          <div class="wg-map-desc">Manages the staff team itself — hiring, culture, insights, and development.<br>
            <b>Head Recruiter</b> — leads recruitment and onboarding new staff.<br>
            <b>Head Insights</b> — tracks staff performance and analytics.<br>
            <b>Head L&D</b> — oversees Learning &amp; Development (training, skill-building).
          </div>
        </div>

        <div class="wg-map" style="border-color:#00ff80">
          <div class="wg-map-head" style="color:#00ff80">💚 Operations (Head Operations)</div>
          <div class="wg-map-desc">Runs the core Wave products — routes, maps, logistics, and content.<br>
            <b>Head Logistics</b> — manages map request flow and coordination.<br>
            <b>Head Loot Routes</b> — owns the loot route team and rotation.<br>
            <b>Head Tips &amp; Tricks</b> — leads the tips/tricks content team.<br>
            <b>Head Surge Routes</b> — owns the surge route team and rotation.
          </div>
        </div>

        <div class="wg-map" style="border-color:#ff8c00">
          <div class="wg-map-head" style="color:#ff8c00">🧡 Marketing (Head Marketing)</div>
          <div class="wg-map-desc">Grows the Wave community and handles outreach.<br>
            <b>Head Promotions</b> — runs server promotions and partnerships.
          </div>
        </div>

        <h2 class="wg-h2">👑 Leadership Ladder</h2>
        <table class="wg-table">
          <tr><th>Role</th><th>What they do</th></tr>
          <tr><td>Executive Director</td><td class="base">Overall head of the Wave team</td></tr>
          <tr><td>Management</td><td>Senior leadership — cross-branch oversight</td></tr>
          <tr><td>Head Admin</td><td>Top of the admin ladder, reports to Management</td></tr>
        </table>

        <div class="wg-note">💡 If a role shows <b>N/A</b>, that position is currently vacant — nobody holds that role in the Staff Hub server right now.</div>

        <p class="wg-outro">Click any card to view that person's full profile. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
      `
    },

    /* ─────────────────────  TIPS & TRICKS  ─────────────────────────────── */
    "tips_tricks_leaderboard.html": {
      title: "Tips & Tricks",
      sub: "Tasks · Duties · Shop",
      accent: "#a855f7",
      rgb: "168,85,247",
      html: `
        <p class="wg-intro">The <b>Tips &amp; Tricks</b> board is where you claim and complete content tasks across 9 duty types, climb the leaderboard, and spend what you earn. Everything is driven by commands in Discord — the board is your live view of it all.</p>

        <h2 class="wg-h2">📑 The Tabs</h2>
        <ul class="wg-ul">
          <li><b>Tasks</b> — the live pool of available tasks. Claim one, complete it, get paid.</li>
          <li><b>Leaderboard</b> — rankings by total points earned across all duties.</li>
          <li><b>Duties</b> — the 9 duty types and how each is scored.</li>
          <li><b>Shop</b> — spend your points on rewards.</li>
        </ul>

        <h2 class="wg-h2">🎯 The 9 Duty Types</h2>
        <div class="wg-tiers">
          <span>SPAWNS</span><span>SURGE</span><span>CREATIVE</span>
          <span>PRONOTES</span><span>GAMESTAGES</span><span>LOADOUTS</span>
          <span>MECHANICS</span><span>DROPSPOTS</span><span>LOOTPOOLS</span>
        </div>

        <h2 class="wg-h2">⚡ How to Claim &amp; Complete</h2>
        <ul class="wg-ul">
          <li><code class="wg-cmd">&gt;mytttasks</code> — view your claimed tasks</li>
          <li><code class="wg-cmd">&gt;claimtttask &lt;id&gt;</code> — claim a task from the pool</li>
          <li><code class="wg-cmd">&gt;completetask &lt;id&gt;</code> — submit a finished task for points</li>
          <li><code class="wg-cmd">&gt;unclaim &lt;id&gt;</code> — release a task you can't finish</li>
        </ul>

        <h2 class="wg-h2">✨ Special Tasks</h2>
        <ul class="wg-ul">
          <li>🟧 <b>Lucky tasks</b> (orange glow) — boosted reward.</li>
          <li>🟩 <b>Bonus tasks</b> (green border) — extra points up for grabs.</li>
        </ul>

        <p class="wg-outro">Pick a lane, claim a task, and start stacking points. <img src="/assets/wave-logo.png" class="wave-logo-inline" alt="Wave"></p>
      `
    },

  };

  /* ── Styles (injected once) ────────────────────────────────────────────── */
  const CSS = `
    .wg-btn{position:fixed;top:62px;right:14px;z-index:99999;display:inline-flex;align-items:center;gap:8px;
      background:rgba(5,12,22,0.92);backdrop-filter:blur(10px);border:1px solid rgba(var(--wg-rgb),0.45);
      border-radius:24px;padding:8px 16px;color:var(--wg);font-family:'Orbitron',monospace;font-size:10px;
      font-weight:700;letter-spacing:2.5px;text-transform:uppercase;cursor:pointer;
      box-shadow:0 0 14px rgba(var(--wg-rgb),0.25),0 4px 18px rgba(0,0,0,0.55);transition:all .25s;}
    .wg-btn:hover{background:rgba(var(--wg-rgb),0.15);color:#fff;transform:translateY(-2px);
      box-shadow:0 0 24px rgba(var(--wg-rgb),0.55),0 6px 22px rgba(0,0,0,0.65);}
    .wg-btn .wg-q{display:inline-flex;align-items:center;justify-content:center;width:16px;height:16px;
      border-radius:50%;border:1.5px solid currentColor;font-size:11px;font-weight:900;line-height:1;
      letter-spacing:0;text-indent:0;}

    .wg-backdrop{position:fixed;inset:0;z-index:10000;background:rgba(3,7,14,0.62);backdrop-filter:blur(3px);
      opacity:0;pointer-events:none;transition:opacity .35s;}
    .wg-backdrop.open{opacity:1;pointer-events:auto;}

    .wg-panel{position:fixed;top:0;right:0;z-index:10001;height:100%;width:min(460px,100vw);
      background:linear-gradient(165deg,rgba(10,16,28,0.99),rgba(6,11,20,0.99));
      border-left:1px solid rgba(var(--wg-rgb),0.4);box-shadow:-12px 0 50px rgba(0,0,0,0.6);
      transform:translateX(100%);transition:transform .38s cubic-bezier(.4,0,.2,1);
      display:flex;flex-direction:column;font-family:'Exo 2',sans-serif;}
    .wg-panel.open{transform:translateX(0);}

    .wg-head{position:relative;flex-shrink:0;padding:22px 54px 18px 22px;
      border-bottom:1px solid rgba(var(--wg-rgb),0.22);
      background:linear-gradient(90deg,rgba(var(--wg-rgb),0.10),transparent);}
    .wg-head h2{font-family:'Orbitron',monospace;font-size:17px;font-weight:900;letter-spacing:1.5px;
      color:#fff;text-shadow:0 0 16px rgba(var(--wg-rgb),0.6);margin:0;text-transform:uppercase;}
    .wg-head .wg-sub{font-family:'JetBrains Mono',monospace;font-size:9.5px;letter-spacing:2px;
      color:var(--wg);text-transform:uppercase;margin-top:6px;}
    .wg-close{position:absolute;top:16px;right:16px;width:30px;height:30px;border-radius:8px;
      border:1px solid rgba(var(--wg-rgb),0.3);background:rgba(255,255,255,0.04);color:#cdd9e8;
      font-size:17px;cursor:pointer;line-height:1;display:flex;align-items:center;justify-content:center;transition:all .2s;}
    .wg-close:hover{background:rgba(var(--wg-rgb),0.18);color:#fff;border-color:rgba(var(--wg-rgb),0.6);}

    .wg-body{flex:1;overflow-y:auto;padding:20px 22px 64px;color:#e8eef6;font-size:13.5px;line-height:1.65;}
    .wg-body::-webkit-scrollbar{width:6px;}
    .wg-body::-webkit-scrollbar-thumb{background:rgba(var(--wg-rgb),0.5);border-radius:3px;}

    .wg-intro{color:#cdd9e8;font-size:13px;line-height:1.62;margin:0 0 18px;padding-bottom:16px;
      border-bottom:1px dashed rgba(var(--wg-rgb),0.22);}
    .wg-h2{display:flex;align-items:center;gap:9px;font-family:'Orbitron',monospace;font-size:13px;
      font-weight:800;letter-spacing:0.5px;color:var(--wg);text-transform:uppercase;
      margin:26px 0 12px;padding-left:11px;border-left:3px solid var(--wg);
      text-shadow:0 0 12px rgba(var(--wg-rgb),0.45);}
    .wg-h3{font-weight:800;font-size:13px;color:#fff;margin:16px 0 7px;}
    .wg-p{margin:0 0 10px;color:#dde6f0;}
    .wg-dim{color:#9fb2c6;}
    .wg-ul{list-style:none;margin:0 0 12px;padding:0;}
    .wg-ul li{position:relative;padding:4px 0 4px 17px;color:#dde6f0;}
    .wg-ul li::before{content:'';position:absolute;left:0;top:12px;width:5px;height:5px;border-radius:50%;
      background:var(--wg);box-shadow:0 0 6px rgba(var(--wg-rgb),0.8);}
    .wg-ul li b,.wg-p b,.wg-intro b{color:#fff;}
    .wg-cmd{font-family:'JetBrains Mono',monospace;font-size:11.5px;background:rgba(var(--wg-rgb),0.12);
      border:1px solid rgba(var(--wg-rgb),0.28);border-radius:5px;padding:1px 6px;color:var(--wg);white-space:nowrap;}
    .wg-table{width:100%;border-collapse:collapse;margin:8px 0 14px;font-family:'JetBrains Mono',monospace;font-size:12px;}
    .wg-table th{text-align:left;padding:6px 9px;background:rgba(var(--wg-rgb),0.14);color:var(--wg);
      font-weight:700;letter-spacing:0.5px;border:1px solid rgba(var(--wg-rgb),0.22);}
    .wg-table td{padding:6px 9px;border:1px solid rgba(255,255,255,0.07);color:#dde6f0;}
    .wg-table tr:nth-child(even) td{background:rgba(255,255,255,0.025);}
    .wg-table .base{color:var(--wg);font-weight:700;}
    .wg-note{background:rgba(var(--wg-rgb),0.08);border:1px solid rgba(var(--wg-rgb),0.28);border-radius:9px;
      padding:11px 13px;margin:14px 0;font-size:12.5px;color:#e1eaf4;line-height:1.55;}
    .wg-note b{color:var(--wg);}
    .wg-reward{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:5px 0;
      border-bottom:1px solid rgba(255,255,255,0.06);color:#dde6f0;}
    .wg-reward .cost{font-family:'JetBrains Mono',monospace;color:var(--wg);font-weight:700;white-space:nowrap;}
    .wg-duty{margin:9px 0;padding:10px 12px;border:1px solid rgba(var(--wg-rgb),0.16);border-radius:10px;
      background:rgba(255,255,255,0.02);}
    .wg-duty-head{font-weight:800;color:#fff;font-size:13px;margin-bottom:8px;}
    .wg-duty-head .wg-dim{font-weight:400;}
    .wg-tiers{display:flex;flex-wrap:wrap;gap:6px;}
    .wg-tiers span{font-family:'JetBrains Mono',monospace;font-size:11px;background:rgba(var(--wg-rgb),0.10);
      border:1px solid rgba(var(--wg-rgb),0.22);border-radius:6px;padding:2px 7px;color:#e8eef6;white-space:nowrap;}
    .wg-map{margin:8px 0;padding:11px 14px;border-left:3px solid var(--wg);border-radius:8px;
      background:rgba(255,255,255,0.025);}
    .wg-map-head{font-family:'Orbitron',monospace;font-weight:800;font-size:12.5px;letter-spacing:0.5px;margin-bottom:5px;}
    .wg-map-desc{color:#dde6f0;font-size:12.5px;line-height:1.5;}
    .wg-map-desc b{color:#fff;}
    .wg-hub{text-align:center;}
    .wg-hub .wg-h2{justify-content:center;border-left:none;padding-left:0;}
    .wg-hub .wg-map{border:1px solid;}
    .wg-links{display:flex;flex-direction:column;gap:7px;margin:6px 0 4px;}
    .wg-link{display:flex;align-items:center;gap:9px;padding:9px 12px;border-radius:9px;
      background:rgba(255,255,255,0.03);border:1px solid rgba(var(--wg-rgb),0.18);color:#e8eef6;
      font-size:12.5px;text-decoration:none;transition:all .18s;}
    a.wg-link:hover{background:rgba(var(--wg-rgb),0.12);border-color:rgba(var(--wg-rgb),0.45);transform:translateX(3px);}
    .wg-link .wg-ico{font-size:15px;line-height:1;}
    .wg-link .wg-desc{color:#9fb2c6;font-size:11px;margin-left:auto;text-align:right;}
    .wg-outro{margin-top:22px;padding-top:14px;border-top:1px dashed rgba(var(--wg-rgb),0.22);
      font-style:italic;color:#cdd9e8;font-size:12.5px;line-height:1.6;}

    .wg-ptabs{display:flex;gap:5px;flex-wrap:wrap;padding:12px 22px 0;flex-shrink:0;border-bottom:1px solid rgba(var(--wg-rgb),0.12);}
    .wg-ptab{font-family:'Orbitron',monospace;font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
      padding:6px 11px;border:1px solid rgba(var(--wg-rgb),0.22);border-radius:16px;background:rgba(255,255,255,0.03);
      color:#4a6080;cursor:pointer;transition:all .2s;white-space:nowrap;margin-bottom:10px;}
    .wg-ptab:hover{border-color:rgba(var(--wg-rgb),0.5);color:#cdd9e8;background:rgba(var(--wg-rgb),0.06);}
    .wg-ptab.active{border-color:var(--wg);color:var(--wg);background:rgba(var(--wg-rgb),0.12);
      box-shadow:0 0 14px rgba(var(--wg-rgb),0.25);}

    @media(max-width:520px){
      .wg-btn{padding:6px 12px;font-size:9px;letter-spacing:1.5px;top:58px;right:10px;}
      .wg-panel{width:100vw;}
      .wg-ptab{font-size:8px;padding:5px 9px;}
    }
  `;

  /* ── Resolve which board this page is (hash → filename → override) ──────── */
  function resolveKey() {
    const hash = (window.location.hash || "").replace("#", "").toLowerCase();
    if (hash && HASH_MAP[hash]) return HASH_MAP[hash];
    const file = (location.pathname.split("/").pop() || "index.html").toLowerCase();
    return window.WAVE_GUIDE_BOARD || file;
  }

  /* ── Boot ──────────────────────────────────────────────────────────────── */
  function init() {
    // Remove any previously-rendered widget (SPA re-init on hashchange).
    const oldBtn = document.getElementById("wg-btn");
    if (oldBtn) oldBtn.remove();
    const oldBackdrop = document.querySelector(".wg-backdrop");
    if (oldBackdrop) oldBackdrop.remove();
    const oldPanel = document.querySelector(".wg-panel");
    if (oldPanel) oldPanel.remove();
    document.body.style.overflow = "";

    const key = resolveKey();
    const board = BOARDS[key];
    if (!board) return; // no guide configured for this page

    // Load the panel's fonts (no-op on pages that already import them — the
    // browser dedupes identical hrefs). Keeps the guide looking identical on
    // every board, even pages that don't load the cyber-theme fonts.
    if (!document.getElementById("wg-fonts")) {
      const l = document.createElement("link");
      l.id = "wg-fonts";
      l.rel = "stylesheet";
      l.href = "https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;800;900&family=Exo+2:wght@300;400;600;700;800&family=JetBrains+Mono:wght@400;700&display=swap";
      document.head.appendChild(l);
    }

    // Inject styles once.
    if (!document.getElementById("wg-style")) {
      const s = document.createElement("style");
      s.id = "wg-style";
      s.textContent = CSS;
      document.head.appendChild(s);
    }

    const accentVars = `--wg:${board.accent};--wg-rgb:${board.rgb};`;

    // Button.
    const btn = document.createElement("button");
    btn.id = "wg-btn";
    btn.className = "wg-btn";
    btn.setAttribute("style", accentVars);
    btn.setAttribute("aria-label", "Open guide");
    btn.title = "What is this board?";
    btn.innerHTML = `<span class="wg-q">?</span>GUIDE`;

    // Backdrop.
    const backdrop = document.createElement("div");
    backdrop.className = "wg-backdrop";
    backdrop.setAttribute("style", accentVars);

    // Panel.
    const panel = document.createElement("aside");
    panel.className = "wg-panel";
    panel.setAttribute("style", accentVars);
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", board.title + " guide");

    if (board.pages) {
      // Multi-page board: render a mini tab bar below the header.
      const tabsHtml = board.pages.map((p, i) =>
        `<button class="wg-ptab${i === 0 ? " active" : ""}" data-page="${p.id}">${p.label}</button>`
      ).join("");
      panel.innerHTML =
        `<div class="wg-head">
           <h2>${board.title}</h2>
           <div class="wg-sub">${board.sub || ""}</div>
           <button class="wg-close" aria-label="Close guide">✕</button>
         </div>
         <div class="wg-ptabs">${tabsHtml}</div>
         <div class="wg-body">${board.pages[0].html}</div>`;

      // Wire up page switching.
      panel.querySelectorAll(".wg-ptab").forEach(btn => {
        btn.addEventListener("click", () => {
          const pageId = btn.dataset.page;
          const page = board.pages.find(p => p.id === pageId);
          if (!page) return;
          panel.querySelectorAll(".wg-ptab").forEach(b => b.classList.remove("active"));
          btn.classList.add("active");
          panel.querySelector(".wg-body").innerHTML = page.html;
          panel.querySelector(".wg-body").scrollTop = 0;
        });
      });
    } else {
      panel.innerHTML =
        `<div class="wg-head">
           <h2>${board.title}</h2>
           <div class="wg-sub">${board.sub || ""}</div>
           <button class="wg-close" aria-label="Close guide">✕</button>
         </div>
         <div class="wg-body">${board.html}</div>`;
    }

    document.body.appendChild(backdrop);
    document.body.appendChild(panel);
    document.body.appendChild(btn);

    const open = () => {
      backdrop.classList.add("open");
      panel.classList.add("open");
      document.body.style.overflow = "hidden";
    };
    const close = () => {
      backdrop.classList.remove("open");
      panel.classList.remove("open");
      document.body.style.overflow = "";
    };

    btn.addEventListener("click", open);
    backdrop.addEventListener("click", close);
    panel.querySelector(".wg-close").addEventListener("click", close);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && panel.classList.contains("open")) close();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // SPA shell (index.html) swaps pages via hash routing — re-render the guide
  // for the newly-shown board each time the hash changes.
  window.addEventListener("hashchange", function () {
    setTimeout(init, 100);
  });
})();
