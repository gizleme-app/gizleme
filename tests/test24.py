# Push notifications composed on the receiving device: the service worker gets the names you use for your
# contacts (nickname first) and sentence templates in your language, kept in a small cache entry.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, subprocess, json

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site24"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__pstate={}; window.__notify=[];
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
    if(n==="gizleme-push"&&b.action==="notify"){ window.__notify.push(b); return {data:{ok:true,sent:1}}; }
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
const enc=new TextEncoder(), SALT=enc.encode("vesper/v1");
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))), unb=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const b64url=b=>b64(b).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
async function hkdf(ikm,info,len=32){ const k=await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]); return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8); }
window.__nk=async(ck)=>b64url(await hkdf(unb(ck),"gz-notify/v1"));
window.__names=async()=>{ const c=await caches.open("gizleme-meta"); const r=await c.match("/names.json"); return r?await r.json():null; };
'''
(site/"mock.js").write_text(MOCK)
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); }; window.__gz={contacts:()=>contactsLoad(),swNames:()=>swNames()};\n})();\n'
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
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    nick=["Baba"]; p.on("dialog",lambda d: d.accept(nick[0]) if d.type=="prompt" else d.accept()); ctx.add_init_script("window.__promptValue='Baba';")
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    CK2=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    NK=p.evaluate("([ck])=>window.__nk(ck)",[CK]); NK2=p.evaluate("([ck])=>window.__nk(ck)",[CK2])
    import hashlib, base64 as _b
    _h=lambda k: _b.urlsafe_b64encode(hashlib.sha256(k.encode()).digest()).decode().rstrip("=")
    NKH=_h(NK); NK2H=_h(NK2)
    # one real contact, one invite not yet opened (placeholder name)
    p.evaluate("([ck,ck2])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Oz77',ck:ck,ts:Date.now()},{name:'Invited friend',ck:ck2,is:'x',ts:Date.now()}]))",[CK,CK2])
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","fille"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(2500)
    r["sw_active"]= p.evaluate("()=>navigator.serviceWorker.ready.then(r=>!!r.active)")
    n=p.evaluate("()=>window.__names()")
    r["names_afterLogin"]= n and n["names"].get(NKH)=="Oz77" and NK2H not in n["names"] and NK not in n["names"]
    r["tmpl_en"]= n and n["tmpl"].get("msg")=="New message from {name}" and n["tmpl"].get("anyMsg")=="New message"
    # rename for me → "Baba" reaches the worker
    p.click(".ct"); p.wait_for_timeout(500); p.click("#peerMeta"); p.wait_for_timeout(200); p.click("#ciRename"); p.wait_for_timeout(1200); p.click("#ciBack"); p.wait_for_timeout(150)
    n=p.evaluate("()=>window.__names()"); r["names_afterRename"]= n and n["names"].get(NKH)=="Baba"
    # the sender side now says what kind of push it is
    p.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); p.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); p.wait_for_timeout(100)
    p.select_option("#langSel","fr"); p.wait_for_timeout(1200)
    n=p.evaluate("()=>window.__names()"); r["tmpl_fr"]= n and n["tmpl"].get("msg")=="Nouveau message de {name}" and n["names"].get(NKH)=="Baba"
    r["errors"]= errs[:3]
    # logout clears the names
    p.evaluate("()=>document.querySelector('#settingsModal [data-go=account]').click()"); p.click("#logoutBtn"); p.wait_for_timeout(1500)
    n=p.evaluate("()=>window.__names()"); r["cleared_onLogout"]= n is not None and n["names"]=={}
    b.close()
srv.shutdown()

# the worker's composition, run against the real sw.js source
NODE=r'''
const vm=require("vm"), fs=require("fs");
const self={addEventListener(){}, location:{origin:"https://gizleme.com"}, clients:{}, registration:{}, skipWaiting(){}};
vm.runInNewContext(fs.readFileSync(process.argv[3],"utf8"),{self, URL, Response:class{}, caches:{}, fetch(){}, console, crypto:require("crypto").webcrypto, TextEncoder, btoa, Uint8Array});
const cb=self.__composeBody;
const NK=process.argv[1]; const NKH=process.argv[2]; const url="https://gizleme.com/#n="+encodeURIComponent(NK);
const meta={names:{[NKH]:"Baba"}, tmpl:{msg:"Nouveau message de {name}", chat:"{name} veut discuter sur Gizleme", anyMsg:"Nouveau message", anyChat:"Un contact veut discuter"}};
(async()=>{ const out={
  known_msg: await cb({body:"New message from Oz77",kind:"msg",url}, meta),
  known_chat: await cb({body:"Oz77 wants to chat on Gizleme",kind:"chat",url}, meta),
  unknown_msg: await cb({body:"New message from Someone",kind:"msg",url:"https://gizleme.com/#n=other"}, meta),
  unknown_chat: await cb({body:"Someone wants to chat on Gizleme",kind:"chat",url:"https://gizleme.com/#n=other"}, meta),
  no_meta: await cb({body:"New message from Oz77",kind:"msg",url}, null),
  old_payload_no_kind: await cb({body:"New message from Oz77",url}, meta),
  long_name: (await cb({body:"x",kind:"msg",url}, {names:{[NKH]:"B".repeat(300)}, tmpl:meta.tmpl})).length<=140,
};
console.log(JSON.stringify(out)); })();
'''
out=subprocess.run(["node","-e",NODE,NK,NKH,SRC+"sw.js"],capture_output=True,text=True)
try: r["sw_compose"]=json.loads(out.stdout.strip())
except Exception: r["sw_compose"]=out.stdout+out.stderr
print("RESULTS")
for k,v in r.items(): print(f"  {k}: {v}")
