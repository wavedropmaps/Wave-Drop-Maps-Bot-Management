/* wave-user-menu.js — avatar dropdown + profile/account/admin side panel */
(function () {
  'use strict';
  if (document.getElementById('wn-user-zone')) return;

  if (!document.querySelector('link[href*="Orbitron"]')) {
    var fl = document.createElement('link');
    fl.rel = 'stylesheet';
    fl.href = 'https://fonts.googleapis.com/css2?family=Orbitron:wght@700;900&family=JetBrains+Mono:wght@400;700&display=swap';
    document.head.appendChild(fl);
  }

  /* ── CSS ──────────────────────────────────────────────────────────────── */
  var S = document.createElement('style');
  S.textContent = `
    #wn-user-zone{
      flex-shrink:0;display:flex;align-items:center;
      padding:0 14px;height:100%;
      border-left:1px solid rgba(0,212,255,0.1);
      position:relative;
    }
    #wn-avatar-btn{
      width:32px;height:32px;border-radius:50%;
      border:2px solid rgba(0,212,255,0.35);overflow:hidden;
      cursor:pointer;background:rgba(0,212,255,0.08);
      padding:0;transition:border-color .2s,box-shadow .2s;
    }
    #wn-avatar-btn:hover{border-color:#00d4ff;box-shadow:0 0 14px rgba(0,212,255,0.4);}
    #wn-avatar-btn img{width:100%;height:100%;object-fit:cover;display:block;}
    #wn-avatar-btn .wnap{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:15px;color:rgba(0,212,255,0.7);}

    #wn-dropdown{
      position:fixed;top:0;right:0;width:268px;
      background:rgba(4,9,20,0.98);
      backdrop-filter:blur(28px);-webkit-backdrop-filter:blur(28px);
      border:1px solid rgba(0,212,255,0.16);border-radius:14px;
      box-shadow:0 20px 60px rgba(0,0,0,0.75),inset 0 1px 0 rgba(255,255,255,0.05);
      transform-origin:top right;transform:scale(0.9) translateY(-10px);
      opacity:0;pointer-events:none;
      transition:transform .2s cubic-bezier(0.34,1.56,0.64,1),opacity .15s ease;
      z-index:100001;
    }
    #wn-dropdown.wno{transform:scale(1) translateY(0);opacity:1;pointer-events:all;}

    .wn-ddh{display:flex;align-items:center;gap:12px;padding:15px 16px;border-bottom:1px solid rgba(255,255,255,0.06);}
    .wn-ddh-av{width:38px;height:38px;border-radius:50%;border:2px solid rgba(0,212,255,0.3);overflow:hidden;flex-shrink:0;}
    .wn-ddh-av img{width:100%;height:100%;object-fit:cover;}
    .wn-ddh-name{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .wn-ddh-sub{font-family:'JetBrains Mono',monospace;font-size:10px;color:rgba(122,152,176,0.75);margin-top:2px;}
    .wn-ddm{padding:8px;}
    .wn-ddi{
      display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;
      font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:.4px;
      color:rgba(205,217,232,0.85);cursor:pointer;
      transition:background .15s,color .15s;border:none;background:transparent;width:100%;text-align:left;
    }
    .wn-ddi:hover{background:rgba(0,212,255,0.08);color:#fff;}
    .wn-ddi .wni{font-size:15px;width:20px;text-align:center;flex-shrink:0;}
    .wn-ddi .wna{margin-left:auto;color:rgba(122,152,176,0.4);font-size:12px;}
    .wn-ddiv{height:1px;background:rgba(255,255,255,0.06);margin:6px 8px;}
    .wn-ddi.wn-lo{color:rgba(255,77,77,0.8);}
    .wn-ddi.wn-lo:hover{background:rgba(255,77,77,0.1);color:#ff5555;}

    #wn-bk{
      position:fixed;inset:0;background:rgba(0,0,0,0.6);
      backdrop-filter:blur(5px);-webkit-backdrop-filter:blur(5px);
      z-index:15000;opacity:0;pointer-events:none;transition:opacity .25s;
    }
    #wn-bk.wno{opacity:1;pointer-events:all;}

    #wn-panel{
      position:fixed;top:0;right:0;bottom:0;
      width:440px;max-width:100vw;
      background:#04090e;
      border-left:1px solid rgba(0,212,255,0.12);
      z-index:16000;transform:translateX(100%);
      transition:transform .32s cubic-bezier(0.25,1,0.5,1);
      display:flex;flex-direction:column;overflow:hidden;
    }
    #wn-panel.wno{transform:translateX(0);}
    #wn-panel.wn-panel-full{width:100vw;max-width:100vw;}
    body.wn-panel-open .wg-btn,body.wn-dd-open .wg-btn{display:none!important;}
    #wn-panel.wn-panel-full .wn-adm-content,#wn-panel.wn-panel-full .wn-adm-tabbar{max-width:820px;margin-left:auto;margin-right:auto;width:100%;box-sizing:border-box;}

    .wn-ph{
      display:flex;align-items:center;gap:10px;padding:13px 18px;
      border-bottom:1px solid rgba(0,212,255,0.1);flex-shrink:0;
      background:rgba(4,9,18,0.9);
    }
    .wn-phb,.wn-phc{
      width:28px;height:28px;border-radius:7px;
      border:1px solid rgba(255,255,255,0.1);background:transparent;
      color:rgba(205,217,232,0.65);font-size:15px;cursor:pointer;
      display:flex;align-items:center;justify-content:center;
      transition:background .15s,color .15s;
    }
    .wn-phb:hover{background:rgba(255,255,255,0.07);color:#fff;}
    .wn-phc:hover{background:rgba(255,77,77,0.1);color:#ff5555;}
    .wn-pht{
      font-family:'Orbitron','JetBrains Mono',monospace;font-size:10px;font-weight:700;
      letter-spacing:2.5px;text-transform:uppercase;color:rgba(205,217,232,0.85);flex:1;
    }

    .wn-pb{
      flex:1;overflow-y:auto;
      scrollbar-width:thin;scrollbar-color:rgba(0,212,255,0.15) transparent;
    }
    .wn-pb::-webkit-scrollbar{width:3px;}
    .wn-pb::-webkit-scrollbar-thumb{background:rgba(0,212,255,0.2);border-radius:2px;}

    /* ── Profile hero ── */
    .wn-hero{
      display:flex;align-items:center;gap:14px;
      padding:20px 20px 16px;
      background:linear-gradient(135deg,rgba(0,212,255,0.06) 0%,rgba(0,0,0,0) 60%);
      border-bottom:1px solid rgba(255,255,255,0.05);
    }
    .wn-hero-av{
      width:64px;height:64px;border-radius:50%;flex-shrink:0;
      border:3px solid rgba(0,212,255,0.4);overflow:hidden;
      box-shadow:0 0 22px rgba(0,212,255,0.2);
    }
    .wn-hero-av img{width:100%;height:100%;object-fit:cover;}
    .wn-hero-name{font-family:'Orbitron',monospace;font-size:16px;font-weight:800;color:#fff;line-height:1.2;}
    .wn-hero-role{
      font-family:'JetBrains Mono',monospace;font-size:9px;
      color:rgba(0,212,255,0.8);letter-spacing:2px;text-transform:uppercase;margin-top:5px;
    }

    /* ── Stat blocks ── */
    .wn-stats-row{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid rgba(255,255,255,0.05);}
    .wn-stat-block{
      padding:16px 20px;position:relative;overflow:hidden;
    }
    .wn-stat-block:first-child{border-right:1px solid rgba(255,255,255,0.05);}
    .wn-stat-block::before{
      content:'';position:absolute;top:0;left:0;right:0;height:1px;
      background:linear-gradient(90deg,var(--sc,#00d4ff),transparent);opacity:0.4;
    }
    .wn-stat-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:1.8px;text-transform:uppercase;color:rgba(122,152,176,0.6);margin-bottom:6px;}
    .wn-stat-val{font-family:'Orbitron',monospace;font-size:24px;font-weight:900;color:var(--sc,#00d4ff);line-height:1;}
    .wn-stat-sub{font-family:'JetBrains Mono',monospace;font-size:9px;color:rgba(122,152,176,0.5);margin-top:4px;}

    /* ── VBucks sub ── */
    .wn-vb-row{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid rgba(255,255,255,0.05);}
    .wn-vb-cell{padding:12px 20px;}
    .wn-vb-cell:first-child{border-right:1px solid rgba(255,255,255,0.05);}
    .wn-vb-lbl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(122,152,176,0.5);}
    .wn-vb-val{font-family:'JetBrains Mono',monospace;font-size:15px;font-weight:700;color:#FFD93D;margin-top:3px;}

    /* ── Section wrapper ── */
    .wn-section{padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.04);}
    .wn-section:last-child{border-bottom:none;}
    .wn-sec-title{
      font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;
      letter-spacing:2px;text-transform:uppercase;color:rgba(122,152,176,0.5);
      margin-bottom:12px;display:flex;align-items:center;gap:8px;
    }
    .wn-sec-title::after{content:'';flex:1;height:1px;background:rgba(255,255,255,0.05);}

    /* ── Duty chips ── */
    .wn-chips{display:flex;flex-wrap:wrap;gap:6px;}
    .wn-chip{
      display:inline-flex;align-items:center;gap:5px;padding:5px 11px;
      border-radius:20px;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;
      border:1px solid;
    }

    /* ── Route cards ── */
    .wn-route-row{display:grid;grid-template-columns:1fr 1fr;gap:8px;}
    .wn-route-card{
      background:rgba(255,255,255,0.025);border:1px solid rgba(255,255,255,0.07);
      border-radius:10px;padding:14px;text-align:center;
    }
    .wn-route-type{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(122,152,176,0.65);margin-bottom:5px;}
    .wn-route-val{font-family:'Orbitron',monospace;font-size:28px;font-weight:700;}
    .wn-route-sub{font-family:'JetBrains Mono',monospace;font-size:9px;color:rgba(122,152,176,0.5);margin-top:3px;}

    /* ── Chart ── */
    .wn-chart-wrap{
      background:rgba(255,255,255,0.018);border:1px solid rgba(255,255,255,0.06);
      border-radius:10px;padding:14px 10px 10px;margin-bottom:12px;overflow:hidden;
    }
    .wn-chart-legend{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;}
    .wn-legend-item{display:flex;align-items:center;gap:5px;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:1px;text-transform:uppercase;}
    .wn-legend-dot{width:8px;height:8px;border-radius:50%;}

    /* ── Recent weeks table ── */
    .wn-tl-table{width:100%;border-collapse:collapse;}
    .wn-tl-table th{font-family:'JetBrains Mono',monospace;font-size:8px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:rgba(122,152,176,0.5);padding:4px 8px 8px;text-align:right;}
    .wn-tl-table th:first-child{text-align:left;}
    .wn-tl-table td{font-family:'JetBrains Mono',monospace;font-size:11px;padding:7px 8px;border-top:1px solid rgba(255,255,255,0.04);text-align:right;font-weight:700;}
    .wn-tl-table td:first-child{text-align:left;font-size:9px;color:rgba(122,152,176,0.6);font-weight:400;}
    .wn-tl-table tr:hover td{background:rgba(255,255,255,0.02);}

    /* ── Account rows ── */
    .wn-ar{display:flex;align-items:center;gap:12px;padding:12px 14px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:10px;margin-bottom:8px;}
    .wn-ari{font-size:17px;flex-shrink:0;}
    .wn-arl{font-family:'JetBrains Mono',monospace;font-size:9px;letter-spacing:1.5px;text-transform:uppercase;color:rgba(122,152,176,0.6);}
    .wn-arv{font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:#fff;margin-top:2px;}
    .wn-disc{
      width:100%;padding:11px;border-radius:10px;
      border:1px solid rgba(255,107,0,0.28);background:rgba(255,107,0,0.07);
      color:#FF6B00;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;
      letter-spacing:.8px;cursor:pointer;transition:all .2s;margin-top:8px;
    }
    .wn-disc:hover{background:rgba(255,107,0,0.14);border-color:rgba(255,107,0,0.45);}

    /* ── Loading / empty ── */
    .wn-spin-wrap{display:flex;align-items:center;justify-content:center;padding:60px 20px;color:rgba(122,152,176,0.5);font-family:'JetBrains Mono',monospace;font-size:11px;}
    .wn-sp{width:18px;height:18px;border:2px solid rgba(0,212,255,0.18);border-top-color:#00d4ff;border-radius:50%;animation:wn-rot .8s linear infinite;margin-right:10px;}
    @keyframes wn-rot{to{transform:rotate(360deg);}}
    .wn-nd{text-align:center;padding:50px 20px;color:rgba(122,152,176,0.4);font-family:'JetBrains Mono',monospace;font-size:11px;line-height:2;}

    /* ── Admin panel ── */
    .wn-adm-tabbar{display:flex;gap:4px;padding:12px 16px 0;border-bottom:1px solid rgba(255,255,255,0.06);flex-shrink:0;}
    .wn-adm-tab{padding:8px 14px;border-radius:8px 8px 0 0;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:rgba(122,152,176,0.65);background:transparent;border:none;border-bottom:2px solid transparent;cursor:pointer;transition:all .15s;}
    .wn-adm-tab:hover{color:#fff;background:rgba(255,255,255,0.04);}
    .wn-adm-tab.wn-adm-tab-active{color:#A855F7;border-bottom-color:#A855F7;background:rgba(168,85,247,0.07);}
    .wn-adm-content{flex:1;overflow-y:auto;padding:14px 16px;scrollbar-width:thin;scrollbar-color:rgba(168,85,247,0.2) transparent;}
    .wn-adm-section-title{font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(122,152,176,0.5);margin:4px 0 10px;display:flex;align-items:center;gap:8px;}
    .wn-adm-section-title::after{content:'';flex:1;height:1px;background:rgba(255,255,255,0.05);}
    .wn-adm-card{background:rgba(255,255,255,0.024);border:1px solid rgba(255,255,255,0.07);border-radius:10px;padding:12px 14px;margin-bottom:8px;}
    .wn-adm-card-row{display:flex;align-items:flex-start;gap:10px;margin-bottom:10px;}
    .wn-adm-card-info{display:flex;align-items:flex-start;gap:10px;flex:1;min-width:0;}
    .wn-adm-card-info[data-profile-uid]{cursor:pointer;border-radius:8px;transition:background .15s;}
    .wn-adm-card-info[data-profile-uid]:hover{background:rgba(168,85,247,0.06);}
    .wn-adm-card-rank{font-family:'Orbitron',monospace;font-size:13px;font-weight:700;color:rgba(122,152,176,0.5);flex-shrink:0;min-width:28px;text-align:center;}
    .wn-adm-card-av{width:40px;height:40px;border-radius:50%;overflow:hidden;flex-shrink:0;border:2px solid rgba(168,85,247,0.25);background:rgba(255,255,255,0.04);}
    .wn-adm-card-av img{width:100%;height:100%;object-fit:cover;display:block;}
    .wn-adm-card-av-ph{display:flex;align-items:center;justify-content:center;font-size:18px;color:rgba(168,85,247,0.6);}
    .wn-adm-card-id{font-family:'JetBrains Mono',monospace;font-size:9px;color:rgba(122,152,176,0.45);margin-top:1px;user-select:all;}
    .wn-adm-card-name{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .wn-adm-card-pts{font-family:'JetBrains Mono',monospace;font-size:10px;color:rgba(122,152,176,0.6);margin-top:2px;}
    .wn-adm-card-badges{display:flex;align-items:center;gap:4px;flex-shrink:0;}
    .wn-adm-card-actions{display:flex;flex-wrap:wrap;gap:6px;}
    .wn-adm-sub{font-family:'JetBrains Mono',monospace;font-size:9px;color:rgba(122,152,176,0.55);margin-top:2px;}
    .wn-adm-badge{font-family:'JetBrains Mono',monospace;font-size:8px;font-weight:700;letter-spacing:1px;text-transform:uppercase;padding:3px 7px;border-radius:20px;}
    .wn-adm-badge-active{background:rgba(0,212,255,0.1);color:#00d4ff;border:1px solid rgba(0,212,255,0.25);}
    .wn-adm-badge-free{background:rgba(0,255,136,0.08);color:#00FF88;border:1px solid rgba(0,255,136,0.2);}
    .wn-adm-badge-away{background:rgba(255,180,0,0.08);color:#FFB400;border:1px solid rgba(255,180,0,0.2);}
    .wn-adm-btn{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:.5px;padding:7px 13px;border-radius:7px;border:none;cursor:pointer;transition:all .15s;white-space:nowrap;}
    .wn-adm-btn-sm{font-size:9px;padding:5px 10px;}
    .wn-adm-btn-primary{background:rgba(168,85,247,0.18);color:#A855F7;border:1px solid rgba(168,85,247,0.3);}
    .wn-adm-btn-primary:hover{background:rgba(168,85,247,0.28);border-color:#A855F7;}
    .wn-adm-btn-success{background:rgba(0,255,136,0.1);color:#00FF88;border:1px solid rgba(0,255,136,0.2);}
    .wn-adm-btn-success:hover{background:rgba(0,255,136,0.18);}
    .wn-adm-btn-warning{background:rgba(255,180,0,0.1);color:#FFB400;border:1px solid rgba(255,180,0,0.2);}
    .wn-adm-btn-warning:hover{background:rgba(255,180,0,0.18);}
    .wn-adm-btn-danger{background:rgba(255,77,77,0.1);color:#ff5555;border:1px solid rgba(255,77,77,0.2);}
    .wn-adm-btn-danger:hover{background:rgba(255,77,77,0.18);}
    .wn-adm-btn-ghost{background:rgba(255,255,255,0.04);color:rgba(205,217,232,0.65);border:1px solid rgba(255,255,255,0.1);}
    .wn-adm-btn-ghost:hover{background:rgba(255,255,255,0.08);color:#fff;}
    .wn-adm-actions-bar{display:flex;gap:8px;margin-top:8px;}
    .wn-adm-loading{text-align:center;padding:40px 20px;color:rgba(122,152,176,0.45);font-family:'JetBrains Mono',monospace;font-size:11px;}
    .wn-adm-err{text-align:center;padding:30px 20px;color:rgba(255,77,77,0.7);font-family:'JetBrains Mono',monospace;font-size:11px;}
    .wn-adm-empty{text-align:center;padding:20px;color:rgba(122,152,176,0.4);font-family:'JetBrains Mono',monospace;font-size:10px;}
    .wn-adm-modal-ov{position:fixed;inset:0;background:rgba(0,0,0,0.7);backdrop-filter:blur(6px);z-index:30000;display:flex;align-items:center;justify-content:center;padding:20px;}
    .wn-adm-modal{background:#07101c;border:1px solid rgba(168,85,247,0.25);border-radius:14px;padding:24px;width:100%;max-width:420px;box-shadow:0 24px 60px rgba(0,0,0,0.7);}
    .wn-adm-modal-title{font-family:'Orbitron',monospace;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#fff;margin-bottom:14px;}
    .wn-adm-modal-body{font-family:'JetBrains Mono',monospace;font-size:12px;color:rgba(205,217,232,0.8);line-height:1.6;margin-bottom:18px;}
    .wn-adm-modal-btns{display:flex;gap:8px;justify-content:flex-end;}
    .wn-adm-field{margin-bottom:14px;}
    .wn-adm-label{display:block;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:rgba(122,152,176,0.65);margin-bottom:5px;}
    .wn-adm-input{width:100%;box-sizing:border-box;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);border-radius:8px;padding:9px 12px;color:#fff;font-family:'JetBrains Mono',monospace;font-size:12px;outline:none;resize:vertical;}
    .wn-adm-input:focus{border-color:rgba(168,85,247,0.5);background:rgba(168,85,247,0.05);}
    select.wn-adm-input{background:#0a1422;color:#fff;appearance:none;-webkit-appearance:none;background-image:url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23A855F7' stroke-width='3'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;padding-right:34px;cursor:pointer;}
    .wn-adm-input option{background:#0a1422;color:#fff;}
    .wn-adm-toast{position:fixed;bottom:56px;right:18px;z-index:40000;padding:10px 18px;border-radius:9px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;background:rgba(0,255,136,0.15);color:#00FF88;border:1px solid rgba(0,255,136,0.3);opacity:0;transform:translateY(6px);transition:opacity .25s,transform .25s;pointer-events:none;}
    .wn-adm-toast-err{background:rgba(255,77,77,0.15);color:#ff5555;border-color:rgba(255,77,77,0.3);}
    .wn-adm-toast-show{opacity:1;transform:translateY(0);}

    /* Premium Add Duty Modal */
    .wn-premium-modal{background:linear-gradient(180deg, rgba(16,21,36,0.95), rgba(7,16,28,0.98));border:1px solid rgba(0,212,255,0.3);border-radius:18px;padding:28px;width:100%;max-width:460px;box-shadow:0 30px 80px rgba(0,212,255,0.15), inset 0 1px 0 rgba(255,255,255,0.1);position:relative;overflow:hidden;animation:wn-fade-up 0.3s cubic-bezier(0.25,1,0.5,1) forwards;opacity:0;transform:translateY(20px);}
    @keyframes wn-fade-up{to{opacity:1;transform:translateY(0);}}
    .wn-premium-modal::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg, #00d4ff, #a855f7, #ff0080);opacity:0.8;}
    .wn-premium-title{font-family:'Orbitron',monospace;font-size:18px;font-weight:800;color:#fff;margin-bottom:20px;text-shadow:0 2px 10px rgba(0,212,255,0.4);display:flex;align-items:center;gap:10px;}
    .wn-premium-field{margin-bottom:18px;}
    .wn-premium-label{display:block;font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:rgba(0,212,255,0.8);margin-bottom:8px;}
    .wn-premium-select, .wn-premium-input{width:100%;background:rgba(0,0,0,0.4);border:1px solid rgba(0,212,255,0.2);border-radius:10px;padding:12px 14px;color:#fff;font-family:'JetBrains Mono',monospace;font-size:13px;outline:none;transition:all 0.2s;box-sizing:border-box;}
    .wn-premium-select:focus, .wn-premium-input:focus{border-color:#00d4ff;background:rgba(0,212,255,0.05);box-shadow:0 0 12px rgba(0,212,255,0.15);}
    .wn-premium-select{appearance:none;background-image:url("data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%2300d4ff' stroke-width='3'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 14px center;}
    .wn-premium-select option{background:#07101c;color:#fff;}
    .wn-premium-btns{display:flex;gap:12px;justify-content:flex-end;margin-top:24px;}
    .wn-premium-btn-submit{background:linear-gradient(135deg, #a855f7, #00d4ff);color:#fff;border:none;padding:10px 20px;border-radius:10px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;cursor:pointer;transition:transform 0.2s, box-shadow 0.2s;box-shadow:0 4px 15px rgba(0,212,255,0.3);}
    .wn-premium-btn-submit:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,212,255,0.5);}
    .wn-premium-btn-cancel{background:rgba(255,255,255,0.05);color:rgba(255,255,255,0.7);border:1px solid rgba(255,255,255,0.1);padding:10px 20px;border-radius:10px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;cursor:pointer;transition:all 0.2s;}
    .wn-premium-btn-cancel:hover{background:rgba(255,255,255,0.1);color:#fff;}
    .wn-premium-btn-top{background:linear-gradient(135deg, rgba(0,212,255,0.15), rgba(168,85,247,0.15));color:#fff;border:1px solid rgba(0,212,255,0.3);padding:9px 16px;border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:700;letter-spacing:0.5px;cursor:pointer;transition:all 0.2s;display:inline-flex;align-items:center;gap:8px;}
    .wn-premium-btn-top:hover{background:linear-gradient(135deg, rgba(0,212,255,0.25), rgba(168,85,247,0.25));border-color:#00d4ff;box-shadow:0 0 15px rgba(0,212,255,0.2);transform:translateY(-1px);}

    /* Away Status Section */
    .wn-status-section{padding:16px 20px;border-bottom:1px solid rgba(255,255,255,0.06);}
    .wn-status-grid{margin-top:12px;}
    .wn-status-card{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:14px;overflow:hidden;}
    .wn-status-card-title{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:rgba(122,152,176,0.65);margin-bottom:10px;display:flex;align-items:center;gap:6px;}
    .wn-status-circle{width:6px;height:6px;border-radius:50%;flex-shrink:0;}
    .wn-status-circle-away{background:#FFB400;box-shadow:0 0 8px rgba(255,180,0,0.5);}
    .wn-status-users{display:flex;flex-direction:column;gap:8px;max-height:180px;overflow-y:auto;}
    .wn-status-user{display:flex;align-items:center;gap:8px;padding:8px;background:rgba(255,255,255,0.025);border-radius:8px;border:1px solid rgba(255,255,255,0.06);}
    .wn-status-user[data-profile-uid]{cursor:pointer;transition:background .15s,border-color .15s;}
    .wn-status-user[data-profile-uid]:hover{background:rgba(255,255,255,0.05);border-color:rgba(168,85,247,0.2);}
    .wn-status-user-av{width:28px;height:28px;border-radius:50%;overflow:hidden;flex-shrink:0;border:1px solid rgba(255,255,255,0.1);}
    .wn-status-user-av img{width:100%;height:100%;object-fit:cover;}
    .wn-status-user-av-ph{display:flex;align-items:center;justify-content:center;font-size:14px;color:rgba(122,152,176,0.6);}
    .wn-status-user-info{flex:1;min-width:0;}
    .wn-status-user-name{font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:700;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
    .wn-status-user-sub{font-family:'JetBrains Mono',monospace;font-size:8px;color:rgba(122,152,176,0.5);margin-top:2px;}
    .wn-status-empty{text-align:center;padding:12px;font-family:'JetBrains Mono',monospace;font-size:9px;color:rgba(122,152,176,0.4);}
  `;
  document.head.appendChild(S);

  /* ── Nav injection ────────────────────────────────────────────────────── */
  var nav = document.getElementById('wave-nav');
  if (!nav) return;

  var uz = document.createElement('div');
  uz.id = 'wn-user-zone';
  uz.innerHTML = '<button id="wn-avatar-btn" aria-label="User menu"><div class="wnap">&#x1F464;</div></button>';
  nav.appendChild(uz);

  var dd = document.createElement('div');
  dd.id = 'wn-dropdown';
  dd.setAttribute('role', 'menu');
  dd.innerHTML =
    '<div class="wn-ddh">' +
      '<div class="wn-ddh-av" id="wn-ddh-av"><div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:18px;color:rgba(0,212,255,0.6)">&#x1F464;</div></div>' +
      '<div><div class="wn-ddh-name" id="wn-ddh-name">Wave Staff</div><div class="wn-ddh-sub" id="wn-ddh-sub">Staff Hub</div></div>' +
    '</div>' +
    '<div class="wn-ddm">' +
      '<button class="wn-ddi" id="wn-open-profile"><span class="wni">&#x1F464;</span>Profile<span class="wna">&#x203A;</span></button>' +
      '<button class="wn-ddi" id="wn-open-account"><span class="wni">&#x2699;&#xFE0F;</span>Account Settings<span class="wna">&#x203A;</span></button>' +
      '<button class="wn-ddi" id="wn-open-admin" style="color:#A855F7;display:none"><span class="wni">&#x1F6E1;&#xFE0F;</span>Admin Control<span class="wna">&#x203A;</span></button>' +
      '<div class="wn-ddiv"></div>' +
      '<button class="wn-ddi wn-lo" id="wn-logout"><span class="wni">&#x1F6AA;</span>Log Out</button>' +
    '</div>';
  document.body.appendChild(dd);

  var bk = document.createElement('div');
  bk.id = 'wn-bk';
  document.body.appendChild(bk);

  var panel = document.createElement('div');
  panel.id = 'wn-panel';
  panel.innerHTML =
    '<div class="wn-ph">' +
      '<button class="wn-phb" id="wn-ph-back">&#x2039;</button>' +
      '<div class="wn-pht" id="wn-pht">Profile</div>' +
      '<button class="wn-phc" id="wn-ph-close">&#x2715;</button>' +
    '</div>' +
    '<div class="wn-pb" id="wn-pb"><div class="wn-spin-wrap"><div class="wn-sp"></div>Loading&#x2026;</div></div>';
  document.body.appendChild(panel);

  /* ── State ────────────────────────────────────────────────────────────── */
  var ddOpen = false, apiCache = {}, currentUser = null;

  /* ── Dropdown ─────────────────────────────────────────────────────────── */
  var avatarBtn = document.getElementById('wn-avatar-btn');

  function positionDropdown() {
    var r = avatarBtn.getBoundingClientRect();
    dd.style.top  = (r.bottom + 8) + 'px';
    dd.style.right = (window.innerWidth - r.right) + 'px';
  }

  avatarBtn.addEventListener('click', function (e) {
    e.preventDefault();
    ddOpen = !ddOpen;
    if (ddOpen) positionDropdown();
    dd.classList.toggle('wno', ddOpen);
    document.body.classList.toggle('wn-dd-open', ddOpen);
  });
  document.addEventListener('click', function (e) {
    if (ddOpen && !uz.contains(e.target) && !dd.contains(e.target)) { ddOpen = false; dd.classList.remove('wno'); document.body.classList.remove('wn-dd-open'); }
  }, true);

  /* ── Admin role constants ─────────────────────────────────────────────── */
  var ADMIN_ROLES = {
    management: '1041582103927726170',
    headLoot:   '1231187220208025620',
    headSurge:  '1414071449743921303',
    headTT:     '1286285354462085182',
    headStaff:  '1041582510955561021',
  };
  function _roleIdSet(roles) {
    var set = {};
    (roles || []).forEach(function (r) {
      if (r == null) return;
      var id = String(r).trim();
      if (/^\d+$/.test(id)) set[id] = true;
    });
    return set;
  }
  function _hasRoleId(roles, id) { return !!_roleIdSet(roles)[String(id)]; }
  function _canSeeLoot(roles)      { return _hasRoleId(roles, ADMIN_ROLES.management) || _hasRoleId(roles, ADMIN_ROLES.headLoot); }
  function _canSeeSurge(roles)     { return _hasRoleId(roles, ADMIN_ROLES.management) || _hasRoleId(roles, ADMIN_ROLES.headSurge); }
  function _canSeeTT(roles)        { return _hasRoleId(roles, ADMIN_ROLES.management) || _hasRoleId(roles, ADMIN_ROLES.headTT); }
  function _canSeeStaff(roles)     { return _hasRoleId(roles, ADMIN_ROLES.management) || _hasRoleId(roles, ADMIN_ROLES.headStaff); }
  function _hasAnyAdminRole(roles) { return _canSeeLoot(roles) || _canSeeSurge(roles) || _canSeeTT(roles) || _canSeeStaff(roles); }
  function _canSeeAdminTab(tab, roles) {
    if (tab === 'loot')  return _canSeeLoot(roles);
    if (tab === 'surge') return _canSeeSurge(roles);
    if (tab === 'tt')    return _canSeeTT(roles);
    if (tab === 'staff') return _canSeeStaff(roles);
    return false;
  }

  /* ── Panel ────────────────────────────────────────────────────────────── */
  function openPanel(mode) {
    ddOpen = false; dd.classList.remove('wno'); document.body.classList.remove('wn-dd-open');
    var titles = { account: 'Account Settings', admin: 'Admin Control' };
    document.getElementById('wn-pht').textContent = titles[mode] || 'Profile';
    panel.classList.toggle('wn-panel-full', mode === 'admin');
    document.body.classList.add('wn-panel-open');
    bk.classList.add('wno'); panel.classList.add('wno');
    renderPanel(mode);
  }
  function closePanel() { panel.classList.remove('wno'); bk.classList.remove('wno'); document.body.classList.remove('wn-panel-open'); }

  document.getElementById('wn-open-profile').addEventListener('click', function () {
    var uid = currentUser && currentUser.user_id;
    if (uid) { window.location.href = 'profile.html?id=' + uid; } else { openPanel('profile'); }
  });
  document.getElementById('wn-open-account').addEventListener('click', function () { openPanel('account'); });
  var _adminBtn = document.getElementById('wn-open-admin');
  if (_adminBtn) _adminBtn.addEventListener('click', function () { window.location.href = 'admin.html'; });
  document.getElementById('wn-ph-back').addEventListener('click', closePanel);
  document.getElementById('wn-ph-close').addEventListener('click', closePanel);
  bk.addEventListener('click', closePanel);
  document.getElementById('wn-logout').addEventListener('click', function () {
    window.location.href = '/__auth/logout';
  });

  /* ── User identity ────────────────────────────────────────────────────── */
  async function fetchUser() {
    try {
      var r = await fetch('/api/me');
      if (r.ok) { currentUser = await r.json(); }
    } catch (e) {}
    if (currentUser && currentUser.user_id) {
      /* Show avatar + name immediately from /api/me (worker forwards from session) */
      if (currentUser.avatar_url || currentUser.display_name) refreshDropdownHeader();
      /* Show admin button if user has qualifying role */
      var roles = currentUser.roles || [];
      if (_hasAnyAdminRole(roles)) {
        var ab = document.getElementById('wn-open-admin');
        if (ab) ab.style.display = '';
      } else {
        var abHide = document.getElementById('wn-open-admin');
        if (abHide) abHide.style.display = 'none';
      }
      /* Enrich with loot data (fills in avatar/name for users not yet in /api/me session) */
      await enrichFromLoot(currentUser.user_id);
    }
  }

  async function enrichFromLoot(uid) {
    try {
      var r = await fetch('/api/loot');
      if (!r.ok) return;
      var d = await r.json(); apiCache.loot = d;
      var p = (d.players || []).find(function (x) { return String(x.user_id) === String(uid); });
      if (p) {
        if (!currentUser.display_name) currentUser.display_name = p.display_name;
        if (!currentUser.avatar_url)   currentUser.avatar_url   = p.avatar_url;
        refreshDropdownHeader();
      }
    } catch (e) {}
  }

  function refreshDropdownHeader() {
    var u = currentUser || {};
    if (u.avatar_url) {
      var img = '<img src="' + u.avatar_url + '" alt="">';
      avatarBtn.innerHTML = img;
      document.getElementById('wn-ddh-av').innerHTML = img;
    }
    if (u.display_name) document.getElementById('wn-ddh-name').textContent = u.display_name;
    if (u.user_type === 'trainee') {
      document.getElementById('wn-ddh-sub').textContent = 'Trainee';
    } else if (u.user_id) {
      document.getElementById('wn-ddh-sub').textContent = 'ID: ' + u.user_id;
    }
  }

  /* ── API data ─────────────────────────────────────────────────────────── */
  async function fetchAll() {
    await Promise.allSettled(['loot','surge','vbucks','economy','lifetime'].map(async function (k) {
      if (apiCache[k]) return;
      try { var r = await fetch('/api/' + k); if (r.ok) apiCache[k] = await r.json(); } catch (e) {}
    }));
  }

  function getUserStats(uid) {
    var str = String(uid), s = { uid: uid };
    var lp = ((apiCache.loot  || {}).players || []).find(function (x) { return String(x.user_id) === str; });
    var sp = ((apiCache.surge || {}).players || []).find(function (x) { return String(x.user_id) === str; });
    if (lp) s.loot  = lp;
    if (sp) s.surge = sp;
    var vbr = ((apiCache.vbucks || {}).role || []).find(function (x) { return String(x.uid) === str; });
    var vbq = ((apiCache.vbucks || {}).req  || []).find(function (x) { return String(x.uid) === str; });
    s.vbucks_role = vbr ? (vbr.vbucks || 0) : 0;
    s.vbucks_req  = vbq ? (vbq.vbucks || 0) : 0;
    var lifeUsers = (apiCache.lifetime || {}).users || {};
    var le = lifeUsers[str];
    if (le) {
      var L = le.lifetime || {};
      // Compat shim: downstream code reads s.milestones.{message,modlog,req,reviews}.
      // No `role` key (role duty retired); no activity_timeline (not tracked anymore).
      s.milestones = {
        uid: uid,
        message: L.message, modlog: L.modlog, req: L.req, reviews: L.reviews,
        avatar_url: le.avatar_url, toprole: le.top_role
      };
      s.display_name = s.display_name || le.name;
      s.avatar_url = s.avatar_url || le.avatar_url;
    }
    if (!s.display_name && lp) { s.display_name = lp.display_name; s.avatar_url = lp.avatar_url; }
    if (!s.display_name && currentUser) { s.display_name = currentUser.display_name; s.avatar_url = s.avatar_url || currentUser.avatar_url; }
    var wp = ((apiCache.economy || {}).leaderboard || []);
    if (s.display_name) {
      var wpm = wp.find(function (x) { return (x.name || '').toLowerCase() === s.display_name.toLowerCase(); });
      if (wpm) s.wave_points = wpm.wp;
    }
    return s;
  }

  /* ── Render panel ─────────────────────────────────────────────────────── */
  function renderPanel(mode) {
    var body = document.getElementById('wn-pb');
    if (mode === 'account') { renderAccount(body); return; }
    if (mode === 'admin') {
      var roles = (currentUser && currentUser.roles) || [];
      if (!_hasAnyAdminRole(roles)) {
        body.innerHTML = '<div class="wn-nd">&#x1F512;<br>Access denied.<br>Admin Control is role-restricted.</div>';
        return;
      }
      renderAdmin(body);
      return;
    }
    body.innerHTML = '<div class="wn-spin-wrap"><div class="wn-sp"></div>Loading&#x2026;</div>';
    var uid = currentUser && currentUser.user_id;
    if (!uid) {
      body.innerHTML = '<div class="wn-nd">&#x1F512;<br>Sign in via Discord<br>to view your profile.</div>';
      return;
    }
    fetchAll().then(function () {
      renderProfile(body, getUserStats(uid));
    });
  }

  /* ── Helpers ──────────────────────────────────────────────────────────── */
  function fmt(n) {
    if (n == null || n === '') return '&#x2014;';
    var x = Number(n); return isNaN(x) ? String(n) : x.toLocaleString();
  }
  function avHtml(url) {
    return url
      ? '<img src="' + url + '" alt="" onerror="this.style.display=\'none\'">'
      : '<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:26px;">&#x1F464;</div>';
  }
  function esc(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

  /* ── SVG multi-line chart ─────────────────────────────────────────────── */
  var DUTY_META = {
    role:    { label: 'Role',     color: '#00D4FF' },
    req:     { label: 'Req',      color: '#FF0080' },
    modlog:  { label: 'Mod',      color: '#A855F7' },
    message: { label: 'Messages', color: '#00FF88' },
  };

  function buildChart(weeks) {
    var data = weeks.slice().reverse();
    if (!data.length) return '';

    var activeDuties = Object.keys(DUTY_META).filter(function (d) {
      return data.some(function (w) { return w.duties && w.duties[d] != null; });
    });
    if (!activeDuties.length) return '';

    var W = 400, H = 160;
    var pad = { top: 12, right: 10, bottom: 28, left: 38 };
    var cW = W - pad.left - pad.right;
    var cH = H - pad.top - pad.bottom;

    var maxVal = 0;
    data.forEach(function (w) {
      activeDuties.forEach(function (d) { if (w.duties[d] != null) maxVal = Math.max(maxVal, w.duties[d]); });
    });
    if (!maxVal) maxVal = 10;

    function xS(i) { return pad.left + (data.length > 1 ? (i / (data.length - 1)) * cW : cW / 2); }
    function yS(v) { return pad.top + cH - (v / maxVal) * cH; }

    var grid = '';
    var steps = 4;
    for (var gi = 0; gi <= steps; gi++) {
      var pct = gi / steps;
      var gy = pad.top + cH * (1 - pct);
      var gv = Math.round(maxVal * pct);
      grid += '<line x1="' + pad.left + '" y1="' + gy.toFixed(1) + '" x2="' + (W - pad.right) + '" y2="' + gy.toFixed(1) + '" stroke="rgba(255,255,255,0.05)" stroke-width="1"/>';
      grid += '<text x="' + (pad.left - 5) + '" y="' + (gy + 3).toFixed(1) + '" text-anchor="end" font-size="8" fill="rgba(122,152,176,0.5)" font-family="JetBrains Mono,monospace">' + gv + '</text>';
    }

    var xLabels = '';
    data.forEach(function (w, i) {
      if (data.length <= 8 || i % 2 === 0) {
        var parts = (w.week_start || '').split('/');
        var lbl = parts.length >= 2 ? parts[0] + '/' + parts[1] : (w.week_start || '');
        xLabels += '<text x="' + xS(i).toFixed(1) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="8" fill="rgba(122,152,176,0.5)" font-family="JetBrains Mono,monospace">' + lbl + '</text>';
      }
    });

    var lines = '';
    activeDuties.forEach(function (d) {
      var color = DUTY_META[d].color;
      var pts = [];
      data.forEach(function (w, i) {
        if (w.duties && w.duties[d] != null) pts.push([xS(i), yS(w.duties[d])]);
        else pts.push(null);
      });

      var areaSegs = [], lineSeg = [], inSeg = false;
      pts.forEach(function (p) {
        if (p) {
          if (!inSeg) { lineSeg = []; inSeg = true; }
          lineSeg.push(p);
        } else if (inSeg) {
          inSeg = false;
          if (lineSeg.length > 1) {
            var ad = 'M ' + lineSeg.map(function (pp) { return pp[0].toFixed(1) + ' ' + pp[1].toFixed(1); }).join(' L ');
            ad += ' L ' + lineSeg[lineSeg.length-1][0].toFixed(1) + ' ' + (pad.top + cH).toFixed(1);
            ad += ' L ' + lineSeg[0][0].toFixed(1) + ' ' + (pad.top + cH).toFixed(1) + ' Z';
            areaSegs.push(ad);
          }
          lineSeg = [];
        }
      });
      if (inSeg && lineSeg.length > 1) {
        var ad = 'M ' + lineSeg.map(function (pp) { return pp[0].toFixed(1) + ' ' + pp[1].toFixed(1); }).join(' L ');
        ad += ' L ' + lineSeg[lineSeg.length-1][0].toFixed(1) + ' ' + (pad.top + cH).toFixed(1);
        ad += ' L ' + lineSeg[0][0].toFixed(1) + ' ' + (pad.top + cH).toFixed(1) + ' Z';
        areaSegs.push(ad);
      }
      areaSegs.forEach(function (ad) {
        lines += '<path d="' + ad + '" fill="' + color + '" opacity="0.07"/>';
      });

      var segments = [], cur = [];
      pts.forEach(function (p) {
        if (p) { cur.push(p); }
        else { if (cur.length) segments.push(cur); cur = []; }
      });
      if (cur.length) segments.push(cur);

      segments.forEach(function (seg) {
        if (seg.length > 1) {
          var d2 = 'M ' + seg.map(function (pp) { return pp[0].toFixed(1) + ' ' + pp[1].toFixed(1); }).join(' L ');
          lines += '<path d="' + d2 + '" stroke="' + color + '" stroke-width="2" fill="none" stroke-linejoin="round" stroke-linecap="round" opacity="0.9"/>';
        }
        seg.forEach(function (pp) {
          lines += '<circle cx="' + pp[0].toFixed(1) + '" cy="' + pp[1].toFixed(1) + '" r="3" fill="' + color + '" opacity="0.9"/>';
        });
      });
    });

    var legend = activeDuties.map(function (d) {
      return '<div class="wn-legend-item"><div class="wn-legend-dot" style="background:' + DUTY_META[d].color + '"></div><span style="color:' + DUTY_META[d].color + '">' + DUTY_META[d].label + '</span></div>';
    }).join('');

    return '<div class="wn-chart-wrap">' +
      '<div class="wn-chart-legend">' + legend + '</div>' +
      '<svg width="100%" viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg" style="display:block;overflow:visible;">' +
        grid + lines + xLabels +
      '</svg>' +
    '</div>';
  }

  /* ── Profile render ───────────────────────────────────────────────────── */
  function renderProfile(body, s) {
    var totalVb  = (s.vbucks_role || 0) + (s.vbucks_req || 0);
    var mil      = s.milestones || {};
    var timeline = mil.activity_timeline || [];

    var duties = [];
    if (s.loot)              duties.push({ label: 'Loot Routes',  icon: '&#x1F5FA;&#xFE0F;', c: '#FF0080' });
    if (s.surge)             duties.push({ label: 'Surge Routes', icon: '&#x26A1;',           c: '#FF6B00' });
    if (mil.role   != null)  duties.push({ label: 'Role Giving',  icon: '&#x1F464;',          c: '#00D4FF' });
    if (mil.req    != null)  duties.push({ label: 'Map Requests', icon: '&#x1F4CB;',          c: '#A855F7' });
    if (mil.modlog != null)  duties.push({ label: 'Mod Commands', icon: '&#x1F528;',          c: '#00FF88' });

    var chipHtml = duties.map(function (d) {
      return '<span class="wn-chip" style="color:' + d.c + ';border-color:' + d.c + '40;background:' + d.c + '10;">' + d.icon + ' ' + d.label + '</span>';
    }).join('');

    var routeHtml = '';
    if (s.loot || s.surge) {
      routeHtml =
        '<div class="wn-section">' +
          '<div class="wn-sec-title">Routes Completed</div>' +
          '<div class="wn-route-row">' +
            (s.loot  ? '<div class="wn-route-card"><div class="wn-route-type">&#x1F5FA;&#xFE0F; Loot Routes</div><div class="wn-route-val" style="color:#FF0080">' + fmt(s.loot.routes_completed) + '</div><div class="wn-route-sub">Rank #' + (s.loot.rotation_rank || '&#x2014;') + '</div></div>' : '') +
            (s.surge ? '<div class="wn-route-card"><div class="wn-route-type">&#x26A1; Surge Routes</div><div class="wn-route-val" style="color:#FF6B00">' + fmt(s.surge.routes_completed) + '</div><div class="wn-route-sub">Rank #' + (s.surge.rotation_rank || '&#x2014;') + '</div></div>' : '') +
          '</div>' +
        '</div>';
    }

    var tlHtml = '';
    if (timeline.length) {
      var chartSvg = buildChart(timeline);
      var activeDutyCols = Object.keys(DUTY_META).filter(function (d) {
        return timeline.some(function (w) { return w.duties && w.duties[d] != null; });
      });
      var thead = '<tr><th>Week</th>' + activeDutyCols.map(function (d) {
        return '<th style="color:' + DUTY_META[d].color + '">' + DUTY_META[d].label + '</th>';
      }).join('') + '</tr>';
      var tbody = timeline.map(function (w) {
        var cells = activeDutyCols.map(function (d) {
          var v = w.duties && w.duties[d] != null ? w.duties[d] : null;
          return '<td style="color:' + (v != null ? DUTY_META[d].color : 'rgba(122,152,176,0.4)') + '">' + (v != null ? fmt(v) : '&#x2014;') + '</td>';
        }).join('');
        return '<tr><td>' + (w.week_start || '') + '</td>' + cells + '</tr>';
      }).join('');
      tlHtml =
        '<div class="wn-section">' +
          '<div class="wn-sec-title">Activity Timeline</div>' +
          chartSvg +
          '<table class="wn-tl-table"><thead>' + thead + '</thead><tbody>' + tbody + '</tbody></table>' +
        '</div>';
    }

    var lifetimeHtml = '';
    var lifeRows = [];
    if (mil.role   != null) lifeRows.push(['<span style="color:#00D4FF">&#x1F464; Role Duty</span>',   '<span style="color:#00D4FF">' + fmt(mil.role)    + '</span>', mil.role_weekly   != null ? fmt(mil.role_weekly)    + ' this week' : '']);
    if (mil.req    != null) lifeRows.push(['<span style="color:#A855F7">&#x1F4CB; Map Requests</span>', '<span style="color:#A855F7">' + fmt(mil.req)     + '</span>', mil.req_weekly    != null ? fmt(mil.req_weekly)     + ' this week' : '']);
    if (mil.modlog != null) lifeRows.push(['<span style="color:#00FF88">&#x1F528; Mod Commands</span>', '<span style="color:#00FF88">' + fmt(mil.modlog)  + '</span>', mil.modlog_weekly != null ? fmt(mil.modlog_weekly)  + ' this week' : '']);
    if (mil.message != null) lifeRows.push(['<span style="color:#FFD93D">&#x1F4AC; Messages</span>',   '<span style="color:#FFD93D">' + fmt(mil.message) + '</span>', mil.message_weekly != null ? fmt(mil.message_weekly) + ' this week' : '']);
    if (mil.reviews != null) lifeRows.push(['<span style="color:#39ff14">&#x1F50D; Reviews</span>',    '<span style="color:#39ff14">' + fmt(mil.reviews) + '</span>', '']);
    if (lifeRows.length) {
      lifetimeHtml =
        '<div class="wn-section">' +
          '<div class="wn-sec-title">Lifetime Totals</div>' +
          '<table class="wn-tl-table"><thead><tr><th>Duty</th><th>Total</th><th>This Week</th></tr></thead><tbody>' +
          lifeRows.map(function (r) {
            return '<tr><td>' + r[0] + '</td><td>' + r[1] + '</td><td style="color:rgba(122,152,176,0.6);font-weight:400;">' + (r[2] || '&#x2014;') + '</td></tr>';
          }).join('') +
          '</tbody></table>' +
        '</div>';
    }

    body.innerHTML =
      '<div class="wn-hero">' +
        '<div class="wn-hero-av">' + avHtml(s.avatar_url || (currentUser && currentUser.avatar_url)) + '</div>' +
        '<div>' +
          '<div class="wn-hero-name">' + (s.display_name || (currentUser && currentUser.display_name) || '&#x2014;') + '</div>' +
          (mil.toprole ? '<div class="wn-hero-role">' + mil.toprole + '</div>' : '') +
        '</div>' +
      '</div>' +
      '<div class="wn-stats-row">' +
        '<div class="wn-stat-block" style="--sc:#00D4FF">' +
          '<div class="wn-stat-lbl">Wave Points</div>' +
          '<div class="wn-stat-val">' + fmt(s.wave_points) + '</div>' +
        '</div>' +
        '<div class="wn-stat-block" style="--sc:#FFD93D">' +
          '<div class="wn-stat-lbl">V-Bucks Total</div>' +
          '<div class="wn-stat-val" style="color:#FFD93D">' + fmt(totalVb) + '</div>' +
        '</div>' +
      '</div>' +
      (totalVb > 0 ?
        '<div class="wn-vb-row">' +
          '<div class="wn-vb-cell"><div class="wn-vb-lbl">Role Duty Wallet</div><div class="wn-vb-val">' + fmt(s.vbucks_role) + '</div></div>' +
          '<div class="wn-vb-cell"><div class="wn-vb-lbl">Map Request Wallet</div><div class="wn-vb-val">' + fmt(s.vbucks_req) + '</div></div>' +
        '</div>' : '') +
      (chipHtml ? '<div class="wn-section"><div class="wn-sec-title">Active Duties</div><div class="wn-chips">' + chipHtml + '</div></div>' : '') +
      routeHtml + lifetimeHtml + tlHtml +
      (!chipHtml && !s.loot && !s.surge && !timeline.length ?
        '<div class="wn-nd">No stats found for your account.</div>' : '');
  }

  /* ── Account settings ─────────────────────────────────────────────────── */
  function renderAccount(body) {
    var u = currentUser || {};
    body.innerHTML =
      '<div class="wn-hero">' +
        '<div class="wn-hero-av">' + avHtml(u.avatar_url) + '</div>' +
        '<div><div class="wn-hero-name">' + (u.display_name || '&#x2014;') + '</div><div class="wn-hero-role">Discord Account</div></div>' +
      '</div>' +
      '<div style="padding:16px 20px;">' +
        '<div class="wn-ar"><div class="wn-ari">&#x1FA7A;</div><div><div class="wn-arl">Discord ID</div><div class="wn-arv">' + (u.user_id || '&#x2014;') + '</div></div></div>' +
        '<div class="wn-ar"><div class="wn-ari">&#x1F464;</div><div><div class="wn-arl">Username</div><div class="wn-arv">' + (u.display_name || '&#x2014;') + '</div></div></div>' +
        '<div class="wn-ar"><div class="wn-ari">&#x1F6E1;&#xFE0F;</div><div><div class="wn-arl">Auth Method</div><div class="wn-arv">Discord OAuth2</div></div></div>' +
        '<div style="height:1px;background:rgba(255,255,255,0.06);margin:16px 0;"></div>' +
        '<button class="wn-disc" onclick="window.open(\'https://discord.com/settings/authorized-apps\',\'_blank\');window.location.href=\'/__auth/logout\'">&#x26A1; Disconnect Account</button>' +
        '<div style="font-size:11px;color:rgba(255,255,255,0.4);text-align:center;margin-top:8px;">To fully revoke access, go to Discord &rarr; User Settings &rarr; Authorized Apps</div>' +
      '</div>';
  }

  /* ── Admin helpers ────────────────────────────────────────────────────── */
  function _admToast(msg, isErr) {
    var t = document.createElement('div');
    t.className = 'wn-adm-toast' + (isErr ? ' wn-adm-toast-err' : '');
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(function () { t.classList.add('wn-adm-toast-show'); }, 10);
    setTimeout(function () { t.classList.remove('wn-adm-toast-show'); setTimeout(function () { t.remove(); }, 300); }, 3200);
  }

  function _admConfirm(title, msg, onConfirm) {
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-adm-modal">' +
        '<div class="wn-adm-modal-title">' + title + '</div>' +
        '<div class="wn-adm-modal-body">' + msg + '</div>' +
        '<div class="wn-adm-modal-btns">' +
          '<button class="wn-adm-btn wn-adm-btn-ghost" id="_amc-cancel">Go back</button>' +
          '<button class="wn-adm-btn wn-adm-btn-danger" id="_amc-ok">Confirm</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);
    ov.querySelector('#_amc-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#_amc-ok').onclick = function () { ov.remove(); onConfirm(); };
  }

  function _admActionBtn(e) {
    var t = e.target;
    if (!t || !t.closest) t = t && t.parentElement;
    return t && t.closest ? t.closest('[data-action]') : null;
  }

  function _admBindClick(el, key, handler) {
    if (!el._admClickKeys) el._admClickKeys = {};
    if (el._admClickKeys[key]) el.removeEventListener('click', el._admClickKeys[key]);
    el._admClickKeys[key] = handler;
    el.addEventListener('click', handler);
  }

  function _admTryProfileNav(e) {
    if (e.target.closest('[data-action]')) return false;
    var profileEl = e.target.closest('[data-profile-uid]');
    if (profileEl && profileEl.dataset.profileUid) {
      window.location.href = 'profile.html?id=' + profileEl.dataset.profileUid;
      return true;
    }
    return false;
  }

  function _admPrompt(title, fields, onSubmit) {
    var fieldsHtml = fields.map(function (f) {
      return '<div class="wn-adm-field">' +
        '<label class="wn-adm-label">' + f.label + (f.required ? ' *' : '') + '</label>' +
        (f.type === 'textarea'
          ? '<textarea class="wn-adm-input" data-key="' + f.key + '" placeholder="' + (f.placeholder || '') + '" rows="4"></textarea>'
          : f.type === 'select'
            ? '<select class="wn-adm-input" data-key="' + f.key + '">' +
                (f.placeholder ? '<option value="">' + esc(f.placeholder) + '</option>' : '') +
                (f.options || []).map(function (o) {
                  return '<option value="' + esc(o.value) + '">' + esc(o.label) + '</option>';
                }).join('') +
              '</select>'
            : '<input class="wn-adm-input" type="' + (f.type || 'text') + '" data-key="' + f.key + '" placeholder="' + (f.placeholder || '') + '" value="' + (f.value || '') + '">') +
      '</div>';
    }).join('');
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-adm-modal">' +
        '<div class="wn-adm-modal-title">' + title + '</div>' +
        '<div class="wn-adm-modal-body">' + fieldsHtml + '</div>' +
        '<div class="wn-adm-modal-btns">' +
          '<button class="wn-adm-btn wn-adm-btn-ghost" id="_amp-cancel">Cancel</button>' +
          '<button class="wn-adm-btn wn-adm-btn-primary" id="_amp-ok">Submit</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);
    ov.querySelector('#_amp-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#_amp-ok').onclick = function () {
      var data = {};
      ov.querySelectorAll('[data-key]').forEach(function (el) { data[el.dataset.key] = el.value.trim(); });
      var missing = fields.filter(function (f) { return f.required && !data[f.key]; });
      if (missing.length) { _admToast('Please fill in: ' + missing.map(function (f) { return f.label; }).join(', '), true); return; }
      ov.remove();
      onSubmit(data);
    };
  }

  function _admSuperTaskForm(ttEl) {
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-adm-modal" style="min-width:380px;max-width:520px;">' +
        '<div class="wn-adm-modal-title">🎯 Create Super Task</div>' +
        '<div class="wn-adm-modal-body">' +
          '<div class="wn-adm-field">' +
            '<label class="wn-adm-label">Parent Title *</label>' +
            '<textarea class="wn-adm-input" id="_st-parent" placeholder="Describe the overall super task…" rows="2"></textarea>' +
          '</div>' +
          '<div class="wn-adm-label" style="margin-bottom:6px;">Subtasks * <span style="font-weight:400;opacity:0.6;">(min 2, max 20)</span></div>' +
          '<div id="_st-subtasks">' +
            '<input class="wn-adm-input" placeholder="Subtask 1…" style="margin-bottom:6px;">' +
            '<input class="wn-adm-input" placeholder="Subtask 2…" style="margin-bottom:6px;">' +
          '</div>' +
          '<button class="wn-adm-btn wn-adm-btn-ghost" id="_st-add-row" style="margin-top:4px;font-size:0.82em;">+ Add subtask</button>' +
        '</div>' +
        '<div class="wn-adm-modal-btns">' +
          '<button class="wn-adm-btn wn-adm-btn-ghost" id="_st-cancel">Cancel</button>' +
          '<button class="wn-adm-btn wn-adm-btn-primary" id="_st-submit">Create</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);
    ov.querySelector('#_st-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#_st-add-row').onclick = function () {
      var box = ov.querySelector('#_st-subtasks');
      if (box.children.length >= 20) { _admToast('Max 20 subtasks', true); return; }
      var inp = document.createElement('input');
      inp.className = 'wn-adm-input';
      inp.placeholder = 'Subtask ' + (box.children.length + 1) + '…';
      inp.style.marginBottom = '6px';
      box.appendChild(inp);
    };
    ov.querySelector('#_st-submit').onclick = function () {
      var parent = ov.querySelector('#_st-parent').value.trim();
      var subtasks = Array.from(ov.querySelectorAll('#_st-subtasks input')).map(function (i) { return i.value.trim(); }).filter(Boolean);
      if (!parent) { _admToast('Parent title required', true); return; }
      if (subtasks.length < 2) { _admToast('At least 2 subtasks required', true); return; }
      ov.remove();
      _admPost('tt/create_super_task', { parent_desc: parent, subtasks: subtasks }).then(function (r) {
        if (r.ok) { _admToast('Super task created (' + (r.subtask_ids || []).length + ' subtasks)'); _admRenderTT(ttEl); }
        else _admToast(r.error || 'Failed', true);
      });
    };
  }

  function _admPremiumDutyModal(onSubmit) {
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-premium-modal">' +
        '<div class="wn-premium-title"><span>✨</span> Add Duty</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Select Duty *</label>' +
          '<select class="wn-premium-select" id="p-duty-val">' +
            '<option value="">Select a duty...</option>' +
            '<option value="add_loot">Loot Route Maker</option>' +
            '<option value="add_surge">Surge Route Maker</option>' +
            '<option value="add_tips">Tips &amp; Tricks Helper</option>' +
            '<option value="add_map">Map Request Helper</option>' +
          '</select>' +
        '</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Discord User ID *</label>' +
          '<input type="text" class="wn-premium-input" id="p-user-id" placeholder="e.g., 123456789012345678">' +
        '</div>' +
        '<div class="wn-premium-btns">' +
          '<button class="wn-premium-btn-cancel" id="p-cancel">Cancel</button>' +
          '<button class="wn-premium-btn-submit" id="p-submit">Confirm Addition</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);

    var dutySel   = ov.querySelector('#p-duty-val');
    var uidInput  = ov.querySelector('#p-user-id');

    ov.querySelector('#p-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#p-submit').onclick = function () {
      var dty = dutySel.value;
      var uid = uidInput.value.trim();
      
      if (!dty) { _admToast('Please select what duty', true); return; }
      if (!uid) { _admToast('Please enter a Discord User ID', true); return; }
      if (!/^\d{17,19}$/.test(uid)) { _admToast('Invalid Discord User ID format (must be 17-19 digits)', true); return; }
      
      ov.remove();
      onSubmit({ duty: dty, user_id: uid });
    };

    return {
      ov: ov,
      setUid: function(id) { uidInput.value = id; }
    };
  }

  function _admPremiumTrainModal(onSubmit) {
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-premium-modal">' +
        '<div class="wn-premium-title"><span>✨</span> Train a User</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Select Duty *</label>' +
          '<select class="wn-premium-select" id="p-duty-val">' +
            '<option value="">Select a duty...</option>' +
            '<option value="train_surge">Surge Route Maker</option>' +
            '<option value="train_tips">Tips &amp; Tricks Helper</option>' +
            '<option value="train_loot">Loot Route Maker</option>' +
            '<option value="train_map">Map Request</option>' +
          '</select>' +
        '</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Discord User ID *</label>' +
          '<input type="text" class="wn-premium-input" id="p-user-id" placeholder="e.g., 123456789012345678">' +
        '</div>' +
        '<div class="wn-premium-btns">' +
          '<button class="wn-premium-btn-cancel" id="p-cancel">Cancel</button>' +
          '<button class="wn-premium-btn-submit" id="p-submit">Confirm Addition</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);

    var dutySel   = ov.querySelector('#p-duty-val');
    var uidInput  = ov.querySelector('#p-user-id');

    ov.querySelector('#p-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#p-submit').onclick = function () {
      var dty = dutySel.value;
      var uid = uidInput.value.trim();
      
      if (!dty) { _admToast('Please select what duty', true); return; }
      if (!uid) { _admToast('Please enter a Discord User ID', true); return; }
      if (!/^\d{17,19}$/.test(uid)) { _admToast('Invalid Discord User ID format (must be 17-19 digits)', true); return; }
      
      ov.remove();
      onSubmit({ duty: dty, user_id: uid });
    };

    return {
      ov: ov,
      setUid: function(id) { uidInput.value = id; }
    };
  }

  function _admPromoteModal(onSubmit) {
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-premium-modal">' +
        '<div class="wn-premium-title"><span>⬆️</span> Promote a User</div>' +
        '<div class="wn-premium-field" style="font-size:11px;color:rgba(205,217,232,0.6);margin-bottom:8px;">' +
          'Ladder: Support → Senior Support → Admin → Senior Admin → Head Admin' +
        '</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Discord User ID *</label>' +
          '<input type="text" class="wn-premium-input" id="p-promote-uid" placeholder="e.g., 123456789012345678">' +
        '</div>' +
        '<div class="wn-premium-btns">' +
          '<button class="wn-premium-btn-cancel" id="p-promote-cancel">Cancel</button>' +
          '<button class="wn-premium-btn-submit" id="p-promote-submit">Promote</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);

    var uidInput = ov.querySelector('#p-promote-uid');
    ov.querySelector('#p-promote-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#p-promote-submit').onclick = function () {
      var uid = uidInput.value.trim();
      if (!uid) { _admToast('Please enter a Discord User ID', true); return; }
      if (!/^\d{17,19}$/.test(uid)) { _admToast('Invalid Discord User ID format (must be 17-19 digits)', true); return; }
      ov.remove();
      onSubmit({ user_id: uid });
    };

    return {
      ov: ov,
      setUid: function(id) { uidInput.value = id; }
    };
  }

  function _admAwayModal(onSubmit) {
    var ov = document.createElement('div');
    ov.className = 'wn-adm-modal-ov';
    ov.innerHTML =
      '<div class="wn-premium-modal">' +
        '<div class="wn-premium-title"><span>⏸️</span> Set User Away</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Discord User ID *</label>' +
          '<input type="text" class="wn-premium-input" id="p-away-uid" placeholder="e.g., 123456789012345678">' +
        '</div>' +
        '<div class="wn-premium-field">' +
          '<label class="wn-premium-label">Return Date (optional)</label>' +
          '<input type="text" class="wn-premium-input" id="p-away-date" placeholder="YYYY-MM-DD">' +
        '</div>' +
        '<div class="wn-premium-btns">' +
          '<button class="wn-premium-btn-cancel" id="p-away-cancel">Cancel</button>' +
          '<button class="wn-premium-btn-submit" id="p-away-submit">Set Away</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(ov);

    var uidInput = ov.querySelector('#p-away-uid');
    var dateInput = ov.querySelector('#p-away-date');
    ov.querySelector('#p-away-cancel').onclick = function () { ov.remove(); };
    ov.querySelector('#p-away-submit').onclick = function () {
      var uid = uidInput.value.trim();
      var date = dateInput.value.trim();
      if (!uid) { _admToast('Please enter a Discord User ID', true); return; }
      if (!/^\d{17,19}$/.test(uid)) { _admToast('Invalid Discord User ID format (must be 17-19 digits)', true); return; }
      if (date) {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { _admToast('Date must be in YYYY-MM-DD format', true); return; }
        var parts = date.split('-');
        var y = parseInt(parts[0], 10), m = parseInt(parts[1], 10), d = parseInt(parts[2], 10);
        if (m < 1 || m > 12 || d < 1 || d > 31) { _admToast('Invalid date (month 1-12, day 1-31)', true); return; }
      }
      ov.remove();
      onSubmit({ user_id: uid, return_date: date || null });
    };

    return {
      ov: ov,
      setUid: function(id) { uidInput.value = id; }
    };
  }

  function _admPost(path, body) {
    return fetch('/api/admin/' + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.text().then(function (txt) {
        try { return JSON.parse(txt); }
        catch (e) { return { error: 'Bad response (' + r.status + '). Try again in a moment.' }; }
      });
    }).catch(function () { return { error: 'Network error — could not reach the bot. Try again.' }; });
  }

  function _admGet(path) {
    return fetch('/api/admin/' + path).then(function (r) {
      return r.text().then(function (txt) {
        try { return JSON.parse(txt); }
        catch (e) { return { error: 'Bad response (' + r.status + '). Try again in a moment.' }; }
      });
    }).catch(function () { return { error: 'Network error — could not reach the bot. Try again.' }; });
  }

  /* ── Admin: Loot Routes ───────────────────────────────────────────────── */
  function _admRenderLoot(el) {
    el.innerHTML = '<div class="wn-adm-loading">Loading rotation&#x2026;</div>';
    _admGet('loot/data').then(function (d) {
      if (d.error) { el.innerHTML = '<div class="wn-adm-err">' + esc(d.error) + '</div>'; return; }
      var rows = (d.makers || []).map(function (m) {
        var statusBadge;
        if (m.is_away) {
          statusBadge = m.away_return
            ? '<span class="wn-adm-badge wn-adm-badge-away">Away</span>'
            : '<span class="wn-adm-badge wn-adm-badge-away">Perm</span>';
        } else {
          statusBadge = m.assignment ? '<span class="wn-adm-badge wn-adm-badge-active">Active</span>' : '<span class="wn-adm-badge wn-adm-badge-free">Free</span>';
        }
        var assignInfo = m.assignment ? '<div class="wn-adm-sub">Assigned ' + esc(m.assignment.assigned_ago) + ' ago</div>' : '';
        var awayInfo = m.is_away && m.away_return ? '<div class="wn-adm-sub">Returns: ' + esc(m.away_return) + '</div>' : '';
        var doneBtn = m.assignment ? '<button class="wn-adm-btn wn-adm-btn-success wn-adm-btn-sm" data-action="loot-done" data-uid="' + m.user_id + '" data-aid="' + m.assignment.assignment_id + '">&#x2713; Mark Done</button>' : '';
        var awayBtn = !m.is_away
          ? '<button class="wn-adm-btn wn-adm-btn-warning wn-adm-btn-sm" data-action="loot-away" data-uid="' + m.user_id + '">Set Away</button>'
          : '<button class="wn-adm-btn wn-adm-btn-ghost wn-adm-btn-sm" data-action="loot-back" data-uid="' + m.user_id + '">Mark Back</button>';
        var removeBtn = '<button class="wn-adm-btn wn-adm-btn-danger wn-adm-btn-sm" data-action="loot-remove" data-uid="' + m.user_id + '" data-name="' + esc(m.display_name || m.user_id) + '">Remove</button>';
        return '<div class="wn-adm-card">' +
          '<div class="wn-adm-card-row">' +
            '<div class="wn-adm-card-info" data-profile-uid="' + esc(m.user_id) + '">' +
              '<div class="wn-adm-card-rank">#' + (m.rotation_rank || '?') + '</div>' +
              (m.avatar_url
                ? '<div class="wn-adm-card-av"><img src="' + esc(m.avatar_url) + '" alt="" onerror="this.parentNode.innerHTML=\'&#x1F464;\';this.remove()"></div>'
                : '<div class="wn-adm-card-av wn-adm-card-av-ph">&#x1F464;</div>') +
              '<div style="min-width:0;"><div class="wn-adm-card-name">' + esc(m.display_name || ('User ' + m.user_id)) + '</div>' +
              '<div class="wn-adm-card-id">' + esc(m.user_id) + '</div>' +
              '<div class="wn-adm-card-pts">' + (m.total_points || 0) + ' pts</div>' + assignInfo + awayInfo + '</div>' +
            '</div>' +
            '<div class="wn-adm-card-badges">' + statusBadge + '</div>' +
          '</div>' +
          '<div class="wn-adm-card-actions">' + doneBtn + ' ' + awayBtn + ' ' + removeBtn + '</div>' +
        '</div>';
      }).join('') || '<div class="wn-adm-empty">No makers in rotation.</div>';
      el.innerHTML = '<div class="wn-adm-section-title">Loot Route Makers (' + (d.makers || []).length + ')</div>' + rows;
      el.addEventListener('click', function (e) {
        if (_admTryProfileNav(e)) return;
        var btn = e.target.closest('[data-action]'); if (!btn) return;
        var action = btn.dataset.action, uid = btn.dataset.uid;
        if (action === 'loot-done') {
          _admConfirm('Mark Route Done', 'Mark this assignment complete? Points calculated from assignment time.', function () {
            _admPost('loot/done', { user_id: uid, assignment_id: btn.dataset.aid }).then(function (r) {
              if (r.ok) { _admToast('Route done — ' + r.points + ' pts awarded'); _admRenderLoot(el); }
              else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'loot-away') {
          _admPrompt('Set Away', [{ key: 'return_date', label: 'Return Date (optional)', placeholder: 'YYYY-MM-DD' }], function (data) {
            _admPost('loot/set_away', { user_id: uid, return_date: data.return_date || null }).then(function (r) {
              if (r.ok) { _admToast('Maker set to Away'); _admRenderLoot(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'loot-back') {
          _admPost('loot/remove_away', { user_id: uid }).then(function (r) {
            if (r.ok) { _admToast('Away status removed'); _admRenderLoot(el); } else _admToast(r.error || 'Failed', true);
          });
        } else if (action === 'loot-remove') {
          _admConfirm('Remove Maker', 'Remove <strong>' + btn.dataset.name + '</strong> from the loot rotation?', function () {
            _admPost('loot/remove_maker', { user_id: uid }).then(function (r) {
              if (r.ok) { _admToast('Maker removed'); _admRenderLoot(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        }
      });
    }).catch(function () { el.innerHTML = '<div class="wn-adm-err">Failed to load loot data.</div>'; });
  }

  /* ── Admin: Surge Routes ──────────────────────────────────────────────── */
  function _admRenderSurge(el) {
    el.innerHTML = '<div class="wn-adm-loading">Loading rotation&#x2026;</div>';
    _admGet('surge/data').then(function (d) {
      if (d.error) { el.innerHTML = '<div class="wn-adm-err">' + esc(d.error) + '</div>'; return; }
      var rows = (d.makers || []).map(function (m) {
        var statusBadge;
        if (m.is_away) {
          statusBadge = m.away_return
            ? '<span class="wn-adm-badge wn-adm-badge-away">Away</span>'
            : '<span class="wn-adm-badge wn-adm-badge-away">Perm</span>';
        } else {
          statusBadge = m.assignment ? '<span class="wn-adm-badge wn-adm-badge-active">Active</span>' : '<span class="wn-adm-badge wn-adm-badge-free">Free</span>';
        }
        var assignInfo = m.assignment ? '<div class="wn-adm-sub">Assigned ' + esc(m.assignment.assigned_ago) + ' ago</div>' : '';
        var awayInfo = m.is_away && m.away_return ? '<div class="wn-adm-sub">Returns: ' + esc(m.away_return) + '</div>' : '';
        var doneBtn = m.assignment ? '<button class="wn-adm-btn wn-adm-btn-success wn-adm-btn-sm" data-action="surge-done" data-uid="' + m.user_id + '" data-aid="' + m.assignment.assignment_id + '">&#x2713; Mark Done</button>' : '';
        var awayBtn = !m.is_away
          ? '<button class="wn-adm-btn wn-adm-btn-warning wn-adm-btn-sm" data-action="surge-away" data-uid="' + m.user_id + '">Set Away</button>'
          : '<button class="wn-adm-btn wn-adm-btn-ghost wn-adm-btn-sm" data-action="surge-back" data-uid="' + m.user_id + '">Mark Back</button>';
        var removeBtn = '<button class="wn-adm-btn wn-adm-btn-danger wn-adm-btn-sm" data-action="surge-remove" data-uid="' + m.user_id + '" data-name="' + esc(m.display_name || m.user_id) + '">Remove</button>';
        return '<div class="wn-adm-card">' +
          '<div class="wn-adm-card-row">' +
            '<div class="wn-adm-card-info" data-profile-uid="' + esc(m.user_id) + '">' +
              '<div class="wn-adm-card-rank">#' + (m.rotation_rank || '?') + '</div>' +
              (m.avatar_url
                ? '<div class="wn-adm-card-av"><img src="' + esc(m.avatar_url) + '" alt="" onerror="this.parentNode.innerHTML=\'&#x1F464;\';this.remove()"></div>'
                : '<div class="wn-adm-card-av wn-adm-card-av-ph">&#x1F464;</div>') +
              '<div style="min-width:0;"><div class="wn-adm-card-name">' + esc(m.display_name || ('User ' + m.user_id)) + '</div>' +
              '<div class="wn-adm-card-id">' + esc(m.user_id) + '</div>' +
              '<div class="wn-adm-card-pts">' + (m.total_points || 0) + ' pts</div>' + assignInfo + awayInfo + '</div>' +
            '</div>' +
            '<div class="wn-adm-card-badges">' + statusBadge + '</div>' +
          '</div>' +
          '<div class="wn-adm-card-actions">' + doneBtn + ' ' + awayBtn + ' ' + removeBtn + '</div>' +
        '</div>';
      }).join('') || '<div class="wn-adm-empty">No makers in rotation.</div>';
      el.innerHTML = '<div class="wn-adm-section-title">Surge Route Makers (' + (d.makers || []).length + ')</div>' + rows;
      el.addEventListener('click', function (e) {
        if (_admTryProfileNav(e)) return;
        var btn = e.target.closest('[data-action]'); if (!btn) return;
        var action = btn.dataset.action, uid = btn.dataset.uid;
        if (action === 'surge-done') {
          _admConfirm('Mark Route Done', 'Mark this surge assignment complete?', function () {
            _admPost('surge/done', { user_id: uid, assignment_id: btn.dataset.aid }).then(function (r) {
              if (r.ok) { _admToast('Route done — ' + r.points + ' pts awarded'); _admRenderSurge(el); }
              else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'surge-away') {
          _admPrompt('Set Away', [{ key: 'return_date', label: 'Return Date (optional)', placeholder: 'YYYY-MM-DD' }], function (data) {
            _admPost('surge/set_away', { user_id: uid, return_date: data.return_date || null }).then(function (r) {
              if (r.ok) { _admToast('Maker set to Away'); _admRenderSurge(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'surge-back') {
          _admPost('surge/remove_away', { user_id: uid }).then(function (r) {
            if (r.ok) { _admToast('Away status removed'); _admRenderSurge(el); } else _admToast(r.error || 'Failed', true);
          });
        } else if (action === 'surge-remove') {
          _admConfirm('Remove Maker', 'Remove <strong>' + btn.dataset.name + '</strong> from the surge rotation?', function () {
            _admPost('surge/remove_maker', { user_id: uid }).then(function (r) {
              if (r.ok) { _admToast('Maker removed'); _admRenderSurge(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        }
      });
    }).catch(function () { el.innerHTML = '<div class="wn-adm-err">Failed to load surge data.</div>'; });
  }

  /* ── Admin: Tips & Tricks ─────────────────────────────────────────────── */
  function _admRenderTT(el) {
    el.innerHTML = '<div class="wn-adm-loading">Loading tasks&#x2026;</div>';
    _admGet('tt/data').then(function (d) {
      if (d.error) { el.innerHTML = '<div class="wn-adm-err">' + esc(d.error) + '</div>'; return; }
      var taskRows = (d.tasks || []).map(function (t) {
        var label = (t.title || t.description || ('Task #' + t.task_id)).split('\n')[0].slice(0, 80);
        var claimBadge = t.claimed_by
          ? '<span class="wn-adm-badge wn-adm-badge-active">Claimed</span>'
          : '<span class="wn-adm-badge wn-adm-badge-free">Open</span>';
        var claimInfo = t.claimed_by ? '<div class="wn-adm-sub">Claimed by: ' + esc(t.claimed_by_name || t.claimed_by) + '</div>' : '';
        return '<div class="wn-adm-card">' +
          '<div class="wn-adm-card-row">' +
            '<div class="wn-adm-card-info" style="flex:1;">' +
              '<div><div class="wn-adm-card-name">#' + esc(t.task_id) + ' — ' + esc(label) + '</div>' +
              '<div class="wn-adm-sub">' + esc(t.description || '') + '</div>' + claimInfo + '</div>' +
            '</div>' +
            '<div class="wn-adm-card-badges">' + claimBadge + '</div>' +
          '</div>' +
          '<div class="wn-adm-card-actions">' +
            '<button type="button" class="wn-adm-btn wn-adm-btn-success wn-adm-btn-sm" data-action="tt-complete" data-tid="' + t.task_id + '" data-ttitle="' + esc(label) + '">&#x2713; Complete</button>' +
            '<button type="button" class="wn-adm-btn wn-adm-btn-danger wn-adm-btn-sm" data-action="tt-cancel" data-tid="' + t.task_id + '" data-ttitle="' + esc(label) + '">&#x2717; Cancel</button>' +
          '</div>' +
        '</div>';
      }).join('') || '<div class="wn-adm-empty">No open tasks.</div>';

      var dutyRows = (d.duties || []).map(function (a) {
        return '<div class="wn-adm-card" style="padding:10px 14px;">' +
          '<div class="wn-adm-card-row">' +
            '<div class="wn-adm-card-info" style="flex:1;" data-profile-uid="' + esc(a.user_id) + '">' +
              (a.avatar_url
                ? '<div class="wn-adm-card-av"><img src="' + esc(a.avatar_url) + '" alt="" onerror="this.parentNode.innerHTML=\'&#x1F464;\';this.remove()"></div>'
                : '<div class="wn-adm-card-av wn-adm-card-av-ph">&#x1F464;</div>') +
              '<div style="min-width:0;"><div class="wn-adm-card-name">' + esc(a.display_name || ('User ' + a.user_id)) + '</div>' +
              '<div class="wn-adm-sub">Code: <strong>' + esc(a.code) + '</strong></div></div>' +
            '</div>' +
            '<button class="wn-adm-btn wn-adm-btn-danger wn-adm-btn-sm" data-action="tt-rmduty" data-uid="' + a.user_id + '" data-code="' + esc(a.code) + '">Remove</button>' +
          '</div>' +
        '</div>';
      }).join('') || '<div class="wn-adm-empty">No active assignments.</div>';

      el.innerHTML =
        '<div class="wn-adm-section-title">Open Tasks</div>' + taskRows +
        '<div class="wn-adm-actions-bar"><button class="wn-adm-btn wn-adm-btn-primary" id="_tt-new-task">+ New Task</button><button class="wn-adm-btn wn-adm-btn-primary" id="_tt-new-super-task">+ Super Task</button></div>' +
        '<div class="wn-adm-section-title" style="margin-top:20px;">Duty Assignments</div>' + dutyRows +
        '<div class="wn-adm-actions-bar"><button class="wn-adm-btn wn-adm-btn-primary" id="_tt-assign-duty">+ Assign Duty</button></div>';

      el.querySelector('#_tt-new-task').onclick = function () {
        _admPrompt('Create Task (paste Discord message format)', [
          { key: 'raw', label: 'Message Content', type: 'textarea', required: true, placeholder: 'Paste the task message here…' }
        ], function (data) {
          _admPost('tt/create_task', { raw: data.raw }).then(function (r) {
            if (r.ok) { _admToast('Task created'); _admRenderTT(el); } else _admToast(r.error || 'Failed', true);
          });
        });
      };
      el.querySelector('#_tt-new-super-task').onclick = function () {
        _admSuperTaskForm(el);
      };
      el.querySelector('#_tt-assign-duty').onclick = function () {
        var dutyOpts = (d.duty_codes || []).map(function (c) {
          return { value: c.code, label: c.code + ' — ' + c.name };
        });
        var helperOpts = (d.helpers || []).map(function (h) {
          return { value: h.user_id, label: h.display_name + ' (' + h.user_id + ')' };
        });
        if (!helperOpts.length) { _admToast('No Tips & Tricks Helpers found in the guild', true); return; }
        _admPrompt('Assign Duty', [
          { key: 'code', label: 'Duty', type: 'select', required: true, placeholder: 'Select a duty…', options: dutyOpts },
          { key: 'user_id', label: 'Tips & Tricks Helper', type: 'select', required: true, placeholder: 'Select a helper…', options: helperOpts }
        ], function (data) {
          _admPost('tt/assign_duty', { user_id: data.user_id, code: data.code }).then(function (r) {
            if (r.ok) { _admToast('Duty assigned'); _admRenderTT(el); } else _admToast(r.error || 'Failed', true);
          });
        });
      };
      _admBindClick(el, 'tt', function (e) {
        if (_admTryProfileNav(e)) return;
        var btn = _admActionBtn(e); if (!btn) return;
        var action = btn.dataset.action;
        var taskId = parseInt(btn.dataset.tid, 10);
        if (action === 'tt-complete') {
          if (!taskId) { _admToast('Invalid task — refresh and try again', true); return; }
          _admPrompt('Force Complete Task', [
            { key: 'user_id', label: 'Award to Discord User ID', required: true, placeholder: '123456789012345678' }
          ], function (data) {
            _admPost('tt/complete_task', { task_id: taskId, user_id: data.user_id }).then(function (r) {
              if (r.ok) { _admToast('Task completed and awarded'); _admRenderTT(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'tt-cancel') {
          if (!taskId) { _admToast('Invalid task — refresh and try again', true); return; }
          _admConfirm('Cancel Task', 'Remove task <strong>#' + taskId + '</strong> (' + esc(btn.dataset.ttitle || '') + ')? This cannot be undone.', function () {
            _admPost('tt/cancel_task', { task_id: taskId }).then(function (r) {
              if (r.ok) { _admToast('Task removed'); _admRenderTT(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'tt-rmduty') {
          _admConfirm('Remove Duty', 'Remove duty <strong>' + btn.dataset.code + '</strong>?', function () {
            _admPost('tt/remove_duty', { code: btn.dataset.code, user_id: btn.dataset.uid }).then(function (r) {
              if (r.ok) { _admToast('Duty removed'); _admRenderTT(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        }
      });
    }).catch(function () { el.innerHTML = '<div class="wn-adm-err">Failed to load tips &amp; tricks data.</div>'; });
  }

  function _admRenderStaff(el) {
    var globalAddBtnHtml =
      '<div class="wn-adm-actions-bar" style="margin-bottom:20px; margin-top:20px; justify-content: flex-start; gap: 12px; flex-wrap: wrap;">' +
        '<button class="wn-premium-btn-top" id="_staff-premium-add"><span>✨</span> Add a staff member to duty</button>' +
        '<button class="wn-premium-btn-top" id="_staff-premium-train"><span>✨</span> Train a User</button>' +
        '<button class="wn-premium-btn-top" id="_staff-premium-promote"><span>⬆️</span> Promote a User</button>' +
        '<button class="wn-premium-btn-top" id="_staff-premium-away"><span>⏸️</span> Set User Away</button>' +
      '</div>';

    function attachModal() {
      var addBtn = el.querySelector('#_staff-premium-add');
      if (addBtn) {
        addBtn.addEventListener('click', function() {
          _admPremiumDutyModal(function(data) {
            _admPost('staff/assign', data).then(function (r) {
              if (r.ok) { _admToast('Action successful!'); _admRenderStaff(el); } 
              else _admToast(r.error || 'Request sent (backend not wired).', false);
            }).catch(function() {
              _admToast('Action submitted (backend API requires wiring).', false);
            });
          });
        });
      }
      var trainBtn = el.querySelector('#_staff-premium-train');
      if (trainBtn) {
        trainBtn.addEventListener('click', function() {
          _admPremiumTrainModal(function(data) {
            _admPost('staff/train', data).then(function (r) {
              if (r.ok) { _admToast('Action successful!'); _admRenderStaff(el); }
              else _admToast(r.error || 'Request sent (backend not wired).', false);
            }).catch(function() {
              _admToast('Action submitted (backend API requires wiring).', false);
            });
          });
        });
      }
      var promoteBtn = el.querySelector('#_staff-premium-promote');
      if (promoteBtn) {
        promoteBtn.addEventListener('click', function() {
          _admPromoteModal(function(data) {
            _admPost('staff/promote', data).then(function (r) {
              if (r.ok) {
                var results = r.results || {};
                var lines = Object.entries(results).map(function(kv){ return kv[0] + ': ' + kv[1]; }).join('\n');
                _admToast('Promoted! ' + lines);
                _admRenderStaff(el);
              } else {
                _admToast(r.error || 'Promotion failed', true);
              }
            }).catch(function() {
              _admToast('Network error during promotion', true);
            });
          });
        });
      }
      var awayBtn = el.querySelector('#_staff-premium-away');
      if (awayBtn) {
        awayBtn.addEventListener('click', function() {
          _admAwayModal(function(data) {
            _admPost('staff/set_away', data).then(function (r) {
              if (r.ok) { _admToast('Staff set to Away'); _admRenderStaff(el); }
              else _admToast(r.error || 'Failed', true);
            }).catch(function() {
              _admToast('Network error setting away', true);
            });
          });
        });
      }
    }

    el.innerHTML = '<div class="wn-adm-section-title">Head of Staff Management</div><div class="wn-adm-loading">Loading staff&#x2026;</div>';

    _admGet('staff/data').then(function (d) {
      fetch('/api/duty_needs').then(res => res.json()).then(fetchedDutyData => {
        var dutyData = fetchedDutyData;
        if (!dutyData || dutyData.error || !dutyData.length) {
          dutyData = [
            { id: "surge-route-maker", name: "Surge Route Maker", description: "Makes surge routes for wave", difficulty: "", status: 1 },
            { id: "loot-route-maker", name: "Loot Route Maker", description: "Makes loot routes for wave", difficulty: "Easy", status: 0 },
            { id: "tips-tricks-helper", name: "Tips and Tricks Helper", description: "Adds tips & tricks in improvement for fn", difficulty: "Medium", status: 0 },
            { id: "map-request-helper", name: "Map Request Helper", description: "Helps members find the maps", difficulty: "Medium", status: 1 },
            { id: "promoters", name: "Promoters", description: "Makes vfx or gfx or gets partnerships", difficulty: "Pre-existing skill set needed", status: 0 }
          ];
        }

        var dutyHtml = dutyData.map(function(item) {
          var diffClass = item.difficulty ? item.difficulty.split(' ')[0].toLowerCase() : 'easy';
          var diffHtml = item.difficulty ? '<span class="diff-tag diff-' + diffClass + '">' + esc(item.difficulty) + '</span>' : '';
          return '<div class="duty-matrix-row" data-state="' + item.status + '" id="dmr-' + item.id + '">' +
            '<div class="matrix-info">' +
              '<div class="matrix-title">@' + esc(item.name) + ' ' + diffHtml + '</div>' +
              '<div class="matrix-desc">' + esc(item.description) + '</div>' +
            '</div>' +
            '<div class="sync-track-wrap">' +
              '<div class="sync-track-labels">' +
                '<span class="sync-label ' + (item.status === 0 ? 'active-label' : '') + '" id="lbl-' + item.id + '-0" style="opacity:' + (item.status === 0 ? '1' : '0.3') + ';">Disabled</span>' +
                '<span class="sync-label ' + (item.status === 1 ? 'active-label' : '') + '" id="lbl-' + item.id + '-1" style="opacity:' + (item.status === 1 ? '1' : '0.3') + ';">Open</span>' +
                '<span class="sync-label ' + (item.status === 2 ? 'active-label' : '') + '" id="lbl-' + item.id + '-2" style="opacity:' + (item.status === 2 ? '1' : '0.3') + ';">Almost Full</span>' +
                '<span class="sync-label ' + (item.status === 3 ? 'active-label' : '') + '" id="lbl-' + item.id + '-3" style="opacity:' + (item.status === 3 ? '1' : '0.3') + ';">Closed</span>' +
              '</div>' +
              '<input type="range" class="sync-slider" data-id="' + item.id + '" min="0" max="3" value="' + item.status + '">' +
            '</div>' +
          '</div>';
        }).join('');

        var dutyPanelHtml = '<div class="duty-matrix-panel">' + 
                            dutyHtml + 
                            '<button class="wn-adm-btn wn-adm-btn-primary" id="save-duties-btn" style="margin-top:20px; width:100%; border-radius:12px; padding:12px; font-weight:700;">Save Duty Configuration</button>' +
                            '</div>';

        function attachDutyEvents() {
          el.querySelectorAll('.sync-slider').forEach(function(slider) {
            slider.addEventListener('input', function(e) {
              var val = parseInt(e.target.value, 10);
              var id = e.target.dataset.id;
              var row = el.querySelector('#dmr-' + id);
              if(row) {
                row.setAttribute('data-state', val);
                for(var i=0; i<=3; i++) {
                  var lbl = el.querySelector('#lbl-' + id + '-' + i);
                  if(lbl) {
                    if (i === val) { lbl.style.opacity = '1'; lbl.classList.add('active-label'); }
                    else { lbl.style.opacity = '0.3'; lbl.classList.remove('active-label'); }
                  }
                }
              }
            });
          });
          
          var saveBtn = el.querySelector('#save-duties-btn');
          if(saveBtn) {
            saveBtn.addEventListener('click', function() {
              var payload = [];
              el.querySelectorAll('.sync-slider').forEach(function(slider) {
                var origItem = dutyData.find(function(x){ return x.id === slider.dataset.id; });
                var copy = Object.assign({}, origItem);
                copy.status = parseInt(slider.value, 10);
                payload.push(copy);
              });
              _admPost('duty_needs', payload).then(function(r) {
                if (r.ok) _admToast('Duties successfully synchronized!');
                else _admToast('Failed to save', true);
              }).catch(function() {
                _admToast('Network error saving duties', true);
              });
            });
          }
        }

        if (d.error) { 
          el.innerHTML = '<div class="wn-adm-section-title">Head of Staff Management</div>' + dutyPanelHtml + '<div class="wn-adm-err">' + esc(d.error) + '</div>' + globalAddBtnHtml; 
          attachModal();
          attachDutyEvents();
          return; 
        }
        var rows = (d.staff || []).map(function (m) {
        var statusBadge;
        if (m.is_away) {
          statusBadge = m.away_return
            ? '<span class="wn-adm-badge wn-adm-badge-away">Away</span>'
            : '<span class="wn-adm-badge wn-adm-badge-away">Perm</span>';
        } else {
          statusBadge = '<span class="wn-adm-badge wn-adm-badge-free">Active</span>';
        }
        var awayInfo = m.is_away && m.away_return ? '<div class="wn-adm-sub">Returns: ' + esc(m.away_return) + '</div>' : '';
        var roleInfo = m.role_name ? '<div class="wn-adm-card-pts">' + esc(m.role_name) + '</div>' : '';
        var awayBtn = !m.is_away
          ? '<button class="wn-adm-btn wn-adm-btn-warning wn-adm-btn-sm" data-action="staff-away" data-uid="' + m.user_id + '" data-name="' + esc(m.display_name || m.user_id) + '">Set Away</button>'
          : '<button class="wn-adm-btn wn-adm-btn-ghost wn-adm-btn-sm" data-action="staff-back" data-uid="' + m.user_id + '">Mark Back</button>';
        var addDutyBtn  = '<button class="wn-adm-btn wn-adm-btn-primary wn-adm-btn-sm" data-action="staff-add-duty" data-uid="' + m.user_id + '">Add Duty</button>';
        var trainBtn    = '<button class="wn-adm-btn wn-adm-btn-ghost wn-adm-btn-sm" data-action="staff-train" data-uid="' + m.user_id + '">Train</button>';
        var promoteBtn  = '<button class="wn-adm-btn wn-adm-btn-success wn-adm-btn-sm" data-action="staff-promote" data-uid="' + m.user_id + '" data-name="' + esc(m.display_name || m.user_id) + '">Promote</button>';

        return '<div class="wn-adm-card">' +
          '<div class="wn-adm-card-row">' +
            '<div class="wn-adm-card-info" data-profile-uid="' + esc(m.user_id) + '">' +
              (m.avatar_url
                ? '<div class="wn-adm-card-av"><img src="' + esc(m.avatar_url) + '" alt="" onerror="this.parentNode.innerHTML=\'&#x1F464;\';this.remove()"></div>'
                : '<div class="wn-adm-card-av wn-adm-card-av-ph">&#x1F464;</div>') +
              '<div style="min-width:0;"><div class="wn-adm-card-name">' + esc(m.display_name || ('User ' + m.user_id)) + '</div>' +
              '<div class="wn-adm-card-id">' + esc(m.user_id) + '</div>' + roleInfo + awayInfo + '</div>' +
            '</div>' +
            '<div class="wn-adm-card-badges">' + statusBadge + '</div>' +
          '</div>' +
          '<div class="wn-adm-card-actions" style="gap:8px;">' + addDutyBtn + trainBtn + promoteBtn + awayBtn + '</div>' +
        '</div>';
      }).join('') || '<div class="wn-adm-empty">No general staff found.</div>';

      // Build away status section
      var awayUsers = (d.staff || []).filter(function (m) { return m.is_away; });

      function _buildStatusUsersHtml(users, subLabelFn, emptyText) {
        return users.length > 0
          ? users.map(function (m) {
              return '<div class="wn-status-user" data-profile-uid="' + esc(m.user_id) + '">' +
                (m.avatar_url
                  ? '<div class="wn-status-user-av"><img src="' + esc(m.avatar_url) + '" alt=""></div>'
                  : '<div class="wn-status-user-av wn-status-user-av-ph">&#x1F464;</div>') +
                '<div class="wn-status-user-info">' +
                  '<div class="wn-status-user-name">' + esc(m.display_name || ('User ' + m.user_id)) + '</div>' +
                  (subLabelFn(m) ? '<div class="wn-status-user-sub">' + subLabelFn(m) + '</div>' : '') +
                '</div>' +
              '</div>';
            }).join('')
          : '<div class="wn-status-empty">' + emptyText + '</div>';
      }

      var awayUsersHtml = _buildStatusUsersHtml(
        awayUsers,
        function (m) { return m.away_return ? 'Back: ' + esc(m.away_return) : ''; },
        'No users away'
      );

      var statusSectionHtml = awayUsers.length > 0
        ? '<div class="wn-status-section">' +
            '<div class="wn-status-grid">' +
              '<div class="wn-status-card">' +
                '<div class="wn-status-card-title"><div class="wn-status-circle wn-status-circle-away"></div>ON AWAY</div>' +
                '<div class="wn-status-users">' + awayUsersHtml + '</div>' +
              '</div>' +
            '</div>' +
          '</div>'
        : '';

        el.innerHTML = '<div class="wn-adm-section-title">Duty Configuration</div>' +
                       dutyPanelHtml +
                       statusSectionHtml +
                       '<div class="wn-adm-section-title" style="margin-top:32px;">General Staff (' + (d.staff || []).length + ')</div>' +
                       rows + globalAddBtnHtml;
        attachModal();
        attachDutyEvents();

      el.addEventListener('click', function (e) {
        if (_admTryProfileNav(e)) return;
        var btn = e.target.closest('[data-action]'); if (!btn) return;
        var action = btn.dataset.action, uid = btn.dataset.uid;
        if (action === 'staff-add-duty') {
          var m = _admPremiumDutyModal(function(data) {
            _admPost('staff/assign', data).then(function (r) {
              if (r.ok) { _admToast('Action successful!'); _admRenderStaff(el); } 
              else _admToast(r.error || 'Request sent (backend not wired).', false);
            }).catch(function() {
              _admToast('Action submitted (backend API requires wiring).', false);
            });
          });
          m.setUid(uid);
        }
        if (action === 'staff-train') {
          var tm = _admPremiumTrainModal(function(data) {
            _admPost('staff/train', data).then(function (r) {
              if (r.ok) { _admToast('Training sent!'); _admRenderStaff(el); }
              else _admToast(r.error || 'Failed', true);
            });
          });
          tm.setUid(uid);
        }
        if (action === 'staff-promote') {
          _admConfirm('Promote ' + (btn.dataset.name || uid), 'Promote this user to the next role in the ladder across all guilds?', function () {
            _admPost('staff/promote', { user_id: uid }).then(function (r) {
              if (r.ok) {
                var lines = Object.entries(r.results || {}).map(function(kv){ return '• ' + kv[0] + ': ' + kv[1]; }).join('\n');
                _admToast('Promoted!\n' + lines);
                _admRenderStaff(el);
              } else {
                _admToast(r.error || 'Promotion failed', true);
              }
            });
          });
        }
        if (action === 'staff-away') {
          _admPrompt('Set Away — ' + (btn.dataset.name || ''), [
            { key: 'return_date', label: 'Return Date (optional)', placeholder: 'YYYY-MM-DD' }
          ], function (data) {
            _admPost('staff/set_away', { user_id: uid, return_date: data.return_date || null }).then(function (r) {
              if (r.ok) { _admToast('Staff set to Away'); _admRenderStaff(el); } else _admToast(r.error || 'Failed', true);
            });
          });
        } else if (action === 'staff-back') {
          _admPost('staff/remove_away', { user_id: uid }).then(function (r) {
            if (r.ok) { _admToast('Away status removed'); _admRenderStaff(el); } else _admToast(r.error || 'Failed', true);
          });
        }
      }); // closes el.addEventListener
      }).catch(function() { // closes fetch().then()
        el.innerHTML = '<div class="wn-adm-err">Failed to fetch duty settings</div>';
      }); // closes .catch()
    }).catch(function () { el.innerHTML = '<div class="wn-adm-err">Failed to load staff data.</div>'; });
  }

  /* ── Admin: Tab switcher + main render ────────────────────────────────── */
  function _admLoadTab(tab, tabBar, content) {
    var roles = (currentUser && currentUser.roles) || [];
    if (!_canSeeAdminTab(tab, roles)) {
      content.innerHTML = '<div class="wn-adm-err">Access denied for this section.</div>';
      return;
    }
    tabBar.querySelectorAll('.wn-adm-tab').forEach(function (t) {
      t.classList.toggle('wn-adm-tab-active', t.dataset.tab === tab);
    });
    content.innerHTML = '';
    if (tab === 'loot')  _admRenderLoot(content);
    if (tab === 'surge') _admRenderSurge(content);
    if (tab === 'tt')    _admRenderTT(content);
    if (tab === 'staff') _admRenderStaff(content);
  }

  function renderAdmin(body) {
    var roles = (currentUser && currentUser.roles) || [];
    var tabs = [];
    if (_canSeeLoot(roles))  tabs.push({ key: 'loot',  label: '&#x1F5FA;&#xFE0F; Loot Routes' });
    if (_canSeeSurge(roles)) tabs.push({ key: 'surge', label: '&#x26A1; Surge Routes' });
    if (_canSeeTT(roles))    tabs.push({ key: 'tt',    label: '&#x1F4A1; Tips &amp; Tricks' });
    if (_canSeeStaff(roles)) tabs.push({ key: 'staff', label: '&#x1F465; Head of Staff' });
    
    if (!tabs.length) {
      body.innerHTML = '<div style="padding:32px 20px;text-align:center;color:rgba(205,217,232,0.5);font-family:\'JetBrains Mono\',monospace;font-size:12px;">No admin sections available for your roles.</div>';
      return;
    }
    var tabHtml = tabs.map(function (t) {
      return '<button class="wn-adm-tab" data-tab="' + t.key + '">' + t.label + '</button>';
    }).join('');
    body.innerHTML =
      '<div class="wn-adm-tabbar" id="_adm-tabbar">' + tabHtml + '</div>' +
      '<div class="wn-adm-content" id="_adm-content"></div>';
    var tabBar = body.querySelector('#_adm-tabbar');
    var content = body.querySelector('#_adm-content');
    tabBar.addEventListener('click', function (e) {
      var t = e.target.closest('.wn-adm-tab');
      if (t) _admLoadTab(t.dataset.tab, tabBar, content);
    });
    _admLoadTab(tabs[0].key, tabBar, content);
  }

  /* ── Boot ─────────────────────────────────────────────────────────────── */
  fetchUser().then(function() {
    if (window.location.pathname.endsWith('admin.html')) {
      var adminRoot = document.getElementById('admin-root');
      if (adminRoot) {
        if (!_hasAnyAdminRole((currentUser && currentUser.roles) || [])) {
          adminRoot.innerHTML = '<div style="padding:40px; text-align:center; color:rgba(255,255,255,0.5);">Access Denied</div>';
          return;
        }
        renderAdmin(adminRoot);
      }
    }
  });
})();
