# v42 security of groups and devices: a group key rotation carries its number and the fingerprint of the key it
# replaces, so a replayed (re-sealed) old rotation can't take the group back to a key a removed member still holds;
# signed group envelopes carry the sender's clock and a stale one is dropped; ids already seen survive a lock
# (14 days); a session the server no longer knows signs the device out at unlock; blob uploads, deletions and
# acknowledgements carry the session token; notification keys name a direction (inviter / opener), never the pair,
# and no sender marker goes with them; the opener's hello vouches for its own fields; group typing and the chat's
# disappearing timer need a member's signature; a lock empties what the dialogs showed.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site58"); site.mkdir(exist_ok=True)
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

RELAY={}; RLOCK=threading.Lock(); MBOX={}; ACKS=[]; BLOBS={}; TOKENS=[]
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
def unlock(P): P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(1500)
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    errs=[]
    def ctxp(w=390, h=780, scheme="dark", locale="en-US", ua=None, dialogs=True):
        kw=dict(viewport={"width":w,"height":h},locale=locale,color_scheme=scheme)
        if ua: kw["user_agent"]=ua
        c=b.new_context(**kw); c.add_init_script(NOINST); p=c.new_page(); p.on("pageerror",lambda e:errs.append(str(e)+" @ "+str(getattr(e,"stack","") or "")[:300]))
        if dialogs: p.on("dialog",lambda d:d.accept())
        return c,p
    def register(p, name):
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300); p.evaluate(SKIP)
        p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
    def invite(P):
        P.evaluate("()=>{ const b=document.getElementById('backHome'); if(b) b.click(); }"); P.wait_for_timeout(200)
        P.click("#sbNew"); P.wait_for_timeout(300); l=P.eval_on_selector("#invLinkOut","e=>e.value"); P.click("#joinBtn"); P.wait_for_timeout(600); return l
    def open_link(P, link):
        P.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(2000)
    def join_group(P, link):
        P.goto(f"http://127.0.0.1:{port}/?g=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(2000)
    cA,A=ctxp(w=1000,h=820); register(A,"oguz")
    cB,B=ctxp(w=1000,h=820); register(B,"serap")
    l1=invite(A); open_link(B,l1)
    r["paired"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    A.wait_for_timeout(600)
    # ---- 1. roles, the keys each side registers, the key a sender wakes ----
    ca=A.evaluate("()=>window.__gz.contacts()[0]"); cb=B.evaluate("()=>window.__gz.contacts()[0]")
    r["roles"]= ca.get("nr")=="i" and cb.get("nr")=="o" and ca["ck"]==cb["ck"] and cb.get("prev")==ca.get("prev")
    ck=ca["ck"]; ck0=cb.get("prev")
    nkI=A.evaluate("([ck])=>window.__gz.nk(ck,'i')",[ck]); nkO=A.evaluate("([ck])=>window.__gz.nk(ck,'o')",[ck]); nk1=A.evaluate("([ck])=>window.__gz.nk(ck)",[ck])
    ra=A.evaluate("()=>window.__gz.regKeys()"); rb=B.evaluate("()=>window.__gz.regKeys()")
    r["registers_own_side"]= (nkI in ra) and (nkO not in ra) and (nkO in rb) and (nkI not in rb) and (nk1 in ra) and (nk1 in rb) and len(set([nkI,nkO,nk1]))==3
    nb=B.evaluate("()=>window.__notify"); nk0I=B.evaluate("([ck])=>window.__gz.nk(ck,'i')",[ck0])
    r["link_wakes_inviter_only"]= len(nb)>=1 and nb[0]["notify_key"]==nk0I and ("from_acct" not in nb[0]) and ("from" not in nb[0]) and nb[0]["kind"]=="chat"
    # B locks (its presence fades): A's message wakes B's own side, with no sender marker
    lock(B); r["unpaired_after_lock"]= wait_for(A,"()=>{ const x=window.__gz.room(); return x && !x.paired; }",8000)
    A.evaluate("()=>window.__gz.clearNotified()"); send(A,"réveil"); A.wait_for_timeout(800)
    na=A.evaluate("()=>window.__notify"); last=na[-1] if na else {}
    r["wakes_other_side"]= last.get("notify_key")==nkO and ("from_acct" not in last) and ("from" not in last) and last.get("kind")=="msg"
    # nobody registered under that key (an older build there): the pair's key follows, with the sender marker
    A.evaluate("()=>{ window.__targets=0; window.__gz.clearNotified(); }"); n0=len(na); send(A,"réveil 2"); A.wait_for_timeout(800)
    na=A.evaluate("()=>window.__notify"); A.evaluate("()=>{ window.__targets=1; }")
    r["falls_back_to_pair_key"]= len(na)==n0+2 and na[-2]["notify_key"]==nkO and na[-1]["notify_key"]==nk1 and bool(na[-1].get("from")) and bool(na[-1].get("from_acct"))
    r["notify_v"]=[len(nb), len(na)]
    # ---- 2. the hello vouches for its fields: a hello with a wrong tag binds nothing ----
    l2=invite(A); A.wait_for_timeout(200)
    pend=A.evaluate("()=>window.__gz.contacts().find(c=>c.pk)")
    e=A.evaluate("()=>window.__gz.mkPub()")
    ok=A.evaluate("([ck,e])=>window.__gz.hello(ck,e,'bogus')",[pend["ck"],e])
    r["bad_hello_tag_refused"]= ok==False and A.evaluate("([ck])=>{ const c=window.__gz.contacts().find(x=>x.ck===ck); return !!(c && c.pk); }",[pend["ck"]])
    # ---- 3. B unlocks: the queued message arrives once, is acknowledged with the session token ----
    unlock(B); B.click(".ct"); B.wait_for_timeout(1200)
    r["msg_arrived"]= wait_for(B,has("réveil"),10000)
    with RLOCK: toks=list(TOKENS)
    r["ack_has_token"]= any(a=="ack" and t=="t" for a,t in toks)
    A.evaluate("()=>{ const b=document.getElementById('backHome'); if(b) b.click(); }"); A.wait_for_timeout(300)
    A.evaluate("()=>{ const e=[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')); if(e) e.click(); }"); A.wait_for_timeout(500)
    A.set_input_files("#fileInput", files=[{"name":"a.png","mimeType":"image/png","buffer":png((200,40,40))}]); A.wait_for_timeout(1500)
    with RLOCK: toks=list(TOKENS)
    r["putblob_has_token"]= any(a=="putblob" and t=="t" for a,t in toks)
    # ---- 4. ids already seen survive a lock: a copy of a delivered message (same id) is not shown again ----
    mid=[x.split("|")[0] for x in hist(B) if x.endswith("|recv|undefined") or x.endswith("|recv|txt")]
    mid=[m for m in mid if not m.startswith("h")]
    r["mid_known"]= len(mid)>=1
    m0=mid[0] if mid else ""
    B.evaluate("([m])=>window.__gz.purge([m])",[m0]); B.wait_for_timeout(300)
    lock(B); unlock(B); B.click(".ct"); B.wait_for_timeout(800)
    sids=B.evaluate("()=>window.__gz.sids()")
    r["sids_persisted"]= any(m0 in v for v in sids.values())
    r["purged_gone"]= not B.evaluate(has("réveil"))
    with RLOCK:
        copies=0
        for box in MBOX.values():
            for x in list(box):
                if x["mid"]==m0: box.append({"mid":m0,"from_user":x["from_user"],"data":x["data"],"ts":datetime.datetime.now(datetime.timezone.utc).isoformat(),"delivered_at":None}); copies+=1
    B.evaluate("()=>window.__gz.inbox()"); B.wait_for_timeout(1500)
    r["replayed_copy_not_shown"]= copies>=1 and not B.evaluate(has("réveil")) and len([x for x in hist(B) if x.startswith(m0+"|")])==0
    # ---- 5. a group: rotations are numbered and never go backwards ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200)
    A.click("#sbNew"); A.wait_for_timeout(300); A.click(".nctab[data-nc='group']"); A.wait_for_timeout(200); A.fill("#gnameInput","Les potes"); A.click("#joinBtn"); A.wait_for_timeout(1500)
    glink=A.evaluate("()=>window.__gz.glink()"); g0=A.evaluate("()=>window.__gz.group()")
    r["first_key_fp_known"]= bool(g0.get("rotFp")) and g0.get("fpSeen")==[g0["rotFp"]]
    cC,C=ctxp(w=1000,h=820); register(C,"can"); join_group(C,glink)
    cD,D=ctxp(w=1000,h=820); register(D,"deniz"); join_group(D,glink)
    r["joined"]= all(wait_for(P,"()=>document.getElementById('bar').classList.contains('st-online') && window.__gz.room().group",10000) for P in (A,C,D))
    r["hi_keys"]= wait_for(A,"()=>{ const g=window.__gz.group(); const m=g.mem||{}; return Object.values(m).filter(x=>x.ek).length>=2; }",10000)
    idD=D.evaluate("()=>window.__gz.ident()")
    A.evaluate("()=>window.__gz.rotate(null)"); A.wait_for_timeout(2000)
    g1=A.evaluate("()=>window.__gz.group()")
    r["rot1"]= g1.get("rotN")==1 and g1["gk"]!=g0["gk"] and wait_for(C,"()=>window.__gz.group().gk==='"+g1["gk"]+"'",8000) and wait_for(D,"()=>window.__gz.group().gk==='"+g1["gk"]+"'",8000)
    gk2s=D.evaluate("()=>window.__gz.gk2s()")
    r["gk2_numbered"]= len(gk2s)>=1 and gk2s[-1].get("rc")==1 and gk2s[-1].get("p")==g0["rotFp"] and gk2s[-1].get("g")==g1["rotFp"] and isinstance(gk2s[-1].get("sts"),(int,float))
    A.evaluate("([pk])=>window.__gz.rotate(pk)",[idD["pk"]]); A.wait_for_timeout(2000)
    g2=A.evaluate("()=>window.__gz.group()")
    r["rot2"]= g2.get("rotN")==2 and g2["gk"]!=g1["gk"] and wait_for(C,"()=>window.__gz.group().gk==='"+g2["gk"]+"'",8000) and wait_for(D,"()=>window.__gz.group().left===1",8000)
    gC=C.evaluate("()=>window.__gz.group()")
    r["member_tracks"]= gC.get("rotN")==2 and gC.get("rotFp")==g2["rotFp"] and sorted(gC.get("fpSeen") or [])==sorted([g0["rotFp"],g1["rotFp"],g2["rotFp"]])
    # deniz (removed, still on key 1) re-seals the signed rotation #1 under key 1 and leaves it in that key's mailbox —
    # which can (the key before the last rotation) still read for 14 days; can has also forgotten the ids it saw
    old=gk2s[-1]
    C.evaluate("()=>window.__gz.forgetSeen()")
    r["replay_deposited"]= D.evaluate("([env])=>window.__gz.replay(env)",[old])
    C.evaluate("()=>window.__gz.inbox()"); C.wait_for_timeout(2500)
    gC2=C.evaluate("()=>window.__gz.group()")
    r["replay_refused"]= gC2["gk"]==g2["gk"] and gC2.get("rotN")==2 and not any("renewed the group key" in x for x in C.evaluate("()=>window.__gz.lastSysAll()")[-2:])
    # ---- 6. a signed envelope older than the relay keeps anything is stale ----
    C.evaluate("()=>window.__gz.forgeOld('vieux', 20*86400000)"); C.evaluate("()=>window.__gz.forgeOld('frais', 0)"); C.wait_for_timeout(1500)
    r["fresh_shown_stale_dropped"]= wait_for(A,has("frais"),6000) and not A.evaluate(has("vieux"))
    # ---- 7. "X is typing" needs a member's signature ----
    C.evaluate("()=>window.__gz.typSend('t')"); C.wait_for_timeout(900)
    r["signed_typing_shown"]= wait_for(A,"()=>window.__gz.typing().includes('can')",5000)
    A.wait_for_timeout(7000)
    C.evaluate("()=>window.__gz.rawTyp('mallory')"); C.wait_for_timeout(1200)
    r["unsigned_typing_ignored"]= "mallory" not in A.evaluate("()=>window.__gz.typing()")
    # ---- 8. the disappearing timer of a group can't be set by an unsigned envelope ----
    C.evaluate("()=>window.__gz.rawMsg({t:'exp', v:300000, body:'x'})"); C.wait_for_timeout(1200)
    r["unsigned_exp_ignored"]= A.evaluate("()=>window.__gz.exp()")==0
    # ---- 9. a lock empties what the dialogs showed ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200); A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()"); A.wait_for_timeout(500)
    A.click("#peerMeta"); A.wait_for_timeout(300); nm=A.eval_on_selector("#ciName","e=>e.textContent"); A.click("#ciVerify"); A.wait_for_timeout(600)
    code=A.eval_on_selector("#safetyCode","e=>e.textContent")
    r["dialogs_filled"]= nm=="serap" and bool(re.fullmatch(r"[0-9A-F ]{20,}", code))
    lock(A)
    r["dialogs_emptied"]= A.eval_on_selector("#safetyCode","e=>e.textContent")=="————" and A.eval_on_selector("#ciName","e=>e.textContent")=="—" and A.eval_on_selector("#memList","e=>e.innerHTML")=="" and A.eval_on_selector("#callName","e=>e.textContent")=="—"
    unlock(A)
    # ---- 10. a session the server no longer knows signs the device out at unlock ----
    lock(B); B.evaluate("()=>{ window.__valid=false; }"); unlock(B); B.wait_for_timeout(1000)
    r["revoked_signed_out"]= wait_for(B,"()=>document.getElementById('join').dataset.mode==='login'",6000) and B.evaluate("()=>window.__gz.contacts().length")==0 and "signed out" in B.eval_on_selector("#authMsg","e=>e.textContent") and B.evaluate("()=>!localStorage.getItem('gz-session')")
    lock(A); unlock(A); A.wait_for_timeout(800)
    r["valid_stays_in"]= A.evaluate("()=>document.getElementById('app').style.display==='flex' && window.__gz.contacts().length>=1")
    r["errors"]= errs[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
