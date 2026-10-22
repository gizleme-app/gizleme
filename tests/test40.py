# Vault merge rules for the key chain: newer epoch wins, equal epochs converge on the smaller root, older never overrides.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site40"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__calls=[]; window.__puts=[]; window.__gets=[]; window.__MBOX={}; window.__pstate={}; window.__vault={abk:null,contacts:null,cver:0};
window.supabase={createClient:()=>({
  channel:(name)=>{ try{ window.__lastJoin=(name||"").replace("ratchet-",""); }catch(e){} const c={ _cbs:{}, _tracks:[],
    on(type,opts,cb){ this._cbs[type+":"+(opts&&opts.event)]=cb; return this; },
    subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; this._tracks.push(JSON.parse(JSON.stringify(p))); return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); },
    send(m){ (window.__sent=window.__sent||[]).push(m); return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({upload:async()=>({}),getPublicUrl:(p)=>({data:{publicUrl:"/blob/"+p}}),remove:async()=>({})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{}; window.__calls.push([n,b.action]);
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-auth"&&b.action==="salt") return {data:{ok:true,salt:btoa("0123456789abcdef")}};
    if(n==="gizleme-auth"&&b.action==="login") return {data:{ok:true,token:"t2",username:b.username,display:b.username}};
    if(n==="gizleme-vault"&&b.action==="pull") return {data:{ok:true,abk:window.__vault.abk,contacts:window.__vault.contacts,cver:window.__vault.cver}};
    if(n==="gizleme-vault"&&b.action==="pushAbk"){ if(!window.__vault.abk) window.__vault.abk=b.abk; return {data:{ok:true}}; }
    if(n==="gizleme-vault"&&b.action==="pushContacts"){ if((b.cver||0)!==window.__vault.cver) return {data:{ok:false,conflict:true,cver:window.__vault.cver}}; window.__vault.contacts=b.contacts; window.__vault.cver++; return {data:{ok:true,cver:window.__vault.cver}}; }
    if(n==="gizleme-mbox"&&b.action==="get"){ window.__gets.push(b.mbox); const items=(window.__MBOX[b.mbox]||[]).filter(it=>!b.since||Date.parse(it.ts)>Date.parse(b.since)); return {data:{ok:true,items}}; }
    if(n==="gizleme-mbox"&&b.action==="put"){ window.__puts.push(b); return {data:{ok:true}}; }
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
window.__sync=(state)=>{ window.__pstate=state; const cb=window.__chan&&window.__chan._cbs["presence:sync"]; cb&&cb(); };
const enc=new TextEncoder(), SALT=enc.encode("vesper/v1");
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))), unb=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const b64url=b=>b64(b).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
async function hkdf(ikm,info,len=32){ const k=await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]); return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8); }
window.__ckFromSecret=async s=>b64(await hkdf(unb(s),"gz-invite/v1"));
window.__mboxId=async ck=>b64url(new Uint8Array(await hkdf(unb(ck),"gz-mbox/v1",16)));
window.__tag=async(ck,pub)=>{ const bits=await hkdf(unb(ck),"gz-auth/v1"); const hk=await crypto.subtle.importKey("raw",bits,{name:"HMAC",hash:"SHA-256"},false,["sign","verify"]); return b64(await crypto.subtle.sign("HMAC",hk,unb(pub))); };
window.__verify=async(ck,pub,tag)=>{ const bits=await hkdf(unb(ck),"gz-auth/v1"); const hk=await crypto.subtle.importKey("raw",bits,{name:"HMAC",hash:"SHA-256"},false,["sign","verify"]); return crypto.subtle.verify("HMAC",hk,unb(tag),unb(pub)); };
window.__seal=async(ck,env)=>{ const key=await crypto.subtle.importKey("raw",await hkdf(unb(ck),"gz-mbox-key/v1"),{name:"AES-GCM"},false,["encrypt"]); const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify(env))); return {iv:b64(iv),ct:b64(ct)}; };
window.__drop=async(ck,env,from)=>{ const id=await window.__mboxId(ck); const mid="m"+Math.random().toString(16).slice(2); env.mid=mid; (window.__MBOX[id]=window.__MBOX[id]||[]).push({mid,from_user:from||"peer-acct",data:await window.__seal(ck,env),ts:new Date().toISOString()}); };
window.__peer={ async init(){ this.kp=await crypto.subtle.generateKey({name:"ECDH",namedCurve:"P-256"},true,["deriveBits"]); this.pub=b64(await crypto.subtle.exportKey("raw",this.kp.publicKey)); return this.pub; },
  async rotated(ourPub){ const pk=await crypto.subtle.importKey("raw",unb(ourPub),{name:"ECDH",namedCurve:"P-256"},false,[]); const sec=await crypto.subtle.deriveBits({name:"ECDH",public:pk},this.kp.privateKey,256); return b64(await hkdf(sec,"gz-contact/v2")); } };
'''
(site/"mock.js").write_text(MOCK)
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={save:(l)=>contactsSave(l),chainCacheSize:()=>_chainCache.size,chainCachePut:()=>_chainCache.set("x|y",1),legacyPending:()=>{ const l=contactsLoad(); l.forEach(c=>{ if(c.inv&&c.pk){ delete c.pk; delete c.pp; delete c.v3; } }); contactsSave(l); },contacts:()=>contactsLoad(),groups:()=>groupsLoad(),meta:()=>_meta,merge:(r)=>mergeContacts(r)}; window.__rv=(ck)=>rvCodeFromCK(ck);\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg"]:
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
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); entered(p, 2500)
    CK="Q"*43+"="
    # local: chain B at epoch 5 ; remote: chain A at epoch 5 (seeded at the same moment by two device pairs) -> both keep the smaller
    p.evaluate("([ck])=>window.__gz.save([{name:'Ami',ck,kc:'BBBB'+'x'.repeat(39)+'=',kce:5,ts:1}])",[CK])
    p.evaluate("()=>window.__gz.chainCachePut()")
    m=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Ami',ck,kc:'AAAA'+'x'.repeat(39)+'=',kce:5,ts:1}]})",[CK])
    c=[x for x in m["contacts"] if x["ck"]==CK][0]
    r["tie_smallerWins"]= c["kc"].startswith("AAAA") and c["kce"]==5
    r["tie_cacheCleared"]= p.evaluate("()=>window.__gz.chainCacheSize()")==0
    # the reverse order gives the same answer (symmetric rule)
    p.evaluate("([ck])=>window.__gz.save([{name:'Ami',ck,kc:'AAAA'+'x'.repeat(39)+'=',kce:5,ts:1}])",[CK])
    m2=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Ami',ck,kc:'BBBB'+'x'.repeat(39)+'=',kce:5,ts:1}]})",[CK])
    r["tie_symmetric"]= [x for x in m2["contacts"] if x["ck"]==CK][0]["kc"].startswith("AAAA")
    # a more advanced epoch always wins, whatever the root
    m3=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Ami',ck,kc:'ZZZZ'+'x'.repeat(39)+'=',kce:7,ts:1}]})",[CK])
    r["newerEpochWins"]= [x for x in m3["contacts"] if x["ck"]==CK][0]["kc"].startswith("ZZZZ")
    # an older epoch never replaces a newer one
    p.evaluate("([ck])=>window.__gz.save([{name:'Ami',ck,kc:'ZZZZ'+'x'.repeat(39)+'=',kce:7,ts:1}])",[CK])
    m4=p.evaluate("([ck])=>window.__gz.merge({contacts:[{name:'Ami',ck,kc:'AAAA'+'x'.repeat(39)+'=',kce:5,ts:1}]})",[CK])
    r["olderEpochIgnored"]= [x for x in m4["contacts"] if x["ck"]==CK][0]["kce"]==7
    r["errors"]=errs[:3]
    b.close()
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
