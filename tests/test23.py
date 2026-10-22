# Local nicknames ("Rename for me") and selectable message tones.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site18"); site.mkdir(exist_ok=True)
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
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    nick=["Baba"]; p.on("dialog",lambda d: d.accept(nick[0]) if d.type=="prompt" else d.accept()); ctx.add_init_script("window.__promptValue='Baba';")
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Oz77',ck:ck,ts:Date.now()}]))",[CK])
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","fille"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1800)
    p.click(".ct"); p.wait_for_timeout(600)
    r["before_header"]= (p.eval_on_selector("#peerName","e=>e.textContent"))=='Oz77'
    # ⋮ → Rename for me → "Baba"
    p.click("#peerMeta"); p.wait_for_timeout(200); r["menuHasRename"]= p.is_visible("#ciRename")   # v37: in Chat info (tap the name)
    p.click("#ciRename"); p.wait_for_timeout(400); r["info_shows_nick"]= p.eval_on_selector("#ciName","e=>e.textContent")=="Baba"; p.click("#ciBack"); p.wait_for_timeout(150)
    r["header_nick"]= (p.eval_on_selector("#peerName","e=>e.textContent"))=='Baba'
    r["list_nick"]= (p.eval_on_selector(".ct .cn","e=>e.textContent.trim()"))=='Baba'
    r["list_avatar"]= (p.eval_on_selector(".ct .ava","e=>e.textContent"))=='B'
    c=p.evaluate("()=>window.__gz.contacts()[0]"); r["record"]= ({"alias":c.get("alias"),"nameKept":c.get("name")})=={'alias': 'Baba', 'nameKept': 'Oz77'}
    # Oz77 comes online with his own display name → the nickname stays
    pub=p.evaluate("()=>window.__pub()"); tag=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK,pub])
    p.evaluate("([a,t])=>window.__sync({k1:[{id:'a1',name:'Oz77',u:'oz-acct',pub:a,tag:t}]})",[pub,tag]); p.wait_for_timeout(900)
    r["paired"]= "secure" in p.eval_on_selector("#peerMeta","e=>e.title") and p.eval_on_selector("#bar","e=>e.classList.contains('st-online')")
    r["header_afterPairing"]= (p.eval_on_selector("#peerName","e=>e.textContent"))=='Baba'
    r["verifiedLineUsesNick"]= p.eval_on_selector_all(".log .sys","els=>els.some(e=>e.textContent.includes('End-to-end encrypted with Baba'))")
    # vault merge from another device: the other device renamed later → its nickname wins; an older record → ours stays
    m=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Oz77',ck:ck,ts:Date.now(),alias:'Papa',ats:Date.now()+100000}],groups:[]})",[CK])
    r["merge_newerWins"]= m["contacts"][0].get("alias")=="Papa"
    m2=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Oz77',ck:ck,ts:Date.now(),alias:'Old',ats:1}],groups:[]})",[CK])
    r["merge_olderIgnored"]= m2["contacts"][0].get("alias")=="Baba"
    # empty name restores his own name
    nick[0]=""; p.evaluate("()=>{ window.__promptValue=''; }"); p.click("#peerMeta"); p.wait_for_timeout(200); p.click("#ciRename"); p.wait_for_timeout(400); p.click("#ciBack"); p.wait_for_timeout(150)
    r["cleared_header"]= (p.eval_on_selector("#peerName","e=>e.textContent"))=='Oz77'; r["cleared_record"]= "alias" not in p.evaluate("()=>window.__gz.contacts()[0]")
    # message tones: select → persisted + previewed; receive uses it
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.evaluate("()=>document.querySelector('#settingsModal [data-go=notif]').click()"); p.wait_for_timeout(100)
    r["toneOptions"]= (p.eval_on_selector_all("#toneSel .tone","els=>els.map(e=>e.dataset.tone)"))==['gizleme', 'classic', 'pop', 'chime', 'marimba', 'soft']
    p.evaluate("()=>{ window.__beeps.length=0; }"); p.click("#toneSel .tone[data-tone=chime]"); p.wait_for_timeout(400)
    r["tonePersisted"]= (p.evaluate("()=>localStorage.getItem('gz-tone')"))=='chime'
    r["tonePreviewed"]= (p.evaluate("()=>window.__beeps.slice(0,4)"))==[1046.5, 2093, 1318.51, 1567.98]
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
