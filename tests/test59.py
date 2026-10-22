# v43 load and start-up: one version number stamped everywhere and a minified build that is up to date (and boots:
# an account is created and a message sent on the minified bundle, with no test hook); the first screen is drawn by
# boot.js before app.js has loaded, in the device's language, the password usable at once; one relay call reads every
# mailbox of a pass (getmany), none while the chat is quiet beyond the pace, and a relay without getmany is read box
# by box; the mailbox pace follows activity and hiding; the chats list keeps unchanged rows; the QR library is
# fetched only when a QR code is shown; the service worker's shell files exist and its critical ones are in the shell.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site59"); site.mkdir(exist_ok=True)
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
  exp:()=>expFor(histKeyOf(A())), every:()=>inboxEvery(), touch:(ago)=>{ _lastActive=Date.now()-(ago||0); }, rows:()=>[...document.querySelectorAll('#contactList .ct')].map(e=>e.dataset.id),
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


import re, hashlib
r={}
import traceback
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
SKIP="()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
def has(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
def lock(P): P.evaluate("()=>document.getElementById('sbLock').click()"); P.wait_for_timeout(700)
def unlock(P): P.fill("#pwInput","password123"); P.click("#joinBtn"); entered(P)
def calls(a, cl="A"):
    with RLOCK: return len([x for x in CALLS if x[0]==a and x[1]==cl])
try:
 # ---- 0. the repository: one version everywhere, a fresh minified build, the worker's shell ----
 appv=int(re.search(r"^const APP_VERSION = (\d+);", _app, re.M).group(1))
 sw_src=pathlib.Path(SRC+"sw.js").read_text(); idx=pathlib.Path(SRC+"index.html").read_text()
 r["version_everywhere"]= int(re.search(r'const CACHE = "gizleme-v(\d+)";', sw_src).group(1))==appv and set(re.findall(r'\?v=(\d+)"', sw_src))=={str(appv)} and set(re.findall(r'\?v=(\d+)"', idx))=={str(appv)}
 mn=pathlib.Path(SRC+"app.min.js"); mtxt=mn.read_text(errors="replace") if mn.exists() else ""
 r["min_build_fresh"]= mn.exists() and ("sha256:"+hashlib.sha256(pathlib.Path(SRC+"app.js").read_bytes()).hexdigest()) in mtxt[:600] and "AGPL" in mtxt[:600] and len(mtxt)<len(_app)*0.75
 r["page_loads_min"]= '<script src="/app.min.js?v=%d"></script>'%appv in idx and '/app.js"' not in idx
 shell=re.search(r"const SHELL = \[(.*?)\];", sw_src, re.S).group(1); shell=re.findall(r'"([^"]+)"', shell)
 crit=re.findall(r'"([^"]+)"', re.search(r"const CRITICAL = \[(.*?)\];", sw_src, re.S).group(1))
 r["shell_files_exist"]= all(pathlib.Path(SRC+u.split("?")[0].lstrip("/")).exists() for u in shell) and "/" not in shell
 r["critical_in_shell"]= bool(crit) and all(c in shell for c in crit) and "/app.min.js?v=%d"%appv in crit
 # boot.js carries the same words as i18n.js
 bt=pathlib.Path(SRC+"boot.js").read_text(); i18=pathlib.Path(SRC+"i18n.js").read_text()
 fr_i=dict(re.findall(r'^    "((?:[^"\\]|\\.)*)": "((?:[^"\\]|\\.)*)"', i18[:i18.index("  tr: {")], re.M)); tr_i=dict(re.findall(r'^    "((?:[^"\\]|\\.)*)": "((?:[^"\\]|\\.)*)"', i18[i18.index("  tr: {"):], re.M))
 bfr=re.search(r"fr:\{(.*?)\},\s*tr:", bt, re.S).group(1); btr=re.search(r"tr:\{(.*?)\}\};", bt, re.S).group(1)
 pairs=lambda blob: re.findall(r'"((?:[^"\\]|\\.)*)":"((?:[^"\\]|\\.)*)"', blob)
 bad=[(k,v) for k,v in pairs(bfr) if fr_i.get(k)!=v]+[(k,v) for k,v in pairs(btr) if tr_i.get(k)!=v]
 r["boot_words_match_i18n"]= len(pairs(bfr))>=12 and not bad
 r["boot_words_v"]=bad[:3]
 with sync_playwright() as pw:
    b=pw.chromium.launch()
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
    # ---- 1. the first screen before app.js: French, unlock, the password field there while app.js is held back ----
    cA,A=ctxp(w=1000,h=820,locale="fr-FR",tag="A"); register(A,"oguz")
    r["qr_not_loaded_at_start"]= not A.evaluate("()=>window.__gz.qrLoaded()")
    A.evaluate("()=>document.getElementById('sbNew').click()"); A.wait_for_timeout(300); A.click("#qrShow")
    r["qr_loaded_on_demand"]= wait_for(A,"()=>window.__gz.qrLoaded() && !document.getElementById('qrBox').hidden",6000)
    A.evaluate("()=>document.getElementById('joinBtn').click()"); A.wait_for_timeout(500)
    lock(A)
    A.evaluate("()=>navigator.serviceWorker.getRegistrations().then(rs=>Promise.all(rs.map(r=>r.unregister())))"); A.wait_for_timeout(300)   # no worker: app.js must come from the (slow) server
    SLOW[0]=True
    t0=time.time(); A.reload(wait_until="commit"); A.wait_for_timeout(600)
    early=A.evaluate("()=>{ const j=document.getElementById('join'); const c=j.querySelector('.card'); const cs=getComputedStyle(c); const pw=document.getElementById('pwInput'); return {boot:j.dataset.boot||'', mode:j.dataset.mode||'', vis:cs.visibility, title:(document.getElementById('lockHeadTitle')||{}).textContent, sub:(document.getElementById('lockSub')||{}).textContent, btn:document.getElementById('joinBtn').textContent, dis:document.getElementById('joinBtn').disabled, pwShown:getComputedStyle(pw.parentNode).display!=='none', userShown:getComputedStyle(document.getElementById('userField')).display!=='none', lang:document.documentElement.lang}; }")
    A.fill("#pwInput","password123")   # typed while app.js is still on its way
    r["boot_screen_before_app"]= early["boot"]=="unlock" and early["mode"]=="" and early["vis"]=="visible" and early["title"]=="Gizleme est verrouillé" and early["sub"]=="Content de te revoir, oguz." and early["btn"]=="Déverrouiller" and early["dis"] and early["pwShown"] and not early["userShown"] and early["lang"]=="fr"
    r["boot_v"]=early
    SLOW[0]=False
    r["app_takes_over"]= wait_for(A,"()=>document.getElementById('join').dataset.mode==='unlock' && !document.getElementById('join').dataset.boot && !document.getElementById('joinBtn').disabled && document.getElementById('lockHeadTitle').textContent==='Gizleme est verrouillé'",8000) and A.eval_on_selector("#pwInput","e=>e.value")=="password123"
    A.click("#joinBtn"); entered(A)
    r["unlocks_after"]= A.evaluate("()=>document.getElementById('app').style.display==='flex'")
    # switching the language later still translates what boot.js wrote (the English stays on the element)
    A.evaluate("()=>document.getElementById('sbSettings').click()"); A.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); A.wait_for_timeout(200)
    A.select_option("#langSel","tr"); A.wait_for_timeout(300); A.keyboard.press("Escape"); A.wait_for_timeout(200); A.keyboard.press("Escape"); A.wait_for_timeout(200)
    lock(A)
    r["boot_text_retranslates"]= A.evaluate("()=>document.getElementById('lockHeadTitle').textContent==='Gizleme kilitli' && document.getElementById('joinBtn').textContent==='Kilidi aç'")
    A.evaluate("()=>document.getElementById('sbLock')"); unlock(A)
    A.evaluate("()=>document.getElementById('sbSettings').click()"); A.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); A.wait_for_timeout(200)
    A.select_option("#langSel","en"); A.wait_for_timeout(300); A.keyboard.press("Escape"); A.wait_for_timeout(200); A.keyboard.press("Escape"); A.wait_for_timeout(200)
    # ---- 2. one relay call per pass for every mailbox; box by box when the relay has no getmany ----
    cB,B=ctxp(w=1000,h=820,tag="B"); register(B,"serap"); l1=invite(A); open_link(B,l1)
    cC,C=ctxp(w=1000,h=820,tag="C"); register(C,"can"); l2=invite(A); open_link(C,l2)
    r["paired"]= wait_for(A,"()=>window.__gz.contacts().filter(c=>!c.pk).length===2",10000)
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(2500)   # v46: a pairing reads that contact's box once (1.2 s later) — let it pass
    with RLOCK: CALLS.clear()
    A.evaluate("()=>window.__gz.inbox()"); A.wait_for_timeout(1500)
    r["one_call_per_pass"]= calls("getmany")==1 and calls("get")==0
    r["one_call_v"]=[calls("getmany"), calls("get")]
    # a message deposited for A while its chat is closed arrives through that one call
    lock(B); r["B_gone"]= wait_for(A,"()=>true",100) and True
    B.wait_for_timeout(300); unlock(B); B.click(".ct"); B.wait_for_timeout(600)
    lock(A); A.wait_for_timeout(300); send(B,"par la boîte"); B.wait_for_timeout(800)
    unlock(A); A.wait_for_timeout(500)
    with RLOCK: CALLS.clear()
    A.evaluate("()=>window.__gz.inbox()")
    r["batched_delivers"]= wait_for(A,"()=>{ const row=[...document.querySelectorAll('#contactList .ct')].find(e=>e.textContent.includes('serap')); return !!row && /par la boîte/.test(row.textContent); }",8000) and calls("get")==0
    NOMANY[0]=True
    with RLOCK: CALLS.clear()
    A.evaluate("()=>window.__gz.inbox()"); A.wait_for_timeout(1500)
    r["falls_back_box_by_box"]= calls("getmany")>=1 and calls("get")>=2
    r["fallback_v"]=[calls("getmany"), calls("get")]
    NOMANY[0]=False
    # ---- 3. the pace: alive 20 s, quiet 45 s / 60 s, hidden 2 min ----
    A.evaluate("()=>window.__gz.touch(0)"); e1=A.evaluate("()=>window.__gz.every()")
    A.evaluate("()=>window.__gz.touch(5*60000)"); e2=A.evaluate("()=>window.__gz.every()")
    A.evaluate("()=>window.__gz.touch(20*60000)"); e3=A.evaluate("()=>window.__gz.every()")
    e4=A.evaluate("()=>{ Object.defineProperty(document,'hidden',{get:()=>true,configurable:true}); const v=window.__gz.every(); delete document.hidden; return v; }")
    r["pace_follows_activity"]= [e1,e2,e3,e4]==[20000,45000,60000,120000]
    r["pace_v"]=[e1,e2,e3,e4]
    # ---- 4. the chats list keeps its rows when nothing changed, rebuilds the one that did ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(300)
    ids=A.evaluate("()=>window.__gz.rows()")
    same=A.evaluate("([id])=>{ const a=window.__gz.rowEl(id); window.__gz.rc(); return a===window.__gz.rowEl(id); }",[ids[-1]]) if ids else False   # the invite row: no "typing…" age in its signature
    r["rows_kept"]= len(ids)==3 and same
    C.evaluate("()=>document.getElementById('backHome').click()"); C.wait_for_timeout(200); C.click(".ct"); C.wait_for_timeout(500); send(C,"salut A"); C.wait_for_timeout(600)
    A.evaluate("()=>window.__gz.inbox()")
    r["row_rebuilt_on_change"]= wait_for(A,"()=>{ const row=[...document.querySelectorAll('#contactList .ct')].find(e=>e.textContent.includes('can')); return !!row && /salut A/.test(row.textContent) && document.querySelectorAll('#contactList .ct')[0]===row; }",8000)
    r["row_v"]=A.evaluate("()=>[...document.querySelectorAll('#contactList .ct')].map(e=>e.textContent.slice(0,40))")
    r["errors"]= errs[:4]
    b.close()
 # ---- 5. the minified build boots and works (no test hook; the page as shipped, supabase-js mocked) ----
 site2=pathlib.Path(TMP+"site59min"); site2.mkdir(exist_ok=True)
 for f in os.listdir(site):
     pth=pathlib.Path(site)/f
     if pth.is_file(): (site2/f).write_bytes(pth.read_bytes())
 (site2/"vendor").mkdir(exist_ok=True)
 for f in os.listdir(pathlib.Path(site)/"vendor"): (site2/"vendor"/f).write_bytes((pathlib.Path(site)/"vendor"/f).read_bytes())
 html2=pathlib.Path(SRC+"index.html").read_text(); html2=_re.sub(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html2)
 (site2/"index.html").write_text(html2); (site2/"app.min.js").write_bytes(pathlib.Path(SRC+"app.min.js").read_bytes())
 os.chdir(site2)
 with sync_playwright() as pw:
    b=pw.chromium.launch(); errs2=[]
    c=b.new_context(timezone_id=TZ, viewport={"width":1000,"height":820},locale="fr-FR"); c.add_init_script(NOINST); p=c.new_page(); p.on("pageerror",lambda e:errs2.append(str(e)[:200])); p.on("dialog",lambda d:d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(400); p.evaluate(SKIP)
    p.fill("#userInput","mini"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1800)
    ok1=p.evaluate("()=>document.getElementById('app').style.display==='flex' && document.querySelector('script[src^=\"/app.min.js\"]')!==null")
    p.click("#sbNew"); p.wait_for_timeout(300); p.click(".nctab[data-nc='group']"); p.wait_for_timeout(200); p.fill("#gnameInput","Mini"); p.click("#joinBtn"); entered(p)
    send(p,"ça marche en minifié")
    ok2=wait_for(p,has("ça marche en minifié"),6000)
    r["min_build_boots"]= ok1 and ok2 and not errs2
    r["min_build_v"]=[ok1, ok2, errs2[:2]]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
