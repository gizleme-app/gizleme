# Lock and log-out screens on a phone: the form stays above the keyboard, nothing hidden underneath.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site29"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__pstate={}; window.__beeps=[];
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{}, on(type,opts,cb){ this._cbs[type+":"+(opts&&opts.event)]=cb; return this; }, subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); }, send(){ return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{};
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-auth"&&b.action==="logout") return {data:{ok:true}};
    if(n==="gizleme-vault") return {data:{ok:true,abk:null,contacts:null,cver:0}};
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
// a controllable visual viewport (installed before app.js captures it)
const fakeVV={height:window.innerHeight, offsetTop:0, _h:{}, addEventListener(t,f){ (this._h[t]=this._h[t]||[]).push(f); }, fire(t){ (this._h[t]||[]).forEach(f=>f()); }};
Object.defineProperty(window,"visualViewport",{value:fakeVV,configurable:true});
window.__vv=fakeVV;
// a fake AudioContext that records what is played, and a fake iOS audio session
window.AudioContext=function(){ this.currentTime=0; this.state="suspended"; this.destination={}; this.resume=()=>{ this.state="running"; return Promise.resolve(); };
  this.createOscillator=()=>({type:"sine",frequency:{value:0},connect(g){ window.__beeps.push(this.frequency.value); return g; },start(){},stop(){}});
  this.createGain=()=>({gain:{setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){ return {}; }}); };
window.__sessionLog=[]; const sess={ _t:"auto", get type(){ return this._t; }, set type(v){ this._t=v; window.__sessionLog.push(v); } };
Object.defineProperty(navigator,"audioSession",{value:sess,configurable:true});
'''
(site/"mock.js").write_text(MOCK)
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={contacts:()=>contactsLoad(),fit:()=>fitViewport()};\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","logo-head.png","logo-word.png","logo-dot.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
(site/"sw.js").write_text(pathlib.Path(SRC+"sw.js").read_text().replace("/app.min.js?v=","/app.js?v="))   # the worker precaches what the page loads
os.chdir(site)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=socketserver.ThreadingTCPServer(("127.0.0.1",0),Q); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()

IPHONE="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
r={}
JOIN_H="()=>document.getElementById('join').getBoundingClientRect().height"
with sync_playwright() as pw:
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":390,"height":780}, user_agent=IPHONE, has_touch=True, is_mobile=True, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    p.on("dialog",lambda d: d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(400)
    # register screen (tall content) on a short phone: the screen scrolls inside itself, the page never does
    r["auth_bodyFixed"]= p.evaluate("()=>document.body.classList.contains('in-auth') && getComputedStyle(document.body).position==='fixed'")
    r["auth_fillsViewport"]= p.evaluate("()=>Math.abs(document.getElementById('join').getBoundingClientRect().height-window.innerHeight)<2")
    r["auth_pageNotScrollable"]= p.evaluate("()=>document.documentElement.scrollHeight<=window.innerHeight+1")
    p.set_viewport_size({"width":390,"height":480}); p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.fire('resize'); }"); p.wait_for_timeout(300)
    r["short_joinScrolls"]= p.evaluate("()=>{ const j=document.getElementById('join'); return j.scrollHeight>j.clientHeight+20 && document.documentElement.scrollHeight<=window.innerHeight+1; }")
    r["short_buttonReachable"]= p.evaluate("()=>{ const j=document.getElementById('join'); j.scrollTop=j.scrollHeight; const b=document.getElementById('joinBtn').getBoundingClientRect(); return b.top>=0 && b.bottom<=window.innerHeight+1; }")
    p.set_viewport_size({"width":390,"height":780}); p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.fire('resize'); }"); p.wait_for_timeout(300)
    # register, then lock → the unlock screen
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(3200)
    p.evaluate("()=>document.getElementById('installModal').classList.remove('show')")
    r["app_bodyNotAuth"]= p.evaluate("()=>!document.body.classList.contains('in-auth') && document.body.classList.contains('in-app')")
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(500)
    r["lock_mode"]= p.get_attribute("#join","data-mode")=="unlock"
    r["lock_bodyAuth"]= p.evaluate("()=>document.body.classList.contains('in-auth') && !document.body.classList.contains('in-app')")
    r["lock_cardCentered"]= p.evaluate("()=>{ const c=document.querySelector('#join .card').getBoundingClientRect(); return c.top>40 && c.bottom<window.innerHeight-40; }")
    r["lock_logoutLinkShown"]= p.is_visible("#switchLink") and "Log out" in p.eval_on_selector("#switchLink","e=>e.textContent")
    # the password field is focused → the keyboard opens (visual viewport shrinks)
    p.focus("#pwInput"); p.evaluate("()=>{ window.__vv.height=window.innerHeight-330; window.__vv.offsetTop=0; window.__vv.fire('resize'); }"); p.wait_for_timeout(900)
    r["kb_joinShrinks"]= p.evaluate("()=>Math.abs(document.getElementById('join').getBoundingClientRect().height-(window.innerHeight-330))<2")
    r["kb_pageNotScrolled"]= p.evaluate("()=>window.scrollY===0")
    r["kb_inputVisible"]= p.evaluate("()=>{ const i=document.getElementById('pwInput').getBoundingClientRect(); return i.top>=0 && i.bottom<=window.innerHeight-330; }")
    r["kb_logoutReachableByScroll"]= p.evaluate("()=>{ const j=document.getElementById('join'); j.scrollTop=j.scrollHeight; const l=document.getElementById('switchLink').getBoundingClientRect(); return l.top>=0 && l.bottom<=window.innerHeight-330+1; }")
    # tap "Log out" with the keyboard still open → confirm (accepted) → back to the register screen
    p.click("#switchLink"); p.wait_for_timeout(1500)
    r["logout_fromLockScreen"]= p.get_attribute("#join","data-mode")=="login" and p.evaluate("()=>!localStorage.getItem('gz-session')")
    # keyboard closes → full height again, card centered
    p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.fire('resize'); }"); p.wait_for_timeout(300)
    r["kb_closed_restored"]= p.evaluate("()=>Math.abs(document.getElementById('join').getBoundingClientRect().height-window.innerHeight)<2")
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
