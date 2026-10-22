# Lot A checks: CSP compatibility, contacts encrypted at rest (lock/logout residue), anti-replay on the live
# path, fragment deep links, photo upload through the relay function.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, re, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site12"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
csp=[l for l in pathlib.Path(SRC+"_headers").read_text().splitlines() if l.strip().startswith("Content-Security-Policy:")][0].split(":",1)[1].strip()
csp_meta=re.sub(r";\s*frame-ancestors[^;]*","",csp)
MOCK='''<script>
window.__calls=[]; window.__pstate={};
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{},
    on(type,opts,cb){ this._cbs[type+":"+(opts&&opts.event)]=cb; return this; },
    subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); },
    send(m){ window.__sent=(window.__sent||[]); window.__sent.push(m); return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({upload:async()=>{ window.__storageUpload=true; return {}; },getPublicUrl:(p)=>({data:{publicUrl:"/blob/"+p}}),remove:async()=>({})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{}; window.__calls.push([n,b.action]);
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-auth"&&b.action==="salt") return {data:{ok:true,salt:btoa("0123456789abcdef")}};
    if(n==="gizleme-auth"&&b.action==="login") return {data:{ok:true,token:"t2",username:b.username,display:b.username}};
    if(n==="gizleme-vault") return {data:{ok:true,abk:null,contacts:null,cver:0}};
    if(n==="gizleme-mbox"&&b.action==="putblob"){ window.__putblob=(b.data||"").length; return {data:{ok:true,path:"deadbeef".repeat(6)+".bin"}}; }
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
window.__sync=(state)=>{ window.__pstate=state; const cb=window.__chan&&window.__chan._cbs["presence:sync"]; cb&&cb(); };
window.__deliver=(payload)=>{ const cb=window.__chan&&window.__chan._cbs["broadcast:msg"]; cb&&cb({payload}); };
// a fake peer that speaks the protocol
const enc=new TextEncoder(), SALT=enc.encode("vesper/v1");
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))), unb=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
async function hkdf(ikm,info,len=32){ const k=await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]); return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8); }
window.__tag=async(ck,pub)=>{ const ik=await crypto.subtle.importKey("raw",unb(ck),"HKDF",false,["deriveBits"]);
  const bits=await crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode("gz-auth/v1")},ik,256);
  const hk=await crypto.subtle.importKey("raw",bits,{name:"HMAC",hash:"SHA-256"},false,["sign"]);
  return b64(await crypto.subtle.sign("HMAC",hk,unb(pub))); };
window.__peer={ async init(){ this.kp=await crypto.subtle.generateKey({name:"ECDH",namedCurve:"P-256"},true,["deriveBits"]); this.pub=b64(await crypto.subtle.exportKey("raw",this.kp.publicKey)); this.i=0; return this.pub; },
  async root(ourPubB64){ const pk=await crypto.subtle.importKey("raw",unb(ourPubB64),{name:"ECDH",namedCurve:"P-256"},false,[]); const sec=await crypto.subtle.deriveBits({name:"ECDH",public:pk},this.kp.privateKey,256); this._root=await hkdf(sec,"root"); },
  async msg(text, opts){ opts=opts||{}; const dir=opts.dir||(opts.me+">"+opts.them); const i=opts.i!==undefined?opts.i:this.i++;
    const mk=await hkdf(this._root,"msg|"+dir+"|"+i); const key=await crypto.subtle.importKey("raw",mk,{name:"AES-GCM"},false,["encrypt"]);
    const mid=opts.mid||Math.random().toString(16).slice(2); const env={t:"txt",body:text,mid:opts.innerMid===undefined?mid:opts.innerMid}; if(opts.noInnerMid) delete env.mid;
    const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify(env)));
    return {from:opts.from||opts.me,name:"Majins",dir,i,iv:b64(iv),ct:b64(ct),mid:opts.outerMid||mid}; } };
</script>'''
(site/"mock.js").write_text(MOCK.replace('<script>','').replace('</script>',''))   # same-origin file: the CSP forbids inline scripts
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
html=html.replace('<meta charset="utf-8"/>','<meta charset="utf-8"/>\n<meta http-equiv="Content-Security-Policy" content="'+csp_meta.replace('"','&quot;')+'"/>')
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad()};\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
png=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
(site/"tiny.png").write_bytes(png)
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
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}); p=ctx.new_page()
    errs=[]; csp_viol=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    p.on("console",lambda m: csp_viol.append(m.text) if "Content Security Policy" in m.text else None)
    p.on("dialog",lambda d:d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Majins',ck:ck,ts:Date.now()}]))",[CK])   # legacy plaintext from an older build
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
    # --- contacts at rest ---
    r["legacyPlaintextRemoved"]= p.evaluate("()=>localStorage.getItem('gz-contacts')===null && localStorage.getItem('gz-groups')===null")
    r["encryptedBlobPresent"]= p.evaluate("()=>{const r=JSON.parse(localStorage.getItem('gz-local')||'null'); return !!(r&&r.ct&&r.iv);}")
    r["blobHasNoKeyInClear"]= p.evaluate("([ck])=>!(localStorage.getItem('gz-local')||'').includes(ck.slice(0,12))",[CK])
    r["contactsInMemory"]= p.evaluate("()=>window.__gz.contacts().map(c=>c.name)")
    # --- live chat with the fake peer: anti-replay ---
    p.click(".ct"); p.wait_for_timeout(600)
    me=p.evaluate("()=>window.__chan._me.id"); ourPub=p.evaluate("()=>window.__chan._me.pub")
    peerPub=p.evaluate("()=>window.__peer.init()")
    tag=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK,peerPub])
    p.evaluate("([a,t])=>window.__sync({k1:[{id:'a1',name:'Majins',u:'other-acct',pub:a,tag:t}]})",[peerPub,tag]); p.wait_for_timeout(600)
    r["pairedVerified"]= p.eval_on_selector("#statusText","e=>e.textContent")
    p.evaluate("([pub])=>window.__peer.root(pub)",[ourPub])
    def recv(): return p.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    def fails(): return p.eval_on_selector_all(".log .bubble.fail","els=>els.map(e=>e.textContent)")
    def deliver(js): p.evaluate(js); p.wait_for_timeout(1300)   # scramble animation settles
    deliver(f"async()=>window.__deliver(await window.__peer.msg('hello 1',{{me:'a1',them:'{me}'}}))")
    r["normalMessageShown"]= recv()==["hello 1"]
    # replay: same ciphertext again under a fresh outer mid -> must not appear
    p.evaluate(f"async()=>{{ window.__replay=await window.__peer.msg('replayed',{{me:'a1',them:'{me}',i:5}}); }}")
    deliver("()=>window.__deliver(window.__replay)")
    deliver("()=>window.__deliver(Object.assign({},window.__replay,{mid:'fresh-'+Math.random()}))")
    r["replayIgnored"]= recv()==["hello 1","replayed"]
    # counter going backwards -> ignored
    deliver(f"async()=>window.__deliver(await window.__peer.msg('old counter',{{me:'a1',them:'{me}',i:2}}))")
    r["backwardCounterIgnored"]= "old counter" not in recv()
    # reflection: relay flips the sender id on a message in OUR direction -> ignored
    deliver(f"async()=>window.__deliver(await window.__peer.msg('reflected',{{me:'a1',them:'{me}',dir:'{me}>a1',i:9}}))")
    r["reflectionIgnored"]= "reflected" not in recv()
    # id tampering: outer mid differs from the sealed inner mid -> not shown (treated as undecryptable)
    deliver(f"async()=>window.__deliver(await window.__peer.msg('tampered',{{me:'a1',them:'{me}',i:10,innerMid:'inner-x',outerMid:'outer-y'}}))")
    r["midMismatchIgnored"]= "tampered" not in recv()
    # a message from someone who is not our paired peer -> ignored (no scary failure line either)
    deliver(f"async()=>window.__deliver(await window.__peer.msg('stranger',{{me:'zz9',them:'{me}',from:'zz9',i:11}}))")
    r["strangerIgnored"]= "stranger" not in recv() and not fails()
    # our own sent message seals the mid inside
    p.fill("#msgInput","hi back"); p.click("#sendBtn"); p.wait_for_timeout(500)
    sent=p.evaluate("()=>window.__sent[window.__sent.length-1].payload")
    r["sentHasMid"]= bool(sent.get("mid")) and sent.get("dir")==f"{me}>a1"
    # --- photo goes through the relay function, never the storage client ---
    p.set_input_files("#fileInput", str(site/"tiny.png")); p.wait_for_timeout(1200)
    r["photoViaFunction"]= p.evaluate("()=>!!window.__putblob && !window.__storageUpload")
    r["photoBubble"]= p.eval_on_selector_all(".log .bubble.img-wrap","els=>els.length")==1
    # --- lock: nothing readable in memory; unlock: back ---
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(400)
    r["lockedContactsCleared"]= p.evaluate("()=>window.__gz.contacts().length")==0
    r["lockedBlobStays"]= p.evaluate("()=>!!localStorage.getItem('gz-local')")
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1200)
    r["unlockContactsBack"]= p.evaluate("()=>window.__gz.contacts().map(c=>c.name)")
    # --- deep links in the fragment ---
    nk=p.evaluate("([ck])=>(async()=>{const enc=new TextEncoder();const k=await crypto.subtle.importKey('raw',Uint8Array.from(atob(ck),c=>c.charCodeAt(0)),'HKDF',false,['deriveBits']);const bits=await crypto.subtle.deriveBits({name:'HKDF',hash:'SHA-256',salt:enc.encode('vesper/v1'),info:enc.encode('gz-notify/v1')},k,256);return btoa(String.fromCharCode(...new Uint8Array(bits))).replace(/\\+/g,'-').replace(/\\//g,'_').replace(/=+$/,'');})()",[CK])
    p.goto(f"http://127.0.0.1:{port}/?x=2#n={nk}"); p.wait_for_timeout(500)
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
    r["hashNotifyOpensContact"]= p.eval_on_selector("#peerName","e=>e.textContent").startswith("Majins")
    p.click("#sbNew"); p.wait_for_timeout(300); p.click("#advRoom"); p.wait_for_timeout(150); p.fill("#roomInput","QRST23"); p.click("#joinBtn"); p.wait_for_timeout(600)
    r["roomInFragment"]= p.evaluate("()=>location.hash==='#room=QRST23' && location.search===''")
    # --- logout erases everything ---
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.evaluate("()=>document.querySelector('#settingsModal [data-go=account]').click()"); p.wait_for_timeout(150); p.click("#logoutBtn"); p.wait_for_timeout(1500)
    r["logoutLocalGone"]= p.evaluate("()=>localStorage.getItem('gz-local')===null && localStorage.getItem('gz-mkpin')===null && localStorage.getItem('gz-abk')===null")
    r["logoutIdbGone"]= p.evaluate("async()=>!(await indexedDB.databases()).some(d=>d.name==='vesper')")
    r["cspViolations"]= csp_viol[:3]
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
