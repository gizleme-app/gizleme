# Settings → Sounds (messages and calls / calls only / none), per-chat mute (1 h, 8 h, always; synced; silent
# pushes), the unread count in the tab title and on the icon, the "New messages" line, and invites sent through
# WhatsApp or the share sheet opening the new chat (no blank page left behind on a phone), and the
# "new version available" pill.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site44"); site.mkdir(exist_ok=True)
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
HOOK='''const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); };   // tests: the house dialog answers like page.on("dialog") did — yes, or the prompt value; window.__askPolicy decides per question
window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),
  callState:()=>call?{state:call.state,live:!!call.t1,group:!!call.group,video:call.video,dir:call.dir,peers:[...call.peers.values()].map(P=>({pid:P.pid,cs:P.pc.connectionState,connected:P.connected,tracks:P.stream.getTracks().map(t=>t.kind)})),localAudioOn:call.local?call.local.getAudioTracks().every(t=>t.enabled):null,localVideo:call.local?call.local.getVideoTracks().length:0}:null,
  setIce:(l)=>{ _iceCache={servers:l,exp:Date.now()+1e9}; }, room:()=>{ const R=A(); return R?{paired:R.paired,group:R.group,gcall:R.gcall?R.gcall.cid:null,ck:R.fromContact}:null; },
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), histOf:async()=>{ const R=A(); const l=await histLoad(histKeyOf(R)); return l.map(r=>r.mid+'|'+r.dir+'|'+(r.env&&r.env.t)); }, lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; },
  merge:(x)=>JSON.parse(JSON.stringify(mergeContacts(x))), soundMode:()=>soundMode(), unreadTotal:()=>unreadTotal(), checkUpdate:()=>checkUpdate(true) };
'''
_app=_app[:_app.rstrip().rfind("})();")]+HOOK+'})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg","logo-head.png","logo-word.png","logo-dot.png"]:
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
IPHONE="Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
STUB="window.__opened=[]; window.open=function(u){ window.__opened.push(String(u)); return null; };"
SHARE="navigator.share=async()=>{ window.__shared=(window.__shared||0)+1; };"
SWJS=r"""async ()=>{ const sw=await fetch('/sw.js').then(r=>r.text()); const H={}, shown=[], store=new Map(); let badge=null;
  const fakeCaches={ open: async()=>({ put: async(k,res)=>{ store.set(k, await res.text()); }, match: async(k)=> store.has(k) ? new Response(store.get(k)) : undefined }), keys: async()=>[], delete: async()=>true };
  const fakeSelf={ addEventListener:(t,f)=>{ H[t]=f; }, location:{origin:location.origin}, registration:{ showNotification: async(title,o)=>{ shown.push(o); } },
    navigator:{ setAppBadge: async(n)=>{ badge=n; } }, clients:{ claim: async()=>{} }, skipWaiting:()=>{} };
  new Function("self","caches", sw)(fakeSelf, fakeCaches);
  const run=async(type, ev)=>{ let p=null; ev.waitUntil=x=>{ p=x; }; H[type](ev); await p; };
  const hh=async s=>{ const b=new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s))); return btoa(String.fromCharCode(...b)).replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/,""); };
  await run("message",{data:{type:"names", names:{[await hh("NK1")]:"Baba",[await hh("NK2")]:"Ali"}, muted:{[await hh("NK1")]:Date.now()+3600000}, tmpl:{msg:"New message from {name}", call:"{name} is calling you"}}});
  await run("message",{data:{type:"badge", n:2}});
  const push=d=>run("push",{data:{json:()=>d}});
  await push({kind:"msg", url:"/#n=NK1", tag:"a"}); const r1={silent:shown[0].silent, renotify:shown[0].renotify, badge};
  await push({kind:"msg", url:"/#n=NK2", tag:"b"}); const r2={silent:shown[1].silent, renotify:shown[1].renotify, body:shown[1].body, badge};
  await push({kind:"call", url:"/#n=NK1", tag:"c"}); const r3={silent:shown[2].silent, body:shown[2].body, badge};
  return {r1,r2,r3}; }"""
HIDE="()=>{ Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>'hidden'}); Object.defineProperty(document,'hidden',{configurable:true,get:()=>true}); document.dispatchEvent(new Event('visibilitychange')); }"
SHOW="()=>{ delete document.visibilityState; delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); }"
INCHAT="()=>{ const x=window.__gz.room(); return !!(x && x.ck) && getComputedStyle(document.getElementById('join')).display==='none' && !document.getElementById('app').classList.contains('home'); }"
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000, ua=None, extra=""):
        kw={"viewport":{"width":w,"height":820},"locale":"en-US"}
        if ua: kw["user_agent"]=ua
        ctx=b.new_context(**kw); ctx.add_init_script(COUNT); ctx.add_init_script(STUB+extra); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    errsA=[]; errsB=[]; errsC=[]
    ctxA,A=boot("oguz",errsA)
    # --- invite through WhatsApp on a computer: wa.me in a new tab, and the new chat is open here
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value")
    A.click("#waShare"); A.wait_for_timeout(300)
    op=A.evaluate("()=>window.__opened")
    r["wa_desktop_waMe"]= len(op)==1 and op[0].startswith("https://wa.me/?text=") and urllib.parse.quote(link[link.index("#"):],safe="") in op[0]
    r["wa_desktop_chatOpens"]= wait_for(A, INCHAT, 5000)
    ctxB,B=boot("florian",errsB,w=390)
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(2500)
    r["paired"]= wait_for(A,"()=>{ const x=window.__gz.room(); return x && x.paired; }",10000) and wait_for(B,"()=>{ const x=window.__gz.room(); return x && x.paired; }",10000)
    A.wait_for_timeout(600)
    # --- unread count in the title, and the "New messages" line when the chat is opened
    B.click("#backHome"); B.wait_for_timeout(400)
    for m in ["m1","m2","m3"]: send(A,m)
    r["title_count"]= wait_for(B,"()=>document.title==='(3) Gizleme'",8000)
    r["title_v"]=B.evaluate("()=>document.title")
    B.click(".ct"); B.wait_for_timeout(700)
    r["divider"]= B.evaluate("()=>{ const s=document.querySelector('.log:not([style*=\"display: none\"]) .newsep'); if(!s) return false; const n=s.nextElementSibling; return s.textContent==='3 new messages' && !!n && n.classList.contains('recv') && n.querySelector('.txt').textContent==='m1'; }")
    r["title_cleared"]= B.evaluate("()=>document.title==='Gizleme'")
    B.click("#backHome"); B.wait_for_timeout(300); B.click(".ct"); B.wait_for_timeout(400)
    r["divider_gone_on_reopen"]= B.evaluate("()=>!document.querySelector('.newsep')")
    # a chat opened from scratch (after unlocking): the line is placed once its history is on screen
    B.evaluate("()=>document.getElementById('sbLock').click()"); B.wait_for_timeout(2600)
    send(A,"n1"); send(A,"n2"); A.wait_for_timeout(800)
    B.fill("#pwInput","password123"); B.click("#joinBtn")
    r["unlock_counted"]= wait_for(B,"()=>document.title==='(2) Gizleme'",10000)
    B.click(".ct"); B.wait_for_timeout(1200)
    r["divider_after_unlock"]= B.evaluate("()=>{ const s=document.querySelector('.log:not([style*=\"display: none\"]) .newsep'); return !!s && s.textContent==='2 new messages' && s.nextElementSibling.querySelector('.txt').textContent==='n1'; }")
    wait_for(A,"()=>{ const x=window.__gz.room(); return x && x.paired; }",10000); wait_for(B,"()=>{ const x=window.__gz.room(); return x && x.paired; }",10000)
    # --- Settings → Sounds
    B.click("#backHome"); B.wait_for_timeout(300)
    B.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); B.evaluate("()=>document.querySelector('#settingsModal [data-go=notif]').click()"); B.select_option("#soundSel","calls"); B.evaluate("()=>document.getElementById('settingsModal').classList.remove('show')")
    r["mode_saved"]= B.evaluate("()=>localStorage.getItem('gz-sounds')")=="calls"
    B.wait_for_timeout(4200); b0=osc(B); send(A,"silence"); wait_for(B,"()=>!!document.querySelector('.ct .ubadge')",8000); B.wait_for_timeout(1200)
    r["callsOnly_msgSilent"]= osc(B)==b0
    B.evaluate("()=>document.getElementById('settingsModal').classList.add('show')"); B.evaluate("()=>document.querySelector('#settingsModal [data-go=notif]').click()"); B.select_option("#soundSel","all"); B.evaluate("()=>document.getElementById('settingsModal').classList.remove('show')")
    B.wait_for_timeout(4200); b1=osc(B); send(A,"ding")
    r["all_rings"]= wait_for(B,"()=>(window.__osc||0)>"+str(b1),8000)
    r["migration_offMeansCalls"]= B.evaluate("()=>{ localStorage.removeItem('gz-sounds'); localStorage.setItem('vesper-sound','off'); const m=window.__gz.soundMode(); localStorage.setItem('gz-sounds','all'); return m; }")=="calls"
    r["defaultTone_gizleme"]= B.evaluate("()=>{ document.getElementById('settingsModal').classList.add('show'); const c=document.querySelector('#toneSel .tone[aria-checked=true]'); document.getElementById('settingsModal').classList.remove('show'); return c && c.dataset.tone; }")=="gizleme"
    # --- mute for 1 hour from the chat menu
    B.click(".ct"); B.wait_for_timeout(500)
    B.click("#menuBtn"); B.wait_for_timeout(150)
    r["menu_muteShown"]= B.is_visible("#mi-mute") and not B.is_visible("#mi-unmute")
    B.click("#mi-mute"); B.wait_for_timeout(150)
    r["menu_optsOpen"]= B.is_visible("#mi-mute-opts") and B.is_visible("#barMenu")
    B.click("#mi-mute-opts [data-act=mute1h]"); B.wait_for_timeout(300)
    mu=B.evaluate("()=>{ const c=window.__gz.contacts()[0]; return [c.mu||0, c.mts||0, Date.now()]; }")
    r["mute_1h"]= abs(mu[0]-(mu[2]+3600000))<60000 and mu[1]>0
    r["mute_toast"]= "Muted until" in B.eval_on_selector("#toast","e=>e.textContent")
    B.wait_for_timeout(1500); b2=osc(B); send(A,"chut (open)"); B.wait_for_timeout(1500)
    r["muted_openChat_silent"]= osc(B)==b2
    B.click("#backHome"); B.wait_for_timeout(400)
    r["row_mutedIcon"]= B.evaluate("()=>!!document.querySelector('.ct.muted .mute-ico')")
    b3=osc(B); send(A,"chut"); wait_for(B,"()=>!!document.querySelector('.ct .ubadge')",8000); B.wait_for_timeout(1200)
    r["muted_noSound"]= osc(B)==b3
    r["muted_noGlow"]= B.evaluate("()=>!document.querySelector('.ct.pulse')")
    r["muted_badgeGrey"]= B.evaluate("()=>!!document.querySelector('.ct .ubadge.muted')")
    r["muted_notCounted"]= B.evaluate("()=>document.title==='Gizleme' && window.__gz.unreadTotal()===0")
    # the menu now offers to turn the sound back on, with the time it ends
    B.click(".ct"); B.wait_for_timeout(400); B.click("#menuBtn"); B.wait_for_timeout(150)
    r["menu_unmuteShown"]= B.is_visible("#mi-unmute") and not B.is_visible("#mi-mute") and len(B.eval_on_selector("#mi-mute-until","e=>e.textContent"))>4
    B.click("#mi-unmute"); B.wait_for_timeout(300)
    r["unmuted"]= B.evaluate("()=>!('mu' in window.__gz.contacts()[0])")
    B.click("#menuBtn"); B.wait_for_timeout(150); B.click("#mi-mute"); B.wait_for_timeout(100); B.click("#mi-mute-opts [data-act=muteall]"); B.wait_for_timeout(300)
    r["mute_always"]= B.evaluate("()=>window.__gz.contacts()[0].mu===8.64e15")
    B.click("#menuBtn"); B.wait_for_timeout(150)
    r["always_noUntil"]= B.is_visible("#mi-unmute") and B.eval_on_selector("#mi-mute-until","e=>e.textContent")==""
    B.click("#mi-unmute"); B.wait_for_timeout(300)
    # --- across devices: the last change wins
    m=B.evaluate("()=>{ const c=window.__gz.contacts()[0]; const now=Date.now();"
                 " const newer=window.__gz.merge({contacts:[Object.assign({},c,{mu:now+5000,mts:now+1000})]}).contacts.find(x=>x.ck===c.ck);"
                 " const older=window.__gz.merge({contacts:[Object.assign({},c,{mu:now+5000,mts:1})]}).contacts.find(x=>x.ck===c.ck);"
                 " return [!!newer.mu, !older.mu]; }")
    r["merge_newerWins"]=m[0]; r["merge_olderIgnored"]=m[1]
    # --- the service worker: a muted chat's push is silent and not counted; another one adds one to the icon
    sw=A.evaluate(SWJS)
    r["sw_muted_silent"]= sw["r1"]["silent"] is True and sw["r1"]["renotify"] is False and sw["r1"]["badge"] is None
    r["sw_other_counts"]= sw["r2"]["silent"] is False and sw["r2"]["renotify"] is True and sw["r2"]["badge"]==3 and sw["r2"]["body"]=="New message from Ali"
    r["sw_call_rings"]= sw["r3"]["silent"] is False and sw["r3"]["badge"]==3
    # --- on a phone: WhatsApp's own link scheme (no wa.me page left behind), and the chat opens once WhatsApp is in front
    NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"   # not about installing: no invitation popping up mid-test
    ctxC,C=boot("carla",errsC,w=390,ua=IPHONE,extra=SHARE+NOINST)
    C.click("#fabNew"); C.wait_for_timeout(300)
    C.click("#waShare"); C.wait_for_timeout(400)
    r["wa_phone_noWebPage"]= C.evaluate("()=>window.__opened.length")==0 and C.evaluate("()=>location.origin")==f"http://127.0.0.1:{port}"
    r["wa_phone_staysUntilHandoff"]= not C.evaluate(INCHAT)
    C.evaluate(HIDE); C.wait_for_timeout(200); C.evaluate(SHOW)
    r["wa_phone_chatOpens"]= wait_for(C, INCHAT, 5000)
    # WhatsApp missing: nothing happens on screen → a hint, and you stay on the link page
    C.click("#backHome"); C.wait_for_timeout(300)
    C.evaluate("()=>document.querySelectorAll('.modal.show').forEach(m=>m.classList.remove('show'))")   # the iPhone "add to Home Screen" tip
    C.click("#fabNew"); C.wait_for_timeout(300)
    C.click("#waShare"); C.wait_for_timeout(3400)
    r["wa_phone_hint"]= "WhatsApp" in C.eval_on_selector("#toast","e=>e.textContent") and not C.evaluate(INCHAT)
    # the share sheet: once it completed, the new chat opens
    C.click("#copyLink"); C.wait_for_timeout(600)
    r["share_thenChat"]= C.evaluate("()=>window.__shared")==1 and wait_for(C, INCHAT, 5000)
    # --- a newer version on the server: a pill offers to update (the page's version and the worker's agree)
    import re as _re2
    appv=int(_re2.search(r"const APP_VERSION = (\d+);", pathlib.Path(SRC+"app.js").read_text()).group(1))
    swv=int(_re2.search(r'const CACHE = "gizleme-v(\d+)";', pathlib.Path(SRC+"sw.js").read_text()).group(1))
    r["version_inStep"]= appv==swv
    B.evaluate("()=>window.__gz.checkUpdate()"); B.wait_for_timeout(500)
    r["upd_noPillWhenCurrent"]= not B.is_visible("#updPill")
    swtxt=(site/"sw.js").read_text(); (site/"sw.js").write_text(swtxt.replace(f'gizleme-v{swv}"', f'gizleme-v{swv+1}"'))
    B.evaluate("()=>window.__gz.checkUpdate()")
    r["upd_pillShown"]= wait_for(B,"()=>!document.getElementById('updPill').hidden",4000) and B.is_visible("#updGo")
    B.click("#updX"); B.wait_for_timeout(200); B.evaluate("()=>window.__gz.checkUpdate()"); B.wait_for_timeout(500)
    r["upd_laterHolds"]= not B.is_visible("#updPill")
    # at the login screen with nothing typed, it just reloads
    ctxD=b.new_context(viewport={"width":390,"height":820},locale="en-US"); D=ctxD.new_page(); D.on("pageerror",lambda e:errsC.append(str(e)))
    D.goto(f"http://127.0.0.1:{port}/"); D.wait_for_timeout(600); D.evaluate("()=>{ window.__mark=1; }")
    D.evaluate("()=>window.__gz && window.__gz.checkUpdate ? window.__gz.checkUpdate() : null"); D.wait_for_timeout(1500)
    r["upd_reloadsWhenIdle"]= D.evaluate("()=>window.__mark===undefined")
    # tapping the pill reloads (here: an open, unlocked app → it comes back on the unlock screen)
    B.evaluate("()=>{ document.getElementById('updPill').hidden=false; window.__mark=1; }"); B.click("#updGo"); B.wait_for_timeout(1500)
    r["upd_tapReloads"]= B.evaluate("()=>window.__mark===undefined") and B.is_visible("#pwInput")
    (site/"sw.js").write_text(swtxt)
    r["errors"]= (errsA+errsB+errsC)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
