# Invite links: expiry, optional 4-digit code (proved to the inviter, three misses cancel), QR code.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site35"); site.mkdir(exist_ok=True)
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
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), save:(l)=>contactsSave(l), lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; } };
'''
_app=_app[:_app.rstrip().rfind("})();")]+HOOK+'})();\n'
(site/"app.js").write_text(_app)
(site/"vendor").mkdir(exist_ok=True)
for f in ["vendor/qrcode-1.4.4.js"]: (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg","logo-head.png","logo-word.png","logo-dot.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"sw.js").write_text(pathlib.Path(SRC+"sw.js").read_text().replace("/app.min.js?v=","/app.js?v="))   # the worker precaches what the page loads
os.chdir(site)

RELAY={}; RLOCK=threading.Lock(); MBOX={}; ACKS=[]
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

r={}
import traceback, cv2, numpy as np
def link_payload(link): return json.loads(base64.urlsafe_b64decode(link.split("#i=")[1]+"=="))
def contacts(p): return p.evaluate("()=>window.__gz.contacts()")
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs):
        ctx=b.new_context(timezone_id=TZ, viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); entered(p)
        return ctx,p
    errsA=[]; errsB=[]; errsC=[]; errsD=[]
    ctxA,A=boot("oguz",errsA)
    # ---- options: default 24 h expiry, optional code; the link text follows the options ----
    A.click("#sbNew"); A.wait_for_timeout(400)
    l1=link_payload(A.eval_on_selector("#invLinkOut","e=>e.value"))
    r["default_expiry24h"]= abs(l1.get("x",0)-(time.time()*1000+86400000))<60000 and "c" not in l1
    A.select_option("#invExp","3600000"); A.check("#invPinOn"); A.wait_for_timeout(200)
    l2=link_payload(A.eval_on_selector("#invLinkOut","e=>e.value"))
    r["options_applied"]= abs(l2.get("x",0)-(time.time()*1000+3600000))<60000 and l2.get("c")==1 and l2["s"]==l1["s"]
    pin=A.eval_on_selector("#invPinVal","e=>e.textContent"); r["pin_shown"]= bool(__import__("re").fullmatch(r"\d{4}",pin)) and A.evaluate("()=>!document.getElementById('invPinBox').hidden")
    # ---- QR: drawn on share, decodes to the very same link ----
    A.click("#qrShow"); A.wait_for_timeout(500)
    png=A.eval_on_selector("#qrCanvas","e=>e.toDataURL('image/png')")
    img=cv2.imdecode(np.frombuffer(base64.b64decode(png.split(",")[1]),np.uint8),cv2.IMREAD_COLOR)
    img=cv2.copyMakeBorder(img,60,60,60,60,cv2.BORDER_CONSTANT,value=(255,255,255))
    decoded=""
    for sc in (1,2,3):
        im2=cv2.resize(img,None,fx=sc,fy=sc,interpolation=cv2.INTER_NEAREST); decoded,_,_=cv2.QRCodeDetector().detectAndDecode(im2)
        if decoded: break
    link=A.eval_on_selector("#invLinkOut","e=>e.value")
    r["qr_decodes"]= decoded==link
    r["qr_freezesOptions"]= A.evaluate("()=>document.getElementById('invExp').disabled && document.getElementById('invPinOn').disabled") and contacts(A)[0].get("pin")==pin and bool(contacts(A)[0].get("x"))
    A.click("#joinBtn"); A.wait_for_timeout(1000)
    # ---- B opens with a WRONG code: no binding, B is told, A counts 1/3 ----
    ctxB,B=boot("florian",errsB)
    B.goto(f"http://127.0.0.1:{port}/?r=1#i="+link.split("#i=")[1]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); entered(B)
    r["B_askedCode"]= B.evaluate("()=>document.getElementById('pinModal').classList.contains('show')")
    wrong=str((int(pin)+1)%10000).zfill(4); B.fill("#pinInput",wrong); B.click("#pinOk"); B.wait_for_timeout(2500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2000)
    ca=contacts(A)[0]
    r["A_notBound_wrongCode"]= bool(ca.get("pk")) and ca.get("pinFails")==1 and not ca.get("dead")
    r["A_warned"]= wait_for(A,"()=>window.__gz.lastSys().some(x=>/wrong code \\(1\\/3\\)/.test(x))",5000)
    B.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); B.wait_for_timeout(2500)
    r["B_toldWrong"]= wait_for(B,"()=>window.__gz.lastSys().some(x=>/code you entered was wrong/.test(x)) && !!window.__gz.contacts()[0].nopin",8000)
    # ---- B opens again with the RIGHT code: bound; the void attempt is replaced ----
    B.goto(f"http://127.0.0.1:{port}/?r=2#i="+link.split("#i=")[1]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); entered(B)
    r["B_askedAgain"]= B.evaluate("()=>document.getElementById('pinModal').classList.contains('show')")
    B.fill("#pinInput",pin); B.click("#pinOk"); B.wait_for_timeout(2500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2500)
    ca=contacts(A)[0]; cb=contacts(B)
    r["A_bound_rightCode"]= (not ca.get("pk")) and ca.get("v3")==1 and ca.get("name")=="florian"
    r["B_oneContact_bound"]= len(cb)==1 and (not cb[0].get("nopin")) and (not cb[0].get("dead")) and cb[0].get("v3")==1
    B.fill("#msgInput","avec le code"); B.press("#msgInput","Enter"); B.wait_for_timeout(1000)
    r["chat_works"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='avec le code')",8000)
    # ---- three wrong codes cancel a link ----
    A.click("#sbNew"); A.wait_for_timeout(400); A.check("#invPinOn"); A.wait_for_timeout(200); link3=A.eval_on_selector("#invLinkOut","e=>e.value"); pin3=A.eval_on_selector("#invPinVal","e=>e.textContent")
    A.click("#joinBtn"); A.wait_for_timeout(800)
    ctxC,C=boot("eve",errsC)
    for k in range(3):
        C.goto(f"http://127.0.0.1:{port}/?r={10+k}#i="+link3.split("#i=")[1]); C.wait_for_timeout(400); C.fill("#pwInput","password123"); C.click("#joinBtn"); C.wait_for_timeout(1200)
        C.fill("#pinInput",str((int(pin3)+k+1)%10000).zfill(4)); C.click("#pinOk"); C.wait_for_timeout(1500)
        A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(1500)
        C.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); C.wait_for_timeout(1500)
    pend=[c for c in contacts(A) if c.get("is")]
    r["dead_after3"]= len(pend)==1 and pend[0].get("dead")==1 and pend[0].get("pinFails")==3 and bool(pend[0].get("pk"))
    r["dead_statusShown"]= wait_for(A,"()=>window.__gz.lastSys().some(x=>/Three wrong codes/.test(x))",5000)
    # even the right code is refused now
    C.goto(f"http://127.0.0.1:{port}/?r=20#i="+link3.split("#i=")[1]); C.wait_for_timeout(400); C.fill("#pwInput","password123"); C.click("#joinBtn"); C.wait_for_timeout(1200)
    C.fill("#pinInput",pin3); C.click("#pinOk"); C.wait_for_timeout(1500); A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(1500)
    r["dead_staysDead"]= [c for c in contacts(A) if c.get("is")][0].get("dead")==1 and bool([c for c in contacts(A) if c.get("is")][0].get("pk"))
    # ---- expiry: an expired link is refused by the opener; a late hello is ignored by the inviter ----
    A.click("#sbNew"); A.wait_for_timeout(400); link4=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    pl=link_payload(link4); pl["x"]=int(time.time()*1000)-3600000; expired=base64.urlsafe_b64encode(json.dumps(pl,separators=(",",":")).encode()).decode().rstrip("=")
    ctxD,D=boot("dan",errsD)
    D.goto(f"http://127.0.0.1:{port}/?r=30#i="+expired); D.wait_for_timeout(400); D.fill("#pwInput","password123"); D.click("#joinBtn"); entered(D)
    r["opener_refusesExpired"]= wait_for(D,"()=>/expired/.test(document.getElementById('toast')?document.getElementById('toast').textContent:'')",3000) and len(contacts(D))==0
    # the inviter's copy expires too (clock moved on): a hello arriving now is ignored
    A.evaluate("()=>{ const l=window.__gz.contacts(); const c=l.find(x=>x.is && !x.dead && x.pk && !x.pin); c.x=Date.now()-3600000; window.__gz.save(l); }")
    D.goto(f"http://127.0.0.1:{port}/?r=31#i="+link4.split("#i=")[1]); D.wait_for_timeout(400); D.fill("#pwInput","password123"); D.click("#joinBtn"); entered(D)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2000)
    pc=A.evaluate("()=>window.__gz.contacts().find(x=>x.is && x.pk && !x.pin)")
    r["inviter_ignoresLateHello"]= bool(pc) and bool(pc.get("pk")) and pc.get("expired")==1 and pc.get("name")=="Invited friend"
    r["inviter_expiredLineAndList"]= wait_for(A,"()=>window.__gz.lastSys().some(x=>/after it expired/.test(x))",4000) and A.evaluate("()=>[...document.querySelectorAll('.ct .cm')].some(e=>/Invite expired/.test(e.textContent))")
    # ---- links without x / c (older) still open as before ----
    r["errors"]= (errsA+errsB+errsC+errsD)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
