# Local nicknames ("Rename for me") and selectable message tones.
from playwright.sync_api import sync_playwright
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
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),merge:(r)=>mergeContacts(r)};\n})();\n'
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

r={}
with sync_playwright() as pw:
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    nick=["Baba"]; p.on("dialog",lambda d: d.accept(nick[0]) if d.type=="prompt" else d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Oz77',ck:ck,ts:Date.now()}]))",[CK])
    p.fill("#userInput","fille"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1800)
    p.click(".ct"); p.wait_for_timeout(600)
    r["before_header"]= p.eval_on_selector("#peerName","e=>e.textContent")
    # ⋮ → Rename for me → "Baba"
    p.click("#menuBtn"); p.wait_for_timeout(150); r["menuHasRename"]= p.is_visible("#mi-rename")
    p.click("#mi-rename"); p.wait_for_timeout(400)
    r["header_nick"]= p.eval_on_selector("#peerName","e=>e.textContent")
    r["list_nick"]= p.eval_on_selector(".ct .cn","e=>e.textContent.trim()")
    r["list_avatar"]= p.eval_on_selector(".ct .ava","e=>e.textContent")
    c=p.evaluate("()=>window.__gz.contacts()[0]"); r["record"]= {"alias":c.get("alias"),"nameKept":c.get("name")}
    # Oz77 comes online with his own display name → the nickname stays
    pub=p.evaluate("()=>window.__pub()"); tag=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK,pub])
    p.evaluate("([a,t])=>window.__sync({k1:[{id:'a1',name:'Oz77',u:'oz-acct',pub:a,tag:t}]})",[pub,tag]); p.wait_for_timeout(900)
    r["paired"]= "secure" in p.eval_on_selector("#peerMeta","e=>e.title") and p.eval_on_selector("#bar","e=>e.classList.contains('st-online')")
    r["header_afterPairing"]= p.eval_on_selector("#peerName","e=>e.textContent")
    r["verifiedLineUsesNick"]= p.eval_on_selector_all(".log .sys","els=>els.some(e=>e.textContent.includes('End-to-end encrypted with Baba'))")
    # vault merge from another device: the other device renamed later → its nickname wins; an older record → ours stays
    m=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Oz77',ck:ck,ts:Date.now(),alias:'Papa',ats:Date.now()+100000}],groups:[]})",[CK])
    r["merge_newerWins"]= m["contacts"][0].get("alias")=="Papa"
    m2=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Oz77',ck:ck,ts:Date.now(),alias:'Old',ats:1}],groups:[]})",[CK])
    r["merge_olderIgnored"]= m2["contacts"][0].get("alias")=="Baba"
    # empty name restores his own name
    nick[0]=""; p.click("#menuBtn"); p.wait_for_timeout(150); p.click("#mi-rename"); p.wait_for_timeout(400)
    r["cleared_header"]= p.eval_on_selector("#peerName","e=>e.textContent"); r["cleared_record"]= "alias" not in p.evaluate("()=>window.__gz.contacts()[0]")
    # message tones: select → persisted + previewed; receive uses it
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.wait_for_timeout(100)
    r["toneOptions"]= p.eval_on_selector_all("#toneSel .tone","els=>els.map(e=>e.dataset.tone)")
    p.evaluate("()=>{ window.__beeps.length=0; }"); p.click("#toneSel .tone[data-tone=chime]"); p.wait_for_timeout(400)
    r["tonePersisted"]= p.evaluate("()=>localStorage.getItem('gz-tone')")
    r["tonePreviewed"]= p.evaluate("()=>window.__beeps.slice(0,4)")
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
