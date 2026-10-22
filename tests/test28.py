# Chat header: logo beside the name, red/green status dot instead of status text, details on tap.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site28"); site.mkdir(exist_ok=True)
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
    if(n==="gizleme-vault") return {data:{ok:true,abk:null,contacts:null,cver:0}};
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
window.__sync=(state)=>{ window.__pstate=state; const cb=window.__chan&&window.__chan._cbs["presence:sync"]; cb&&cb(); };
// a fake AudioContext that records what is played
window.AudioContext=function(){ this.currentTime=0; this.state="running"; this.destination={}; this.resume=()=>{};
  this.createOscillator=()=>({type:"sine",frequency:{value:0},connect(g){ window.__beeps.push(this.frequency.value); return g; },start(){},stop(){}});
  this.createGain=()=>({gain:{setValueAtTime(){},linearRampToValueAtTime(){},exponentialRampToValueAtTime(){}},connect(){ return {}; }}); };
const enc=new TextEncoder(), SALT=enc.encode("vesper/v1");
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))), unb=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function hkdf(ikm,info,len=32){ const k=await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]); return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8); }
window.__pub=async()=>{ const k=await crypto.subtle.generateKey({name:"ECDH",namedCurve:"P-256"},true,["deriveBits"]); return b64(await crypto.subtle.exportKey("raw",k.publicKey)); };
window.__tag=async(ck,pub)=>{ const bits=await hkdf(unb(ck),"gz-auth/v1"); const hk=await crypto.subtle.importKey("raw",bits,{name:"HMAC",hash:"SHA-256"},false,["sign"]); return b64(await crypto.subtle.sign("HMAC",hk,unb(pub))); };
'''
(site/"mock.js").write_text(MOCK)
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),merge:(r)=>mergeContacts(r)};\n})();\n'
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

r={}
with sync_playwright() as pw:
    b=pw.chromium.launch(); ctx=b.new_context(timezone_id=TZ, viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d: d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Florian',ck:ck,ts:Date.now()}]))",[CK])
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1800)
    p.click(".ct"); p.wait_for_timeout(700)
    # header: logo right beside the name
    r["nameStandsAlone"]= p.evaluate("()=>{ const n=document.getElementById('peerName'); return !n.nextElementSibling && !document.querySelector('.peer-logo') && getComputedStyle(document.getElementById('chatBrand')).display==='none'; }")   # v36: no logo or brand in a chat's header
    # offline: red dot, one short word, full explanation kept on the element (hover) and on tap (toast)
    r["offline_class"]= p.eval_on_selector("#bar","e=>e.classList.contains('st-offline') && !e.classList.contains('st-online')")
    r["offline_short"]= (p.eval_on_selector("#statusText","e=>e.textContent"))=='offline'
    r["offline_fullKept"]= "delivered when they reconnect" in p.eval_on_selector("#peerMeta","e=>e.title")
    r["offline_dotRed"]= p.evaluate("()=>{ const c=getComputedStyle(document.querySelector('#bar .led')).backgroundColor; const bad=getComputedStyle(document.documentElement).getPropertyValue('--bad').trim(); const d=document.createElement('div'); d.style.color=bad; document.body.appendChild(d); const want=getComputedStyle(d).color; d.remove(); return c===want; }")
    p.click("#peerMeta"); p.wait_for_timeout(250)      # v37: the name opens Chat info, which shows the full status
    r["tap_showsFull"]= "delivered when they reconnect" in p.eval_on_selector("#ciStatus","e=>e.textContent") and p.is_visible("#infoModal")
    p.click("#ciBack"); p.wait_for_timeout(150)
    # a tap anywhere unlocked audio → the connection sound can play when Florian comes online
    p.evaluate("()=>{ window.__beeps.length=0; }")
    pub=p.evaluate("()=>window.__pub()"); tag=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK,pub])
    p.evaluate("([a,t])=>window.__sync({k1:[{id:'a1',name:'Florian',u:'flo-acct',pub:a,tag:t}]})",[pub,tag]); p.wait_for_timeout(1000)
    r["online_class"]= p.eval_on_selector("#bar","e=>e.classList.contains('st-online')")
    r["online_short"]= (p.eval_on_selector("#statusText","e=>e.textContent"))=='online'
    r["online_fullKept"]= "same key as your first connection" in p.eval_on_selector("#peerMeta","e=>e.title")
    r["connectIsSilent"]= p.evaluate("()=>window.__beeps.length===0")   # a contact coming online is shown by the green dot, not a chime
    r["connLineOnce"]= p.eval_on_selector_all(".log .sys","els=>els.filter(e=>e.textContent.includes('End-to-end encrypted with')).length")==1
    # Florian drops and comes back with a new session: dot red then green again, no second connection line
    p.evaluate("()=>window.__sync({})"); p.wait_for_timeout(500)
    r["back_offline"]= p.eval_on_selector("#bar","e=>e.classList.contains('st-offline')")
    pub2=p.evaluate("()=>window.__pub()"); tag2=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK,pub2])
    p.evaluate("([a,t])=>window.__sync({k2:[{id:'a2',name:'Florian',u:'flo-acct',pub:a,tag:t}]})",[pub2,tag2]); p.wait_for_timeout(1000)
    r["back_online"]= p.eval_on_selector("#bar","e=>e.classList.contains('st-online')")
    r["connLineStillOnce"]= p.eval_on_selector_all(".log .sys","els=>els.filter(e=>e.textContent.includes('End-to-end encrypted with')).length")==1
    # French
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); p.select_option("#langSel","fr"); p.wait_for_timeout(500)
    p.evaluate("()=>document.getElementById('settingsModal').classList.remove('show')")
    p.evaluate("()=>window.__sync({})"); p.wait_for_timeout(400)
    r["fr_offline"]= (p.eval_on_selector("#statusText","e=>e.textContent"))=='hors ligne'
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
