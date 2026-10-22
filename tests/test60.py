# v44 accessibility and consistency: the app's own question dialog (role, title and text, focus on the button, Escape
# cancels, a prompt answers with its field, a destructive question has a red button); every dialog gets a role and a
# name, the focus goes in, stays in (Tab cycles) and comes back; the chats-list rows and the bubbles are reachable with
# the keyboard (Enter opens a chat, Enter on a bubble opens its menu) and rows carry a spoken name; the more-menu says
# whether it is open and closes on Escape; settings are switches with a state; the chat log is no longer a live region
# while the toast and the auth message are; a muted microphone is shown and said; the voice recording shows a clock and
# stops at the cap instead of sending; colour names and the glossary are in the device's language; targets and
# contrasts (header buttons 40×44, list header 44, reaction chips, the amber banner, sent-bubble meta).
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site60"); site.mkdir(exist_ok=True)
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
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-auth"&&b.action==="logout") return {data:{ok:true}};
    if(n==="gizleme-auth"&&b.action==="validate") return {data:{ok:true, valid: window.__valid!==false}};
    if(n==="gizleme-push"&&b.action==="register"){ window.__reg.push(b); return {data:{ok:true}}; }
    if(n==="gizleme-vault"&&b.action==="pull") return {data:{ok:true,abk:window.__vault.abk,contacts:window.__vault.contacts,cver:window.__vault.cver}};
    if(n==="gizleme-vault"&&b.action==="pushAbk"){ if(!window.__vault.abk) window.__vault.abk=b.abk; return {data:{ok:true}}; }
    if(n==="gizleme-vault"&&b.action==="pushContacts"){ window.__vault.contacts=b.contacts; window.__vault.cver++; return {data:{ok:true,cver:window.__vault.cver}}; }
    if(n==="gizleme-mbox"){ const j=await fetch("/mbox",{method:"POST",body:JSON.stringify(Object.assign({__cl:window.__clientTag||""},b))}).then(r=>r.json()); return {data:j}; }
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
  exp:()=>expFor(histKeyOf(A())), every:()=>inboxEvery(), t:(k)=>t(k), rec:(on)=>on?startRec():stopRec(false), recState:()=>rec?{t1:!!rec.t1, n:rec.chunks.length}:null, capRec:()=>{ if(rec) rec.t0=Date.now()-(VOICE_MAX_S+1)*1000; }, picker:()=>!document.getElementById('rxPick').hidden, touch:(ago)=>{ _lastActive=Date.now()-(ago||0); }, rows:()=>[...document.querySelectorAll('#contactList .ct')].map(e=>e.dataset.id),
  rowEl:(id)=>document.querySelector('#contactList .ct[data-id="'+id+'"]'), rc:()=>renderContacts(), qrLoaded:()=>typeof qrcode==='function', older:()=>{ const R=A(); return R&&R._older?R._older.length:-1; } };
const _onGk2=onGk2; onGk2=async(R,env,vf,who)=>{ window.__gk2s=(window.__gk2s||[]).concat([env]); return _onGk2(R,env,vf,who); };
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

RELAY={}; RLOCK=threading.Lock(); MBOX={}; ACKS=[]; BLOBS={}; TOKENS=[]; CALLS=[]; NOMANY=[False]; SLOW=[False]
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
    def _json(self,o): b=json.dumps(o).encode(); self.send_response(200); self.send_header("Content-Type","application/json"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if SLOW[0] and self.path.startswith("/app.js"): time.sleep(2.5)   # the app held back: what the page shows meanwhile
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
                if a in ("putblob","delblob","ack"): TOKENS.append((a, body.get("token")))
                CALLS.append((a, body.get("__cl","")))
                if a=="getmany" and not NOMANY[0]:
                    out={}
                    for bx in body.get("boxes",[])[:150]:
                        box=MBOX.get(bx["mbox"],[]); since=bx.get("since") or 0
                        out[bx["mbox"]]=[{"mid":x["mid"],"from_user":x["from_user"],"data":x["data"],"ts":x["ts"]} for x in box if (not since or x["ts"]>since)]
                    return self._json({"ok":True,"items":out,"more":False})
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
import traceback
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
SKIP="()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"
VIS="(id)=>{ const e=document.getElementById(id); if(!e) return false; const r=e.getBoundingClientRect(); return !e.closest('[hidden]') && getComputedStyle(e).display!=='none' && r.width>0 && r.height>0; }"
def vis(P, i): return P.evaluate(VIS, i)
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
def has(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
def active(P): return P.evaluate("()=>{ const a=document.activeElement; return a ? (a.id||a.className||a.tagName) : ''; }")
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream","--autoplay-policy=no-user-gesture-required"])
    errs=[]
    def ctxp(w=390, h=780, scheme="dark", locale="en-US", ua=None, dialogs=True, tag=""):
        kw=dict(viewport={"width":w,"height":h},locale=locale,color_scheme=scheme)
        if ua: kw["user_agent"]=ua
        c=b.new_context(timezone_id=TZ, **kw); c.add_init_script(NOINST); c.add_init_script("window.__clientTag="+json.dumps(tag)+";"); p=c.new_page(); p.on("pageerror",lambda e:errs.append(str(e)+" @ "+str(getattr(e,"stack","") or "")[:300]))
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
    cA,A=ctxp(w=1000,h=820,locale="fr-FR",tag="A"); register(A,"oguz")
    cB,B=ctxp(w=390,h=780,tag="B"); register(B,"serap"); l1=invite(A); open_link(B,l1)
    r["paired"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    A.wait_for_timeout(400); send(A,"bonjour"); r["msg"]= wait_for(B,has("bonjour"),8000)
    # ---- 1. the house dialog, for real ----
    A.evaluate("()=>{ window.__askPolicy=()=>'__dialog__'; }")   # the real modal, not the test shim
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200); A.click(".ct"); A.wait_for_timeout(400); A.click("#peerMeta"); A.wait_for_timeout(300)
    A.evaluate("()=>document.getElementById('ciRemove').click()"); A.wait_for_timeout(400)
    d=A.evaluate("()=>{ const m=document.getElementById('askModal'); return {show:m.classList.contains('show'), role:m.getAttribute('role'), modal:m.getAttribute('aria-modal'), title:document.getElementById('askTitle').textContent, text:document.getElementById('askText').textContent, ok:document.getElementById('askOk').textContent, danger:document.getElementById('askOk').classList.contains('danger'), cancel:document.getElementById('askCancel').textContent, focus:document.activeElement&&document.activeElement.id, field:document.getElementById('askField').hidden}; }")
    r["ask_dialog"]= d["show"] and d["role"]=="dialog" and d["modal"]=="true" and d["title"].startswith("Supprimer serap de tes discussions") and "nouveau lien" in d["text"] and d["ok"]=="Supprimer le contact" and d["danger"] and d["cancel"]=="Annuler" and d["focus"]=="askOk" and d["field"]
    r["ask_v"]=d
    A.keyboard.press("Escape"); A.wait_for_timeout(300)
    r["ask_escape_cancels"]= not A.evaluate("()=>document.getElementById('askModal').classList.contains('show')") and A.evaluate("()=>window.__gz.contacts().length")==1 and A.evaluate("()=>document.getElementById('infoModal').classList.contains('show')")
    # a prompt: the nickname, answered with Enter
    A.evaluate("()=>document.getElementById('ciRename').click()"); A.wait_for_timeout(400)
    r["ask_prompt_field"]= A.evaluate("()=>!document.getElementById('askField').hidden && document.activeElement===document.getElementById('askInput') && document.getElementById('askOk').textContent==='Enregistrer'")
    A.fill("#askInput","Ma sœur"); A.keyboard.press("Enter"); A.wait_for_timeout(500)
    r["ask_prompt_answers"]= A.evaluate("()=>(window.__gz.contacts()[0].alias||'')")=="Ma sœur" and not A.evaluate("()=>document.getElementById('askModal').classList.contains('show')")
    A.evaluate("()=>{ window.__askPolicy=null; }")
    A.click("#ciBack"); A.wait_for_timeout(200)
    # ---- 2. every dialog: role, name, focus in, kept, back ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    A.focus("#sbSettings"); A.keyboard.press("Enter"); A.wait_for_timeout(400)
    m=A.evaluate("()=>{ const m=document.getElementById('settingsModal'); const a=document.activeElement; return {role:m.getAttribute('role'), modal:m.getAttribute('aria-modal'), lab:m.getAttribute('aria-labelledby'), labText:(document.getElementById(m.getAttribute('aria-labelledby')||'x')||{}).textContent, inside:m.contains(a)}; }")
    r["dialog_role_focus"]= m["role"]=="dialog" and m["modal"]=="true" and bool(m["lab"]) and bool(m["labText"]) and m["inside"]
    r["dialog_v"]=m
    for _ in range(25): A.keyboard.press("Tab")
    r["focus_trapped"]= A.evaluate("()=>document.getElementById('settingsModal').contains(document.activeElement)")
    A.keyboard.press("Escape"); A.wait_for_timeout(300)
    r["focus_returns"]= active(A)=="sbSettings"
    # ---- 3. rows and bubbles from the keyboard ----
    row=A.evaluate("()=>{ const e=document.querySelector('#contactList .ct'); return {role:e.getAttribute('role'), ti:e.tabIndex, lab:e.getAttribute('aria-label'), cx:!!e.querySelector('.cx')}; }")
    r["row_keyboard"]= row["role"]=="button" and row["ti"]==0 and "Ma sœur" in (row["lab"] or "") and not row["cx"]
    A.focus("#contactList .ct"); A.keyboard.press("Enter"); A.wait_for_timeout(500)
    r["row_enter_opens"]= A.evaluate("()=>{ const x=window.__gz.room(); return !!(x && x.ck); }") and A.evaluate("()=>!!document.querySelector('"+OPEN+"')")
    bub=A.evaluate("()=>{ const b=document.querySelector('"+OPEN+" .bubble.sent'); b.focus(); return {ti:b.tabIndex, focused:document.activeElement===b}; }")
    A.keyboard.press("Enter"); A.wait_for_timeout(300)
    r["bubble_enter_menu"]= bub["ti"]==0 and bub["focused"] and A.evaluate("()=>window.__gz.picker()")
    A.keyboard.press("Escape"); A.wait_for_timeout(200)
    r["live_regions"]= A.evaluate("()=>!document.getElementById('logs').hasAttribute('aria-live') && document.getElementById('toast').getAttribute('role')==='status' && document.getElementById('authMsg').getAttribute('role')==='alert' && document.getElementById('callStatus').getAttribute('aria-live')==='polite'")
    # ---- 4. the more-menu ----
    A.click("#menuBtn"); A.wait_for_timeout(200)
    r["menu_expanded"]= A.get_attribute("#menuBtn","aria-expanded")=="true" and not A.evaluate("()=>document.getElementById('barMenu').hidden")
    A.keyboard.press("Escape"); A.wait_for_timeout(200)
    r["menu_escape"]= A.evaluate("()=>document.getElementById('barMenu').hidden") and A.get_attribute("#menuBtn","aria-expanded")=="false"
    # ---- 5. switches ----
    A.evaluate("()=>document.getElementById('sbSettings').click()"); A.evaluate("()=>document.querySelector('#settingsModal [data-go=privacy]').click()"); A.wait_for_timeout(200)
    sw=A.evaluate("()=>['typToggle','prevToggle','shieldToggle'].map(id=>{ const e=document.getElementById(id); return [e.getAttribute('role'), e.getAttribute('aria-checked'), e.getAttribute('aria-label')]; })")
    A.click("#typToggle"); A.wait_for_timeout(200)
    r["switches"]= all(x[0]=="switch" and x[1]=="true" and x[2] for x in sw) and A.get_attribute("#typToggle","aria-checked")=="false" and A.evaluate("()=>localStorage.getItem('gz-typing')")=="0"
    r["switches_v"]=sw
    A.click("#typToggle"); A.keyboard.press("Escape"); A.wait_for_timeout(150); A.keyboard.press("Escape"); A.wait_for_timeout(200)
    # ---- 6. words in the device's language ----
    r["glossary_fr"]= A.evaluate("()=>[window.__gz.t('Location'), window.__gz.t('Blue'), window.__gz.t('{n} unread').replace('{n}','3'), window.__gz.t('Notify contact'), window.__gz.t('Encrypted voice call')]")==["Position","Bleu","3 non lus","Lui envoyer une notification","Appel audio chiffré"]
    A.click("#peerMeta"); A.wait_for_timeout(300)
    cn=A.evaluate("()=>[...document.querySelectorAll('#ciColors [role=radio]')].map(b=>b.getAttribute('aria-label'))")
    r["colour_names_fr"]= "Bleu" in cn and "Vert" in cn and "blue" not in cn
    r["colour_v"]=cn[:4]
    A.click("#ciBack"); A.wait_for_timeout(200)
    # ---- 7. the voice recording: a clock, and a stop at the cap ----
    A.evaluate("()=>window.__gz.rec(true)"); A.wait_for_timeout(1500)
    r["rec_clock"]= bool(re.fullmatch(r"0:0[0-9] / 2:00", A.eval_on_selector("#recTime","e=>e.textContent")))
    A.evaluate("()=>window.__gz.capRec()"); A.wait_for_timeout(700)
    st=A.evaluate("()=>window.__gz.recState()")
    r["rec_cap_waits"]= bool(st) and st["t1"] and not A.evaluate("()=>document.getElementById('recBar').hidden") and A.eval_on_selector("#recTime","e=>e.textContent")=="2:00 / 2:00" and "maximale" in A.eval_on_selector("#recHint","e=>e.textContent")
    A.evaluate("()=>window.__gz.rec(false)"); A.wait_for_timeout(300)
    r["rec_cancel_after_cap"]= A.evaluate("()=>document.getElementById('recBar').hidden && !window.__gz.recState()")
    # ---- 8. targets and contrast ----
    css=A.evaluate("()=>{ const g=id=>document.getElementById(id).getBoundingClientRect(); const cs=sel=>getComputedStyle(document.querySelector(sel)); return {back:[g('backHome').width,g('backHome').height], menu:[g('menuBtn').width,g('menuBtn').height], tiles:cs('.tiles').gridTemplateColumns, net:cs('#netBar').backgroundColor, meta:cs('"+OPEN+" .bubble.sent .meta').opacity}; }")
    r["targets"]= css["back"][0]>=40 and css["back"][1]>=44 and css["menu"][0]>=40 and css["menu"][1]>=44 and (css["tiles"].startswith("repeat(3") or len(css["tiles"].split(" "))==3)
    r["contrast"]= css["net"]=="rgb(245, 158, 11)" and float(css["meta"])>=0.9
    r["css_v"]=css
    B.evaluate("()=>document.getElementById('backHome').click()"); B.wait_for_timeout(200)
    r["phone_list_buttons"]= B.evaluate("()=>{ const r=document.getElementById('sbLock').getBoundingClientRect(); return r.width>=44 && r.height>=44; }")
    r["errors"]= errs[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
