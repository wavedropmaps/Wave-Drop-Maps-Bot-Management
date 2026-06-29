(function () {
  /* Skip injection if already running inside the SPA shell (index.html) */
  if (window.__WAVE_SPA || document.getElementById('wave-nav')) return;

  var NAV_H = 52;
  var BANNER_H = 36;
  var BANNER_KEY = 'wave-banner-dismissed-4yr';

  var PAGES = [
    { file: 'economy.html',                     label: 'Wave Shop' },
    { file: 'activity_leaderboard.html',         label: 'Activity' },
    { file: 'index.html#events',                label: 'Events' },
    { file: 'index.html',                       label: 'Home' },
    { file: 'index.html#duty-needs',            label: 'Duties Needed' },
    { file: 'index.html#team',                  label: 'Team' },
    { file: 'loot_routes_leaderboard.html',     label: 'Loot Routes' },
    { file: 'surge_routes_leaderboard.html',    label: 'Surge Routes' },
    { file: 'tips_tricks_leaderboard.html',     label: 'Tips & Tricks' },
  ];

  var current = window.location.pathname.split('/').pop() || 'index.html';
  if (current === '') current = 'index.html';

  // Load Google Fonts if not already present on this page
  if (!document.querySelector('link[href*="Instrument+Serif"]')) {
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;700&display=swap';
    document.head.appendChild(link);
  }

  var bannerDismissed = localStorage.getItem(BANNER_KEY);
  var totalOffset = NAV_H + (bannerDismissed ? 0 : BANNER_H);

  // Inject nav CSS
  var style = document.createElement('style');
  style.textContent = [
    '#wave-announce-banner{position:fixed;top:52px;left:0;right:0;height:36px;z-index:9999;display:flex;align-items:center;justify-content:center;pointer-events:none;}',
    '.wab-pill{display:inline-flex;align-items:center;gap:9px;background:linear-gradient(135deg,rgba(0,28,50,0.99) 0%,rgba(0,12,32,0.99) 100%);border:1px solid rgba(0,212,255,0.55);border-radius:5px;padding:0 8px 0 14px;height:27px;pointer-events:all;font-family:"JetBrains Mono",monospace;font-size:11px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;box-shadow:0 0 0 1px rgba(0,212,255,0.08),0 0 22px rgba(0,212,255,0.22),0 2px 14px rgba(0,0,0,0.75);}',
    '.wab-star{color:#00d4ff;font-size:12px;flex-shrink:0;filter:drop-shadow(0 0 5px rgba(0,212,255,0.9));animation:wab-pulse 2.4s ease-in-out infinite;}',
    '.wab-text{background:linear-gradient(90deg,#c8eeff,#00d4ff,#c8eeff);background-size:200% auto;-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;animation:wab-shimmer 3.5s linear infinite;white-space:nowrap;}',
    '.wab-sub{-webkit-text-fill-color:unset;color:rgba(160,205,225,0.72);font-size:9.5px;letter-spacing:1.1px;font-weight:400;background:none;-webkit-background-clip:unset;background-clip:unset;animation:none;white-space:nowrap;}',
    '.wab-close{background:none;border:none;cursor:pointer;color:rgba(122,152,176,0.55);font-size:15px;line-height:1;padding:2px 3px;margin-left:3px;transition:color 0.15s;flex-shrink:0;}',
    '.wab-close:hover{color:rgba(200,235,255,0.95);}',
    '@keyframes wab-pulse{0%,100%{opacity:1;}50%{opacity:0.35;}}',
    '@keyframes wab-shimmer{0%{background-position:0% center;}100%{background-position:200% center;}}',
    '@media(max-width:480px){.wab-sub{display:none;}}',
    '#wave-nav{',
      'position:fixed;top:0;left:0;right:0;height:' + NAV_H + 'px;z-index:10000;',
      'background:rgba(4,9,18,0.97);',
      'backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);',
      'border-bottom:1px solid rgba(0,212,255,0.13);',
      'box-shadow:0 2px 28px rgba(0,0,0,0.65);',
      'display:flex;align-items:center;',
    '}',

    '#wave-nav-logo{flex-shrink:0;display:flex;align-items:center;gap:9px;padding:0 20px 0 18px;border-right:1px solid rgba(255,255,255,0.07);height:100%;text-decoration:none;}',
    '#wave-nav-logo .wn-wave{font-size:19px;line-height:1;filter:drop-shadow(0 0 10px rgba(0,212,255,0.5));}',
    '#wave-nav-logo .wn-text{',
      'font-family:"Instrument Serif",serif;font-size:19px;font-weight:400;',
      'letter-spacing:0.5px;color:#fff;',
    '}',

    '#wave-nav-tabs{',
      'display:flex;align-items:center;height:100%;',
      'overflow-x:auto;scrollbar-width:none;-ms-overflow-style:none;flex:1;',
    '}',
    '#wave-nav-tabs::-webkit-scrollbar{display:none;}',

    '.wn-tab{',
      'display:flex;align-items:center;height:100%;padding:0 15px;',
      'font-family:"JetBrains Mono",monospace;font-size:10px;font-weight:700;',
      'letter-spacing:1.5px;text-transform:uppercase;white-space:nowrap;',
      'color:rgba(122,152,176,0.75);text-decoration:none;',
      'border-bottom:2px solid transparent;box-sizing:border-box;',
      'transition:color 0.18s;',
    '}',
    '.wn-tab:hover{color:rgba(205,217,232,0.95);}',
    '.wn-tab.wn-active{',
      'color:#fff;border-bottom-color:#00d4ff;',
      'text-shadow:0 0 8px rgba(0,212,255,0.35);',
    '}',

    // Hide old back-to-hub buttons (class-based, inline href="/" variant, and button.back-btn)
    '.wsh-back{display:none!important;}',
    'body>a[href="/"]{display:none!important;}',
    '.back-btn{display:none!important;}',

    // Push each page's content below the nav bar
    'body{padding-top:' + totalOffset + 'px!important;}',

    '@media(max-width:640px){',
      '#wave-nav-logo .wn-text{display:none;}',
      '#wave-nav-logo{padding:0 12px;}',
      '.wn-tab{padding:0 11px;font-size:9px;letter-spacing:1px;}',
    '}',
  ].join('');
  document.head.appendChild(style);

  // Build tab links
  var tabsHTML = PAGES.map(function (p) {
    var active = current === p.file ? ' wn-active' : '';
    return '<a href="' + p.file + '" class="wn-tab' + active + '">' + p.label + '</a>';
  }).join('');

  // Build and prepend nav element
  var nav = document.createElement('nav');
  nav.id = 'wave-nav';
  nav.setAttribute('aria-label', 'Wave Staff Hub navigation');
  nav.innerHTML =
    '<a href="index.html" id="wave-nav-logo" title="Wave Staff Hub">' +
      '<span class="wn-wave"><img src="/assets/wave-logo.png" class="wave-logo-inline" style="height:24px;" alt="Wave"></span>' +
      '<span class="wn-text">Wave</span>' +
    '</a>' +
    '<div id="wave-nav-tabs" role="list">' + tabsHTML + '</div>';

  document.body.insertBefore(nav, document.body.firstChild);

  if (!bannerDismissed) {
    var banner = document.createElement('div');
    banner.id = 'wave-announce-banner';
    banner.innerHTML =
      '<div class="wab-pill">' +
        '<span class="wab-star">✦</span>' +
        '<span class="wab-text">Wave 4 Year Anniversary</span>' +
        '<span class="wab-star">✦</span>' +
        '<span class="wab-sub">Thank you to everyone in this server for an amazing journey!</span>' +
        '<button class="wab-close" id="wave-announce-close" aria-label="Dismiss banner">×</button>' +
      '</div>';
    document.body.insertBefore(banner, nav.nextSibling);
    document.getElementById('wave-announce-close').addEventListener('click', function () {
      banner.remove();
      localStorage.setItem(BANNER_KEY, '1');
      document.body.style.paddingTop = NAV_H + 'px';
    });
  }

  // Load user menu (avatar dropdown + profile/account panels)
  if (!document.querySelector('script[src*="wave-user-menu"]')) {
    var um = document.createElement('script');
    um.src = 'wave-user-menu.js?v=4';
    document.head.appendChild(um);
  }
})();
