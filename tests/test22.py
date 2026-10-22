# Protocol v2: single-use invite links. A fake peer holding the link key pairs live (authenticated with the
# link key) → both derive the same rotated key from the ECDH secret; the link key is retired; history stays
# attached; later presence signed with the old link key is not paired with (calm "stale" note, no alarm);
# a holder of the old link who writes to the old mailbox is never read; vault merge and re-opened links
# resolve to the rotated contact.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site16"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__calls=[]; window.__puts=[]; window.__gets=[]; window.__MBOX={}; window.__pstate={}; window.__vault={abk:null,contacts:null,cver:0};
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{}, _tracks:[],
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
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={legacyPending:()=>{ const l=contactsLoad(); l.forEach(c=>{ if(c.inv&&c.pk){ delete c.pk; delete c.pp; delete c.v3; } }); contactsSave(l); },contacts:()=>contactsLoad(),groups:()=>groupsLoad(),meta:()=>_meta,merge:(r)=>mergeContacts(r)};\n})();\n'
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
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    # Oguz registers and invites; Camille (fake peer) has opened the link: both hold the LINK key
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2000)
    p.click("#sbNew"); p.wait_for_timeout(300); link=p.eval_on_selector("#invLinkOut","e=>e.value"); p.click("#joinBtn"); p.wait_for_timeout(1500); p.evaluate("()=>window.__gz.legacyPending()")
    secret=json.loads(base64.urlsafe_b64decode(link.split("#i=")[1]+"=="))["s"]
    CK0=p.evaluate("([s])=>window.__ckFromSecret(s)",[secret])
    r["placeholderContact"]= p.evaluate("()=>window.__gz.contacts().map(c=>[c.name,!!c.is])")
    # a message from Camille's device waited in the (link-key) mailbox → delivered into history under the stable key
    p.evaluate("([ck])=>window.__drop(ck,{t:'txt',body:'Salut Oguz !',n:'Camille'},'cam-acct')",[CK0]); p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    r["beforeRotation_recv"]= p.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    # --- Camille comes online, signs with the LINK key → authenticated pairing → rotation on our side ---
    ourPub=p.evaluate("()=>window.__chan._me.pub"); peerPub=p.evaluate("()=>window.__peer.init()")
    tag0=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK0,peerPub])
    p.evaluate("([a,t])=>window.__sync({k1:[{id:'a1',name:'Camille',u:'cam-acct',pub:a,tag:t}]})",[peerPub,tag0]); p.wait_for_timeout(1500)
    r["paired"]= p.eval_on_selector("#peerMeta","e=>e.title")
    r["retiredLine"]= p.eval_on_selector_all(".log .sys","els=>els.some(e=>e.textContent.includes('Invite link closed'))")
    c=p.evaluate("()=>window.__gz.contacts()[0]")
    CK2=p.evaluate("([pub])=>window.__peer.rotated(pub)",[ourPub])          # what Camille's device derives independently
    r["rotation_sameKeyBothSides"]= c["ck"]==CK2 and c["ck"]!=CK0
    r["rotation_record"]= {"prev":c.get("prev")==CK0, "hk":c.get("hk")=="c:"+CK0, "rot":bool(c.get("rot")), "isDeleted":"is" not in c, "name":c["name"]}
    # our re-announced presence is signed with the rotated key (Camille can verify it with HER derived key)
    last=p.evaluate("()=>window.__chan._tracks[window.__chan._tracks.length-1]")
    r["reannouncedUnderNewKey"]= p.evaluate("([ck,pub,tag])=>window.__verify(ck,pub,tag)",[CK2,last["pub"],last["tag"]])
    # right after the first (link-key) pairing the window is still open: the link key is kept alive so a peer
    # who has not rotated yet is still reached. It closes only once Camille confirms (rk) she sees us on the
    # new key AND signs with it — mirroring a real client — so neither side is left on a different room.
    r["reconActiveRightAfterRotation"]= p.evaluate("()=>!!window.__gz.contacts()[0].recon")
    cP=p.evaluate("()=>window.__peer.init()"); cT=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK2,cP])
    p.evaluate("([a,t])=>window.__sync({kc:[{id:'ac',name:'Camille',u:'cam-acct',pub:a,tag:t,rk:1}]})",[cP,cT]); p.wait_for_timeout(900)
    r["reconClearedOnMutual"]= p.evaluate("()=>!window.__gz.contacts()[0].recon")
    # history survived the rotation (same stable key), previews too
    r["previewKept"]= p.eval_on_selector(".ct .cm","e=>e.textContent")   # sidebar is visible at desktop width
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(400)      # lock/unlock → history reloaded from disk under the stable key
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500); p.click(".ct"); p.wait_for_timeout(800)
    r["historyKept"]= p.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    r["unreadKeyStable"]= p.evaluate("([k])=>Object.keys(window.__gz.meta().unread).every(x=>x==='c:'+k)||Object.keys(window.__gz.meta().unread).length===0",[CK0])
    # sending now deposits into the NEW mailbox, never the old one
    p.evaluate("()=>{ window.__puts.length=0; }")
    p.fill("#msgInput","après rotation"); p.click("#sendBtn"); p.wait_for_timeout(800)
    newId=p.evaluate("([ck])=>window.__mboxId(ck)",[CK2]); oldId=p.evaluate("([ck])=>window.__mboxId(ck)",[CK0])
    r["depositsToNewMailbox"]= p.evaluate("()=>window.__puts.filter(x=>!x.mid.startsWith('r')).map(x=>x.mbox)")==[newId]
    # someone who kept the link writes to the OLD mailbox → never read
    p.evaluate("([ck])=>window.__drop(ck,{t:'txt',body:'je suis l intrus',n:'Camille'},'evil-acct')",[CK0]); p.evaluate("()=>{ window.__gets.length=0; }")
    p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    r["oldMailboxNotPolled"]= oldId not in p.evaluate("()=>window.__gets")
    r["intruderNotShown"]= "je suis l intrus" not in p.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    # a device still signing with the LINK key (leaked link, or Camille's un-synced tablet): no pairing, calm note, no alarm
    p.evaluate("()=>window.__sync({})"); p.wait_for_timeout(400)
    leakPub=p.evaluate("()=>window.__peer.init()"); leakTag=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK0,leakPub])
    p.evaluate("([a,t])=>window.__sync({k9:[{id:'z9',name:'Camille',u:'other-acct',pub:a,tag:t}]})",[leakPub,leakTag]); p.wait_for_timeout(1200)
    r["stale_notPaired"]= not p.eval_on_selector("#sendBtn","e=>e.disabled") and not p.eval_on_selector("#bar","e=>e.classList.contains('st-online')")
    r["stale_calmNote"]= p.eval_on_selector_all(".log .sys","els=>els.some(e=>e.textContent.includes('retired invite key'))")
    r["stale_noAlarm"]= p.eval_on_selector_all(".log .sys.warnline","els=>els.map(e=>e.textContent)")==[]
    # Camille comes back signing with the ROTATED key → paired again, verified
    camPub=p.evaluate("()=>window.__peer.init()"); camTag=p.evaluate("([ck,pub])=>window.__tag(ck,pub)",[CK2,camPub])
    p.evaluate("([a,t])=>window.__sync({k2:[{id:'a2',name:'Camille',u:'cam-acct',pub:a,tag:t}]})",[camPub,camTag]); p.wait_for_timeout(1200)
    r["rotatedKey_pairs"]= "same key as your first connection" in p.eval_on_selector("#peerMeta","e=>e.title")
    # vault merge: our other device still has the pre-rotation record → one contact, the rotated one
    m=p.evaluate("([ck0])=>window.__gz.merge({contacts:[{name:'Camille',ck:ck0,inv:1,ts:Date.now()+5,v:1}],groups:[]})",[CK0])
    r["merge_oneContact"]= len(m["contacts"])==1 and m["contacts"][0]["ck"]==CK2 and m["contacts"][0].get("v")==1
    r["merge_debug"]= [(c["ck"]==CK2, c["ck"]==CK0, c.get("v"), c.get("prev")==CK0) for c in m["contacts"]]
    # the reverse: a device that only knows the rotated record merging an old one from the vault
    m2=p.evaluate("([ck0,ck2])=>{ const rot=window.__gz.contacts()[0]; return window.__gz.merge({contacts:[rot],groups:[]}); }",[CK0,CK2])
    r["merge_idempotent"]= len(m2["contacts"])==1
    # opening the same link again (e.g. Camille's second device) resolves to the rotated contact, no duplicate
    p.goto(f"http://127.0.0.1:{port}/?r=2#i="+link.split("#i=")[1]); p.wait_for_timeout(400)   # new query → real reload (a same-document hash change would not)
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
    r["reopenLink_noDuplicate"]= p.evaluate("()=>window.__gz.contacts().length")==1
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
