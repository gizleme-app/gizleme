# v29: editing a sent message (long press / right click → Edit; 1:1 rules, history, preview, draft kept, group
# signer rule); a call rings the other phone again every few seconds and ends as "missed call" (tag, kind, SW
# alert with the ringing icon); a 1:1 video call fills the screen (HD capture, tap hides the buttons); the install
# invitation comes back (spaced out) until the app is installed, with steps for iPhone / Android / Mac Safari;
# a colour for each chat's avatar (long press / right click in the list), synced newest-wins; "typing…" and
# "recording a voice message…" (header, end of chat, chats list; stops, fades; setting off both ways).
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site48"); site.mkdir(exist_ok=True)
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
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
HOOK='''window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),
  callState:()=>call?{state:call.state,live:!!call.t1,group:!!call.group,video:call.video,dir:call.dir,peers:[...call.peers.values()].map(P=>({pid:P.pid,cs:P.pc.connectionState,connected:P.connected,tracks:P.stream.getTracks().map(t=>t.kind)})),localAudioOn:call.local?call.local.getAudioTracks().every(t=>t.enabled):null,localVideo:call.local?call.local.getVideoTracks().length:0}:null,
  setIce:(l)=>{ _iceCache={servers:l,exp:Date.now()+1e9}; }, room:()=>{ const R=A(); return R?{paired:R.paired,group:R.group,gcall:R.gcall?R.gcall.cid:null,ck:R.fromContact}:null; },
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), histOf:async()=>{ const R=A(); const l=await histLoad(histKeyOf(R)); return l.map(r=>r.mid+'|'+r.dir+'|'+(r.env&&r.env.t)); }, lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; },
  merge:(x)=>JSON.parse(JSON.stringify(mergeContacts(x))), soundMode:()=>soundMode(), unreadTotal:()=>unreadTotal(), checkUpdate:()=>checkUpdate(true), openCk:(ck)=>openContact(ck,'x'), inbox:()=>inboxPull(true),
  editsFrom:(g,past)=>[...editsFrom({group:g},past)].map(([k,v])=>[k,v.x]), onEdit:(env,own,ts)=>{ const R=A(); onEditEnv(R,env,'x',ts||Date.now(),rid(),!!own); },
  rec:(on)=>on?startRec():stopRec(false), typLabel:(g,e)=>typingLabel({group:g, typing:new Map(e.map(([k,x])=>[k,{s:x,until:Date.now()+5000}]))}),
  localCam:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; if(!tr) return null; const P=[...call.peers.values()][0]; const sn=P&&P.pc.getSenders().find(x=>x.track&&x.track.kind==='video'); return {id:tr.getSettings().deviceId, same:!!(sn&&sn.track===tr), live:tr.readyState, n:call.local.getVideoTracks().length, mirror:document.getElementById('callLocal').style.transform}; },
  tiles:(pid)=>{ if(pid) peerEl(pid,'x'); return document.querySelectorAll('#callStage .peer').length; },
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install') };
'''
_app=_app[:_app.rstrip().rfind("})();")]+HOOK+'})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg","logo-head.png","logo-word.png","logo-dot.png","call-icon.png","call-badge.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
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
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(300)
RECV="(t)=>[...document.querySelectorAll('.log:not([style*=\"display: none\"]) .bubble .txt')].some(e=>e.textContent===t)"
TEXTS="()=>[...document.querySelectorAll('.log:not([style*=\"display: none\"]) .bubble .txt')].map(e=>e.textContent)"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
SENTS=".log:not([style*='display: none']) .bubble.sent"; RECVS=".log:not([style*='display: none']) .bubble.recv"
BUB="([sel])=>{ const b=[...document.querySelectorAll(sel)].pop(); if(!b) return null; return {txt:(b.querySelector(':scope > .txt')||{}).textContent, edited:b.classList.contains('edited'), edm:!!b.querySelector('.meta .edm'), n:document.querySelectorAll(sel).length, mid:b.dataset.mid}; }"
PICK="()=>({open:!document.getElementById('rxPick').hidden, edit:!document.getElementById('rxEdit').hidden, copy:!document.getElementById('rxCopy').hidden})"
LONG=r"""([sel, ms])=>new Promise(res=>{ const el=[...document.querySelectorAll(sel)].pop(); if(!el) return res('no-el'); const t=el.querySelector('.txt')||el; const r=t.getBoundingClientRect(); const x=r.left+Math.min(12,r.width/3), y=r.top+r.height/2;
  const mk=()=>new Touch({identifier:11,target:t,clientX:x,clientY:y,pageX:x,pageY:y});
  t.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,cancelable:true,touches:[mk()],targetTouches:[mk()],changedTouches:[mk()]}));
  setTimeout(()=>{ const open=!document.getElementById('rxPick').hidden; const np=t.dispatchEvent(new TouchEvent('touchend',{bubbles:true,cancelable:true,touches:[],changedTouches:[mk()]})); res({open, prevented:!np}); }, ms); })"""
SWJS48=r"""async ()=>{ const sw=await fetch('/sw.js').then(r=>r.text()); const H={}, shown=[], store=new Map(); let badge=null, closed=0, live=[];
  const fakeCaches={ open: async()=>({ put: async(k,res)=>{ store.set(k, await res.text()); }, match: async(k)=> store.has(k) ? new Response(store.get(k)) : undefined }), keys: async()=>[], delete: async()=>true };
  const reg={ showNotification: async(title,o)=>{ const n={title, o, close(){ closed++; live=live.filter(x=>x!==n); }}; live.push(n); shown.push(n); },
              getNotifications: async(f)=> live.filter(n=>!f || !f.tag || n.o.tag===f.tag) };
  const fakeSelf={ addEventListener:(t,f)=>{ H[t]=f; }, location:{origin:location.origin}, registration:reg,
    navigator:{ setAppBadge: async(n)=>{ badge=n; } }, clients:{ claim: async()=>{}, matchAll: async()=>[] }, skipWaiting:()=>{} };
  new Function("self","caches", sw)(fakeSelf, fakeCaches);
  const run=async(type, ev)=>{ let p=null; ev.waitUntil=x=>{ p=x; }; H[type](ev); await p; };
  const hh=async s=>{ const b=new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))); return btoa(String.fromCharCode(...b)).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,""); };
  await run("message",{data:{type:"names", names:{[await hh("NK1")]:"Baba"}, muted:{}, tmpl:{msg:"New message from {name}", call:"{name} is calling you", missed:"Missed call from {name}", anyMissed:"Missed call", anyCall:"Incoming call"}}});
  await run("message",{data:{type:"badge", n:2}});
  const push=d=>run("push",{data:{json:()=>d}});
  await push({kind:"call", url:"/#n=NK1", tag:"cNK1"}); await push({kind:"call", url:"/#n=NK1", tag:"cNK1"});
  const c=shown[1]; const r1={title:c.title, icon:c.o.icon, badge:c.o.badge, req:c.o.requireInteraction, ring:c.o.data.ring, vib:Array.isArray(c.o.vibrate), renotify:c.o.renotify, silent:c.o.silent, body:c.o.body, closedBefore:closed, live:live.length};
  await push({kind:"missed", url:"/#n=NK1", tag:"cNK1"}); const m=shown[2]; const r2={title:m.title, body:m.o.body, silent:m.o.silent, ring:m.o.data.ring, req:m.o.requireInteraction, live:live.length, badge};
  await push({kind:"missed", url:"/#n=ZZ", tag:"cZZ"}); const r3={body:shown[3].o.body};
  await push({kind:"msg", url:"/#n=NK1", tag:"m1"}); const r4={icon:shown[4].o.icon, req:shown[4].o.requireInteraction, title:shown[4].title, badge};
  return {r1,r2,r3,r4}; }"""
IPHONE="Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1"
ANDROID="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36"
MODAL="()=>document.getElementById('installModal').classList.contains('show')"
SAMSUNG=r"""(()=>{ const md=navigator.mediaDevices, real=md.getUserMedia.bind(md), live=new Set(); window.__gumLog=[];
  md.enumerateDevices=async()=>[{kind:'videoinput',deviceId:'front',label:'camera2 1, facing front',groupId:'a'},{kind:'videoinput',deviceId:'back',label:'camera2 0, facing back',groupId:'b'},{kind:'audioinput',deviceId:'mic',label:'mic',groupId:'c'}];
  md.getUserMedia=async(c)=>{ const v=c&&c.video; let id=null;
    if(v){ for(const t of [...live]) if(t.readyState==='live'){ window.__gumLog.push('busy'); throw new DOMException('Could not start video source','NotReadableError'); }
      const fm=v.facingMode&&(v.facingMode.exact||v.facingMode); const di=v.deviceId&&(v.deviceId.exact||v.deviceId);
      if(v.facingMode && v.facingMode.exact){ window.__gumLog.push('exact-fail'); throw new DOMException('','OverconstrainedError'); }
      id= di || (fm==='environment'?'back':'front'); }
    const s=await real(c); s.getVideoTracks().forEach(t=>{ live.add(t); const g=t.getSettings.bind(t); t.getSettings=()=>Object.assign(g(),{deviceId:id, facingMode:id==='back'?'environment':'user'}); });
    window.__gumLog.push('ok:'+id); return s; }; })()"""
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream","--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000, ua=None, init=None):
        kw={"viewport":{"width":w,"height":820},"locale":"en-US","permissions":["camera","microphone"]}
        if ua: kw["user_agent"]=ua
        ctx=b.new_context(**kw)
        if init: ctx.add_init_script(init)
        p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    def open_link(P, link):
        P.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(2000)
    def relock(P):
        P.reload(); P.wait_for_timeout(500); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(1500)
    errsA=[]; errsB=[]; errsI=[]
    ctxA,A=boot("oguz",errsA)
    A.click("#sbNew"); A.wait_for_timeout(300); link1=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    ctxB,B=boot("serap",errsB,w=390)
    open_link(B, link1)
    r["paired"]= wait_for(A,PAIRED,10000) and wait_for(B,PAIRED,10000)
    A.evaluate("()=>window.__gz.setIce([])"); B.evaluate("()=>window.__gz.setIce([])")
    send(A,"helo wrold"); r["delivered"]= wait_for(B,"()=>("+RECV+")('helo wrold')",8000)
    A.wait_for_timeout(1200)   # the tick: sent → received
    # ---------- 1. edit (computer: right click) ----------
    A.fill("#msgInput","half typed")
    A.locator(SENTS+" .txt").last.click(button="right"); A.wait_for_timeout(200)
    p=A.evaluate(PICK); r["rightclick_menu_edit_copy"]= p=={"open":True,"edit":True,"copy":True}
    A.click("#rxEdit"); A.wait_for_timeout(200)
    r["edit_bar"]= A.is_visible("#replyBar") and A.evaluate("()=>document.getElementById('replyBar').classList.contains('editing')") and A.input_value("#msgInput")=="helo wrold"
    r["edit_bar_label"]= A.eval_on_selector("#rbName","e=>e.textContent")=="Editing your message"
    A.fill("#msgInput","hello world"); A.press("#msgInput","Enter"); A.wait_for_timeout(500)
    r["draft_back"]= A.input_value("#msgInput")=="half typed" and not A.is_visible("#replyBar")
    a=A.evaluate(BUB,[SENTS]); r["A_edited"]= a["txt"]=="hello world" and a["edm"] and a["n"]==1
    r["B_edited"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll(\""+RECVS+"\")].pop(); return b && b.querySelector('.txt').textContent==='hello world' && b.classList.contains('edited'); }",8000)
    bb=B.evaluate(BUB,[RECVS]); r["B_no_new_bubble"]= bb["n"]==1 and bb["edm"]
    r["B_meta_label"]= B.evaluate("()=>{ const b=[...document.querySelectorAll('.log .bubble.recv')].pop(); return b.querySelector('.meta .edm').textContent; }")=="edited"
    # preview in the list shows the new text
    B.evaluate("()=>document.getElementById('backHome').click()"); B.wait_for_timeout(1200)
    r["B_preview"]= wait_for(B,"()=>[...document.querySelectorAll('.ct')].some(e=>e.textContent.includes('hello world'))",5000) and not B.evaluate("()=>[...document.querySelectorAll('.ct')].some(e=>e.textContent.includes('✏️'))")
    B.click(".ct"); B.wait_for_timeout(1200)
    # ---------- 2. long press on a phone ----------
    lp=B.evaluate(LONG,[RECVS,650]); r["longpress_opens"]= lp=={"open":True,"prevented":True}
    p=B.evaluate(PICK); r["recv_menu_no_edit"]= p=={"open":True,"edit":False,"copy":True}
    B.keyboard.press("Escape"); B.wait_for_timeout(150)
    sp=B.evaluate(LONG,[RECVS,120]); B.wait_for_timeout(500); r["short_touch_no_menu"]= sp["open"]==False and not B.evaluate(PICK)["open"]
    send(B,"from serap"); wait_for(A,"()=>("+RECV+")('from serap')",8000)
    A.locator(RECVS+" .txt").last.click(button="right"); A.wait_for_timeout(200)
    r["A_recv_not_editable"]= A.evaluate(PICK)=={"open":True,"edit":False,"copy":True}
    A.keyboard.press("Escape")
    # copy
    ctxA.grant_permissions(["clipboard-read","clipboard-write"])
    A.locator(SENTS+" .txt").last.click(button="right"); A.wait_for_timeout(150); A.click("#rxCopy"); A.wait_for_timeout(300)
    r["copy"]= A.evaluate("()=>navigator.clipboard.readText()")=="hello world"
    # ---------- 2b. "typing…" / "recording a voice message…" ----------
    TYPING="()=>({st:document.getElementById('statusText').textContent, bar:document.getElementById('bar').classList.contains('typing'), bub:!!document.querySelector('.log:not([style*=\"display: none\"]) > .typing-bub'), voice:!!document.querySelector('.log:not([style*=\"display: none\"]) > .typing-bub.voice'), row:(document.querySelector('.ct .cm.typing')||{}).textContent||''})"
    B.locator("#msgInput").press_sequentially("Sal", delay=60)
    r["typing_shown"]= wait_for(A,"()=>{ const x=("+TYPING+")(); return x.st==='typing…' && x.bar && x.bub && !x.voice; }",5000)
    r["typing_in_list"]= A.evaluate(TYPING)["row"]=="typing…"
    r["typing_bubble_last"]= A.evaluate("()=>{ const L=document.querySelector('.log:not([style*=\"display: none\"])'); const b=L.querySelector(':scope > .typing-bub'); return getComputedStyle(b).order==='1'; }")
    B.locator("#msgInput").press("Control+a"); B.locator("#msgInput").press("Backspace")
    r["typing_stops_on_empty"]= wait_for(A,"()=>{ const x=("+TYPING+")(); return !x.bar && !x.bub && x.row===''; }",4000)
    B.locator("#msgInput").press_sequentially("Salut", delay=60)
    wait_for(A,"()=>("+TYPING+")().bub",5000)
    B.press("#msgInput","Enter")
    r["typing_ends_with_message"]= wait_for(A,"()=>("+RECV+")('Salut')",8000) and wait_for(A,"()=>!("+TYPING+")().bub",3000)
    B.locator("#msgInput").press_sequentially("x", delay=60)
    wait_for(A,"()=>("+TYPING+")().bub",5000); t0=time.time()
    r["typing_fades"]= wait_for(A,"()=>!("+TYPING+")().bub",10000) and time.time()-t0>4.5
    B.locator("#msgInput").press("Backspace"); B.wait_for_timeout(300)
    B.evaluate("()=>window.__gz.rec(true)")
    r["recording_shown"]= wait_for(A,"()=>{ const x=("+TYPING+")(); return x.st==='recording a voice message…' && x.voice; }",6000)
    r["recording_kept_alive"]= (A.wait_for_timeout(7500) or True) and A.evaluate(TYPING)["voice"]
    B.evaluate("()=>window.__gz.rec(false)")
    r["recording_stops"]= wait_for(A,"()=>!("+TYPING+")().bub",4000)
    A.evaluate("()=>document.getElementById('typToggle').click()"); A.wait_for_timeout(200)
    r["setting_off_saved"]= A.evaluate("()=>localStorage.getItem('gz-typing')")=="0" and A.eval_on_selector("#typToggle","e=>e.textContent")=="Off"
    B.locator("#msgInput").press_sequentially("hey", delay=60); A.wait_for_timeout(1500)
    r["setting_off_hides"]= not A.evaluate(TYPING)["bub"] and not A.evaluate(TYPING)["bar"]
    B.locator("#msgInput").press("Control+a"); B.locator("#msgInput").press("Backspace")
    A.locator("#msgInput").press_sequentially("yo", delay=60); B.wait_for_timeout(1500)
    r["setting_off_sends_nothing"]= not B.evaluate(TYPING)["bub"]
    A.locator("#msgInput").press("Control+a"); A.locator("#msgInput").press("Backspace")
    A.evaluate("()=>document.getElementById('typToggle').click()"); A.wait_for_timeout(200)
    with RLOCK: evs=sorted({m["event"] for st in RELAY.values() for m in st["msgs"]})
    r["relay_sees_only_msg_rcpt"]= set(evs)<={"msg","rcpt"}
    r["relay_events_v"]=evs
    r["group_labels"]= A.evaluate("()=>[window.__gz.typLabel(true,[['Ali','t']]), window.__gz.typLabel(true,[['Ali','v']]), window.__gz.typLabel(true,[['Ali','t'],['Can','v']]), window.__gz.typLabel(false,[['','v']])]")==["Ali is typing…","Ali is recording a voice message…","2 people are typing…","recording a voice message…"]
    # ---------- 3. rules ----------
    mid=a["mid"]
    A.evaluate("([m])=>window.__gz.onEdit({t:'edit',m:m,x:'HACK',body:'✏️ HACK'},false)",[mid]); A.wait_for_timeout(200)
    r["recv_edit_cant_touch_sent"]= A.evaluate(BUB,[SENTS])["txt"]=="hello world"
    A.evaluate("([m])=>window.__gz.onEdit({t:'edit',m:m,x:'',body:'x'},true)",[mid]); A.wait_for_timeout(100)
    r["empty_edit_ignored"]= A.evaluate(BUB,[SENTS])["txt"]=="hello world"
    A.evaluate("()=>{ const b=[...document.querySelectorAll('.log .bubble.sent')].pop(); b.dataset.ts0=b.dataset.ts; b.dataset.ts=String(Date.now()-25*3600*1000); }")
    A.locator(SENTS+" .txt").last.click(button="right"); A.wait_for_timeout(150)
    r["window_24h"]= A.evaluate(PICK)["edit"]==False
    A.keyboard.press("Escape"); A.evaluate("()=>{ const b=[...document.querySelectorAll('.log .bubble.sent')].pop(); b.dataset.ts=b.dataset.ts0; }")
    A.fill("#msgInput","x2"); A.locator(SENTS+" .txt").last.click(button="right"); A.wait_for_timeout(150); A.click("#rxEdit"); A.wait_for_timeout(150)
    A.click("#rbCancel"); A.wait_for_timeout(150)
    r["cancel_restores"]= A.input_value("#msgInput")=="x2" and not A.is_visible("#replyBar") and A.evaluate(BUB,[SENTS])["txt"]=="hello world"
    A.fill("#msgInput","")
    M=lambda c: c*16
    past=[{"mid":M("a"),"dir":"recv","env":{"t":"txt","body":"orig","pk":"P1"},"ts":1000,"vf":"ok"},
          {"mid":M("b"),"dir":"recv","env":{"t":"edit","m":M("a"),"x":"by P2","pk":"P2"},"ts":2000,"vf":"ok"},
          {"mid":M("c"),"dir":"recv","env":{"t":"edit","m":M("a"),"x":"unsigned","pk":"P1"},"ts":3000,"vf":"unsigned"},
          {"mid":M("d"),"dir":"recv","env":{"t":"edit","m":M("a"),"x":"good","pk":"P1"},"ts":4000,"vf":"ok"},
          {"mid":M("e"),"dir":"sent","env":{"t":"edit","m":M("a"),"x":"mine","pk":"P0"},"ts":5000},
          {"mid":M("f"),"dir":"recv","env":{"t":"edit","m":M("a"),"x":"too late","pk":"P1"},"ts":1000+25*3600*1000,"vf":"ok"},
          {"mid":"0"+M("1")[1:],"dir":"recv","env":{"t":"edit","m":M("a"),"x":"older","pk":"P1"},"ts":3500,"vf":"ok"}]
    r["group_rules"]= A.evaluate("([p])=>window.__gz.editsFrom(true,p)",[past])==[[M("a"),"good"]]
    r["onetoone_rules"]= A.evaluate("([p])=>window.__gz.editsFrom(false,p)",[past])==[[M("a"),"good"]]
    # ---------- 4. history: survives a lock / unlock ----------
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(800)
    A.fill("#pwInput","password123"); A.click("#joinBtn"); A.wait_for_timeout(1500)
    A.click(".ct"); A.wait_for_timeout(1500)
    tx=A.evaluate(TEXTS); a2=A.evaluate(BUB,[SENTS])
    r["history_edit_applied"]= a2["txt"]=="hello world" and a2["edm"] and "helo wrold" not in tx and not any("✏️" in x for x in tx)
    r["history_v"]=tx
    r["A_still_paired"]= wait_for(A,PAIRED,10000)
    # ---------- 4b. a colour for each chat (long press / right click on it in the list) ----------
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(300)
    A.locator(".ct").first.click(button="right"); A.wait_for_timeout(200)
    r["col_rightclick_opens"]= A.is_visible("#colPick") and A.evaluate("()=>document.querySelectorAll('#colGrid button').length")==13 and A.eval_on_selector("#colTitle","e=>e.textContent")=="Colour for serap"
    r["col_default_marked"]= A.evaluate("()=>document.querySelector('#colGrid button.on').dataset.c")==""
    A.click("#colGrid button[data-c=teal]"); A.wait_for_timeout(500)
    r["col_applied_list"]= not A.is_visible("#colPick") and A.evaluate("()=>getComputedStyle(document.querySelector('.ct .ava')).backgroundColor")=="rgb(15, 118, 110)"
    r["col_saved"]= A.evaluate("()=>{ const c=window.__gz.contacts().find(x=>!x.into); return c.cl==='teal' && c.cts>0; }")
    r["col_still_home"]= A.evaluate("()=>document.getElementById('app').classList.contains('home')")
    A.click(".ct"); A.wait_for_timeout(800)
    r["col_header_avatar"]= A.evaluate("()=>getComputedStyle(document.getElementById('peerAvatar')).backgroundColor")=="rgb(15, 118, 110)"
    cnow=A.evaluate("()=>window.__gz.contacts().find(x=>!x.into)")
    m1=A.evaluate("([c])=>window.__gz.merge({contacts:[Object.assign({},c,{cl:'red',cts:c.cts+1000})]}).contacts.find(x=>x.ck===c.ck).cl",[cnow])
    m2=A.evaluate("([c])=>window.__gz.merge({contacts:[Object.assign({},c,{cl:'red',cts:c.cts-1000})]}).contacts.find(x=>x.ck===c.ck).cl",[cnow])
    m3=A.evaluate("([c])=>{ const x=Object.assign({},c,{cts:c.cts+1000}); delete x.cl; return window.__gz.merge({contacts:[x]}).contacts.find(y=>y.ck===c.ck).cl||null; }",[cnow])
    r["col_vault_newest_wins"]= m1=="red" and m2=="teal" and m3 is None
    B.evaluate("()=>document.getElementById('backHome').click()"); B.wait_for_timeout(400)
    LONGROW=r"""([ms])=>new Promise(res=>{ const el=document.querySelector('.ct .cn'); const r=el.getBoundingClientRect(); const x=r.left+8, y=r.top+r.height/2;
      const mk=()=>new Touch({identifier:13,target:el,clientX:x,clientY:y,pageX:x,pageY:y});
      el.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,cancelable:true,touches:[mk()],targetTouches:[mk()],changedTouches:[mk()]}));
      setTimeout(()=>{ const np=el.dispatchEvent(new TouchEvent('touchend',{bubbles:true,cancelable:true,touches:[],changedTouches:[mk()]})); el.click(); res({open:!document.getElementById('colPick').hidden, prevented:!np}); }, ms); })"""
    lr=B.evaluate(LONGROW,[650]); B.wait_for_timeout(300)
    r["col_longpress_phone"]= lr=={"open":True,"prevented":True} and B.evaluate("()=>document.getElementById('app').classList.contains('home')")
    B.click("#colGrid button[data-c=pink]"); B.wait_for_timeout(400)
    r["col_phone_applied"]= B.evaluate("()=>getComputedStyle(document.querySelector('.ct .ava')).backgroundColor")=="rgb(219, 39, 119)"
    B.locator(".ct").first.click(button="right"); B.wait_for_timeout(150); B.click("#colGrid button[data-c='']"); B.wait_for_timeout(400)
    # back to the default: the contact's own colour, worked out from its key (v36), and no choice stored
    AUTO=r"""((ck)=>{ const hx={violet:'#7c3aed',indigo:'#4f46e5',blue:'#2563eb',sky:'#0369a1',teal:'#0f766e',green:'#15803d',lime:'#4d7c0f',amber:'#b45309',orange:'#c2410c',red:'#dc2626',pink:'#db2777',slate:'#475569'};
      const ks=Object.keys(hx); let h=0; for(const ch of ck) h=(h*31+ch.charCodeAt(0))>>>0; const c=hx[ks[h%ks.length]]; return 'rgb('+[1,3,5].map(i=>parseInt(c.slice(i,i+2),16)).join(', ')+')'; })"""
    r["col_reset"]= B.evaluate("()=>{ const c=window.__gz.contacts().find(x=>!x.into); return !c.cl && getComputedStyle(document.querySelector('.ct .ava')).backgroundColor==="+AUTO+"(c.ck); }")
    r["col_other_side_untouched"]= A.evaluate("()=>window.__gz.contacts().find(x=>!x.into).cl")=="teal"
    B.click(".ct"); B.wait_for_timeout(800)
    # ---------- 5. 1:1 video call: full screen ----------
    B.evaluate(SAMSUNG)       # her phone behaves like a Samsung: one camera at a time, no exact facing
    A.click("#videoBtn")
    r["B_incoming"]= wait_for(B,"()=>!document.getElementById('callUI').hidden && !document.getElementById('callIncoming').hidden",10000)
    B.evaluate("()=>document.getElementById('callAccept').click()")
    r["video_connected"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s&&s.live&&s.peers[0]&&s.peers[0].tracks.includes('video') && !document.querySelector('#callStage .peer').classList.contains('audio'); }",15000)
    A.wait_for_timeout(1200)
    FULL="()=>{ const v=document.querySelector('#callStage .peer video.mainv'); const r=v.getBoundingClientRect(); return {w:Math.round(r.width), h:Math.round(r.height), W:innerWidth, H:innerHeight, n1:document.getElementById('callStage').classList.contains('n1'), pos:getComputedStyle(v).position, fit:getComputedStyle(v).objectFit}; }"
    fa=A.evaluate(FULL); r["A_fullscreen"]= fa["n1"] and fa["w"]>=fa["W"]-1 and fa["h"]>=fa["H"]-1 and fa["pos"]=="absolute"
    r["A_full_v"]=fa
    wait_for(B,"()=>{ const s=window.__gz.callState(); return s&&s.peers[0]&&s.peers[0].tracks.includes('video'); }",8000); B.wait_for_timeout(800)
    fb=B.evaluate(FULL); r["B_fullscreen_cover"]= fb["w"]>=fb["W"]-1 and fb["h"]>=fb["H"]-1 and fb["fit"]=="cover"
    r["B_full_v"]=fb
    r["local_small"]= A.evaluate("()=>{ const v=document.getElementById('callLocal'); const r=v.getBoundingClientRect(); return !v.hidden && r.width>0 && r.width<innerWidth/3; }")
    cs=A.evaluate("()=>window.__gz.camSettings()"); r["hd_capture"]= bool(cs) and cs.get("width",0)>=1280; r["cam_v"]=cs and {k:cs.get(k) for k in ("width","height","frameRate")}
    r["buttons_fade_by_themselves"]= wait_for(A,"()=>document.getElementById('callUI').classList.contains('bare') && getComputedStyle(document.getElementById('callCtl')).pointerEvents==='none'",6000)
    A.mouse.click(500,400); A.wait_for_timeout(350)
    r["tap_shows_buttons"]= not A.evaluate("()=>document.getElementById('callUI').classList.contains('bare')")
    A.mouse.click(500,400); A.wait_for_timeout(350)
    r["tap_hides_buttons"]= A.evaluate("()=>document.getElementById('callUI').classList.contains('bare')")
    A.mouse.click(500,400); A.wait_for_timeout(300)
    r["fs_button_shown"]= A.is_visible("#callFs")
    A.click("#callFs"); A.wait_for_timeout(500)
    r["fs_button_enters"]= A.evaluate("()=>!!document.fullscreenElement")
    # switching camera on a "Samsung": the current camera is released first, then the back one opens
    c0=B.evaluate("()=>window.__gz.localCam()")
    B.evaluate("()=>document.getElementById('callFlip').click()"); B.wait_for_timeout(1500)
    c1=B.evaluate("()=>window.__gz.localCam()"); lg=B.evaluate("()=>window.__gumLog")
    r["flip_to_back"]= c0["id"]=="front" and c1["id"]=="back" and c1["same"] and c1["live"]=="live" and c1["n"]==1 and c1["mirror"]=="none" and "busy" not in lg
    B.evaluate("()=>document.getElementById('callFlip').click()"); B.wait_for_timeout(1500)
    c2=B.evaluate("()=>window.__gz.localCam()"); lg=B.evaluate("()=>window.__gumLog")
    r["flip_back_to_front"]= c2["id"]=="front" and c2["same"] and c2["mirror"]=="scaleX(-1)" and "busy" not in lg
    r["flip_v"]=[c0,c1,c2,lg]
    r["A_still_sees_video"]= A.evaluate("()=>{ const s=window.__gz.callState(); return s.peers[0].tracks.includes('video') && !document.querySelector('#callStage .peer').classList.contains('audio'); }")
    r["one_tile_in_1to1"]= A.evaluate("()=>window.__gz.tiles('other-device-id')")==1 and A.evaluate("()=>document.getElementById('callStage').classList.contains('n1')")
    A.click("#callEnd")
    r["video_closed"]= wait_for(A,"()=>document.getElementById('callUI').hidden",4000) and wait_for(B,"()=>document.getElementById('callUI').hidden",6000)
    r["no_bare_left"]= not A.evaluate("()=>document.getElementById('callUI').classList.contains('bare')")
    r["fs_left_after_call"]= A.evaluate("()=>!document.fullscreenElement")
    r["no_missed_after_answer"]= not any(x.get("kind")=="missed" for x in A.evaluate("()=>window.__notify"))
    # ---------- 6. she's offline: her phone rings again and again, then "missed call" ----------
    ctxB.close()
    r["B_gone"]= wait_for(A,"()=>{ const x=window.__gz.room(); return x && !x.paired; }",12000)
    A.evaluate("()=>{ window.__notify.length=0; }")
    A.click("#callBtn"); A.wait_for_timeout(1500)
    r["col_call_avatar"]= A.evaluate("()=>getComputedStyle(document.querySelector('#callStage .pav')).backgroundColor")=="rgb(15, 118, 110)"
    A.wait_for_timeout(14300)
    ns=A.evaluate("()=>window.__notify.map(x=>({kind:x.kind,tag:x.tag||'',nk:x.notify_key}))")
    calls=[x for x in ns if x["kind"]=="call"]
    r["ring_repeats"]= len(calls)>=3
    r["ring_count_v"]=len(calls)
    r["ring_tag"]= bool(calls) and len(set(x["tag"] for x in calls))==1 and all(len(x["tag"])==12 and x["tag"][0]=="c" for x in calls)   # v42: the tag names the pair (its v1 key), the key woken names a side
    A.click("#callEnd"); A.wait_for_timeout(900)
    ns2=A.evaluate("()=>window.__notify.map(x=>({kind:x.kind,tag:x.tag||'',nk:x.notify_key,body:x.body}))")
    miss=[x for x in ns2 if x["kind"]=="missed"]
    r["missed_sent"]= len(miss)==1 and miss[0]["tag"]==calls[0]["tag"]   # the body is the relay's fixed text since v41
    A.wait_for_timeout(7600)
    r["ring_stops"]= len([x for x in A.evaluate("()=>window.__notify") if x.get("kind")=="call"])==len(calls)
    # declined → no missed call (checked on the rule: only an unanswered call)
    # ---------- 7. service worker: the ringing alert ----------
    sw=A.evaluate(SWJS48)
    r["sw_call_alert"]= sw["r1"]=={"title":"📞 Gizleme","icon":"/call-icon.png","badge":"/call-badge.png","req":True,"ring":True,"vib":True,"renotify":True,"silent":False,"body":"Baba is calling you","closedBefore":1,"live":1}
    r["sw_missed_replaces"]= sw["r2"]=={"title":"Gizleme","body":"Missed call from Baba","silent":True,"ring":False,"req":False,"live":1,"badge":None}   # a missed call doesn't add to the app icon
    r["sw_missed_unknown"]= sw["r3"]=={"body":"Missed call"}
    r["sw_msg_unchanged"]= sw["r4"]["icon"]=="/icon-192.png" and sw["r4"]["req"]==False and sw["r4"]["title"]=="Gizleme" and sw["r4"]["badge"]==3
    r["sw_v"]=sw
    r["desktop_no_install_popup"]= not A.evaluate(MODAL)
    # ---------- 8. install invitation ----------
    ctxI,I=boot("ines",errsI,w=390,ua=IPHONE)
    r["ios_shown"]= wait_for(I,MODAL,6000)
    r["ios_steps"]= I.evaluate("()=>document.querySelectorAll('#installSteps li').length===3 && document.querySelectorAll('#installSteps svg.iico').length===2 && document.getElementById('installNow').style.display==='none'") and I.is_visible("#installNever")
    st=I.evaluate("()=>JSON.parse(window.__gz.instState())"); import time as _t
    r["ios_state"]= st["n"]==1 and st["next"]>_t.time()*1000+20*3600*1000 and not st.get("never")
    I.click("#installLater"); I.wait_for_timeout(200)
    relock(I); I.wait_for_timeout(3500)
    r["not_again_same_day"]= not I.evaluate(MODAL)
    I.evaluate("()=>{ const o=JSON.parse(localStorage.getItem('gz-install')); o.next=0; localStorage.setItem('gz-install',JSON.stringify(o)); }")
    relock(I)
    r["comes_back"]= wait_for(I,MODAL,6000) and I.evaluate("()=>JSON.parse(localStorage.getItem('gz-install')).n")==2
    I.click("#installNever"); I.wait_for_timeout(200)
    I.evaluate("()=>{ const o=JSON.parse(localStorage.getItem('gz-install')); o.next=0; localStorage.setItem('gz-install',JSON.stringify(o)); }")
    relock(I); I.wait_for_timeout(3500)
    r["never_again"]= not I.evaluate(MODAL)
    ctxI.close()
    ctxL,L=boot("lea",errsI,w=390,ua=IPHONE,init="try{ if(!localStorage.getItem('gz-install')) localStorage.setItem('gz-installPrompted','1'); }catch(e){}")
    r["legacy_flag_reshown"]= wait_for(L,MODAL,6000) and L.evaluate("()=>JSON.parse(localStorage.getItem('gz-install')).n")==2
    ctxL.close()
    ctxK,K=boot("kaan",errsI,w=390,ua=IPHONE,init="try{ localStorage.setItem('gz-installed', String(Date.now())); }catch(e){}")
    K.wait_for_timeout(3500); r["installed_recently_no_popup"]= not K.evaluate(MODAL)
    ctxK.close()
    ctxD,D=boot("deniz",errsI,w=390,ua=ANDROID)
    r["android_steps"]= wait_for(D,MODAL,11000) and D.evaluate("()=>document.getElementById('installSteps').textContent.includes('Install app') && document.querySelectorAll('#installSteps li').length===3")
    D.click("#installLater"); D.wait_for_timeout(200)
    D.evaluate("()=>document.getElementById('installPill').click()"); D.wait_for_timeout(200)
    r["settings_button_opens_steps"]= D.evaluate(MODAL) and not D.is_visible("#installNever") and D.evaluate("()=>JSON.parse(localStorage.getItem('gz-install')).n")==1
    ctxD.close()
    r["errors"]= (errsA+errsB+errsI)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
