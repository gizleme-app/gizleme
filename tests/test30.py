# Location sharing, turning a two-person chat into a group, and group invitations (opt-in: joining is the recipient's tap).
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site30"); site.mkdir(exist_ok=True)
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
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),meta:()=>_meta,merge:(r)=>mergeContacts(r)};\n})();\n'
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
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US", geolocation={"latitude":46.2728,"longitude":6.3612,"accuracy":18}, permissions=["geolocation","clipboard-read","clipboard-write"]); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    dlg=[]; p.on("dialog",lambda d:(dlg.append((d.type,d.default_value)), d.accept()))
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Florian',ck:ck,ts:Date.now()}]))",[CK])
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2000)
    p.click(".ct"); p.wait_for_timeout(700)
    # --- menu entries ---
    p.click("#menuBtn"); p.wait_for_timeout(150)
    r["menu_loc_togroup"]= p.is_visible("#mi-loc") and p.is_visible("#mi-info") and not p.is_visible("#mi-togroup")   # v37: "turn into a group" lives in Chat info
    # --- share my location ---
    p.evaluate("()=>{ window.__puts.length=0; }")
    p.click("#mi-loc"); p.wait_for_timeout(1500)
    card=p.evaluate("()=>{ const d=[...document.querySelectorAll('.log .bubble.sent')].pop(); if(!d) return null; const a=d.querySelector('.cl-btn'); return {t:d.querySelector('.cl-t').textContent, s:d.querySelector('.cl-s').textContent, href:a&&a.getAttribute('href'), target:a&&a.target, st:d.querySelector('.st')&&d.querySelector('.st').textContent}; }")
    r["loc_card"]= bool(card) and card["t"]=="My location" and "±18 m" in card["s"] and "46.27280, 6.36120" in card["s"]
    r["loc_mapsLink"]= bool(card) and "46.2728" in (card["href"] or "") and card["target"]=="_blank"
    r["loc_delivered"]= bool(card) and card["st"]=="✓" and p.evaluate("()=>window.__puts.filter(x=>!x.mid.startsWith('r')).length")==1
    r["loc_preview"]= p.eval_on_selector(".ct .cm","e=>e.textContent")
    # --- inbound location from Florian (mailbox) ---
    p.evaluate("([ck])=>window.__drop(ck,{t:'loc',lat:48.8566,lng:2.3522,acc:30,n:'Florian'},'flo-acct')",[CK]); p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    rc=p.evaluate("()=>{ const d=[...document.querySelectorAll('.log .bubble.recv')].pop(); if(!d) return null; const a=d.querySelector('.cl-btn'); return {t:d.querySelector('.cl-t').textContent, s:d.querySelector('.cl-s').textContent, href:a&&a.getAttribute('href')}; }")
    r["loc_recv"]= bool(rc) and rc["t"]=="Location" and "48.85660, 2.35220" in rc["s"] and "48.8566" in (rc["href"] or "")
    # an invalid location is ignored, not rendered
    p.evaluate("([ck])=>window.__drop(ck,{t:'loc',lat:999,lng:'x'},'flo-acct')",[CK]); p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1200)
    r["loc_invalidIgnored"]= p.eval_on_selector_all(".log .bubble.recv","els=>els.length")==1
    # --- inbound group invitation from Florian: the group appears, card with "Open the group" ---
    GK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck,gk])=>window.__drop(ck,{t:'ginv',rid:'abcdefghij123456',gk:gk,name:'Les potes',n:'Florian'},'flo-acct')",[CK,GK]); p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    r["ginv_notAddedSilently"]= p.evaluate("()=>window.__gz.groups().map(g=>g.name)")==[]   # joining is the recipient's choice
    gc=p.evaluate("()=>{ const d=[...document.querySelectorAll('.log .bubble.recv')].pop(); return d?{t:d.querySelector('.cl-t').textContent, btn:(d.querySelector('.cl-btn')||{}).textContent}:null; }")
    r["ginv_card"]= bool(gc) and gc["t"]=="Florian invited you to the group “Les potes”" and gc["btn"]=="Join the group"
    p.click(".log .bubble.recv:last-child .cl-btn"); p.wait_for_timeout(1200)
    r["ginv_openOpensGroup"]= p.eval_on_selector("#peerName","e=>e.textContent").startswith("Les potes") and p.evaluate("()=>document.getElementById('bar').classList.contains('st-online')")
    r["ginv_joinedOnTap"]= p.evaluate("()=>window.__gz.groups().map(g=>g.name)")==["Les potes"]
    # a second invitation for the same group doesn't rename it
    FLO="()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>x.querySelector('.cn').textContent.trim()==='Florian').click(); }"
    p.evaluate(FLO); p.wait_for_timeout(600)
    p.evaluate("([ck,gk])=>window.__drop(ck,{t:'ginv',rid:'abcdefghij123456',gk:gk,name:'Renamed by Flo',n:'Florian'},'flo-acct')",[CK,GK]); p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1200)
    r["ginv_noRename"]= p.evaluate("()=>window.__gz.groups().map(g=>g.name)")==["Les potes"]
    # --- turn the 1:1 chat into a group ---
    p.evaluate("()=>{ window.__puts.length=0; }")
    p.click("#peerMeta"); p.wait_for_timeout(250); r["info_togroup"]= p.is_visible("#ciToGroup") and p.is_visible("#ciLoc")
    p.click("#ciToGroup"); p.wait_for_timeout(2000)
    r["togroup_prompted"]= any(d[0]=="prompt" and d[1]=="oguz & Florian" for d in dlg) or p.evaluate("()=>(window.__asks||[]).some(t=>/Group name/.test(t))")
    r["togroup_modal"]= p.evaluate("()=>document.getElementById('ginvModal').classList.contains('show')") and "oguz & Florian" in p.eval_on_selector("#ginvTitle","e=>e.textContent") and "Florian has been invited" in p.eval_on_selector("#ginvSub","e=>e.textContent")
    r["togroup_groupCreated"]= p.evaluate("()=>window.__gz.groups().map(g=>g.name)")==["Les potes","oguz & Florian"]
    r["togroup_inGroupNow"]= p.eval_on_selector("#peerName","e=>e.textContent").startswith("oguz & Florian")
    r["togroup_invitationSentToContact"]= p.evaluate("()=>window.__puts.filter(x=>!x.mid.startsWith('r')).length")>=1
    r["togroup_sysline"]= p.eval_on_selector_all(".log .sys","els=>els.some(e=>e.textContent.includes('Group created from your chat with Florian'))")
    p.click("#ginvCopy"); p.wait_for_timeout(500)
    clip=p.evaluate("()=>navigator.clipboard.readText().catch(()=>'')")
    r["togroup_linkCopied"]= clip.startswith("https://gizleme.com/#g=") and not p.evaluate("()=>document.getElementById('ginvModal').classList.contains('show')")
    r["togroup_linkMatchesGroup"]= p.evaluate("([u])=>{ const o=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(u.split('#g=')[1].replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0)))); const g=window.__gz.groups()[1]; return o.rid===g.rid && o.gk===g.gk && o.name===g.name; }",[clip])
    # the 1:1 chat keeps a 'Group created' card and its preview says so
    p.evaluate(FLO); p.wait_for_timeout(600)
    r["togroup_cardIn1to1"]= p.eval_on_selector_all(".log:not([style*='display: none']) .bubble.sent .cl-t","els=>els.some(e=>e.textContent==='Group “oguz & Florian” created')")
    # in a group chat: location available, "turn into a group" not offered
    p.evaluate("()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>x.textContent.includes('Les potes')).click(); }"); p.wait_for_timeout(700)
    p.click("#menuBtn"); p.wait_for_timeout(150)
    r["group_menu"]= p.is_visible("#mi-loc") and p.is_visible("#mi-invite")
    p.keyboard.press("Escape"); p.click("#peerMeta"); p.wait_for_timeout(250)
    r["group_info"]= p.is_visible("#ciLoc") and p.is_visible("#ciMembers") and not p.is_visible("#ciToGroup") and p.eval_on_selector("#ciRemove .il","e=>e.textContent")=="Leave group"
    p.click("#ciBack"); p.wait_for_timeout(150)
    # history survives lock/unlock (cards re-rendered)
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(400)
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500); p.evaluate(FLO); p.wait_for_timeout(900)
    r["history_cards"]= p.eval_on_selector_all(".log:not([style*='display: none']) .bubble .cl-t","els=>els.map(e=>e.textContent)")
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
