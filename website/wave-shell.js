/* ═══════════════════════════════════════════════════════════════════════
   Wave Staff Hub — SPA Shell Router (wave-shell.js)
   PJAX-style navigation: fetch pages, strip decorative elements,
   inject body content into #app, re-execute scripts.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── Page map: hash → file ─────────────────────────────────────────── */
  var PAGES = {
    profiles:  { file: 'profile.html',                     label: 'Player Profiles' },
    economy:   { file: 'economy.html',                     label: 'Economy' },
    activity:  { file: 'activity_leaderboard.html',        label: 'Activity' },
    loot:      { file: 'loot_routes_leaderboard.html',     label: 'Loot Routes' },
    surge:     { file: 'surge_routes_leaderboard.html',    label: 'Surge Routes' },
    tips:      { file: 'tips_tricks_leaderboard.html',     label: 'Tips & Tricks' },
    events:    { file: 'events.html',                      label: 'Events' },
    team:      { file: 'team.html',                        label: 'Team Hierarchy' },
    'duty-needs': { file: 'duty_needs.html',               label: 'Duty Needs' },
    rules:        { file: 'rules.html',                    label: 'Rules' },
  };

  /* Scripts to never re-inject (they belong to the shell) */
  var SKIP_SRCS = ['wave-nav.js', 'wave-shell.js', 'wave-guide.js'];

  /* Fixed decorative elements to strip from fetched page bodies */
  var STRIP_SEL = ['.orb', '.orb1', '.orb2', '.orb3', '.scanlines',
                   '.wsh-back', 'a[href="/"]', 'a[href="index.html"]',
                   '#stars', 'nav#wave-nav', 'canvas#stars',
                   '.ucf-ticker-wrap'];

  var appEl    = document.getElementById('app');
  var hubEl    = document.getElementById('hub-view');
  var loaderEl = document.getElementById('spa-loader');

  /* HTML cache keyed by hash */
  var cache = {};

  /* External script srcs already injected into <head> */
  var loadedSrcs = new Set();

  /* Stylesheet hrefs already injected */
  var loadedCss = new Set();

  /* ── Helpers ───────────────────────────────────────────────────────── */
  function getHash() {
    return window.location.hash.replace('#', '') || 'hub';
  }

  function setActiveTab(hash) {
    document.querySelectorAll('.wn-tab').forEach(function (tab) {
      tab.classList.toggle('wn-active', tab.dataset.hash === hash);
    });
  }

  function loaderShow() { loaderEl.style.display = 'block'; }
  function loaderHide() { loaderEl.style.display = 'none'; }

  /* Load an external script once, resolve when done */
  function loadScript(src, crossOrigin) {
    return new Promise(function (resolve) {
      if (!src || loadedSrcs.has(src)) { resolve(); return; }
      loadedSrcs.add(src);
      var s = document.createElement('script');
      s.src = src;
      s.async = false;
      if (crossOrigin) s.setAttribute('crossorigin', crossOrigin);
      s.onload  = resolve;
      s.onerror = resolve;
      document.head.appendChild(s);
    });
  }

  /* Inject a stylesheet href once */
  function loadCss(href) {
    if (!href || loadedCss.has(href) || href.indexOf('styles.css') !== -1) return;
    loadedCss.add(href);
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    document.head.appendChild(link);
  }

  /* Transform and execute Babel/JSX — inline or from a src URL */
  async function runBabelScript(sc) {
    if (!window.Babel) {
      await loadScript('https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.2/babel.min.js');
    }
    var src = sc.getAttribute('src') || '';
    var jsx;
    if (src) {
      try { jsx = await fetch(src).then(function (r) { return r.text(); }); }
      catch (e) { console.warn('[WaveShell] Could not fetch babel src:', src, e); return; }
    } else {
      jsx = sc.textContent;
    }
    try {
      var code = window.Babel.transform(jsx, { presets: ['react'] }).code;
      var exec = document.createElement('script');
      /* Wrap in IIFE so top-level `const` declarations don't bleed into
         global script scope and throw "already declared" on re-navigation */
      exec.textContent = '(function(){\n' + code + '\n})();';
      document.body.appendChild(exec);
    } catch (e) {
      console.warn('[WaveShell] Babel transform error:', e);
    }
  }

  /* Execute a list of script elements in order */
  async function runScripts(scripts) {
    for (var i = 0; i < scripts.length; i++) {
      var sc = scripts[i];
      var src  = sc.getAttribute('src') || '';
      var type = sc.getAttribute('type') || '';

      /* Skip shell scripts */
      if (src && SKIP_SRCS.some(function (s) { return src.indexOf(s) !== -1; })) continue;

      if (type === 'text/babel') {
        /* JSX — transform and execute */
        await runBabelScript(sc);
      } else if (src) {
        /* External script — load once */
        await loadScript(src, sc.getAttribute('crossorigin') || '');
      } else if (sc.textContent.trim()) {
        /* Inline script — wrap in IIFE so top-level const/let declarations
           don't collide with other pages' scripts on re-navigation.
           (e.g. every page declares `const DATA_URL` — without the IIFE
           the second navigation throws "already declared" and aborts.) */
        var s = document.createElement('script');
        s.textContent = '(function(){\n' + sc.textContent + '\n})();';
        document.body.appendChild(s);
      }
    }
  }

  /* ── Navigation ────────────────────────────────────────────────────── */
  async function navigateTo(hash) {
    window.scrollTo(0, 0);
    if (!hash || hash === 'hub') {
      /* Show hub */
      hubEl.style.display = '';
      appEl.style.display  = 'none';
      document.title = 'Wave Staff Hub';
      setActiveTab('hub');
      loaderHide();
      return;
    }

    var page = PAGES[hash];
    if (!page) { navigateTo('hub'); return; }

    /* Switch to app view */
    hubEl.style.display = 'none';
    appEl.style.display  = 'block';
    setActiveTab(hash);
    document.title = page.label + ' — Wave Staff Hub';

    /* Fade out */
    appEl.style.opacity   = '0';
    appEl.style.transform = 'translateY(14px)';
    loaderShow();

    try {
      /* Fetch (cached) */
      if (!cache[hash]) {
        var res = await fetch(page.file);
        if (!res.ok) throw new Error('HTTP ' + res.status);
        cache[hash] = await res.text();
      }

      var parser = new DOMParser();
      var doc = parser.parseFromString(cache[hash], 'text/html');

      /* Inject page-specific fonts/styles from <head> */
      doc.head.querySelectorAll('link[rel="stylesheet"]').forEach(function (link) {
        loadCss(link.href);
      });
      doc.head.querySelectorAll('link[href*="fonts.googleapis"]').forEach(function (link) {
        loadCss(link.href);
      });
      /* Inline <style> blocks from head — remove previous page's styles then inject fresh.
         Deduplication by first-80-chars was wrong: loot/surge share the same CSS reset
         opening so surge's entire stylesheet was silently dropped after visiting loot. */
      document.head.querySelectorAll('style[data-spa-page]').forEach(function (s) { s.remove(); });
      doc.head.querySelectorAll('style').forEach(function (style) {
        var s = document.createElement('style');
        s.setAttribute('data-spa-page', hash);
        s.textContent = style.textContent;
        document.head.appendChild(s);
      });

      /* Collect head scripts (React, Babel CDN) */
      var headScripts = Array.from(doc.head.querySelectorAll('script'));

      /* Strip decorative fixed elements from body */
      STRIP_SEL.forEach(function (sel) {
        doc.body.querySelectorAll(sel).forEach(function (el) { el.remove(); });
      });

      /* Also strip any inline .wsh-back style blocks (they reference position:fixed) */
      doc.body.querySelectorAll('style').forEach(function (style) {
        if (style.textContent.indexOf('wsh-back') !== -1) style.remove();
      });

      /* Collect and detach body scripts before injecting HTML */
      var bodyScripts = Array.from(doc.body.querySelectorAll('script'));
      bodyScripts.forEach(function (s) { s.remove(); });

      /* Inject body HTML */
      appEl.innerHTML = doc.body.innerHTML;

      /* Re-inject a hidden dummy canvas so star-animation scripts don't throw
         (the real #stars canvas was position:fixed and stripped above) */
      if (!appEl.querySelector('canvas#stars')) {
        var dummyCanvas = document.createElement('canvas');
        dummyCanvas.id = 'stars';
        dummyCanvas.style.cssText = 'display:none!important;position:absolute;pointer-events:none;';
        appEl.appendChild(dummyCanvas);
      }

      /* Fade in */
      loaderHide();
      requestAnimationFrame(function () {
        requestAnimationFrame(function () {
          appEl.style.transition = 'opacity 0.28s ease,transform 0.28s ease';
          appEl.style.opacity    = '1';
          appEl.style.transform  = 'translateY(0)';
          /* After the transition ends, REMOVE the transform so that
             position:fixed children (React modals, etc.) are relative
             to the viewport — a transform on a parent creates a new
             containing block and breaks position:fixed. */
          setTimeout(function () { appEl.style.transform = ''; }, 300);
        });
      });

      /* Shim DOMContentLoaded for PJAX: the event already fired on the SPA
         shell, so any subpage script that does addEventListener('DOMContentLoaded', fn)
         would wait forever. Intercept those calls and invoke fn() immediately. */
      /* Execute scripts: head deps first, then body logic */
      await runScripts(headScripts);
      await runScripts(bodyScripts);

    } catch (err) {
      loaderHide();
      appEl.style.opacity   = '1';
      appEl.style.transform = '';
      appEl.innerHTML =
        '<div style="text-align:center;padding:80px 24px;' +
        'font-family:\'JetBrains Mono\',monospace;color:rgba(122,152,176,0.75)">' +
        '<div style="font-size:36px;margin-bottom:16px">⚠️</div>' +
        '<div style="font-size:13px;letter-spacing:1px">Failed to load page</div>' +
        '<div style="font-size:11px;margin-top:8px;color:rgba(74,96,128,0.7)">' +
        err.message + '</div>' +
        '<a data-hash="hub" style="display:inline-block;margin-top:24px;' +
        'font-size:10px;letter-spacing:2px;text-transform:uppercase;' +
        'color:#00d4ff;cursor:pointer;text-decoration:none">← Back to Hub</a>' +
        '</div>';
    }
  }

  /* ── Event delegation ──────────────────────────────────────────────── */
  document.addEventListener('click', function (e) {
    /* Nav tab clicks */
    var tab = e.target.closest('[data-hash]');
    if (tab) {
      e.preventDefault();
      var h = tab.dataset.hash;
      if (h === 'hub' || !h) {
        history.pushState(null, '', window.location.pathname);
        window.dispatchEvent(new Event('hashchange'));
      } else {
        window.location.hash = h;
      }
      return;
    }

    /* Logo clicks (return to hub without full reload) */
    var logo = e.target.closest('#wave-nav-logo');
    if (logo) {
      e.preventDefault();
      history.pushState(null, '', window.location.pathname);
      window.dispatchEvent(new Event('hashchange'));
      return;
    }

    /* Hub card / bonus link clicks */
    var card = e.target.closest('[data-spa-link]');
    if (card) {
      e.preventDefault();
      window.location.hash = card.dataset.spaLink;
    }
  });

  /* ── Hash routing ──────────────────────────────────────────────────── */
  window.addEventListener('hashchange', function () {
    navigateTo(getHash());
  });

  /* ── Mark as SPA (wave-nav.js guard checks this) ───────────────────── */
  window.__WAVE_SPA = true;

  /* ── Initial route ─────────────────────────────────────────────────── */
  navigateTo(getHash());

})();
