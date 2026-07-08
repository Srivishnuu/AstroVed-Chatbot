(function () {
  if (window.__astrovedWidgetLoaded) return;
  window.__astrovedWidgetLoaded = true;

  /* ── Inject Google Fonts ── */
  var fontLink = document.createElement('link');
  fontLink.rel = 'stylesheet';
  fontLink.href = 'https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=DM+Sans:wght@300;400;500&display=swap';
  document.head.appendChild(fontLink);

  /* ── Inject CSS ── */
  var style = document.createElement('style');
  style.textContent = `
    #av-widget-root *,#av-widget-root *::before,#av-widget-root *::after{box-sizing:border-box;margin:0;padding:0}
    #av-widget-root{
      --gold:#C9A84C;--gold-l:#E8C97A;--gold-glow:rgba(201,168,76,.2);
      --deep:#0A0818;--panel:#12102A;--surface:#1A1735;
      --border:rgba(201,168,76,.18);--border2:rgba(201,168,76,.4);
      --text:#EDE8D8;--muted:rgba(237,232,216,.5);
      --purple:#6C5CE7;--purple2:#4A3580;
      --green:#22c55e;--red:#ef4444;--blue:#3b82f6;
      --font-h:'Cinzel',serif;--font-b:'DM Sans',sans-serif;
    }
    /* WIN */
    #av-win{
      position:fixed;bottom:96px;right:26px;width:390px;max-height:660px;
      background:#12102A;border:1px solid rgba(201,168,76,.18);border-radius:20px;
      display:flex;flex-direction:column;overflow:hidden;
      box-shadow:0 28px 72px rgba(0,0,0,.75),0 0 0 1px rgba(108,92,231,.15);
      z-index:2147483646;transform-origin:bottom right;
      transform:scale(.85) translateY(20px);opacity:0;pointer-events:none;
      transition:transform .3s cubic-bezier(.34,1.56,.64,1),opacity .22s;
      font-family:'DM Sans',sans-serif;
    }
    #av-win.av-open{transform:scale(1) translateY(0);opacity:1;pointer-events:all}
    /* HDR */
    .av-hdr{background:linear-gradient(135deg,#1a1540,#0e0c22);padding:12px 14px;
      display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(201,168,76,.18);
      position:relative;flex-shrink:0}
    .av-hdr::after{content:'';position:absolute;bottom:0;left:0;right:0;height:1px;
      background:linear-gradient(90deg,transparent,rgba(108,92,231,.5),transparent)}
    .av-logo-img{width:38px;height:38px;border-radius:50%;border:1.5px solid #C9A84C;
      object-fit:cover;flex-shrink:0;box-shadow:0 0 12px rgba(201,168,76,.2)}
    .av-hinfo{flex:1}
    .av-hname{font-family:'Cinzel',serif;font-size:14px;font-weight:600;color:#E8C97A;letter-spacing:.05em}
    .av-hsub{font-size:10px;color:rgba(237,232,216,.5);margin-top:2px;display:flex;align-items:center;gap:4px}
    .av-odot{width:5px;height:5px;background:#22c55e;border-radius:50%;animation:av-blink 2s infinite}
    @keyframes av-blink{0%,100%{opacity:1}50%{opacity:.3}}
    .av-hbtns{display:flex;gap:6px;align-items:center}
    .av-hbtn{width:32px;height:32px;border-radius:8px;cursor:pointer;display:flex;align-items:center;
      justify-content:center;transition:all .2s;position:relative;flex-shrink:0;border:1.5px solid}
    .av-hbtn svg{width:15px;height:15px;fill:currentColor;pointer-events:none}
    .av-crm-btn{background:rgba(59,130,246,.2);border-color:rgba(59,130,246,.6);color:#93c5fd}
    .av-crm-btn:hover{background:rgba(59,130,246,.4);border-color:#3b82f6;color:#fff}
    .av-end-btn{background:rgba(239,68,68,.2);border-color:rgba(239,68,68,.6);color:#fca5a5}
    .av-end-btn:hover{background:rgba(239,68,68,.4);border-color:#ef4444;color:#fff}
    .av-min-btn{background:rgba(108,92,231,.2);border-color:rgba(108,92,231,.6);color:#c4b8ff}
    .av-min-btn:hover{background:rgba(108,92,231,.4);border-color:#6c5ce7;color:#fff}
    .av-tip{position:absolute;bottom:-36px;left:50%;transform:translateX(-50%);
      background:rgba(26,23,53,.98);border:1px solid #C9A84C;border-radius:6px;
      padding:5px 11px;font-size:11px;font-weight:600;color:#E8C97A;
      white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .18s;z-index:9999}
    .av-hbtn:hover .av-tip{opacity:1}
    /* SCREENS */
    .av-scr{flex:1;overflow:hidden;display:flex;flex-direction:column;min-height:0}
    /* FORM */
    #av-fs{padding:20px;display:flex;flex-direction:column;overflow-y:auto}
    .av-fhero{text-align:center;margin-bottom:18px}
    .av-fhero-logo{width:60px;height:60px;border-radius:50%;margin:0 auto 10px;display:block;
      border:2px solid #C9A84C;box-shadow:0 0 20px rgba(201,168,76,.2);
      animation:av-logoglow 3s ease-in-out infinite}
    @keyframes av-logoglow{0%,100%{box-shadow:0 0 10px rgba(201,168,76,.2)}50%{box-shadow:0 0 28px rgba(201,168,76,.6)}}
    .av-fhero h2{font-family:'Cinzel',serif;font-size:15px;color:#E8C97A;letter-spacing:.06em;margin-bottom:5px}
    .av-fhero p{font-size:12px;color:rgba(237,232,216,.5);line-height:1.6}
    .av-fg{margin-bottom:12px}
    .av-fg label{display:block;font-size:10px;font-weight:500;color:#C9A84C;
      letter-spacing:.09em;text-transform:uppercase;margin-bottom:5px}
    .av-fg input,.av-fg select{width:100%;background:rgba(255,255,255,.05);
      border:1px solid rgba(201,168,76,.18);border-radius:9px;padding:10px 12px;
      font-family:'DM Sans',sans-serif;font-size:13px;color:#EDE8D8;outline:none;
      transition:border-color .2s,box-shadow .2s;-webkit-appearance:none;appearance:none}
    .av-fg input::placeholder{color:rgba(237,232,216,.28)}
    .av-fg input:focus,.av-fg select:focus{border-color:#C9A84C;box-shadow:0 0 0 3px rgba(201,168,76,.2)}
    .av-fg select option{background:#1a1735;color:#EDE8D8}
    .av-phone-row{display:flex;gap:8px}
    .av-phone-row .av-cc{width:130px;flex-shrink:0;font-size:12px}
    .av-phone-row input{flex:1}
    .av-sbtn{width:100%;background:linear-gradient(135deg,#6C5CE7,#C9A84C);
      border:none;border-radius:10px;padding:11px;font-family:'Cinzel',serif;
      font-size:13px;font-weight:600;letter-spacing:.07em;color:#fff;cursor:pointer;
      margin-top:4px;transition:opacity .2s,transform .15s;box-shadow:0 4px 20px rgba(108,92,231,.4)}
    .av-sbtn:hover{opacity:.9;transform:translateY(-1px)}
    .av-sbtn:disabled{opacity:.6;cursor:not-allowed;transform:none}
    .av-prv{text-align:center;font-size:11px;color:rgba(237,232,216,.5);margin-top:10px}
    /* CHAT */
    #av-cs{display:none;flex-direction:column;flex:1;overflow:hidden;min-height:0}
    #av-cs.av-active{display:flex}
    #av-msgs{flex:1;overflow-y:auto;padding:12px 12px 6px;display:flex;flex-direction:column;gap:8px;
      scrollbar-width:thin;scrollbar-color:rgba(201,168,76,.18) transparent;min-height:0}
    #av-msgs::-webkit-scrollbar{width:3px}
    #av-msgs::-webkit-scrollbar-thumb{background:rgba(201,168,76,.18);border-radius:3px}
    .av-wcard{background:linear-gradient(135deg,rgba(108,92,231,.18),rgba(201,168,76,.08));
      border:1px solid rgba(201,168,76,.18);border-radius:12px;padding:12px 14px;margin-bottom:2px;
      animation:av-fadein .4s ease}
    @keyframes av-fadein{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
    .av-wcard-top{display:flex;align-items:center;gap:10px;margin-bottom:7px}
    .av-wcard-av{width:36px;height:36px;border-radius:50%;border:1.5px solid #C9A84C;flex-shrink:0;
      background:linear-gradient(135deg,rgba(108,92,231,.35),rgba(201,168,76,.18));
      display:flex;align-items:center;justify-content:center;overflow:hidden}
    .av-wcard .av-wn{font-family:'Cinzel',serif;font-size:11px;color:#E8C97A}
    .av-wcard p{font-size:12px;color:#EDE8D8;line-height:1.65;margin-top:2px}
    .av-mrow{display:flex;gap:6px;align-items:flex-end;animation:av-mi .22s ease-out;position:relative}
    @keyframes av-mi{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
    .av-mrow.av-user{flex-direction:row-reverse}
    .av-av{width:26px;height:26px;border-radius:50%;flex-shrink:0;display:flex;
      align-items:center;justify-content:center;overflow:hidden}
    .av-av.av-bot{border:1px solid #C9A84C}
    .av-av.av-bot img{width:100%;height:100%;object-fit:cover}
    .av-av.av-uav{background:linear-gradient(135deg,#6C5CE7,#4A3580);color:#fff;font-size:10px;font-weight:600}
    .av-bbl{max-width:80%;padding:9px 13px;border-radius:14px;font-size:12.5px;line-height:1.55;
      word-break:break-word;position:relative}
    .av-bbl.av-bot{background:#1A1735;color:#EDE8D8;border:1px solid rgba(201,168,76,.18);border-bottom-left-radius:4px}
    .av-bbl.av-user{background:linear-gradient(135deg,#6C5CE7,#4A3580);color:#fff;border-bottom-right-radius:4px}
    .av-tbbl{display:flex;align-items:center;gap:5px;padding:10px 14px}
    .av-tbbl span{width:7px;height:7px;background:#C9A84C;border-radius:50%;
      animation:av-bn .8s ease-in-out infinite;opacity:.6}
    .av-tbbl span:nth-child(2){animation-delay:.14s}
    .av-tbbl span:nth-child(3){animation-delay:.28s}
    @keyframes av-bn{0%,80%,100%{transform:translateY(0)}40%{transform:translateY(-6px)}}
    .av-link-btn{display:inline-flex;align-items:center;gap:5px;
      background:rgba(108,92,231,.22);border:1px solid rgba(108,92,231,.5);
      border-radius:8px;padding:5px 11px;font-size:11px;color:#c4b8ff;
      text-decoration:none;margin-top:7px;transition:all .15s;cursor:pointer}
    .av-link-btn:hover{background:rgba(108,92,231,.4);color:#fff}
    .av-link-btn svg{width:12px;height:12px;fill:currentColor;flex-shrink:0}
    .av-opt-btns{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}
    .av-opt-btn{background:rgba(201,168,76,.1);border:1px solid rgba(201,168,76,.3);
      border-radius:20px;padding:5px 13px;font-size:11.5px;color:#E8C97A;
      cursor:pointer;font-family:'DM Sans',sans-serif;transition:all .18s;white-space:nowrap}
    .av-opt-btn:hover{background:rgba(201,168,76,.25);border-color:#C9A84C}
    /* INPUT BAR */
    .av-ibar{padding:9px 11px;display:flex;align-items:center;gap:7px;
      border-top:1px solid rgba(201,168,76,.18);background:rgba(10,8,24,.8);flex-shrink:0}
    #av-inp{flex:1;background:rgba(255,255,255,.06);border:1px solid rgba(201,168,76,.18);
      border-radius:18px;padding:8px 14px;font-family:'DM Sans',sans-serif;font-size:12.5px;
      color:#EDE8D8;outline:none;resize:none;line-height:1.4;max-height:80px;transition:border-color .2s}
    #av-inp::placeholder{color:rgba(237,232,216,.3)}
    #av-inp:focus{border-color:rgba(108,92,231,.6)}
    #av-send-btn{width:36px;height:36px;background:linear-gradient(135deg,#6C5CE7,#4a3580);
      border:none;border-radius:50%;cursor:pointer;display:flex;align-items:center;
      justify-content:center;flex-shrink:0;transition:transform .15s;
      box-shadow:0 2px 12px rgba(108,92,231,.45)}
    #av-send-btn:hover{transform:scale(1.1)}
    #av-send-btn svg{width:16px;height:16px;fill:#fff;margin-left:2px}
    #av-vbtn{width:34px;height:34px;border-radius:50%;background:rgba(108,92,231,.12);
      border:1px solid rgba(108,92,231,.35);cursor:pointer;display:flex;
      align-items:center;justify-content:center;flex-shrink:0;transition:all .2s}
    #av-vbtn:hover{background:rgba(108,92,231,.28)}
    #av-vbtn.av-listening{background:rgba(239,68,68,.2);border-color:rgba(239,68,68,.6);animation:av-vp 1s infinite}
    @keyframes av-vp{0%,100%{box-shadow:0 0 0 0 rgba(239,68,68,.4)}50%{box-shadow:0 0 0 8px rgba(239,68,68,0)}}
    #av-vbtn svg{width:15px;height:15px;fill:rgba(237,232,216,.5)}
    #av-vbtn.av-listening svg{fill:#fca5a5}
    /* CRM */
    #av-crm-panel{display:none;flex-direction:column;flex:1;overflow:hidden}
    #av-crm-panel.av-active{display:flex}
    .av-crm-hdr{background:linear-gradient(135deg,rgba(59,130,246,.18),rgba(59,130,246,.05));
      border-bottom:1px solid rgba(59,130,246,.2);padding:14px 16px;text-align:center;flex-shrink:0}
    .av-crm-hdr h3{font-family:'Cinzel',serif;font-size:12px;color:#93c5fd;letter-spacing:.05em}
    .av-crm-hdr p{font-size:11px;color:rgba(237,232,216,.5);margin-top:2px}
    .av-crm-contacts{display:flex;flex-direction:column;gap:10px;padding:16px}
    .av-crm-contact-btn{display:flex;align-items:center;gap:12px;padding:13px 16px;
      border-radius:12px;border:1px solid;cursor:pointer;transition:all .2s;text-decoration:none}
    .av-crm-contact-btn:hover{transform:translateY(-2px)}
    .av-crm-wa{background:rgba(37,211,102,.1);border-color:rgba(37,211,102,.35);color:#4ade80}
    .av-crm-mail{background:rgba(59,130,246,.1);border-color:rgba(59,130,246,.35);color:#93c5fd}
    .av-crm-phone{background:rgba(201,168,76,.1);border-color:rgba(201,168,76,.35);color:#E8C97A}
    .av-crm-icon{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
    .av-crm-wa .av-crm-icon{background:rgba(37,211,102,.18)}
    .av-crm-mail .av-crm-icon{background:rgba(59,130,246,.18)}
    .av-crm-phone .av-crm-icon{background:rgba(201,168,76,.18)}
    .av-crm-contact-btn svg{width:18px;height:18px;fill:currentColor}
    .av-crm-text .av-ct{font-size:13px;font-weight:500;color:#EDE8D8}
    .av-crm-text .av-cn{font-size:11px;color:rgba(237,232,216,.5);margin-top:2px}
    .av-crm-back{margin:0 16px 16px;background:transparent;border:1px solid rgba(201,168,76,.18);
      border-radius:9px;padding:9px;font-family:'DM Sans',sans-serif;font-size:12px;
      color:rgba(237,232,216,.5);cursor:pointer;transition:all .15s;width:calc(100% - 32px)}
    .av-crm-back:hover{color:#EDE8D8;border-color:rgba(201,168,76,.4)}
    /* END OVERLAY */
    #av-eo{display:none;position:absolute;inset:0;
      background:radial-gradient(ellipse at center,rgba(20,12,45,.97) 0%,rgba(10,8,24,.98) 100%);
      z-index:50;align-items:center;justify-content:center;flex-direction:column;
      gap:16px;padding:28px;backdrop-filter:blur(16px)}
    #av-eo.av-show{display:flex;animation:av-eoin .3s cubic-bezier(.34,1.56,.64,1)}
    @keyframes av-eoin{from{opacity:0;transform:scale(.92)}to{opacity:1;transform:scale(1)}}
    .av-eo-ring{width:72px;height:72px;border-radius:50%;border:2px solid #C9A84C;
      box-shadow:0 0 0 8px rgba(201,168,76,.08),0 0 32px rgba(201,168,76,.25);
      display:flex;align-items:center;justify-content:center}
    .av-eo-icon{font-size:32px;color:#C9A84C}
    .av-eo-divider{width:60px;height:1px;background:linear-gradient(90deg,transparent,#C9A84C,transparent)}
    .av-eo-title{font-family:'Cinzel',serif;font-size:16px;color:#E8C97A;text-align:center;letter-spacing:.08em}
    .av-eo-sub{font-size:12px;color:rgba(237,232,216,.5);text-align:center;line-height:1.7;max-width:260px}
    .av-eo-btns{display:flex;gap:10px;width:100%;margin-top:4px}
    .av-eo-btn{flex:1;padding:11px;border-radius:12px;border:none;cursor:pointer;
      font-family:'DM Sans',sans-serif;font-size:12.5px;font-weight:500;transition:all .2s}
    .av-eo-btn.av-cancel{background:rgba(255,255,255,.07);color:#EDE8D8;border:1px solid rgba(255,255,255,.1)}
    .av-eo-btn.av-cancel:hover{background:rgba(255,255,255,.13)}
    .av-eo-btn.av-confirm{background:linear-gradient(135deg,#ef4444,#b91c1c);color:#fff}
    .av-eo-btn.av-confirm:hover{opacity:.92}
    /* ENDED */
    #av-ended{display:none;flex-direction:column;align-items:center;justify-content:center;
      flex:1;padding:24px;gap:14px;text-align:center}
    #av-ended.av-show{display:flex;animation:av-fadein .5s ease}
    .av-ended-logo{width:64px;height:64px;border-radius:50%;border:2px solid #C9A84C;
      box-shadow:0 0 0 6px rgba(201,168,76,.1),0 0 28px rgba(201,168,76,.3);object-fit:cover}
    .av-ended-title{font-family:'Cinzel',serif;font-size:15px;color:#E8C97A;letter-spacing:.06em}
    .av-ended-sub{font-size:12px;color:rgba(237,232,216,.5);line-height:1.7}
    .av-rating{display:flex;gap:8px;justify-content:center}
    .av-star{font-size:26px;cursor:pointer;opacity:.25;transition:opacity .2s,transform .2s;color:#C9A84C}
    .av-star:hover,.av-star.av-on{opacity:1;transform:scale(1.25)}
    .av-rate-thanks{font-size:12px;color:#E8C97A;display:none;animation:av-fadein .4s ease}
    .av-restart-btn{background:linear-gradient(135deg,#6C5CE7,#C9A84C);border:none;
      border-radius:12px;padding:11px 26px;font-family:'Cinzel',serif;font-size:11px;
      font-weight:600;letter-spacing:.07em;color:#fff;cursor:pointer;transition:all .22s}
    .av-restart-btn:hover{opacity:.92;transform:translateY(-2px)}
    .av-ft{text-align:center;padding:5px;font-size:10px;color:rgba(237,232,216,.18);flex-shrink:0}
    /* LAUNCHER */
    #av-launcher{position:fixed;bottom:26px;right:26px;z-index:2147483647}
    #av-launcher-menu{position:absolute;bottom:76px;right:0;display:flex;flex-direction:column;
      gap:10px;opacity:0;pointer-events:none;transform:translateY(12px) scale(.96);
      transition:all .28s cubic-bezier(.34,1.56,.64,1)}
    #av-launcher-menu.av-show{opacity:1;pointer-events:all;transform:translateY(0) scale(1)}
    .av-launch-opt{display:flex;align-items:center;gap:10px;background:#12102A;
      border:1px solid rgba(201,168,76,.18);border-radius:30px;padding:9px 18px 9px 9px;
      cursor:pointer;transition:all .2s;white-space:nowrap}
    .av-launch-opt:hover{transform:translateX(-5px)}
    .av-launch-opt .av-lo-icon{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
    .av-launch-opt .av-lo-icon svg{width:20px;height:20px;fill:#fff}
    .av-launch-opt .av-lo-text{font-size:13px;font-weight:500;color:#EDE8D8}
    .av-lo-support .av-lo-icon{background:linear-gradient(135deg,#6C5CE7,#C9A84C)}
    .av-lo-wa .av-lo-icon{background:#25d366}
    #av-launcher-fab{width:58px;height:58px;border-radius:50%;
      background:linear-gradient(135deg,#3b2d6e,#1e1a3a);
      border:2px solid rgba(108,92,231,.6);cursor:pointer;
      display:flex;align-items:center;justify-content:center;
      box-shadow:0 0 24px rgba(108,92,231,.45),0 4px 16px rgba(0,0,0,.5);
      transition:transform .2s;position:relative}
    #av-launcher-fab:hover{transform:scale(1.1)}
    #av-launcher-fab svg{width:26px;height:26px;fill:#c4b8ff;transition:transform .28s}
    #av-launcher-fab.av-open svg{transform:rotate(135deg)}
    #av-launcher-fab::before{content:'';position:absolute;inset:-8px;border-radius:50%;
      border:1.5px solid rgba(108,92,231,.45);opacity:0;animation:av-pr 2.5s ease-out infinite}
    @keyframes av-pr{0%{transform:scale(1);opacity:.6}100%{transform:scale(1.5);opacity:0}}
    #av-launcher-badge{position:absolute;top:-2px;right:-2px;width:18px;height:18px;
      background:#ef4444;border-radius:50%;border:2px solid #0A0818;
      font-size:10px;font-weight:600;color:#fff;display:flex;align-items:center;justify-content:center}
    @keyframes av-shk{0%,100%{transform:translateX(0)}25%{transform:translateX(-5px)}75%{transform:translateX(5px)}}
    @media(max-width:480px){
      #av-win{width:calc(100vw - 16px);right:8px;bottom:86px;max-height:calc(100vh - 110px)}
      #av-launcher{right:12px;bottom:18px}
    }
  `;
  document.head.appendChild(style);

  /* ── AstroVed Logo Base64 ── */
  var LOGO_SRC = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAWgAAAFoCAYAAAB65WHVAAABhmlDQ1BJQ0MgcHJvZmlsZQAAKJGjkLFKA0EQht9ECUGJiIWFhY+QQ7GJIipiJRYWgoVGMRpMLsc5uZzHkbsgNo+ghbWNnYWNb2BhYWMvBMEXECsLsZFsdhMPE8k6sDvf/szssDMDpBuWZflDAMuo3EyckBbZJek/IYKnRxAiJNOyvDSbzTL0fR8rBO89U6u993trDnJpZQqEo4T8YFVuiUfieb2qBuWOuGVV5o64I07rckLcVXpU8IPinYrHittKZxIzhDqJha2fbBe3xW1xT3xSXZHLBxxHpf86cFBrmbZ3WuSoqSqphBRTUKihRIEKGmJqqGmhJkOdS6CoJCOZS54lzyp7lj0Lni3PjmfTs7PJIiISRRRRxhlFFFFEEUMkIkIW2f8P2L0DAO66Ng8=" ;

  /* ── Build HTML ── */
  var root = document.createElement('div');
  root.id = 'av-widget-root';
  root.innerHTML = `
    <!-- LAUNCHER -->
    <div id="av-launcher">
      <div id="av-launcher-menu">
        <div class="av-launch-opt av-lo-wa" id="av-wa-opt">
          <div class="av-lo-icon">
            <svg viewBox="0 0 24 24"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
          </div>
          <div class="av-lo-text">WhatsApp</div>
        </div>
        <div class="av-launch-opt av-lo-support" id="av-support-opt">
          <div class="av-lo-icon">
            <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>
          </div>
          <div class="av-lo-text">Support Chat</div>
        </div>
      </div>
      <button id="av-launcher-fab" aria-label="Open chat">
        <div id="av-launcher-badge">1</div>
        <svg id="av-fab-msg" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>
        <svg id="av-fab-close" viewBox="0 0 24 24" style="display:none"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
      </button>
    </div>

    <!-- CHAT WINDOW -->
    <div id="av-win" role="dialog" aria-label="AstroVed.AI Chat">
      <!-- Header -->
      <div class="av-hdr">
        <img class="av-logo-img" id="av-hdr-logo" alt="AstroVed"/>
        <div class="av-hinfo">
          <div class="av-hname">AstroVed.AI</div>
          <div class="av-hsub"><span class="av-odot"></span>Online — Ask me anything</div>
        </div>
        <div class="av-hbtns">
          <button class="av-hbtn av-crm-btn" id="av-crm-btn" aria-label="Talk to team">
            <svg viewBox="0 0 24 24"><path d="M9 11H7v2h2v-2zm4 0h-2v2h2v-2zm4 0h-2v2h2v-2zm2-7h-1V2h-2v2H8V2H6v2H5c-1.11 0-1.99.9-1.99 2L3 20c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 16H5V9h14v11z"/></svg>
            <span class="av-tip">Talk to Team</span>
          </button>
          <button class="av-hbtn av-end-btn" id="av-end-btn" aria-label="End chat">
            <svg viewBox="0 0 24 24"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
            <span class="av-tip">End Chat</span>
          </button>
          <button class="av-hbtn av-min-btn" id="av-min-btn" aria-label="Minimize">
            <svg viewBox="0 0 24 24"><path d="M19 13H5v-2h14v2z"/></svg>
            <span class="av-tip">Minimize</span>
          </button>
        </div>
      </div>

      <!-- End Overlay -->
      <div id="av-eo">
        <div class="av-eo-ring"><div class="av-eo-icon">✦</div></div>
        <div class="av-eo-divider"></div>
        <div class="av-eo-title">End Conversation?</div>
        <div class="av-eo-sub">Your cosmic session will close. The stars will always guide you back.</div>
        <div class="av-eo-btns">
          <button class="av-eo-btn av-cancel" id="av-eo-cancel">← Stay</button>
          <button class="av-eo-btn av-confirm" id="av-eo-confirm">End Chat</button>
        </div>
      </div>

      <!-- FORM SCREEN -->
      <div class="av-scr" id="av-fs">
        <div class="av-fhero">
          <img class="av-fhero-logo" id="av-form-logo" alt="AstroVed"/>
          <h2>Begin Your Journey</h2>
          <p>Share a little about yourself to get started.</p>
        </div>
        <div class="av-fg">
          <label>Your Name</label>
          <input type="text" id="av-fn" placeholder="e.g. Arjun Sharma" autocomplete="name"/>
        </div>
        <div class="av-fg">
          <label>Email Address</label>
          <input type="email" id="av-fe" placeholder="you@example.com" autocomplete="email"/>
        </div>
        <div class="av-fg">
          <label>Phone Number</label>
          <div class="av-phone-row">
            <select id="av-fcc" class="av-cc" aria-label="Country code">
              <option value="+91">🇮🇳 +91</option>
              <option value="+1">🇺🇸 +1</option>
              <option value="+44">🇬🇧 +44</option>
              <option value="+61">🇦🇺 +61</option>
              <option value="+971">🇦🇪 +971</option>
              <option value="+65">🇸🇬 +65</option>
              <option value="+60">🇲🇾 +60</option>
              <option value="+94">🇱🇰 +94</option>
              <option value="+880">🇧🇩 +880</option>
              <option value="+92">🇵🇰 +92</option>
            </select>
            <input type="tel" id="av-fp" placeholder="98765 43210" autocomplete="tel"/>
          </div>
        </div>
        <button class="av-sbtn" id="av-start-btn">✦ &nbsp;Start Consulting</button>
        <p class="av-prv" id="av-prv-msg">🔒 Your information is private &amp; secure</p>
      </div>

      <!-- CHAT SCREEN -->
      <div class="av-scr" id="av-cs">
        <div id="av-msgs"></div>
        <div class="av-ibar">
          <button id="av-vbtn" aria-label="Voice input">
            <svg viewBox="0 0 24 24"><path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/></svg>
          </button>
          <textarea id="av-inp" placeholder="Ask your question here" rows="1"></textarea>
          <button id="av-send-btn" aria-label="Send">
            <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
          </button>
        </div>
      </div>

      <!-- CRM PANEL -->
      <div class="av-scr" id="av-crm-panel">
        <div class="av-crm-hdr">
          <h3>🎧 Connect with Our Team</h3>
          <p>Choose how you'd like to reach us</p>
        </div>
        <div class="av-crm-contacts">
          <a class="av-crm-contact-btn av-crm-wa"
             href="https://api.whatsapp.com/send?phone=919677391109&text=Hello%2C%20I%20need%20assistance."
             target="_blank" rel="noopener">
            <div class="av-crm-icon">
              <svg viewBox="0 0 24 24"><path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/></svg>
            </div>
            <div class="av-crm-text"><div class="av-ct">WhatsApp Us</div><div class="av-cn">+91 96773 91109</div></div>
          </a>
          <a class="av-crm-contact-btn av-crm-mail" href="mailto:support@astroved.com">
            <div class="av-crm-icon">
              <svg viewBox="0 0 24 24"><path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>
            </div>
            <div class="av-crm-text"><div class="av-ct">Email Support</div><div class="av-cn">support@astroved.com</div></div>
          </a>
          <a class="av-crm-contact-btn av-crm-phone" href="tel:+919677391108">
            <div class="av-crm-icon">
              <svg viewBox="0 0 24 24"><path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/></svg>
            </div>
            <div class="av-crm-text"><div class="av-ct">Call Us</div><div class="av-cn">+91 96773 91108</div></div>
          </a>
        </div>
        <button class="av-crm-back" id="av-crm-back">← Back to Chat</button>
      </div>

      <!-- ENDED SCREEN -->
      <div class="av-scr" id="av-ended">
        <img class="av-ended-logo" id="av-ended-logo" alt="AstroVed"/>
        <div class="av-ended-title">Thank You! ✨</div>
        <div class="av-ended-sub">We hope the stars guided you well.<br>Rate your experience:</div>
        <div class="av-rating" id="av-rating">
          <span class="av-star">★</span><span class="av-star">★</span>
          <span class="av-star">★</span><span class="av-star">★</span><span class="av-star">★</span>
        </div>
        <div class="av-rate-thanks" id="av-rt">Thank you for your feedback! ✨</div>
        <button class="av-restart-btn" id="av-restart-btn">✦ New Conversation</button>
      </div>

      <div class="av-ft">Powered by AstroVed.AI ✦</div>
    </div>
  `;
  document.body.appendChild(root);

  /* ── Set Logos ── */
  document.getElementById('av-hdr-logo').src   = LOGO_SRC;
  document.getElementById('av-form-logo').src  = LOGO_SRC;
  document.getElementById('av-ended-logo').src = LOGO_SRC;

  /* ══════════════════════════════════════
     JAVASCRIPT LOGIC
  ══════════════════════════════════════ */
  var API    = 'https://astroved-chatbot.onrender.com';
  var SITE   = 'https://www.astroved.com';
  var CRM_KW = ['payment','pay','billing','bill','invoice','refund','subscription',
    'plan','price','pricing','cost','charge','cancel','complaint','support',
    'agent','human','team','speak','talk','call me','account','orders','tracking'];

  var isOpen=false, launcherOpen=false;
  // Pre-warm server when page loads
setTimeout(function(){
  fetch(API+'/').catch(function(){});
}, 1000);

  var uName='', uEmail='', uPhone='';
  var sessId='av_'+Math.random().toString(36).slice(2);
  var listening=false, recog=null;
  var msgCounter=0, pollTimer=null, lastMsgId=0;

  /* ── Helpers ── */
  function $(id){ return document.getElementById(id); }

  function cleanMd(t){
    return (t||'')
      .replace(/https?:\/\/[^\s)]+/g,'')
      .replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>')
      .replace(/\*(.*?)\*/g,'$1')
      .replace(/#{1,6}\s/g,'')
      .replace(/`(.*?)`/g,'$1')
      .replace(/\n/g,'<br>');
  }

  function scrl(){
    var m=$('av-msgs'); if(m) m.scrollTop=m.scrollHeight;
  }

  function shk(id){
    var el=$(id); if(!el) return;
    el.style.borderColor='#ef4444';
    el.style.animation='none'; el.offsetHeight;
    el.style.animation='av-shk .4s ease';
    setTimeout(function(){ el.style.borderColor=''; el.style.animation=''; },800);
  }
  
  function getFallbackLink(txt) {
  var t = (txt || '').toLowerCase();
  if (t.includes('horoscope')||t.includes('moon sign')) return { label:'🌙 View Horoscope', url: SITE+'/horoscopes' };
  // ... existing checks stay same ...
  if (t.includes('consult'))    return { label:'🔮 Talk to Astrologer', url: SITE+'/astrovedspeaks/' };

  // NEW — last-resort catch-all so a link is ALWAYS shown for real questions
  if (t.trim().split(' ').length > 3) {
    return { label:'✨ Explore All Services', url: SITE+'/astrology-services' };
  }
  return null;
}

  /* ── Bot Message ── */
  function botMsg(txt, opts, link){
    var m=$('av-msgs');
    var row=document.createElement('div');
    row.className='av-mrow av-bot';

    var linkHtml='';
    if(link&&link.url&&link.label){
      linkHtml='<br><a class="av-link-btn" href="'+link.url+'" target="_blank" rel="noopener">'+
        '<svg viewBox="0 0 24 24"><path d="M19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7zM14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7z"/></svg>'+
        link.label+'</a>';
    }
    var optsHtml='';
    if(opts&&opts.length){
      optsHtml='<div class="av-opt-btns">';
      opts.forEach(function(o){ optsHtml+='<button class="av-opt-btn">'+o+'</button>'; });
      optsHtml+='</div>';
    }
    row.innerHTML='<div class="av-av av-bot"><img src="'+LOGO_SRC+'" alt="bot"/></div>'+
      '<div class="av-bbl av-bot">'+cleanMd(txt)+linkHtml+optsHtml+'</div>';

    if(optsHtml){
      row.querySelectorAll('.av-opt-btn').forEach(function(b){
        b.addEventListener('click',function(){ doOpt(b); });
      });
    }
    m.appendChild(row); scrl();
  }

  /* ── User Message ── */
  function userMsg(txt){
    var m=$('av-msgs');
    var row=document.createElement('div');
    row.className='av-mrow av-user';
    row.innerHTML='<div class="av-bbl av-user">'+cleanMd(txt)+'</div>'+
      '<div class="av-av av-uav">'+(uName.slice(0,2).toUpperCase()||'ME')+'</div>';
    m.appendChild(row); scrl();
  }

  /* ── Typing ── */
  function showTyping(){
    var m=$('av-msgs');
    var r=document.createElement('div');
    r.className='av-mrow av-bot'; r.id='av-typ';
    r.innerHTML='<div class="av-av av-bot"><img src="'+LOGO_SRC+'" alt="bot"/></div>'+
      '<div class="av-bbl av-bot"><div class="av-tbbl"><span></span><span></span><span></span></div></div>';
    m.appendChild(r); scrl();
  }
  function rmTyping(){ var t=$('av-typ'); if(t) t.remove(); }

  /* ── Window Toggle ── */
  function toggleWin(){
    isOpen=!isOpen;
    $('av-win').classList.toggle('av-open',isOpen);
  }

  /* ── Launcher ── */
  function toggleLauncher(){
    if(isOpen){ toggleWin(); return; }
    launcherOpen=!launcherOpen;
    $('av-launcher-menu').classList.toggle('av-show',launcherOpen);
    $('av-launcher-fab').classList.toggle('av-open',launcherOpen);
    $('av-fab-msg').style.display   = launcherOpen ? 'none' : '';
    $('av-fab-close').style.display = launcherOpen ? ''     : 'none';
  }

  function closeLauncherMenu(){
    launcherOpen=false;
    $('av-launcher-menu').classList.remove('av-show');
    $('av-launcher-fab').classList.remove('av-open');
    $('av-fab-msg').style.display   ='';
    $('av-fab-close').style.display ='none';
  }

  function openSupportChat(){
    closeLauncherMenu();
    $('av-launcher-badge').style.display='none';
    if(!isOpen) toggleWin();
  }

  /* ── Start Chat (Form Submit) ── */
  function startChat(){
  var n=$('av-fn').value.trim();
  var e=$('av-fe').value.trim();
  var p=$('av-fp').value.trim();
  var cc=$('av-fcc').value;
  if(!n){ shk('av-fn'); return; }
  if(!e||!e.includes('@')){ shk('av-fe'); return; }
  if(!p||p.length<7){ shk('av-fp'); return; }

  uName=n.split(' ')[0]; uEmail=e; uPhone=p;

  // ✅ go to chat immediately, don't wait for the API
  proceedToChat(uName);

  // fire-and-forget registration
  fetch(API+'/user/register',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({session_id:sessId,user_name:n,user_email:e,user_phone:p,country_code:cc})
  }).catch(function(){});
}
  function proceedToChat(firstName){
    var btn=$('av-start-btn');
    if(btn){ btn.innerHTML='✦ &nbsp;Start Consulting'; btn.disabled=false; }
    $('av-fs').style.display='none';
    $('av-cs').classList.add('av-active');

    var m=$('av-msgs');
    var wc=document.createElement('div');
    wc.className='av-wcard';
    wc.innerHTML='<div class="av-wcard-top">'+
      '<div class="av-wcard-av"><img src="'+LOGO_SRC+'" style="width:100%;height:100%;object-fit:cover;border-radius:50%;" alt=""/></div>'+
      '<div class="av-wn">Namaste, '+firstName+' 🙏</div></div>'+
      '<p>✨ Welcome to AstroVed.AI — your personal Vedic cosmos companion. How may the stars guide your path?</p>';
    m.appendChild(wc);
    botMsg('The cosmos awaits, '+firstName+'! What would you like to explore today?',
      ['🌙 Horoscope','📊 Birth Chart','💑 Compatibility','❤️ Love','🌿 Remedies'], null);
  }

  /* ── Send Message ── */
  function send(){
    var inp=$('av-inp');
    var txt=inp.value.trim();
    if(!txt) return;
    inp.value=''; inp.style.height='';
    userMsg(txt);
    if(CRM_KW.some(function(k){ return txt.toLowerCase().includes(k); })){
      botMsg('Let me connect you with our specialist team right away!', [], null);
      setTimeout(showCRM, 800); return;
    }
    showTyping();
    callAPI(txt, 0);
  }

  function callAPI(txt, attempt){
    setTimeout(function(){
      fetch(API+'/chat',{
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify({session_id:sessId, message:txt})
      })
      .then(function(r){ if(!r.ok) throw new Error('HTTP '+r.status); return r.json(); })
      .then(function(d){
        rmTyping();
        if(d.mode==='with_agent'){ syncThenPoll(); return; }
        if(d.mode==='handoff_triggered'){ botMsg(d.reply,[],null); syncThenPoll(); return; }
        var link=(d.topic_url&&d.topic_label)
          ? {url:d.topic_url, label:d.topic_label}
          : getFallbackLink(txt);
        botMsg(d.reply||'Please try again.', [], link);
      })
      .catch(function(){
        if(attempt<2){ setTimeout(function(){ callAPI(txt, attempt+1); }, 2000); }
        else{ rmTyping(); botMsg('Server is waking up… Please resend in 30 seconds! 🔄',[],null); }
      });
    }, 200);
  }

  /* ── Polling ── */
  function startPolling(){
    if(pollTimer) return;
    pollTimer=setInterval(function(){
      fetch(API+'/poll/'+sessId+'?since_id='+lastMsgId)
        .then(function(r){ return r.json(); })
        .then(function(d){
          d.messages.forEach(function(m){
            lastMsgId=Math.max(lastMsgId,m.id);
            if(m.role==='assistant') botMsg(m.content,[],null);
            else if(m.role==='system') botMsg('🔔 '+m.content,[],null);
          });
          if(d.status==='closed'||d.status==='bot'){ clearInterval(pollTimer); pollTimer=null; }
        }).catch(function(){});
    }, 4000);
  }

  function syncThenPoll(){
    if(pollTimer) return;
    fetch(API+'/poll/'+sessId+'?since_id='+lastMsgId)
      .then(function(r){ return r.json(); })
      .then(function(d){
        if(d.messages&&d.messages.length){
          d.messages.forEach(function(m){ lastMsgId=Math.max(lastMsgId,m.id); });
        }
        startPolling();
      }).catch(function(){ startPolling(); });
  }

  /* ── Opt Buttons ── */
  function doOpt(b){
    var txt=b.textContent.trim();
    var container=b.closest('.av-opt-btns');
    if(container) container.remove();
    $('av-inp').value=txt; send();
  }

  /* ── CRM Panel ── */
  function showCRM(){
  var m = document.getElementById('msgs');  // $ → document.getElementById
  var row = document.createElement('div');
  row.className = 'mrow bot';
  row.innerHTML =
    '<div class="av bot"><img src="'+LOGO_SRC+'" alt="bot"/></div>' +
    '<div class="bbl bot">' +
      '🎧 <strong>Connect with Our Team</strong><br>Choose how you\'d like to reach us:' +
      '<div style="display:flex;flex-direction:column;gap:8px;margin-top:10px">' +
        '<a class="link-btn" style="justify-content:center" href="https://api.whatsapp.com/send?phone=919677391109&text='+encodeURIComponent('Hello, I need assistance.')+'" target="_blank" rel="noopener">💬 WhatsApp — +91 96773 91109</a>' +
        '<a class="link-btn" style="justify-content:center" href="mailto:support@astroved.com">✉️ Email — support@astroved.com</a>' +
        '<a class="link-btn" style="justify-content:center" href="tel:+919677391108">📞 Call — +91 96773 91108</a>' +
      '</div>' +
    '</div>';
  m.appendChild(row);
  scrl();

  fetch(API+'/handoff',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({session_id:sessId, user_name:uName,
      user_email:uEmail, user_phone:uPhone, issue_type:'support_request', priority:'normal'})
  }).catch(function(){});
  syncThenPoll();
}
    
  function backChat(){
    $('av-crm-panel').classList.remove('av-active');
    $('av-cs').classList.add('av-active');
  }

  /* ── End Chat ── */
  function showEnd(){ $('av-eo').classList.add('av-show'); }
  function hideEnd(){ $('av-eo').classList.remove('av-show'); }
  function doEnd(){
    hideEnd();
    $('av-cs').classList.remove('av-active');
    $('av-crm-panel').classList.remove('av-active');
    $('av-ended').classList.add('av-show');
  }

  /* ── Rating ── */
  var stars=document.querySelectorAll('.av-star');
  stars.forEach(function(s,i){
    s.addEventListener('click',function(){
      stars.forEach(function(x,j){ x.classList.toggle('av-on', j<=i); });
      $('av-rt').style.display='block';
    });
  });

  /* ── Restart ── */
  function restart(){
    sessId='av_'+Math.random().toString(36).slice(2);
    uName=''; uEmail=''; uPhone='';
    msgCounter=0; lastMsgId=0;
    if(pollTimer){ clearInterval(pollTimer); pollTimer=null; }
    $('av-ended').classList.remove('av-show');
    $('av-cs').classList.remove('av-active');
    $('av-crm-panel').classList.remove('av-active');
    $('av-fs').style.display='flex';
    $('av-msgs').innerHTML='';
    ['av-fn','av-fe','av-fp'].forEach(function(id){ $(id).value=''; });
    stars.forEach(function(s){ s.classList.remove('av-on'); });
    $('av-rt').style.display='none';
  }

  /* ── Voice ── */
  function toggleVoice(){
    if(!('webkitSpeechRecognition' in window||'SpeechRecognition' in window)){
      botMsg('Voice input needs Chrome browser.',[],null); return;
    }
    if(listening){ if(recog) recog.stop(); listening=false; $('av-vbtn').classList.remove('av-listening'); return; }
    var SR=window.SpeechRecognition||window.webkitSpeechRecognition;
    recog=new SR(); recog.lang='en-IN'; recog.interimResults=false;
    recog.onresult=function(e){ $('av-inp').value=e.results[0][0].transcript; listening=false; $('av-vbtn').classList.remove('av-listening'); send(); };
    recog.onerror=recog.onend=function(){ listening=false; $('av-vbtn').classList.remove('av-listening'); };
    recog.start(); listening=true; $('av-vbtn').classList.add('av-listening');
  }

  /* ── Textarea auto-grow ── */
  function grow(el){ el.style.height=''; el.style.height=Math.min(el.scrollHeight,80)+'px'; }

  /* ── Event Listeners ── */
  $('av-launcher-fab').addEventListener('click', toggleLauncher);
  $('av-support-opt').addEventListener('click', openSupportChat);
  $('av-wa-opt').addEventListener('click', function(){
    window.open('https://api.whatsapp.com/send?phone=919677391109&text='+encodeURIComponent('Hello, I need help.'),'_blank');
    closeLauncherMenu();
  });
  $('av-min-btn').addEventListener('click', toggleWin);
  $('av-end-btn').addEventListener('click', showEnd);
  $('av-crm-btn').addEventListener('click', showCRM);
  $('av-eo-cancel').addEventListener('click', hideEnd);
  $('av-eo-confirm').addEventListener('click', doEnd);
  $('av-crm-back').addEventListener('click', backChat);
  $('av-restart-btn').addEventListener('click', restart);
  $('av-start-btn').addEventListener('click', startChat);
  $('av-send-btn').addEventListener('click', send);
  $('av-vbtn').addEventListener('click', toggleVoice);
  $('av-inp').addEventListener('keydown', function(e){
    if(e.key==='Enter'&&!e.shiftKey){ e.preventDefault(); send(); }
  });
  $('av-inp').addEventListener('input', function(){ grow(this); });
  $('av-fn').addEventListener('keydown', function(e){ if(e.key==='Enter') $('av-fe').focus(); });
  $('av-fe').addEventListener('keydown', function(e){ if(e.key==='Enter') $('av-fp').focus(); });
  $('av-fp').addEventListener('keydown', function(e){ if(e.key==='Enter') startChat(); });

  document.addEventListener('click', function(e){
    var l=$('av-launcher');
    if(launcherOpen && l && !l.contains(e.target)) closeLauncherMenu();
  });

})();