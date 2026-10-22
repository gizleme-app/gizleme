# Key chain for contacts that predate it: seeded from the ECDH secret of the next live, authenticated meeting.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site39"); site.mkdir(exist_ok=True)
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
        if(window.__noFsu){ for(const k in r.pres){ if(r.pres[k] && r.pres[k].fsu) r.pres[k]=Object.assign({},r.pres[k],{fsu:undefined}); } } const pj=JSON.stringify(r.pres); if(pj!==this._presJ){ this._presJ=pj; this._pres=r.pres; const cb=this._cbs["presence:sync"]; cb&&cb(); }
        for(const m of r.msgs){ this._since=m.i; if(m.from===inst) continue; const cb=this._cbs["broadcast:"+m.event]; cb&&cb({payload:m.payload}); } }catch(e){} },
    track(p){ if(window.__noFsu && p){ p=Object.assign({},p); delete p.fsu; } this._me=p; return fetch("/relay",{method:"POST",body:JSON.stringify({type:"track",room:name,key,payload:p})}).then(()=>"ok"); },
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
HOOK='''window.__gz={pp:()=>presencePayload(A()),contacts:()=>contactsLoad(),groups:()=>groupsLoad(),
  callState:()=>call?{state:call.state,live:!!call.t1,group:!!call.group,video:call.video,dir:call.dir,peers:[...call.peers.values()].map(P=>({pid:P.pid,cs:P.pc.connectionState,connected:P.connected,tracks:P.stream.getTracks().map(t=>t.kind)})),localAudioOn:call.local?call.local.getAudioTracks().every(t=>t.enabled):null,localVideo:call.local?call.local.getVideoTracks().length:0}:null,
  setIce:(l)=>{ _iceCache={servers:l,exp:Date.now()+1e9}; }, room:()=>{ const R=A(); return R?{paired:R.paired,group:R.group,gcall:R.gcall?R.gcall.cid:null,ck:R.fromContact}:null; },
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), save:(l)=>contactsSave(l), chainAt:async(kc,kce,ep)=>{ const r=await chainRootAt(kc,kce,ep); return r?b64(r):null; }, advance:()=>advanceChains(), epoch:()=>epochNow(), mbts:()=>JSON.parse(JSON.stringify(_meta.mbts||{})), merge:(r)=>mergeContacts(r), fetchAll:()=>inboxPull(true), leave:()=>{ const R=A(); if(R) leaveRoom(R.code); }, mboxIdOf:(ck)=>mboxIdForSecret(ck), lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; } };
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


def mb_items():
    with RLOCK: return {k:[dict(x) for x in v] for k,v in MBOX.items()}
r={}
import traceback
def link_payload(link): return json.loads(base64.urlsafe_b64decode(link.split("#i=")[1]+"=="))
def contacts(p): return p.evaluate("()=>window.__gz.contacts()")
def unlock(p):
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs):
        ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p

    errsA=[]; errsC=[]
    ctxA,A=boot("oguz",errsA)
    # a contact made with a link that carried no chain flag (pre-chain build): no chain on either side
    A.click("#sbNew"); A.wait_for_timeout(400); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    pl=link_payload(link); pl.pop("f",None); nof=base64.urlsafe_b64encode(json.dumps(pl,separators=(",",":")).encode()).decode().rstrip("=")
    ctxC,C=boot("carla",errsC)
    C.evaluate("()=>{ window.__noFsu=true; }")   # carla still runs the older build for now
    C.goto(f"http://127.0.0.1:{port}/?r=5#i="+nof); C.wait_for_timeout(400); C.evaluate("()=>{ window.__noFsu=true; }"); unlock(C); C.wait_for_timeout(1500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2500)
    r["paired"]= wait_for(A,"()=>{ const x=window.__gz.room(); return x && x.paired; }",8000)
    cA=contacts(A); cC=contacts(C)
    r["old_peer_noChain"]= len(cA)==1 and not cA[0].get("kc") and len(cC)==1 and not cC[0].get("kc")
    r["A_offersInPresence"]= A.evaluate("()=>window.__gz.pp().fsu===1")
    # carla updates her app (reload = new session keys) → both offer → the live key exchange seeds the chain on both sides
    C.evaluate("()=>{ window.__noFsu=false; }"); C.evaluate("()=>document.getElementById('sbLock').click()"); C.wait_for_timeout(500); unlock(C); C.click(".ct"); C.wait_for_timeout(1000)
    r["repaired"]= wait_for(C,"()=>{ const x=window.__gz.room(); return x && x.paired; }",12000) and wait_for(A,"()=>{ const x=window.__gz.room(); return x && x.paired; }",12000)
    A.wait_for_timeout(1500)
    E=A.evaluate("()=>window.__gz.epoch()")
    r["upg_bothChains"]= wait_for(A,"()=>!!window.__gz.contacts()[0].kc",8000) and wait_for(C,"()=>!!window.__gz.contacts()[0].kc",8000)
    cA=contacts(A)[0]; cC=contacts(C)[0]
    r["upg_sameChain"]= bool(cA.get("kc")) and cA.get("kc")==cC.get("kc") and cA.get("kce")==E and cC.get("kce")==E
    r["upg_notFromCk"]= cA.get("kc")!=cA["ck"]
    r["upg_line"]= A.evaluate("()=>[...document.querySelectorAll('.sys')].some(e=>/Forward secrecy is now on/.test(e.textContent))") and C.evaluate("()=>[...document.querySelectorAll('.sys')].some(e=>/Forward secrecy is now on/.test(e.textContent))")
    r["upg_offerStaysThisSession"]= A.evaluate("()=>window.__gz.pp().fsu===1")   # kept up so the slower side takes the same chain
    # from now on the mailbox uses the chain: A away, carla writes, the stored item carries the epoch, A reads it back
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(600)
    C.fill("#msgInput","après mise à niveau"); C.press("#msgInput","Enter"); C.wait_for_timeout(1200)
    items=[x for box in mb_items().values() for x in box if x["mid"][0] not in "hunr"]
    r["upg_mailboxEpoch"]= len(items)>=1 and all(x["data"].get("ep")==E for x in items)
    unlock(A); A.click(".ct"); A.wait_for_timeout(2500)
    r["upg_delivered"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='après mise à niveau')",8000)
    # a second pairing never re-seeds (the chain is kept, not replaced)
    kc1=cA.get("kc"); C.evaluate("()=>document.getElementById('sbLock').click()"); C.wait_for_timeout(500); unlock(C); C.click(".ct"); C.wait_for_timeout(1000)
    wait_for(C,"()=>{ const x=window.__gz.room(); return x && x.paired; }",12000); C.wait_for_timeout(1500)
    r["upg_stable"]= contacts(A)[0].get("kc")==kc1 and contacts(C)[0].get("kc")==kc1
    r["upg_noOfferNextSession"]= A.evaluate("()=>window.__gz.pp().fsu!==1") and C.evaluate("()=>window.__gz.pp().fsu!==1")
    r["errors"]= (errsA+errsC)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
