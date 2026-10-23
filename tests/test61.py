# v45 robustness: removing a contact (or leaving a group) also removes what the chat left on the device — its
# records and media in IndexedDB, its disappearing timer, its seen ids; a chat left open across midnight (UTC) follows
# its rendezvous room, on both sides, so the two still find each other; the account backup answering 401 is said (after
# the session has been checked); a backup that couldn't be opened at log-in is opened at the next "online" (the
# password-derived key stays in memory until then) and the empty list says so; while the account marker is unknown a
# deposit waits; the composer keeps a draft per chat; a pairing alone no longer bumps a contact's record (a removed
# contact can't come back from another device through the merge); a member removed then invited back is not thrown out
# by the old rotation; the history's newest record is the newest by time (DB v3 index).
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site61"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__notify=[]; window.__reg=[]; window.__valid=true; window.__targets=1; window.__vault={abk:null,contacts:null,cver:0};
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
    if(n==="gizleme-auth"||n==="gizleme-vault"){
      if(n==="gizleme-vault" && window.__vault401) return {data:null, error:{context:{status:401}, message:"401"}};
      if(n==="gizleme-vault" && window.__vaultDown) return {data:null, error:{context:{status:503}, message:"503"}};
      if(n==="gizleme-auth" && b.action==="validate" && window.__valid===false) return {data:{ok:true, valid:false}};
      const j=await fetch("/acct",{method:"POST",body:JSON.stringify(Object.assign({fn:n},b))}).then(r=>r.json()); return {data:j}; }
    if(n==="gizleme-push"&&b.action==="register"){ window.__reg.push(b); return {data:{ok:true}}; }
    if(n==="gizleme-mbox"){ const j=await fetch("/mbox",{method:"POST",body:JSON.stringify(b)}).then(r=>r.json()); return {data:j}; }
    if(n==="gizleme-push"&&b.action==="notify"){ window.__notify.push(b); return {data:{ok:true,sent:window.__targets,targets:window.__targets}}; }
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
  merge:(x)=>JSON.parse(JSON.stringify(mergeContacts(x))), soundMode:()=>soundMode(), unreadTotal:()=>unreadTotal(), checkUpdate:()=>checkUpdate(true), openCk:(ck)=>openContact(ck,'x'), inbox:()=>inboxPull(true),
  editsFrom:(g,past)=>[...editsFrom({group:g},past)].map(([k,v])=>[k,v.x]), onEdit:(env,own,ts)=>{ const R=A(); onEditEnv(R,env,'x',ts||Date.now(),rid(),!!own); },
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install'), rid:()=>rid(), sendEnv:(env)=>{ const R=A(); return deliverOut(R, env, rid(), null, Date.now(), true); }, inb:(env,mid,own)=>{ const R=A(); onInbound(R, env, '', Date.now(), mid, !!own, false); }, delm:()=>JSON.parse(JSON.stringify(_meta.delm||{})), localTracks:()=>call&&call.local?call.local.getTracks().map(t=>t.kind):[], qual:(s)=>qualSample(s), live:()=>!!(call&&call.t1), histSave:(rec)=>histSave(histKeyOf(A()),rec), bioLabel:()=>bioLabel(), expG:()=>expGlobal(), outqAll:()=>JSON.parse(JSON.stringify(_meta.outq||{})),
  nk:(ck,role)=>notifyKeyFor(ck,role||undefined), regKeys:()=>notifyKeysToRegister(), clearNotified:()=>{ _meta.notified={}; }, mkPub:async()=>b64(await pubRaw(await genKP())),
  hello:(ck,e,h)=>processHello(ck,e,'x',null,false,undefined,h), sids:()=>JSON.parse(JSON.stringify(_meta.sids||{})), purge:(mids)=>histPurge(histKeyOf(A()),new Set(mids)), forgetSeen:()=>{ for(const k in _seenByKey) _seenByKey[k].clear(); _meta.sids={}; },
  glink:()=>groupInviteLink(A()), group:()=>groupsLoad().find(g=>g.rid===A().rid), ident:()=>identLoad(), rotate:(pk)=>rotateGroup(A(),pk||null), gk2s:()=>JSON.parse(JSON.stringify(window.__gk2s||[])),
  replay:(env)=>{ const R=A(); return depositMailbox(R, env.mid, env); }, lastSysAll:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; },
  forgeOld:async(body, ago)=>{ const R=A(); const mid=rid(); R.seen.add(mid); const obj=Object.assign({},{t:'txt',body},{mid,n:myName,sts:Date.now()-ago}); const id=await identEnsure(); obj.pk=id.pk; obj.ek=id.ek; obj.sig=b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'}, id.priv, gsigData(R.rid,obj))); return broadcastGroup(R,obj,mid); },
  typing:()=>{ const R=A(); return R&&R.typing?[...R.typing.keys()]:[]; }, typSend:(s)=>typingSend(A(),s),
  rawTyp:async(name)=>{ const R=A(); const env={t:'typ',s:'t',n:name}; const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:'AES-GCM',iv},R.gkMsg,enc.encode(JSON.stringify(env))); return R.channel.send({type:'broadcast',event:'rcpt',payload:{from:R.id,iv:b64(iv),ct:b64(ct)}}); },
  rawMsg:async(env)=>{ const R=A(); const mid=rid(); const obj=Object.assign({},env,{mid,n:myName}); const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:'AES-GCM',iv},R.gkMsg,enc.encode(JSON.stringify(obj))); return R.channel.send({type:'broadcast',event:'msg',payload:{from:R.id,iv:b64(iv),ct:b64(ct),mid}}); },
  exp:()=>expFor(histKeyOf(A())) };
const _onGk2=onGk2; onGk2=async(R,env,vf,who,cur)=>{ window.__gk2s=(window.__gk2s||[]).concat([{env,cur}]); return _onGk2(R,env,vf,who,cur); };
Object.assign(window.__gz,{ hk:(ck)=>ckHistKey(ck), code:()=>{ const R=A(); return R?R.code:null; }, rollover:()=>{ _dayAt=0; rolloverRooms(); },
  idbCount:(room)=>idb().then(db=>new Promise((res,rej)=>{ const tx=db.transaction(["msgs","media"]); const out={}; for(const st of ["msgs","media"]){ const rq=tx.objectStore(st).index("room").count(IDBKeyRange.only(room)); rq.onsuccess=()=>{ out[st]=rq.result; }; } tx.oncomplete=()=>res(out); tx.onerror=()=>rej(tx.error); })),
  seedMedia:(room)=>mediaPut(room,'seed-'+rid(),new Uint8Array(64),Date.now()), expMap:()=>expRoomsMap(), setExp:(v)=>{ const R=A(); setExpRoom(histKeyOf(R), v); },
  abk:()=>({abk:!!gABK, ak:!!_abkAK, acct:!!_acct, pending:acctPending()}), listText:()=>{ const e=document.querySelector('.sb-list .empty, .sb-list .hint, .sb-list p'); return e?e.textContent:document.querySelector('.sb-list').textContent; },
  dbVersion:()=>idb().then(db=>({v:db.version, idx:[...db.transaction("msgs").objectStore("msgs").indexNames]})),
  histLast:(room)=>histLast(room).then(r=>r&&r.env&&r.env.body), histSaveAt:(room,body,ts)=>histSave(room,{dir:'recv',env:{t:'txt',body},ts,mid:rid()}),
  canSend:()=>!document.getElementById('msgInput').disabled, left:()=>!!(groupsLoad().find(g=>g.rid===A().rid)||{}).left, doJoinGroup:(l)=>doJoinGroup(l), hold:()=>_meta.mbts });
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

RELAY={}; RLOCK=threading.Lock(); MBOX={}; ACKS=[]; BLOBS={}; TOKENS=[]; ACCTS={}
def acct(body):
    fn=body.get("fn"); a=body.get("action"); u=(body.get("username") or "").lower()
    if fn=="gizleme-auth":
        if a=="register": ACCTS[u]={"salt":body.get("salt"),"abk":None,"contacts":None,"cver":0,"display":body.get("display") or u}; return {"ok":True,"token":"t:"+u,"username":u,"display":ACCTS[u]["display"]}
        if a=="salt": return {"ok":True,"salt":(ACCTS.get(u) or {}).get("salt") or ""}
        if a=="login": return {"ok":True,"token":"t:"+u,"username":u,"display":(ACCTS.get(u) or {}).get("display") or u} if u in ACCTS else {"ok":False}
        if a=="validate": return {"ok":True,"valid":True}
        return {"ok":True}
    acc=ACCTS.get((body.get("token") or "")[2:]) or None
    if acc is None: return {"ok":False}
    if a=="pull": return {"ok":True,"abk":acc["abk"],"contacts":acc["contacts"],"cver":acc["cver"]}
    if a=="pushAbk":
        if not acc["abk"]: acc["abk"]=body.get("abk")
        return {"ok":True}
    if a=="pushContacts":
        if (body.get("cver") or 0)!=acc["cver"]: return {"ok":False,"conflict":True,"cver":acc["cver"]}
        acc["contacts"]=body.get("contacts"); acc["cver"]+=1; return {"ok":True,"cver":acc["cver"]}
    return {"ok":True}
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
        if self.path.startswith("/acct"):
            with RLOCK: return self._json(acct(body))
        if self.path.startswith("/mbox"):
            a=body.get("action")
            with RLOCK:
                if a in ("putblob","delblob","ack"): TOKENS.append((a, body.get("token")))
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


import re
r={}
import traceback, io
from PIL import Image as _Img
def png(color):
    b=io.BytesIO(); _Img.new("RGB",(320,200),color).save(b,"PNG"); return b.getvalue()
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
SKIP="()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
def has(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
def count(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].filter(e=>e.textContent==="+json.dumps(t)+").length"
def hist(P): return P.evaluate("()=>window.__gz.histOf()")
def lock(P): P.evaluate("()=>document.getElementById('sbLock').click()"); P.wait_for_timeout(700)
def unlock(P): P.fill("#pwInput","password123"); P.click("#joinBtn"); entered(P)
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    errs=[]
    def ctxp(w=390, h=780, scheme="dark", locale="en-US", ua=None, dialogs=True):
        kw=dict(viewport={"width":w,"height":h},locale=locale,color_scheme=scheme)
        if ua: kw["user_agent"]=ua
        c=b.new_context(timezone_id=TZ, **kw); c.add_init_script(NOINST); p=c.new_page(); p.on("pageerror",lambda e:errs.append(str(e)+" @ "+str(getattr(e,"stack","") or "")[:300]))
        if dialogs: p.on("dialog",lambda d:d.accept())
        return c,p
    def register(p, name):
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300); p.evaluate(SKIP)
        p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); entered(p)
    def invite(P):
        P.evaluate("()=>{ const b=document.getElementById('backHome'); if(b) b.click(); }"); P.wait_for_timeout(200)
        P.click("#sbNew"); P.wait_for_timeout(300); l=P.eval_on_selector("#invLinkOut","e=>e.value"); P.click("#joinBtn"); P.wait_for_timeout(600); return l
    def open_link(P, link):
        P.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); entered(P, 2500)
    def join_group(P, link):
        P.goto(f"http://127.0.0.1:{port}/?g=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); entered(P, 2500)
    cA,A=ctxp(w=1000,h=820); register(A,"oguz")
    cB,B=ctxp(w=1000,h=820); register(B,"serap")
    l1=invite(A); open_link(B,l1)
    r["paired"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    A.wait_for_timeout(600)
    ca=A.evaluate("()=>window.__gz.contacts()[0]"); cb=B.evaluate("()=>window.__gz.contacts()[0]"); ck=ca["ck"]
    hkA=A.evaluate("([ck])=>window.__gz.hk(ck)",[ck]); hkB=B.evaluate("([ck])=>window.__gz.hk(ck)",[ck])
    send(A,"salut"); r["live"]= wait_for(B,has("salut"),8000)
    B.click(".ct"); B.wait_for_timeout(600); send(B,"salut toi"); wait_for(A,has("salut toi"),8000)
    # ---- 1. the history's newest record is the newest by time, whatever the order they were written in ----
    dbv=A.evaluate("()=>window.__gz.dbVersion()")
    r["db_v3_index"]= dbv["v"]==3 and "roomts" in dbv["idx"]
    now=A.evaluate("()=>Date.now()")
    A.evaluate("([hk,ts])=>window.__gz.histSaveAt(hk,'vieux rattrapé',ts)",[hkA,now-3600000]); A.wait_for_timeout(500)
    last=A.evaluate("([hk])=>window.__gz.histLast(hk)",[hkA])
    r["newest_by_time"]= last=="salut toi"
    # ---- 2. the composer keeps a draft per chat ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    A.click("#sbNew"); A.wait_for_timeout(300); A.click(".nctab[data-nc='group']"); A.wait_for_timeout(200); A.fill("#gnameInput","Les potes"); A.click("#joinBtn"); entered(A)
    r["group_open"]= wait_for(A,"()=>{ const x=window.__gz.room(); return x && x.group; }",8000)
    A.fill("#msgInput","brouillon du groupe")
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()"); A.wait_for_timeout(500)
    d1=A.eval_on_selector("#msgInput","e=>e.value"); A.fill("#msgInput","brouillon pour serap")
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('Les potes')).click()"); A.wait_for_timeout(500)
    d2=A.eval_on_selector("#msgInput","e=>e.value")
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()"); A.wait_for_timeout(500)
    d3=A.eval_on_selector("#msgInput","e=>e.value")
    r["draft_per_chat"]= d1=="" and d2=="brouillon du groupe" and d3=="brouillon pour serap"
    r["draft_v"]=[d1,d2,d3]
    A.fill("#msgInput","")
    # ---- 3. midnight: both sides move to the new day's room and still find each other ----
    for P in (A,B): P.evaluate("()=>{ const t0=Date.now; const real=t0.bind(Date); Date.now=()=>real()+86400000; }")
    c0=A.evaluate("()=>window.__gz.code()")
    for P in (A,B): P.evaluate("()=>window.__gz.rollover()")
    r["room_moved"]= wait_for(A,"()=>window.__gz.code()!=="+json.dumps(c0),10000)
    r["repaired_after_midnight"]= wait_for(A,PAIRED,20000) and wait_for(B,PAIRED,20000) and A.evaluate("()=>window.__gz.code()")==B.evaluate("()=>window.__gz.code()")
    send(A,"après minuit"); r["talks_after_midnight"]= wait_for(B,has("après minuit"),8000)
    # ---- 4. a pairing alone doesn't bump the contact's record ----
    ts1=A.evaluate("()=>window.__gz.contacts()[0].ts")
    lock(B); wait_for(A,"()=>{ const x=window.__gz.room(); return x && !x.paired; }",8000); unlock(B); B.click(".ct"); B.wait_for_timeout(500)
    wait_for(A,PAIRED,15000); A.wait_for_timeout(800)
    r["pairing_keeps_ts"]= A.evaluate("()=>window.__gz.contacts()[0].ts")==ts1
    # ---- 5. the backup answering 401 is said once, after the session has been checked ----
    B.evaluate("()=>{ window.__vault401=true; }"); lock(B); unlock(B); B.wait_for_timeout(300)
    r["vault_401_said"]= wait_for(B,"()=>document.getElementById('toast').textContent.includes('backup')",8000) and B.evaluate("()=>document.getElementById('join').style.display!=='flex'")
    r["toast_v"]= B.eval_on_selector("#toast","e=>e.textContent")
    B.evaluate("()=>{ window.__vault401=false; }")
    # ---- 6. a second device of serap: the backup fails at log-in, opens at the next "online" ----
    cC,C=ctxp(w=1000,h=820)
    C.goto(f"http://127.0.0.1:{port}/"); C.wait_for_timeout(300); C.evaluate(SKIP); C.wait_for_timeout(200)
    C.evaluate("()=>{ window.__vaultDown=true; }")
    C.evaluate("()=>document.getElementById('switchLink').click()"); C.wait_for_timeout(200)
    C.fill("#userInput","serap"); C.fill("#pwInput","password123"); C.click("#joinBtn"); entered(C, 1500)
    st=C.evaluate("()=>window.__gz.abk()")
    r["ak_kept_until_opened"]= st["ak"] and not st["abk"] and not st["acct"] and st["pending"]
    r["empty_list_says_so"]= "restored yet" in C.evaluate("()=>document.querySelector('.sb-list').textContent")
    r["list_v"]= C.evaluate("()=>document.querySelector('.sb-list').textContent").strip()[:80]
    C.evaluate("()=>{ window.__vaultDown=false; window.dispatchEvent(new Event('online')); }")
    r["opened_when_online"]= wait_for(C,"()=>{ const s=window.__gz.abk(); return s.abk && s.acct && !s.ak && !s.pending; }",15000)
    r["chats_restored"]= wait_for(C,"()=>[...document.querySelectorAll('.ct')].some(e=>e.textContent.includes('oguz'))",15000)
    # ---- 7. removing the contact removes what it left on the device ----
    A.evaluate("([hk])=>window.__gz.seedMedia(hk)",[hkA]); A.evaluate("()=>window.__gz.setExp(7*86400000)"); A.wait_for_timeout(600)
    # v48: the timer is in the contact's record (vault), the localStorage map is only a cache
    r["timer_in_record"]= A.evaluate("()=>window.__gz.contacts()[0].ex")==7*86400000 and A.evaluate("()=>typeof window.__gz.contacts()[0].ets==='number'")
    r["timer_survives_cache_loss"]= A.evaluate("()=>{ localStorage.removeItem('gz-exp-rooms'); return window.__gz.exp(); }")==7*86400000
    A.evaluate("()=>window.__gz.setExp(7*86400000)"); A.wait_for_timeout(300)
    before=A.evaluate("([hk])=>window.__gz.idbCount(hk)",[hkA]); em=A.evaluate("()=>window.__gz.expMap()"); sids=A.evaluate("()=>window.__gz.sids()")
    r["before_remove"]= before["msgs"]>=3 and before["media"]>=1 and hkA in em and hkA in sids
    A.click("#peerMeta"); A.wait_for_timeout(300); A.evaluate("()=>document.getElementById('ciRemove').click()"); A.wait_for_timeout(1500)
    after=A.evaluate("([hk])=>window.__gz.idbCount(hk)",[hkA]); em2=A.evaluate("()=>window.__gz.expMap()"); sids2=A.evaluate("()=>window.__gz.sids()")
    r["removed_everything"]= after=={"msgs":0,"media":0} and hkA not in em2 and hkA not in sids2 and A.evaluate("()=>window.__gz.contacts().length")==0
    r["remove_v"]=[before,after]
    # ---- 8. a member removed then invited back is not thrown out by the old rotation ----
    A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('Les potes')).click()"); A.wait_for_timeout(500)
    glink=A.evaluate("()=>window.__gz.glink()")
    C.evaluate("()=>{ const real=Date.now.bind(Date); Date.now=()=>real()+86400000; }")
    join_group(C,glink); C.wait_for_timeout(300); C.evaluate("()=>{ const real=Date.now.bind(Date); Date.now=()=>real()+86400000; }")   # a reload: the clock again
    r["c_joined"]= wait_for(C,"()=>document.getElementById('bar').classList.contains('st-online') && window.__gz.room().group",10000)
    r["c_hi"]= wait_for(A,"()=>{ const g=window.__gz.group(); const m=g.mem||{}; return Object.values(m).filter(x=>x.ek).length>=1; }",10000)
    idC=C.evaluate("()=>window.__gz.ident()")
    A.evaluate("([pk])=>window.__gz.rotate(pk)",[idC["pk"]]); A.wait_for_timeout(2000)
    r["c_removed"]= wait_for(C,"()=>window.__gz.left()",8000) and not C.evaluate("()=>window.__gz.canSend()")
    glink2=A.evaluate("()=>window.__gz.glink()"); r["new_link"]= glink2!=glink
    C.evaluate("()=>window.__gz.forgetSeen()")
    join_group(C,glink2); C.evaluate("()=>{ const real=Date.now.bind(Date); Date.now=()=>real()+86400000; }"); C.wait_for_timeout(2500)
    gC=C.evaluate("()=>window.__gz.group()")
    r["back_in_group"]= wait_for(C,"()=>!window.__gz.left() && window.__gz.room().group",8000) and not gC.get("prevGk") and C.evaluate("()=>window.__gz.canSend()")
    r["back_v"]= [C.evaluate("()=>window.__gz.left()"), bool(gC.get("prevGk")), C.evaluate("()=>window.__gz.canSend()"), C.evaluate("()=>window.__gz.room()")]
    C.evaluate("()=>window.__gz.inbox()"); C.wait_for_timeout(2500)
    r["stays_in_group"]= not C.evaluate("()=>window.__gz.left()") and C.evaluate("()=>window.__gz.canSend()")
    send(C,"de retour"); r["back_talks"]= wait_for(A,has("de retour"),8000)
    r["errors"]= errs[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
