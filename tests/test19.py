# Lot B messaging: inbox for closed chats (badges/previews without opening), timestamps + day separators,
# send states (sent / received receipt / failed→retry), unviewed photo persisted across lock, own-device
# copies, push independent of the sender's own setting.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, re, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site13"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__calls=[]; window.__puts=[]; window.__MBOX={}; window.__pstate={}; window.__notify=null;
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{},
    on(type,opts,cb){ this._cbs[type+":"+(opts&&opts.event)]=cb; return this; },
    subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); },
    send(m){ (window.__sent=window.__sent||[]).push(m); return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({upload:async()=>({}),getPublicUrl:(p)=>({data:{publicUrl:"/blob/"+p}}),remove:async()=>({})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{}; window.__calls.push([n,b.action]);
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-auth"&&b.action==="salt") return {data:{ok:true,salt:btoa("0123456789abcdef")}};
    if(n==="gizleme-vault") return {data:{ok:true,abk:null,contacts:null,cver:0}};
    if(n==="gizleme-push"&&b.action==="notify"){ window.__notify=b; return {data:{ok:true,sent:1}}; }
    if(n==="gizleme-mbox"&&b.action==="get"){ const items=(window.__MBOX[b.mbox]||[]).filter(it=>!b.since||Date.parse(it.ts)>Date.parse(b.since)); return {data:{ok:true,items}}; }
    if(n==="gizleme-mbox"&&b.action==="put"){ if(window.__putFail) return {data:{ok:false}}; window.__puts.push(b); return {data:{ok:true}}; }
    if(n==="gizleme-mbox"&&b.action==="putblob"){ return {data:{ok:true,path:"deadbeef".repeat(6)+".bin"}}; }
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
// crypto helpers mirroring the app (mailbox id/key from a contact key)
const enc=new TextEncoder(), SALT=enc.encode("vesper/v1");
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))), unb=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const b64url=b=>b64(b).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
async function hkdf(ikm,info,len=32){ const k=await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]); return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8); }
window.__mboxId=async ck=>b64url(new Uint8Array(await hkdf(unb(ck),"gz-mbox/v1",16)));
window.__seal=async(ck,env)=>{ const key=await crypto.subtle.importKey("raw",await hkdf(unb(ck),"gz-mbox-key/v1"),{name:"AES-GCM"},false,["encrypt"]);
  const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:"AES-GCM",iv},key,enc.encode(JSON.stringify(env))); return {iv:b64(iv),ct:b64(ct)}; };
window.__open=async(ck,data)=>{ const key=await crypto.subtle.importKey("raw",await hkdf(unb(ck),"gz-mbox-key/v1"),{name:"AES-GCM"},false,["decrypt"]);
  return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:"AES-GCM",iv:unb(data.iv)},key,unb(data.ct)))); };
window.__drop=async(ck,env,from,tsOffset)=>{ const id=await window.__mboxId(ck); const mid=env.mid||("m"+Math.random().toString(16).slice(2)); env.mid=mid;
  (window.__MBOX[id]=window.__MBOX[id]||[]).push({mid, from_user:from||"peer-acct", data:await window.__seal(ck,env), ts:new Date(Date.now()+(tsOffset||0)).toISOString()}); return mid; };
'''
(site/"mock.js").write_text(MOCK)
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),meta:()=>_meta};\n})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg"]:
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
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    mk=lambda: p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    CKB, CKC = mk(), mk()
    p.evaluate("([a,b])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Bob',ck:a,ts:Date.now()-5000},{name:'Camille',ck:b,ts:Date.now()-9000}]))",[CKB,CKC])
    # two messages wait in Camille's mailbox before we even log in (one from yesterday)
    p.evaluate("([ck])=>window.__drop(ck,{t:'txt',body:'Coucou, tu es là ?',n:'Camille'},'cam-acct',-82800000)",[CKC])
    p.evaluate("([ck])=>window.__drop(ck,{t:'txt',body:'Rappelle-moi stp',n:'Camille'},'cam-acct',-1000)",[CKC])
    p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2500)
    def rows(): return p.eval_on_selector_all(".ct","els=>els.map(e=>({name:e.querySelector('.cn').textContent.trim(),prev:e.querySelector('.cm').textContent,badge:(e.querySelector('.ubadge')||{}).textContent||''}))")
    rw=rows()
    r["inbox_badgeWithoutOpening"]= [x for x in rw if x["name"]=="Camille"][0]["badge"]=="2"
    r["inbox_previewWithoutOpening"]= [x for x in rw if x["name"]=="Camille"][0]["prev"]=="Rappelle-moi stp"
    r["inbox_sortedByActivity"]= [x["name"] for x in rw][0]=="Camille"
    r["inbox_persistedUnread"]= p.evaluate("()=>Object.values(window.__gz.meta().unread)")==[2]
    # open Camille: messages are there with times and a day separator; unread cleared; receipt deposited
    p.click(".ct >> text=Camille"); p.wait_for_timeout(1500)
    r["open_recv"]= p.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    r["open_timesShown"]= p.eval_on_selector_all(".log .bubble.recv .meta .time","els=>els.every(e=>/\\d{1,2}:\\d{2}/.test(e.textContent))")
    r["open_daySeps"]= p.eval_on_selector_all(".log .daysep","els=>els.map(e=>e.textContent)")
    r["open_unreadCleared"]= [x for x in rows() if x["name"]=="Camille"][0]["badge"]==""
    p.wait_for_timeout(1200)
    rc=p.evaluate("()=>window.__puts.filter(x=>x.mid.startsWith('r'))")
    r["receipt_deposited"]= len(rc)==1
    r["receipt_content"]= p.evaluate("([ck,d])=>window.__open(ck,d)",[CKC,rc[0]["data"]]) if rc else None
    r["receipt_coversBothMids"]= bool(rc) and sorted(r["receipt_content"]["mids"])==sorted(p.evaluate("()=>Object.values(window.__MBOX).flat().map(x=>x.mid)"))
    # send to Camille (offline): bubble shows time + ✓, push sent WITHOUT our own notifications being on
    p.fill("#msgInput","Je te rappelle ce soir"); p.click("#sendBtn"); p.wait_for_timeout(800)
    r["sent_state"]= p.eval_on_selector(".log .bubble.sent:last-of-type .st","e=>e.dataset.st")
    r["push_sentWithoutOwnPush"]= p.evaluate("()=>window.__notify && window.__notify.body")
    mySent=p.evaluate("()=>window.__puts.filter(x=>!x.mid.startsWith('r')).map(x=>x.mid)")
    myAcct=p.evaluate("()=>window.__puts[0].from")
    # Camille's device acknowledges: a receipt lands in the mailbox → ✓✓
    p.evaluate("([ck,mids])=>window.__drop(ck,{t:'rcpt',mids},'cam-acct',500)",[CKC,mySent]); p.wait_for_timeout(300)
    p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    r["sent_receivedState"]= p.eval_on_selector(".log .bubble.sent .st","e=>e.dataset.st")
    r["rcpt_persisted"]= p.evaluate("([m])=>!!window.__gz.meta().rcpt[m]",[mySent[0]])
    # our other device wrote to Camille: shows here as our own message, no badge
    p.evaluate("([ck,me])=>window.__drop(ck,{t:'txt',body:'(depuis mon iPad)',n:'oguz'},me,800)",[CKC,myAcct]); p.wait_for_timeout(200)
    p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    r["ownDeviceCopy_asSent"]= p.eval_on_selector_all(".log .bubble.sent .txt","els=>els.map(e=>e.textContent)")
    # failure → tap to retry
    p.evaluate("()=>{ window.__putFail=true; }")
    p.fill("#msgInput","ça passe ?"); p.click("#sendBtn"); p.wait_for_timeout(800)
    r["fail_state"]= p.eval_on_selector(".log .bubble.sent:last-of-type .st","e=>e.dataset.st")
    r["fail_notSavedYet"]= p.evaluate("()=>window.__puts.filter(x=>!x.mid.startsWith('r')).length")==1
    p.evaluate("()=>{ window.__putFail=false; }"); p.click(".log .bubble.failed"); p.wait_for_timeout(800)
    r["retry_state"]= p.eval_on_selector(".log .bubble.sent:last-of-type .st","e=>e.dataset.st")
    # a photo arrives for Bob while his chat is closed; it survives lock/unlock as "tap to view"
    p.evaluate("([ck])=>window.__drop(ck,{t:'img',path:'x.bin',k:'a',iv:'b',mime:'image/jpeg',once:true,n:'Bob'},'bob-acct',900)",[CKB]); p.wait_for_timeout(200)
    p.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); p.wait_for_timeout(1500)
    r["photo_badgeOnBob"]= [x for x in rows() if x["name"]=="Bob"][0]["badge"]=="1"
    r["photo_previewOnBob"]= [x for x in rows() if x["name"]=="Bob"][0]["prev"]=="📷 Photo"
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(400)
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(2000)
    r["afterUnlock_badgeKept"]= [x for x in rows() if x["name"]=="Bob"][0]["badge"]=="1"
    p.click(".ct >> text=Bob"); p.wait_for_timeout(1200)
    r["afterUnlock_photoTapToView"]= p.eval_on_selector_all(".log .tapview","els=>els.length")==1
    r["noKeyTags"]= p.evaluate("()=>!document.querySelector('.log .tag')")
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
