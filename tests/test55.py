# v39: one to three emojis alone are drawn big and move (once on arrival / send, again on a tap; not when
# replayed from history; never with reduced motion; an edit can make a message big), a video call can be
# answered without the camera (their picture comes in, ours starts on a tap), the "weak connection" pill
# (two bad readings in, three good out, no false alarm on a clean call), the type scale and three radii, and
# the hidden attribute always wins.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site55"); site.mkdir(exist_ok=True)
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
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install'), rid:()=>rid(), sendEnv:(env)=>{ const R=A(); return deliverOut(R, env, rid(), null, Date.now(), true); }, inb:(env,mid,own)=>{ const R=A(); onInbound(R, env, '', Date.now(), mid, !!own, false); }, delm:()=>JSON.parse(JSON.stringify(_meta.delm||{})), localTracks:()=>call&&call.local?call.local.getTracks().map(t=>t.kind):[], qual:(s)=>qualSample(s), live:()=>!!(call&&call.t1) };
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
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
def has(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
JB="(t)=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble')].reverse().find(x=>{ const e=x.querySelector(':scope > .txt'); return e && e.textContent===t; }); if(!b) return null; const tx=b.querySelector(':scope > .txt'); return {jumbo:b.classList.contains('jumbo'), n:['j1','j2','j3'].find(c=>b.classList.contains(c))||'', play:b.classList.contains('play'), anims:[...b.querySelectorAll('.je')].map(e=>e.dataset.anim), fs:parseFloat(getComputedStyle(tx).fontSize), bg:getComputedStyle(b).backgroundColor}; }"
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream","--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000, h=820, scheme="dark"):
        c=b.new_context(viewport={"width":w,"height":h},locale="en-US",color_scheme=scheme); c.add_init_script(NOINST); p=c.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300); p.evaluate(SKIP)
        p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return c,p
    errs=[]
    ctxA,A=boot("oguz",errs)
    # ---- scale, radii, hidden ----
    sc=A.evaluate("()=>{ const cs=getComputedStyle(document.documentElement); return {cap:cs.getPropertyValue('--fs-cap').trim(), sec:cs.getPropertyValue('--fs-sec').trim(), body:cs.getPropertyValue('--fs-body').trim(), title:cs.getPropertyValue('--fs-title').trim(), rs:cs.getPropertyValue('--r-s').trim(), rm:cs.getPropertyValue('--r-m').trim(), search:getComputedStyle(document.getElementById('sbSearch')).borderTopLeftRadius}; }")
    r["scale_tokens"]= sc=={"cap":".72rem","sec":".84rem","body":".95rem","title":"1.15rem","rs":"8px","rm":"14px","search":"14px"}
    r["scale_v"]=sc
    r["hidden_wins"]= A.evaluate("()=>[...document.querySelectorAll('[hidden]')].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.id||e.className)")==[]
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    errsB=[]; ctxB,B=boot("serap",errsB,w=390,scheme="light")
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(2000)
    r["paired"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    A.wait_for_timeout(400)
    # ---- 1. big emojis ----
    send(A,"😂")
    a1=A.evaluate(JB,"😂")
    r["jumbo_sent"]= bool(a1) and a1["jumbo"] and a1["n"]=="j1" and a1["play"] and a1["anims"]==["laugh"] and a1["fs"]>50 and a1["bg"] in ("rgba(0, 0, 0, 0)","transparent")
    r["jumbo_v"]=a1
    r["jumbo_received"]= wait_for(B,"()=>{ const x=("+JB+")('😂'); return x && x.jumbo && x.play && x.n==='j1'; }",8000)
    send(A,"❤️👍"); send(A,"🎉🎉🎉"); send(A,"😂😂😂😂"); send(A,"👋 hi"); send(A,"1")
    wait_for(B,has("1"),8000)
    two=B.evaluate(JB,"❤️👍"); three=B.evaluate(JB,"🎉🎉🎉")
    r["jumbo_two_three"]= two and two["n"]=="j2" and two["anims"]==["beat","nod"] and three and three["n"]=="j3" and three["anims"]==["party","party","party"] and three["fs"]<two["fs"]<a1["fs"]
    r["not_jumbo"]= all(not (B.evaluate(JB,t) or {}).get("jumbo") for t in ["😂😂😂😂","👋 hi","1"])
    shot(B,"55_jumbo_light")
    B.wait_for_timeout(3800)
    r["play_ends"]= not B.evaluate(JB,"😂")["play"]
    B.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.jumbo')][0]; b.querySelector('.je').click(); }"); B.wait_for_timeout(100)
    r["tap_replays"]= B.evaluate(JB,"😂")["play"]
    # an edit can make a message big
    send(A,"salut"); wait_for(B,has("salut"),8000)
    A.locator(OPEN+" .bubble.sent").last.click(button="right"); A.wait_for_timeout(200); A.click("#rxEdit"); A.wait_for_timeout(200)
    A.fill("#msgInput","🔥"); A.press("#msgInput","Enter"); A.wait_for_timeout(600)
    r["edit_makes_jumbo"]= (A.evaluate(JB,"🔥") or {}).get("anims")==["flare"] and wait_for(B,"()=>{ const x=("+JB+")('🔥'); return x && x.jumbo; }",8000)
    # replayed from history: big, still
    B.evaluate("()=>document.getElementById('sbLock').click()"); B.wait_for_timeout(800)
    B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500); B.click(".ct"); B.wait_for_timeout(1200)
    h1=B.evaluate(JB,"😂")
    r["history_big_still"]= bool(h1) and h1["jumbo"] and not h1["play"]
    B.emulate_media(reduced_motion="reduce"); B.evaluate("()=>[...document.querySelectorAll('"+OPEN+" .bubble.jumbo .je')][0].click()"); B.wait_for_timeout(100)
    r["reduced_motion_still"]= not B.evaluate(JB,"😂")["play"]
    B.emulate_media(reduced_motion="no-preference")
    # ---- 2. a video call answered without the camera ----
    B.click("#videoBtn"); B.wait_for_timeout(300)
    r["incoming_three_choices"]= wait_for(A,"()=>!document.getElementById('callIncoming').hidden",8000) and vis(A,"callNoCam") and vis(A,"callAccept") and vis(A,"callDecline")
    shot(A,"55_incoming_dark")
    A.evaluate("()=>document.getElementById('callNoCam').click()")
    r["live"]= wait_for(A,"()=>window.__gz.live()",12000) and wait_for(B,"()=>window.__gz.live()",12000)
    A.wait_for_timeout(1500)
    r["nocam_no_camera"]= A.evaluate("()=>window.__gz.localTracks()")==["audio"] and vis(A,"callCam")
    r["nocam_sees_them"]= wait_for(A,"()=>{ const p=document.querySelector('#callStage .peer'); const v=p&&p.querySelector('video.mainv'); return !!p && !p.classList.contains('audio') && v && v.videoWidth>0; }",8000)
    r["they_see_avatar"]= B.evaluate("()=>{ const p=document.querySelector('#callStage .peer'); return !!p && p.classList.contains('audio'); }")
    r["no_false_weak"]= not vis(A,"callWeak") and not vis(B,"callWeak")
    A.evaluate("()=>document.getElementById('callCam').click()"); A.wait_for_timeout(1500)
    r["camera_later"]= "video" in A.evaluate("()=>window.__gz.localTracks()") and wait_for(B,"()=>{ const p=document.querySelector('#callStage .peer'); const v=p&&p.querySelector('video.mainv'); return !!p && !p.classList.contains('audio') && v && v.videoWidth>0; }",10000)
    # ---- 3. weak connection ----
    A.evaluate("()=>{ window.__gz.qual({loss:0.25}); window.__gz.qual({rtt:1.2}); }")
    r["weak_shown"]= vis(A,"callWeak") and A.eval_on_selector("#callWeak","e=>e.textContent.trim()")=="Weak connection"
    shot(A,"55_weak_dark")
    A.evaluate("()=>{ window.__gz.qual({loss:0}); window.__gz.qual({loss:0}); }")
    r["weak_hysteresis"]= vis(A,"callWeak")
    A.evaluate("()=>window.__gz.qual({loss:0})")
    r["weak_hidden_again"]= not vis(A,"callWeak")
    A.evaluate("()=>document.getElementById('callEnd').click()"); A.wait_for_timeout(800)
    r["weak_reset_after_call"]= not vis(A,"callWeak")
    # an audio call offers no "without camera"
    B.wait_for_timeout(800); B.click("#callBtn"); B.wait_for_timeout(300)
    r["audio_call_two_choices"]= wait_for(A,"()=>!document.getElementById('callIncoming').hidden",8000) and not vis(A,"callNoCam")
    A.evaluate("()=>document.getElementById('callDecline').click()"); A.wait_for_timeout(500)
    r["errors"]= (errs+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
