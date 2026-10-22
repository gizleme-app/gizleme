# Review fixes: the mailbox key chain counts from the opener's week even when the inviter reads the hello a week
# later; removals are remembered across devices (tombstones); removing a chat clears its unread count; the admin's
# key renewal reaches the admin's own identity; the "new version" pill never reloads the New-chat screen; the
# service worker's offline shell is only the app itself and a tapped notification tells an open window.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site47"); site.mkdir(exist_ok=True)
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
  merge:(x)=>JSON.parse(JSON.stringify(mergeContacts(x))), soundMode:()=>soundMode(), unreadTotal:()=>unreadTotal(), checkUpdate:()=>checkUpdate(true), shiftEpoch:(n)=>{ const o=epochNow; epochNow=()=>o()+n; }, inbox:()=>inboxPull(true), meta:()=>JSON.parse(JSON.stringify({unread:_meta.unread,gone:_meta.gone||{}})), remove:(ck)=>contactRemove(ck), rotate:()=>rotateGroup(A()), gk2:()=>window.__gk2, myPk:async()=>(await identEnsure()).pk };
broadcastGroup=(function(f){ return function(R,env,mid){ if(env&&env.t==='gk2') window.__gk2=JSON.parse(JSON.stringify(env)); return f.apply(this,arguments); }; })(broadcastGroup);

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

def wait_for(page, js, timeout=20000, step=150):
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
RECV="(t)=>[...document.querySelectorAll('.log:not([style*=\"display: none\"]) .bubble.recv .txt')].some(e=>e.textContent===t)"
SWJS=r"""async ()=>{ const sw=await fetch('/sw.js').then(r=>r.text()); const H={}, store=new Map(), posted=[];
  const fakeCaches={ open: async()=>({ put: async(k,res)=>{ store.set(typeof k==='string'?k:k.url, await res.text()); }, match: async(k)=> undefined, addAll: async()=>{} }), keys: async()=>[], delete: async()=>true };
  const fakeSelf={ addEventListener:(t,f)=>{ H[t]=f; }, location:{origin:location.origin}, registration:{ showNotification: async()=>{} }, navigator:{},
    clients:{ matchAll: async()=>[{url:location.origin+"/privacy.html", focus:async()=>{}, postMessage:(m)=>posted.push("privacy")}, {url:location.origin+"/", focus:async()=>{}, postMessage:(m)=>posted.push("app:"+m.url)}], claim: async()=>{} }, skipWaiting:()=>{} };
  const fakeFetch=async(req)=>new Response("<html>x</html>",{status:200,headers:{"Content-Type":"text/html"}});
  new Function("self","caches","fetch", sw)(fakeSelf, fakeCaches, fakeFetch);
  const nav=async(path)=>{ let p=null; H.fetch({ request:{ method:"GET", url:location.origin+path, mode:"navigate" }, respondWith:(x)=>{ p=x; } }); await p; await new Promise(r=>setTimeout(r,50)); };
  await nav("/privacy.html"); const afterPrivacy=[...store.keys()];
  await nav("/"); const afterRoot=[...store.keys()];
  let pr=null; H.notificationclick({ notification:{ close(){}, data:{ url: location.origin+"/#n=ABC" } }, waitUntil:(x)=>{ pr=x; } }); await pr;
  return { afterPrivacy, afterRoot, posted }; }"""
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000):
        ctx=b.new_context(timezone_id=TZ, viewport={"width":w,"height":820},locale="en-US"); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); entered(p)
        return ctx,p
    errsA=[]; errsB=[]
    ctxA,A=boot("oguz",errsA)
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(600)
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    # the inviter will read the hello "a week later": its clock's week moves forward before the hello arrives
    A.evaluate("()=>window.__gz.shiftEpoch(1)")
    ctxB,B=boot("serap",errsB,w=390)
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); entered(B, 2500)
    send(B,"from the past week")      # written under B's week, while A is "offline" (not in the chat)
    r["A_bound"]= wait_for(A,"()=>{ const c=window.__gz.contacts()[0]; return !!(c && c.he); }",10000)
    kc=A.evaluate("()=>{ const c=window.__gz.contacts()[0]; return [c.kce, !!c.kc]; }"); kb=B.evaluate("()=>{ const c=window.__gz.contacts()[0]; return [c.kce, !!c.kc]; }")
    r["chain_sameWeek"]= kc[1] and kb[1] and kc[0]==kb[0]
    A.click(".ct"); A.wait_for_timeout(800)
    r["A_reads_earlier_week"]= wait_for(A, "()=>("+RECV+")('from the past week')", 12000)
    B.evaluate("()=>document.getElementById('backHome').click()"); B.wait_for_timeout(300)
    send(A,"from the next week")      # written under A's (later) week, B not in the chat → mailbox
    B.wait_for_timeout(500); B.click(".ct"); B.wait_for_timeout(800)
    r["B_reads_later_week"]= wait_for(B, "()=>("+RECV+")('from the next week')", 15000)
    # --- removing a chat: unread count gone, and a tombstone that keeps another device's copy from coming back
    B.evaluate("()=>document.getElementById('backHome').click()"); B.wait_for_timeout(300)
    send(A,"unread 1"); send(A,"unread 2")
    r["unread_before"]= wait_for(B,"()=>document.title==='(2) Gizleme'",8000)
    rec=B.evaluate("()=>window.__gz.contacts()[0]")
    B.evaluate("([ck])=>window.__gz.remove(ck)",[rec["ck"]]); B.wait_for_timeout(400)
    r["unread_cleared"]= B.evaluate("()=>document.title==='Gizleme' && Object.keys(window.__gz.meta().unread).length===0")
    r["tombstoned"]= B.evaluate("([ck])=>(window.__gz.meta().gone[ck]||0)>0",[rec["ck"]])
    m=B.evaluate("([rec])=>window.__gz.merge({contacts:[rec]})",[rec])
    r["other_device_copy_not_resurrected"]= not any(c["ck"]==rec["ck"] for c in m["contacts"])
    newer=dict(rec); newer["ts"]=B.evaluate("()=>Date.now()+5000")
    m2=B.evaluate("([rec])=>window.__gz.merge({contacts:[rec]})",[newer])
    r["re_added_later_wins"]= any(c["ck"]==rec["ck"] for c in m2["contacts"])
    # --- the "new version" pill never reloads the New-chat screen
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200); A.click("#sbNew"); A.wait_for_timeout(300)
    swv=int(__import__("re").search(r'const CACHE = "gizleme-v(\d+)";', pathlib.Path(SRC+"sw.js").read_text()).group(1))
    swtxt=(site/"sw.js").read_text(); (site/"sw.js").write_text(swtxt.replace(f'gizleme-v{swv}"', f'gizleme-v{swv+1}"'))
    A.evaluate("()=>{ window.__mark=1; }"); A.evaluate("()=>window.__gz.checkUpdate()"); A.wait_for_timeout(800)
    r["newchat_notReloaded"]= A.evaluate("()=>window.__mark===1") and A.is_visible("#updPill")
    (site/"sw.js").write_text(swtxt)
    # --- the service worker: only the app is the offline shell; a tap tells the app window (not the privacy tab)
    sw=A.evaluate(SWJS)
    r["sw_privacy_not_shell"]= "/index.html" not in sw["afterPrivacy"]
    r["sw_root_is_shell"]= "/index.html" in sw["afterRoot"]
    r["sw_tap_tells_app"]= sw["posted"]==["app:"+f"http://127.0.0.1:{port}"+"/#n=ABC"]
    # --- group key renewal reaches the admin's own identity (its other devices)
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200); A.click("#sbNew"); A.wait_for_timeout(300)
    A.click(".nctab[data-nc=group]"); A.wait_for_timeout(200); A.fill("#gnameInput","Famille"); A.click("#joinBtn"); A.wait_for_timeout(1200)
    r["rotated"]= A.evaluate("async()=>await window.__gz.rotate()")
    A.wait_for_timeout(500)
    r["gk2_selfWrapped"]= A.evaluate("async()=>{ const e=window.__gz.gk2(); const pk=await window.__gz.myPk(); return !!(e && e.w && e.w[pk]); }")
    r["errors"]= (errsA+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
