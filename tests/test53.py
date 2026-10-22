# v37 "structure": a short welcome before the sign-up form (the form comes alone; an invite link goes straight to
# it), Settings as pages (Profile, Privacy, Chats, Notifications and sounds, Account — delete at the bottom),
# and Chat info from a tap on the name (colour, nickname, timer, mute, verify, notify, group, keys, remove) with
# a short ⋮ menu (Chat info, mute, location).
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site53"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__notify=[]; window.__vault={abk:null,contacts:null,cver:0};
const enc=new TextEncoder(), SALT=enc.encode("vesper/v1");
const b64=b=>btoa(String.fromCharCode(...new Uint8Array(b))), unb=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const b64url=b=>b64(b).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,"");
async function hkdf(ikm,info,len=32){ const k=await crypto.subtle.importKey("raw",ikm,"HKDF",false,["deriveBits"]); return crypto.subtle.deriveBits({name:"HKDF",hash:"SHA-256",salt:SALT,info:enc.encode(info)},k,len*8); }
window.__ckFromSecret=async s=>b64(await hkdf(unb(s),"gz-invite/v1"));
window.__mboxId=async ck=>b64url(new Uint8Array(await hkdf(unb(ck),"gz-mbox/v1",16)));
function relayChannel(name, opts){
  const key=opts&&opts.config&&opts.config.presence&&opts.config.presence.key; const inst=Math.random().toString(36).slice(2);
  const c={ _cbs:{}, _since:0, _pres:{}, _presJ:"", _dead:false,
    on(type,o,cb){ this._cbs[type+":"+(o&&o.event)]=cb; return this; },
    subscribe(cb){ this._poll=setInterval(()=>this._tick(),110); setTimeout(()=>cb&&cb("SUBSCRIBED"),10); return this; },
    async _tick(){ if(this._dead) return; try{ const r=await fetch("/relay?room="+encodeURIComponent(name)+"&since="+this._since+"&key="+encodeURIComponent(this._me?key:"")).then(x=>x.json());
        const pj=JSON.stringify(r.pres); if(pj!==this._presJ){ this._presJ=pj; this._pres=r.pres; const cb=this._cbs["presence:sync"]; cb&&cb(); }
        for(const m of r.msgs){ this._since=m.i; if(m.from===inst) continue; const cb=this._cbs["broadcast:"+m.event]; cb&&cb({payload:m.payload}); } }catch(e){} },
    track(p){ this._me=p; return fetch("/relay",{method:"POST",body:JSON.stringify({type:"track",room:name,key,payload:p})}).then(()=>"ok"); },
    untrack(){ return fetch("/relay",{method:"POST",body:JSON.stringify({type:"untrack",room:name,key})}).then(()=>"ok"); },
    send(m){ return fetch("/relay",{method:"POST",body:JSON.stringify({type:"msg",room:name,from:inst,event:m.event,payload:m.payload})}).then(()=>"ok"); },
    presenceState(){ const out={}; for(const k in this._pres) out[k]=[this._pres[k]]; return out; },
    unsubscribe(){ this._dead=true; clearInterval(this._poll); this.untrack(); } };
  return c; }
window.supabase={createClient:()=>({
  channel:(name,opts)=>relayChannel(name,opts),
  storage:{from:()=>({getPublicUrl:(p)=>({data:{publicUrl:"/blob/"+p}})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{};
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-auth"&&b.action==="logout") return {data:{ok:true}};
    if(n==="gizleme-vault"&&b.action==="pull") return {data:{ok:true,abk:window.__vault.abk,contacts:window.__vault.contacts,cver:window.__vault.cver}};
    if(n==="gizleme-vault"&&b.action==="pushAbk"){ if(!window.__vault.abk) window.__vault.abk=b.abk; return {data:{ok:true}}; }
    if(n==="gizleme-vault"&&b.action==="pushContacts"){ window.__vault.contacts=b.contacts; window.__vault.cver++; return {data:{ok:true,cver:window.__vault.cver}}; }
    if(n==="gizleme-mbox"){ const j=await fetch("/mbox",{method:"POST",body:JSON.stringify(b)}).then(r=>r.json()); return {data:j}; }
    if(n==="gizleme-push"&&b.action==="notify"){ window.__notify.push(b); return {data:{ok:true,sent:1}}; }
    if(n==="gizleme-turn") return {data:{ok:true,iceServers:[],turn:false}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
'''
(site/"mock.js").write_text(MOCK)
html=html.replace("/app.min.js?v=","/app.js?v=")   # the page loads the readable app.js here (hooked below), not the minified build
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
HOOK='''window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),
  callState:()=>call?{state:call.state,live:!!call.t1,group:!!call.group,video:call.video,dir:call.dir,peers:[...call.peers.values()].map(P=>({pid:P.pid,cs:P.pc.connectionState,connected:P.connected,tracks:P.stream.getTracks().map(t=>t.kind)})),localAudioOn:call.local?call.local.getAudioTracks().every(t=>t.enabled):null,localVideo:call.local?call.local.getVideoTracks().length:0}:null,
  setIce:(l)=>{ _iceCache={servers:l,exp:Date.now()+1e9}; }, room:()=>{ const R=A(); return R?{paired:R.paired,group:R.group,gcall:R.gcall?R.gcall.cid:null,ck:R.fromContact}:null; },
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), histOf:async()=>{ const R=A(); const l=await histLoad(histKeyOf(R)); return l.map(r=>r.mid+'|'+r.dir+'|'+(r.env&&r.env.t)); }, lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; },
  merge:(x)=>JSON.parse(JSON.stringify(mergeContacts(x))), soundMode:()=>soundMode(), unreadTotal:()=>unreadTotal(), checkUpdate:()=>checkUpdate(true), openCk:(ck)=>openContact(ck,'x'), inbox:()=>inboxPull(true),
  editsFrom:(g,past)=>[...editsFrom({group:g},past)].map(([k,v])=>[k,v.x]), onEdit:(env,own,ts)=>{ const R=A(); onEditEnv(R,env,'x',ts||Date.now(),rid(),!!own); },
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install') };
'''
_app=_app[:_app.rstrip().rfind("})();")]+HOOK+'})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg","logo-head.png","logo-word.png","logo-dot.png","call-icon.png","call-badge.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
(site/"sw.js").write_text(pathlib.Path(SRC+"sw.js").read_text().replace("/app.min.js?v=","/app.js?v="))   # the worker precaches what the page loads
os.chdir(site)

RELAY={}; RLOCK=threading.Lock(); MBOX={}; ACKS=[]; BLOBS={}
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
    def _json(self,o): b=json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path.startswith("/relay?"):
            qs=urllib.parse.parse_qs(self.path.split("?",1)[1]); room=qs.get("room",[""])[0]; since=int(qs.get("since",["0"])[0]); key=qs.get("key",[""])[0]
            with RLOCK:
                st=RELAY.setdefault(room,{"pres":{},"msgs":[],"last":{}}); now=time.time()
                if key and key in st["pres"]: st["last"][key]=now
                for k in [k for k,t0 in st["last"].items() if now-t0>2.0]: st["pres"].pop(k,None); st["last"].pop(k,None)
                out={"pres":dict(st["pres"]),"msgs":[m for m in st["msgs"] if m["i"]>since]}
            return self._json(out)
        if self.path.startswith("/blob/"):
            name=self.path[6:]
            with RLOCK: data=BLOBS.get(name)
            if data is None: self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type","application/octet-stream"); self.send_header("Content-Length",str(len(data))); self.end_headers(); self.wfile.write(data); return
        return super().do_GET()
    def do_POST(self):
        n=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(n) or b"{}")
        if self.path.startswith("/mbox"):
            a=body.get("action")
            with RLOCK:
                if a=="put":
                    box=MBOX.setdefault(body["mbox"],[]); 
                    if not any(x["mid"]==body["mid"] for x in box): box.append({"mid":body["mid"],"from_user":body.get("from"),"data":body["data"],"ts":datetime.datetime.now(datetime.timezone.utc).isoformat(),"delivered_at":None})
                    return self._json({"ok":True})
                if a=="get":
                    box=MBOX.get(body["mbox"],[]); since=body.get("since") or 0
                    items=[{"mid":x["mid"],"from_user":x["from_user"],"data":x["data"],"ts":x["ts"]} for x in box if (not since or x["ts"]>since)]
                    return self._json({"ok":True,"items":items})
                if a=="putblob":
                    import secrets; name=secrets.token_hex(24)+".bin"; BLOBS[name]=base64.b64decode(body["data"]); return self._json({"ok":True,"path":name})
                if a=="delblob":
                    BLOBS.pop(body.get("path",""),None); return self._json({"ok":True})
                if a=="ack":
                    box=MBOX.get(body["mbox"],[]); 
                    for x in box:
                        if x["mid"] in body.get("mids",[]) and not x["delivered_at"]: x["delivered_at"]=datetime.datetime.now(datetime.timezone.utc).isoformat()
                    ACKS.append((body["mbox"],list(body.get("mids",[])))); return self._json({"ok":True})
                return self._json({"ok":True})
        with RLOCK:
            st=RELAY.setdefault(body.get("room",""),{"pres":{},"msgs":[],"last":{}})
            if body["type"]=="track": st["pres"][body["key"]]=body["payload"]; st["last"][body["key"]]=time.time()
            elif body["type"]=="untrack": st["pres"].pop(body.get("key"),None); st["last"].pop(body.get("key"),None)
            elif body["type"]=="msg": st["msgs"].append({"i":len(st["msgs"])+1,"from":body["from"],"event":body["event"],"payload":body["payload"]})
        return self._json({"ok":True})
srv=socketserver.ThreadingTCPServer(("127.0.0.1",0),Q); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()

def wait_for(page, js, timeout=10000, step=150):
    t0=time.time()
    while time.time()-t0<timeout/1000:
        try:
            if page.evaluate(js): return True
        except Exception: pass
        page.wait_for_timeout(step)
    return False


def dump():
    with RLOCK: return {k:[{"mid":x["mid"],"d":bool(x["delivered_at"])} for x in v] for k,v in MBOX.items()}

def blobs():
    with RLOCK: return {k:len(v) for k,v in BLOBS.items()}

TOUCH=r"""([sel, idx, steps])=>{ const el=document.querySelectorAll(sel)[idx]; if(!el) return 'no-el'; const r=el.getBoundingClientRect();
  const x0=r.left+Math.min(24,r.width/3), y0=r.top+r.height/2; const mk=(x,y)=>new Touch({identifier:7,target:el,clientX:x,clientY:y,pageX:x,pageY:y,radiusX:2,radiusY:2,force:1});
  const fire=(type,x,y,list)=>el.dispatchEvent(new TouchEvent(type,{bubbles:true,cancelable:true,composed:true,touches:list?[mk(x,y)]:[],targetTouches:list?[mk(x,y)]:[],changedTouches:[mk(x,y)]}));
  fire('touchstart',x0,y0,true); let last=[0,0]; for(const s of steps){ last=s; fire('touchmove',x0+s[0],y0+s[1],true); } fire('touchend',x0+last[0],y0+last[1],false); return 'ok'; }"""
DTAP=r"""([sel, idx])=>{ const el=document.querySelectorAll(sel)[idx]; if(!el) return 'no-el'; const r=el.getBoundingClientRect(); const x=r.left+Math.min(24,r.width/3), y=r.top+r.height/2;
  const mk=()=>new Touch({identifier:9,target:el,clientX:x,clientY:y,pageX:x,pageY:y});
  const tap=()=>{ el.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,cancelable:true,touches:[mk()],targetTouches:[mk()],changedTouches:[mk()]}));
    return el.dispatchEvent(new TouchEvent('touchend',{bubbles:true,cancelable:true,touches:[],changedTouches:[mk()]})); };
  tap(); return new Promise(res=>setTimeout(()=>{ const notPrevented=tap(); res(notPrevented?'not-prevented':'prevented'); },120)); }"""
def chips(P, sel):
    return P.evaluate("([sel])=>{ const b=[...document.querySelectorAll(sel)].pop(); if(!b) return null; return [...b.querySelectorAll(':scope > .reacts .rx')].map(c=>c.textContent+(c.classList.contains('mine')?'*':'')); }",[sel])
SENT=".log:not([style*='display: none']) .bubble.sent"; RECV=".log:not([style*='display: none']) .bubble.recv"
COUNT="(()=>{ const C=window.AudioContext||window.webkitAudioContext; if(!C) return; const o=C.prototype.createOscillator; window.__osc=0; C.prototype.createOscillator=function(){ window.__osc++; return o.apply(this,arguments); }; })()"
osc=lambda P: P.evaluate("()=>window.__osc||0")


r={}
import traceback
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
SKIP="()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"
VIS="(id)=>{ const e=document.getElementById(id); if(!e) return false; const r=e.getBoundingClientRect(); return !e.closest('[hidden]') && getComputedStyle(e).display!=='none' && r.width>0 && r.height>0; }"
SHOTS=_os.environ.get("GZ_SHOTS")
def shot(P, name):
    if SHOTS: P.screenshot(path=SHOTS+"/"+name+".png")
def vis(P, i): return P.evaluate(VIS, i)
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream"])
    def ctxp(w=390, h=780, scheme="dark", locale="en-US"):
        c=b.new_context(viewport={"width":w,"height":h},locale=locale,color_scheme=scheme); c.add_init_script(NOINST); p=c.new_page(); return c,p
    def boot(name, errs, w=1000, h=820, scheme="dark"):
        ctx,p=ctxp(w,h,scheme); p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300); p.evaluate(SKIP)
        p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    errs=[]
    # ---- 1. the welcome step ----
    cW,W=ctxp(); W.on("pageerror",lambda e:errs.append(str(e))); W.goto(f"http://127.0.0.1:{port}/"); W.wait_for_function("()=>!!document.getElementById('join').dataset.mode"); W.wait_for_timeout(300)
    w=W.evaluate("()=>{ const j=document.getElementById('join'), b=document.getElementById('joinBtn').getBoundingClientRect(), pr=document.getElementById('promises').getBoundingClientRect(); return {mode:j.dataset.mode, btn:document.getElementById('joinBtn').textContent, btnBottom:b.bottom, ih:innerHeight, promBelow:pr.top>=b.bottom, sl:document.getElementById('switchLink').textContent}; }")
    r["welcome_mode"]= w["mode"]=="welcome" and w["btn"]=="Create my account" and w["sl"]=="I already have an account"
    r["welcome_button_above_fold"]= w["btnBottom"]<=w["ih"]
    r["welcome_promises_under_button"]= w["promBelow"] and vis(W,"promises") and vis(W,"introLine")
    r["welcome_no_form"]= not vis(W,"userInput") and not vis(W,"pwInput")
    r["welcome_v"]=w
    shot(W,"53_welcome")
    W.click("#joinBtn"); W.wait_for_timeout(250)
    r["step2_form_alone"]= W.get_attribute("#join","data-mode")=="register" and vis(W,"userInput") and vis(W,"pw2Input") and not vis(W,"promises") and not vis(W,"introLine")
    W.locator("#userInput").press_sequentially("ayse", delay=20); W.wait_for_timeout(100)
    r["first_name_follows_username"]= W.eval_on_selector("#dispInput","e=>e.value")=="ayse"
    W.fill("#dispInput","Ayşe"); W.locator("#userInput").press_sequentially("x", delay=20)
    r["first_name_kept_once_typed"]= W.eval_on_selector("#dispInput","e=>e.value")=="Ayşe"
    r["first_name_label"]= "Your first name" in W.eval_on_selector("label[for=dispInput]","e=>e.textContent")
    shot(W,"53_form")
    cW.close()
    cL,L=ctxp(); L.goto(f"http://127.0.0.1:{port}/"); L.wait_for_function("()=>!!document.getElementById('join').dataset.mode"); L.wait_for_timeout(200); L.click("#switchLink"); L.wait_for_timeout(200)
    r["welcome_to_login"]= L.get_attribute("#join","data-mode")=="login" and vis(L,"userInput") and not vis(L,"pw2Input")
    cL.close()
    cF,F=ctxp(locale="fr-FR"); F.goto(f"http://127.0.0.1:{port}/"); F.wait_for_function("()=>!!document.getElementById('join').dataset.mode"); F.wait_for_timeout(200)
    r["welcome_fr"]= F.eval_on_selector("#joinBtn","e=>e.textContent")=="Créer mon compte" and F.eval_on_selector("#switchLink","e=>e.textContent")=="J'ai déjà un compte" and F.eval_on_selector("#introLine","e=>e.textContent").startswith("Des discussions privées")
    cF.close()
    # ---- 2. Settings as pages ----
    ctxA,A=boot("oguz",errs)
    A.click("#sbSettings"); A.wait_for_timeout(250)
    st=A.evaluate("()=>({h1:document.querySelector('#settingsModal h1').textContent, me:document.getElementById('setMeName').textContent, sub:document.getElementById('setMeSub').textContent, navs:[...document.querySelectorAll('#settingsModal .set-nav')].filter(x=>!x.hidden).map(x=>x.textContent.trim())})")
    r["settings_root"]= st["h1"]=="Settings" and st["me"]=="oguz" and st["sub"]=="@oguz" and st["navs"]==["Privacy","Chats","Notifications and sounds","Account"]
    r["settings_root_v"]=st
    r["settings_root_short"]= not vis(A,"logoutBtn") and not vis(A,"delAcctBtn") and not vis(A,"langSel")
    shot(A,"53_settings_root")
    A.click("#settingsModal [data-go=account]"); A.wait_for_timeout(200)
    ac=A.evaluate("()=>{ const pg=document.querySelector('.set-page[data-page=account]'); const ids=[...pg.querySelectorAll('button[id]')].map(b=>b.id); return {ids, title:pg.querySelector('h2').textContent}; }")
    r["account_page"]= vis(A,"logoutBtn") and vis(A,"delAcctBtn") and ac["title"]=="Account" and ac["ids"][-1]=="delAcctBtn" and not vis(A,"setMeName")
    shot(A,"53_settings_account")
    A.click(".set-page[data-page=account] .set-back"); A.wait_for_timeout(150)
    r["back_to_root"]= vis(A,"setMeName") and not vis(A,"logoutBtn")
    A.click("#settingsModal [data-go=chats]"); A.wait_for_timeout(150)
    r["chats_page"]= vis(A,"langSel") and vis(A,"textSize") and vis(A,"expGlobal") and vis(A,"themeToggle")
    A.keyboard.press("Escape"); A.wait_for_timeout(150)
    r["escape_page_then_root"]= vis(A,"setMeName")
    A.keyboard.press("Escape"); A.wait_for_timeout(150)
    r["escape_closes"]= not A.evaluate("()=>document.getElementById('settingsModal').classList.contains('show')")
    A.click("#sbSettings"); A.wait_for_timeout(150); A.click("#settingsModal [data-go=privacy]"); A.wait_for_timeout(150)
    r["privacy_page"]= vis(A,"autoLock") and vis(A,"typToggle") and vis(A,"shieldToggle") and not vis(A,"langSel")
    A.click("#settingsClose"); A.wait_for_timeout(150); A.click("#sbSettings"); A.wait_for_timeout(150)
    r["reopens_on_root"]= vis(A,"setMeName") and not vis(A,"autoLock")
    A.click("#settingsClose"); A.wait_for_timeout(150)
    # ---- 3. Chat info ----
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    cI,I=ctxp(); I.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); I.wait_for_function("()=>!!document.getElementById('join').dataset.mode"); I.wait_for_timeout(300)
    r["invite_link_skips_welcome"]= I.get_attribute("#join","data-mode")=="register" and vis(I,"userInput")
    cI.close()
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    errsB=[]; ctxB,B=boot("serap",errsB,w=390,scheme="light")
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(2000)
    r["paired"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    A.wait_for_timeout(600)
    A.click("#menuBtn"); A.wait_for_timeout(150)
    mi=A.evaluate("()=>[...document.querySelectorAll('#barMenu > .menu-item')].filter(x=>!x.hidden).map(x=>x.id)")
    r["menu_short"]= mi[0]=="mi-info" and len(mi)<=4 and "mi-loc" in mi and ("mi-mute" in mi or "mi-unmute" in mi)
    r["menu_v"]=mi
    A.click("#mi-info"); A.wait_for_timeout(250)
    r["menu_opens_info"]= vis(A,"ciName")
    A.click("#ciBack"); A.wait_for_timeout(150)
    r["back_closes_info"]= not vis(A,"ciName")
    A.click("#peerMeta"); A.wait_for_timeout(250)
    ci=A.evaluate("()=>({name:document.getElementById('ciName').textContent, st:document.getElementById('ciStatus').textContent, ren:document.getElementById('ciRenameV').textContent, ver:document.getElementById('ciVerifyV').textContent, rm:document.querySelector('#ciRemove .il').textContent, sw:document.querySelectorAll('#ciColors button').length, ava:getComputedStyle(document.getElementById('ciAva')).backgroundColor, head:getComputedStyle(document.getElementById('peerAvatar')).backgroundColor})")
    r["info_content"]= ci["name"]=="serap" and len(ci["st"])>3 and ci["ren"]=="None" and ci["ver"]=="Not verified" and ci["rm"]=="Remove contact" and ci["sw"]==13 and ci["ava"]==ci["head"]
    r["info_rows"]= all(vis(A,i) for i in ["ciCall","ciVideo","ciLoc","ciRename","ciColorRow","ciMuteRow","ciVerify","ciNotify","ciToGroup","ciRekey","ciWire","ciRemove"]) and not vis(A,"ciInvite") and not vis(A,"ciMembers") and not vis(A,"ciMerge")
    r["info_v"]=ci
    shot(A,"53_info_dark")
    A.click("#ciColors button[data-c=red]"); A.wait_for_timeout(300)
    r["info_colour"]= A.evaluate("()=>getComputedStyle(document.getElementById('peerAvatar')).backgroundColor")=="rgb(220, 38, 38)" and A.evaluate("()=>getComputedStyle(document.getElementById('ciAva')).backgroundColor")=="rgb(220, 38, 38)" and A.evaluate("()=>window.__gz.contacts().find(x=>x.ck===window.__gz.room().ck).cl")=="red" and A.evaluate("()=>document.querySelector('#ciColors button.on').dataset.c")=="red"
    r["info_colour_v"]= A.evaluate("()=>[getComputedStyle(document.getElementById('peerAvatar')).backgroundColor, getComputedStyle(document.getElementById('ciAva')).backgroundColor, window.__gz.contacts().find(x=>x.ck===window.__gz.room().ck).cl, (document.querySelector('#ciColors button.on')||{dataset:{}}).dataset.c]")
    if vis(A,"ciExpRow"):
        A.select_option("#ciExp","300000"); A.wait_for_timeout(500)
        r["info_timer"]= A.eval_on_selector("#expNum","e=>e.textContent")=="5" and wait_for(B,"()=>[...document.querySelectorAll('"+OPEN+" .sys')].some(e=>e.textContent.includes('5 minutes'))",8000)
    else: r["info_timer"]=False
    A.select_option("#ciMute","3600000"); A.wait_for_timeout(300)
    mu=A.evaluate("()=>{ const c=window.__gz.contacts().find(x=>x.ck===window.__gz.room().ck); return {mu:c.mu||0, now:Date.now(), sel:document.getElementById('ciMute').value}; }")
    r["info_mute"]= 3500000 < mu["mu"]-mu["now"] <= 3600000 and mu["sel"]=="cur"
    r["info_mute_v"]=mu
    A.select_option("#ciMute","0"); A.wait_for_timeout(200)
    r["info_unmute"]= not A.evaluate("()=>window.__gz.contacts().find(x=>x.ck===window.__gz.room().ck).mu") and A.eval_on_selector("#ciMute","e=>e.value")=="0"
    A.keyboard.press("Escape"); A.wait_for_timeout(150)
    r["escape_closes_info"]= not vis(A,"ciName")
    A.click("#peerAvatar"); A.wait_for_timeout(200)
    r["avatar_opens_info"]= vis(A,"ciName")
    A.click("#ciWire"); A.wait_for_timeout(200)
    r["wire_from_info"]= not vis(A,"ciName") and A.evaluate("()=>document.getElementById('wire').classList.contains('show')")
    A.evaluate("()=>document.getElementById('wire').classList.remove('show')")
    # on a phone Chat info takes the whole screen
    B.click("#peerMeta"); B.wait_for_timeout(250)
    fs=B.evaluate("()=>{ const c=document.querySelector('#infoModal .info-card').getBoundingClientRect(); return {w:c.width, h:c.height, ih:innerHeight, iw:innerWidth}; }")
    r["phone_full_screen"]= abs(fs["w"]-fs["iw"])<1 and abs(fs["h"]-fs["ih"])<2
    shot(B,"53_info_light_phone")
    B.click("#ciRemove"); B.wait_for_timeout(800)
    r["remove_from_info"]= B.evaluate("()=>document.getElementById('app').classList.contains('home')") and B.evaluate("()=>document.querySelectorAll('.ct').length")==0 and not vis(B,"ciName")
    r["errors"]= (errs+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
