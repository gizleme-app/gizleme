# v31: the chat's timer in the header (Off / 5 / 30 / 60 min / 24 h), synced to the other side; with it off,
# photos are kept and shown in the chat on both sides (local encrypted copy, survives the relay's sweep), and a
# long press on one offers Save (a download; the share sheet on iPhone) and Forward (to another chat).
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site49"); site.mkdir(exist_ok=True)
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
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install'), expApply:(ms,ts)=>applyChatExp(A(),ms,ts), expMap:()=>expRoomsMap() };
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
import traceback, io
from PIL import Image as _Img
def png(color):
    b=io.BytesIO(); _Img.new("RGB",(320,200),color).save(b,"PNG"); return b.getvalue()
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(300)
RECV="(t)=>[...document.querySelectorAll('.log:not([style*=\"display: none\"]) .bubble .txt')].some(e=>e.textContent===t)"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
OPEN=".log:not([style*=\"display: none\"])"
EXPST="()=>({off:document.getElementById('expBtn').classList.contains('off'), num:document.getElementById('expNum').textContent, hidden:document.getElementById('expBtn').hidden, color:getComputedStyle(document.getElementById('expBtn')).color})"
SYS="()=>[...document.querySelectorAll('"+OPEN+" .sys')].map(e=>e.textContent)"
LONGIMG=r"""([ms])=>new Promise(res=>{ const L=document.querySelector('.log:not([style*="display: none"])'); const el=[...L.querySelectorAll('.bubble img.keep')].pop(); if(!el) return res('no-el'); const r=el.getBoundingClientRect(); const x=r.left+r.width/2, y=r.top+r.height/2;
  const mk=()=>new Touch({identifier:21,target:el,clientX:x,clientY:y,pageX:x,pageY:y});
  el.dispatchEvent(new TouchEvent('touchstart',{bubbles:true,cancelable:true,touches:[mk()],targetTouches:[mk()],changedTouches:[mk()]}));
  setTimeout(()=>{ const open=!document.getElementById('rxPick').hidden; const np=el.dispatchEvent(new TouchEvent('touchend',{bubbles:true,cancelable:true,touches:[],changedTouches:[mk()]})); res({open, prevented:!np}); }, ms); })"""
PICK="()=>({open:!document.getElementById('rxPick').hidden, save:!document.getElementById('rxSave').hidden, fwd:!document.getElementById('rxFwd').hidden, edit:!document.getElementById('rxEdit').hidden})"
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000):
        ctx=b.new_context(viewport={"width":w,"height":820},locale="en-US",accept_downloads=True); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    def open_link(P, link):
        P.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(2000)
    def invite(P):
        P.evaluate("()=>{ const b=document.getElementById('backHome'); if(b) b.click(); }"); P.wait_for_timeout(200)
        P.click("#sbNew"); P.wait_for_timeout(300); l=P.eval_on_selector("#invLinkOut","e=>e.value"); P.click("#joinBtn"); P.wait_for_timeout(800); return l
    errsA=[]; errsB=[]; errsC=[]
    ctxA,A=boot("oguz",errsA)
    link1=invite(A)
    ctxB,B=boot("serap",errsB,w=1000)
    open_link(B, link1)
    r["paired"]= wait_for(A,PAIRED,10000) and wait_for(B,PAIRED,10000)
    send(A,"hi"); wait_for(B,"()=>("+RECV+")('hi')",8000)
    # ---- 1. the timer in the header ----
    e=A.evaluate(EXPST); r["header_on_24"]= not e["hidden"] and not e["off"] and e["num"]=="24" and e["color"]=="rgb(59, 130, 246)"
    A.click("#expBtn"); A.wait_for_timeout(200)
    r["menu_opens"]= A.is_visible("#expMenu") and A.evaluate("()=>document.querySelector('#expMenu button.on').dataset.v")=="86400000"
    A.click("#expMenu button[data-v='0']"); A.wait_for_timeout(300)
    e=A.evaluate(EXPST); r["off_here"]= not A.is_visible("#expMenu") and e["off"] and e["num"]=="" and e["color"]!="rgb(59, 130, 246)"
    r["off_line_here"]= any("You turned off disappearing messages" in x for x in A.evaluate(SYS))
    r["off_synced"]= wait_for(B,"()=>document.getElementById('expBtn').classList.contains('off')",8000) and any("oguz turned off disappearing messages" in x for x in B.evaluate(SYS))
    r["no_unread_for_change"]= B.evaluate("()=>window.__gz.unreadTotal()")==0
    r["preview_skips_exp"]= wait_for(A,"()=>[...document.querySelectorAll('.ct')].some(e=>e.textContent.includes('hi')) && ![...document.querySelectorAll('.ct')].some(e=>e.textContent.includes('⏱'))",4000)
    # ---- 2. a photo with the timer off: kept on both sides ----
    A.set_input_files("#fileInput", files=[{"name":"red.png","mimeType":"image/png","buffer":png((220,30,30))}]); A.wait_for_timeout(1500)
    r["sent_kept"]= A.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.sent.img-wrap')].pop(); return !!(b && b.querySelector('img.keep') && !b.querySelector('.once')); }")
    r["recv_kept"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.recv.img-wrap')].pop(); return !!(b && b.querySelector('img.keep') && b.querySelector('img.keep').naturalWidth>0 && !b.querySelector('.tapview')); }",10000)
    r["no_view_once_left"]= B.evaluate("()=>document.querySelectorAll('"+OPEN+" .tapview').length")==0
    with RLOCK: nb=len(BLOBS); BLOBS.clear()      # the relay sweeps it: the phone still has its own copy
    r["relay_had_blob"]= nb==1
    B.evaluate("()=>document.querySelector('#barMenu [data-act=lock]').click()"); B.wait_for_timeout(800)
    B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500); B.click(".ct"); B.wait_for_timeout(2000)
    r["kept_after_relock_without_relay"]= wait_for(B,"()=>{ const i=document.querySelector('"+OPEN+" .bubble.recv img.keep'); return !!(i && i.naturalWidth>0); }",6000)
    A.evaluate("()=>document.querySelector('#barMenu [data-act=lock]').click()"); A.wait_for_timeout(800)
    A.fill("#pwInput","password123"); A.click("#joinBtn"); A.wait_for_timeout(1500); A.click(".ct"); A.wait_for_timeout(2000)
    r["sender_keeps_too"]= wait_for(A,"()=>{ const i=document.querySelector('"+OPEN+" .bubble.sent img.keep'); return !!(i && i.naturalWidth>0); }",6000)
    r["timer_kept_after_relock"]= A.evaluate(EXPST)["off"] and B.evaluate(EXPST)["off"]
    # ---- 3. long press: Save / Forward ----
    lp=B.evaluate(LONGIMG,[650]); r["photo_longpress_menu"]= lp=={"open":True,"prevented":True} and B.evaluate(PICK)=={"open":True,"save":True,"fwd":True,"edit":False}
    B.wait_for_timeout(300)
    with B.expect_download(timeout=8000) as dl: B.click("#rxSave")
    d=dl.value; pth=d.path(); import os as _o2
    r["save_downloads"]= d.suggested_filename.startswith("gizleme-") and _o2.path.getsize(pth)>500
    r["save_v"]=d.suggested_filename
    # a third person: Serap forwards the photo to her chat with Can
    ctxC,C=boot("can",errsC,w=1000)
    link2=invite(B); open_link(C, link2)
    r["paired_bc"]= wait_for(C,PAIRED,10000)
    B.evaluate("()=>{ const b=document.getElementById('backHome'); if(b) b.click(); }"); B.wait_for_timeout(300)
    B.evaluate("()=>{ const c=[...document.querySelectorAll('.ct')].find(x=>x.textContent.includes('oguz')); c.click(); }"); B.wait_for_timeout(1500)
    wait_for(B,"()=>{ const i=document.querySelector('"+OPEN+" .bubble.recv img.keep'); return !!(i && i.naturalWidth>0); }",6000)
    B.locator(OPEN+" .bubble.recv img.keep").last.click(button="right"); B.wait_for_timeout(300)
    r["rightclick_photo_menu"]= B.evaluate(PICK)["fwd"]
    B.click("#rxFwd"); B.wait_for_timeout(400)
    r["forward_list"]= B.is_visible("#fwdModal") and B.evaluate("()=>[...document.querySelectorAll('#fwdList .merge-row .mr-t')].map(x=>x.textContent)")==["can"]
    B.click("#fwdList .merge-row"); B.wait_for_timeout(2500)
    r["forward_switches_chat"]= B.eval_on_selector("#peerName","e=>e.textContent")=="can"
    r["forwarded_received"]= wait_for(C,"()=>!!document.querySelector('"+OPEN+" .bubble.recv .tapview') || !!document.querySelector('"+OPEN+" .bubble.recv img.keep')",10000)
    r["forward_follows_target_timer"]= C.evaluate("()=>!!document.querySelector('"+OPEN+" .bubble.recv .tapview')")   # their chat still runs 24 h: view-once there
    # ---- 4. timer back on from the other side: photos view-once again ----
    B.evaluate("()=>{ const b=document.getElementById('backHome'); if(b) b.click(); }"); B.wait_for_timeout(300)
    B.evaluate("()=>{ const c=[...document.querySelectorAll('.ct')].find(x=>x.textContent.includes('oguz')); c.click(); }"); B.wait_for_timeout(1500)
    B.click("#expBtn"); B.wait_for_timeout(150); B.click("#expMenu button[data-v='300000']"); B.wait_for_timeout(300)
    r["on_5_here"]= B.evaluate(EXPST)["num"]=="5" and not B.evaluate(EXPST)["off"]
    r["on_5_synced"]= wait_for(A,"()=>document.getElementById('expNum').textContent==='5' && !document.getElementById('expBtn').classList.contains('off')",8000) and any("serap set messages to disappear after 5 minutes" in x for x in A.evaluate(SYS))
    B.set_input_files("#fileInput", files=[{"name":"blue.png","mimeType":"image/png","buffer":png((30,60,220))}]); B.wait_for_timeout(1500)
    r["photo_once_when_on"]= wait_for(A,"()=>!!document.querySelector('"+OPEN+" .bubble.recv .tapview')",10000) and B.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.sent.img-wrap')].pop(); return !!b.querySelector('.once'); }")
    r["older_change_ignored"]= A.evaluate("()=>window.__gz.expApply(0,1)")==False and A.evaluate(EXPST)["num"]=="5"
    # the Settings selector says the same and changes it for both too
    A.evaluate("()=>{ const s=document.getElementById('expRoom'); s.value='86400000'; s.dispatchEvent(new Event('change',{bubbles:true})); }"); A.wait_for_timeout(300)
    r["settings_select_syncs"]= A.evaluate(EXPST)["num"]=="24" and wait_for(B,"()=>document.getElementById('expNum').textContent==='24'",8000)
    r["errors"]= (errsA+errsB+errsC)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
