# Lot B account & UX: compact lock screen, forgot-password modal, change password (local key re-wrapped,
# server called with the old av), delete account (server + full local wipe), WhatsApp-iOS webview note,
# contact removal confirmation, 15-min default auto-lock.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site14"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__calls=[]; window.__pstate={};
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{}, on(){ return this; }, subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); }, send(){ return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({upload:async()=>({}),getPublicUrl:(p)=>({data:{publicUrl:"/blob/"+p}}),remove:async()=>({})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{}; window.__calls.push([n,b]);
    if(n==="gizleme-auth"&&b.action==="register"){ window.__verifier=b.verifier; window.__salt=b.salt; return {data:{ok:true,token:"t",username:b.username,display:b.display}}; }
    if(n==="gizleme-auth"&&b.action==="salt") return {data:{ok:true,salt:window.__salt}};
    if(n==="gizleme-auth"&&(b.action==="changepw"||b.action==="delete")){
      const calc=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.digest("SHA-256",Uint8Array.from(atob(b.av),c=>c.charCodeAt(0))))));
      if(calc!==window.__verifier) return {data:null,error:{context:{status:401}}};
      if(b.action==="changepw"){ window.__verifier=b.verifier; window.__salt=b.salt; if(b.abk){ window.__rewrap=b; window.__abk=b.abk; } }   // one request, one transaction server-side
      return {data:{ok:true}}; }
    if(n==="gizleme-vault"&&b.action==="pull") return {data:{ok:true,abk:window.__abk||null,contacts:null,cver:0}};
    if(n==="gizleme-vault"&&b.action==="pushAbk"){ window.__abk=b.abk; return {data:{ok:true}}; }
    if(n==="gizleme-vault"&&b.action==="rewrapAbk"){ window.__rewrap=b; window.__abk=b.abk; return {data:{ok:true}}; }
    if(n==="gizleme-vault") return {data:{ok:true,cver:1}};
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
'''
(site/"mock.js").write_text(MOCK)
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad()};\n})();\n'
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
WA_IOS="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
SAFARI_IOS="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"

r={}
with sync_playwright() as pw:
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":414,"height":820}); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    dialogs=[]; accept=[True]
    p.on("dialog",lambda d:(dialogs.append(d.message), d.accept() if accept[0] else d.dismiss()))
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    r["register_noResetWarning"]= "no password reset" in p.eval_on_selector("#joinHint","e=>e.textContent")
    p.evaluate("()=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Bob',ck:btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))),ts:Date.now()}]))")
    p.fill("#userInput","oguz"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2500)
    r["defaultAutoLock15"]= p.evaluate("()=>localStorage.getItem('gz-autolock')")=="900000"
    # --- contact removal asks first; dismiss keeps it ---
    accept[0]=False; p.evaluate("()=>document.querySelector('.ct .cx').click()"); p.wait_for_timeout(300)
    r["remove_asked"]= any("Remove Bob" in m for m in dialogs); r["remove_dismissKeeps"]= p.evaluate("()=>window.__gz.contacts().length")==1
    accept[0]=True
    # --- lock screen: compact, biometrics-first layout, forgot link ---
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(400)
    r["lock_head"]= p.is_visible("#lockHead"); r["lock_heroHidden"]= not p.is_visible(".brandhero"); r["lock_forgotLink"]= p.is_visible("#forgotLink")
    r["lock_bioBeforePassword"]= p.evaluate("()=>{const b=document.getElementById('bioBtn'), f=document.getElementById('pwField'); return !!(b.compareDocumentPosition(f) & Node.DOCUMENT_POSITION_FOLLOWING);}")
    p.click("#forgotLink"); p.wait_for_timeout(200); r["forgot_modal"]= p.is_visible("#forgotModal"); p.click("#forgotClose"); p.wait_for_timeout(100)
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
    # --- change password ---
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.wait_for_timeout(100); p.click("#chpwBtn"); p.wait_for_timeout(200)
    p.fill("#pwCur","wrongpass"); p.fill("#pwNew","newpass456"); p.fill("#pwNew2","newpass456"); p.click("#pwSave"); p.wait_for_timeout(1200)
    r["chpw_wrongCurrentRefused"]= p.eval_on_selector("#pwMsg","e=>e.textContent")
    p.fill("#pwCur","password123"); p.click("#pwSave"); p.wait_for_timeout(2500)
    r["chpw_modalClosed"]= not p.is_visible("#pwModal")
    r["chpw_serverCalled"]= p.evaluate("()=>window.__calls.some(c=>c[0]==='gizleme-auth'&&c[1].action==='changepw'&&c[1].salt&&c[1].verifier)")
    r["chpw_abkRewrapped"]= p.evaluate("()=>!!(window.__rewrap&&window.__rewrap.abk&&window.__rewrap.abk.iv&&window.__rewrap.abk.ct&&window.__rewrap.action==='changepw')")
    # lock → old password fails, new password unlocks and contacts are still there
    p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(400)
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(800); r["chpw_oldPwFails"]= p.eval_on_selector("#authMsg","e=>e.textContent")=="Wrong password"
    p.fill("#pwInput","newpass456"); p.click("#joinBtn"); p.wait_for_timeout(1500); r["chpw_newPwUnlocks"]= p.evaluate("()=>window.__gz.contacts().map(c=>c.name)")==["Bob"]
    # --- delete account ---
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.wait_for_timeout(100); p.click("#delAcctBtn"); p.wait_for_timeout(200)
    p.fill("#delPw","newpass456"); p.click("#delConfirm"); p.wait_for_timeout(2500)
    r["delete_serverCalled"]= p.evaluate("()=>window.__calls.some(c=>c[0]==='gizleme-auth'&&c[1].action==='delete'&&Array.isArray(c[1].owners))")
    r["delete_backToRegister"]= p.get_attribute("#join","data-mode")=="register"
    r["delete_localWiped"]= p.evaluate("()=>Object.keys(localStorage).filter(k=>['gz-session','gz-local','gz-mkpin','gz-abk','gz-contacts'].includes(k)).length")==0
    r["delete_idbGone"]= p.evaluate("async()=>!(await indexedDB.databases()).some(d=>d.name==='vesper')")
    # --- WhatsApp iOS in-app browser: note on the register screen; Safari: none ---
    for name,ua in [("waIos",WA_IOS),("safariIos",SAFARI_IOS)]:
        c2=b.new_context(viewport={"width":390,"height":780}, user_agent=ua); p2=c2.new_page(); p2.goto(f"http://127.0.0.1:{port}/"); p2.wait_for_timeout(400)
        r[name+"_iabNote"]= p2.is_visible("#iabNote") and ("Open in Safari" in p2.eval_on_selector("#iabNote","e=>e.textContent")) if name=="waIos" else p2.is_visible("#iabNote")
        r[name+"_iabBar"]= p2.is_visible("#iabBar"); c2.close()
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
