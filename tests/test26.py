# Phone layout: the page never scrolls, the header stays when the keyboard opens; tone chips unlock audio.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site26"); site.mkdir(exist_ok=True)
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
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={contacts:()=>contactsLoad(),fit:()=>fitViewport()};\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","logo-head.png","logo-word.png","logo-dot.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
os.chdir(site)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=socketserver.ThreadingTCPServer(("127.0.0.1",0),Q); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()

IPHONE="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
r={}
with sync_playwright() as pw:
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":390,"height":780}, user_agent=IPHONE, has_touch=True, is_mobile=True, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    p.on("dialog",lambda d: d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    r["join_bodyScrollable"]= not p.evaluate("()=>document.body.classList.contains('in-app')")
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Oz77',ck:ck,ts:Date.now()}]))",[CK])
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","fille"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(3200)
    p.evaluate("()=>document.getElementById('installModal').classList.remove('show')")   # the iOS 'add to Home Screen' invite
    r["app_bodyFixed"]= p.evaluate("()=>document.body.classList.contains('in-app') && getComputedStyle(document.body).position==='fixed'")
    r["app_fillsViewport"]= p.evaluate("()=>Math.abs(document.getElementById('app').getBoundingClientRect().height-window.innerHeight)<2")
    p.click(".ct"); p.wait_for_timeout(600)
    # 60 messages: the conversation scrolls inside, the page does not, the header with the back button stays put
    p.evaluate("()=>{ for(let i=0;i<60;i++){ const ta=document.getElementById('msgInput'); ta.value='message '+i; ta.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true})); } }"); p.wait_for_timeout(2500)
    r["sixtyMsgs"]= p.eval_on_selector_all(".log:not([style*='display: none']) .bubble, .log:not([style*='display: none']) .msg","els=>els.length")>=60
    r["pageNotScrolled"]= p.evaluate("()=>window.scrollY===0 && document.documentElement.scrollHeight<=window.innerHeight+1")
    r["logDebug"]= p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); return l?[l.scrollTop,l.scrollHeight,l.clientHeight]:'none'; }")
    r["logScrolledToBottom"]= p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); return l && l.scrollTop>100 && (l.scrollHeight-l.scrollTop-l.clientHeight)<4; }")
    r["backBtnVisible"]= p.evaluate("()=>{ const b=document.getElementById('backHome').getBoundingClientRect(); return b.top>=0 && b.bottom<120 && b.width>0; }")
    r["composerAtBottom"]= p.evaluate("()=>{ const c=document.querySelector('.composer').getBoundingClientRect(); return Math.abs(c.bottom-window.innerHeight)<2; }")
    # the keyboard opens (visual viewport shrinks and iOS shifts it): the app follows, header still at the top
    p.evaluate("()=>{ window.__vv.height=window.innerHeight-320; window.__vv.offsetTop=140; window.__vv.fire('resize'); window.__vv.fire('scroll'); }"); p.wait_for_timeout(300)
    r["kb_appHeight"]= p.evaluate("()=>document.getElementById('app').style.height===(window.innerHeight-320)+'px'")
    r["kb_appRenderedHeight"]= p.evaluate("()=>Math.abs(document.getElementById('app').getBoundingClientRect().height-(window.innerHeight-320))<2")
    # the visual viewport is offset by 140 (iOS shifted it): the app follows, so its bottom sits at offsetTop+height
    r["kb_composerAboveKeyboard"]= p.evaluate("()=>{ const c=document.querySelector('.composer').getBoundingClientRect(); return Math.abs(c.bottom-(140+window.innerHeight-320))<2 && c.height>40; }")
    r["kb_inputVisible"]= p.evaluate("()=>{ const i=document.getElementById('msgInput').getBoundingClientRect(); return i.top>140 && i.bottom<=140+window.innerHeight-320; }")
    r["kb_headerAtVisualTop"]= p.evaluate("()=>Math.abs(document.getElementById('bar').getBoundingClientRect().top-140)<2")
    r["kb_pinned"]= p.evaluate("()=>document.getElementById('app').style.transform==='translateY(140px)' && document.body.classList.contains('kb')")
    r["kb_noSafeAreaPad"]= p.evaluate("()=>getComputedStyle(document.querySelector('.composer')).paddingBottom==='10px'")
    r["kb_logStillAtBottom"]= p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); return (l.scrollHeight-l.scrollTop-l.clientHeight)<4; }")
    p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.offsetTop=0; window.__vv.fire('resize'); window.__vv.fire('scroll'); }"); p.wait_for_timeout(200)
    # installed-app flavour: innerHeight shrinks with the keyboard too (judged against the tallest viewport seen)
    p.set_viewport_size({"width":390,"height":470}); p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.offsetTop=0; window.__vv.fire('resize'); }"); p.wait_for_timeout(300)
    r["standalone_kb"]= p.evaluate("()=>document.body.classList.contains('kb') && document.getElementById('app').style.height==='470px'")
    r["standalone_logAtBottom"]= p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); return (l.scrollHeight-l.scrollTop-l.clientHeight)<4; }")
    # a reader who scrolled up is left alone when the area resizes
    p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); l.scrollTop=0; l.dispatchEvent(new Event('scroll')); }"); p.wait_for_timeout(100)
    p.set_viewport_size({"width":390,"height":420}); p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.fire('resize'); }"); p.wait_for_timeout(300)
    r["readerUp_notForced"]= p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); return l.scrollTop<40; }")
    p.evaluate("()=>{ const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); l.scrollTop=l.scrollHeight; l.dispatchEvent(new Event('scroll')); }"); p.wait_for_timeout(100)
    p.set_viewport_size({"width":390,"height":780}); p.evaluate("()=>{ window.__vv.height=window.innerHeight; window.__vv.fire('resize'); }"); p.wait_for_timeout(300)
    # the composer growing to several lines keeps the latest message visible
    p.evaluate("()=>{ const ta=document.getElementById('msgInput'); ta.value='l1\\nl2\\nl3\\nl4\\nl5'; ta.dispatchEvent(new Event('input',{bubbles:true})); }"); p.wait_for_timeout(300)
    r["multiline_logAtBottom"]= p.evaluate("()=>{ const ta=document.getElementById('msgInput'); const l=[...document.querySelectorAll('.log')].find(e=>e.style.display!=='none'); return ta.offsetHeight>60 && (l.scrollHeight-l.scrollTop-l.clientHeight)<4; }")
    p.evaluate("()=>{ const ta=document.getElementById('msgInput'); ta.value=''; ta.dispatchEvent(new Event('input',{bubbles:true})); }")
    r["kb_closed_restored"]= p.evaluate("()=>document.getElementById('app').style.transform==='' && !document.body.classList.contains('kb') && document.getElementById('app').style.height===window.innerHeight+'px'")
    # tone chips: a tap selects, previews (audio unlocked in the gesture), persists; iOS hint shown
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.evaluate("()=>document.querySelector('#settingsModal [data-go=notif]').click()"); p.wait_for_timeout(100)
    r["chips"]= p.eval_on_selector_all("#toneSel .tone","els=>els.map(e=>e.dataset.tone)")
    r["hintOnIOS"]= p.is_visible("#toneHint")
    p.evaluate("()=>{ window.__beeps.length=0; }"); p.click("#toneSel .tone[data-tone=chime]"); p.wait_for_timeout(400)
    r["chime_selected"]= p.eval_on_selector("#toneSel .tone[data-tone=chime]","e=>e.getAttribute('aria-checked')")=="true" and p.evaluate("()=>localStorage.getItem('gz-tone')")=="chime"
    r["chime_previewed"]= p.evaluate("()=>window.__beeps.slice(0,2)")==[1046.5,2093]
    r["session_playbackThenAuto"]= p.evaluate("()=>window.__sessionLog[0]")=="playback"
    p.wait_for_timeout(1500); r["session_backToAuto"]= p.evaluate("()=>navigator.audioSession.type")=="auto"
    r["onlyOneChecked"]= p.eval_on_selector_all("#toneSel .tone[aria-checked=true]","els=>els.length")==1
    # log out: the body scrolls again
    p.evaluate("()=>document.querySelector('#settingsModal [data-go=account]').click()"); p.click("#logoutBtn"); p.wait_for_timeout(1200)
    r["logout_bodyFree"]= p.evaluate("()=>!document.body.classList.contains('in-app') && document.getElementById('app').style.height===''")
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
