# Invite links v3: one-time pre-key in the link, ECDH agreement in the hello, link reuse detected and refused, link-key messages ignored.
from playwright.sync_api import sync_playwright
import sys as _sys, os as _os0; _sys.path.insert(0, _os0.path.dirname(_os0.path.abspath(__file__))); from harness import wait_for as _wait_for, entered, TZ   # shared waits (tests/harness.py)
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site32"); site.mkdir(exist_ok=True)
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
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; } };
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
import traceback
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs):
        ctx=b.new_context(timezone_id=TZ, viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); entered(p)
        return ctx,p
    errsA=[]; errsB=[]; errsE=[]; errsF=[]
    ctxA,A=boot("oguz",errsA)
    # ---- A creates an invite: the link carries a pre-key; the pending contact keeps the private half ----
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value")
    payload=json.loads(base64.urlsafe_b64decode(link.split("#i=")[1]+"=="))
    r["link_hasPrekey"]= isinstance(payload.get("p"),str) and 80<=len(payload["p"])<=100 and len(payload.get("s",""))>20
    CKL=A.evaluate("([s])=>window.__ckFromSecret(s)",[payload["s"]]); MB_LINK=A.evaluate("([ck])=>window.__mboxId(ck)",[CKL])
    A.click("#joinBtn"); A.wait_for_timeout(1200)
    c=A.evaluate("()=>window.__gz.contacts()[0]")
    r["pending_v3"]= c.get("v3")==1 and bool(c.get("pk")) and bool(c.get("is")) and c["ck"]==CKL
    # a message written before the link is opened waits on the device — nothing lands under the link key
    A.fill("#msgInput","avant ouverture"); A.press("#msgInput","Enter"); A.wait_for_timeout(800)
    r["preOpen_queued"]= A.evaluate("([ck])=>(window.__gz.outq()[ck]||[]).length",[CKL])==1 and A.eval_on_selector_all(".log .bubble.sent .st","els=>els.map(e=>e.dataset.st)")==["pending"]
    r["preOpen_nothingOnRelay"]= MB_LINK not in dump()
    # ---- B opens the link: agrees a key with the pre-key, leaves a hello, writes under the agreed key ----
    ctxB,B=boot("florian",errsB)
    B.goto(f"http://127.0.0.1:{port}/?r=2#i="+link.split("#i=")[1]); B.wait_for_timeout(400)
    B.fill("#pwInput","password123"); B.click("#joinBtn"); entered(B, 1500)
    cb=B.evaluate("()=>window.__gz.contacts()[0]")
    r["B_agreedKey"]= cb["ck"]!=CKL and cb.get("prev")==CKL and cb.get("v3")==1 and bool(cb.get("sv"))
    r["B_helloOnRelay"]= len(dump().get(MB_LINK,[]))==1
    B.fill("#msgInput","coucou"); B.press("#msgInput","Enter"); B.wait_for_timeout(1000)
    MB2=B.evaluate("([ck])=>window.__mboxId(ck)",[cb["ck"]])
    d=dump(); r["B_msgUnderAgreedKeyOnly"]= len(d.get(MB2,[]))>=1 and all(m["mid"][0]=="h" for m in d.get(MB_LINK,[]))
    r["DBG_dump"]= {k[:10]:[m["mid"][:3] for m in v] for k,v in d.items()}; r["DBG_ids"]= {"link":MB_LINK[:10],"b2":MB2[:10]}; r["DBG_cb"]= {k:(v if k in ("v3","dead","recon") else "…") for k,v in cb.items()}
    # ---- A, online in the link room, sees the hello in presence: binds, flushes, both pair on the agreed key ----
    r["A_bound"]= wait_for(A,"()=>{ const c=window.__gz.contacts()[0]; return !c.pk && !c.is && c.name==='florian' && c.v3===1 && !!c.prev && c.ck!==c.prev; }",12000)
    r["A_sameKeyAsB"]= A.evaluate("()=>window.__gz.contacts()[0].ck")==cb["ck"] and A.evaluate("()=>window.__gz.contacts()[0].sv")==cb.get("sv")
    r["A_openedLine"]= wait_for(A,"()=>window.__gz.lastSys().some(x=>x.includes('opened your link'))",5000)
    r["A_queueFlushed"]= wait_for(A,"()=>Object.keys(window.__gz.outq()).length===0",6000) and A.eval_on_selector_all(".log .bubble.sent .st","els=>els.map(e=>e.dataset.st)")[0]!="pending"
    r["DBG_outq"]= A.evaluate("()=>Object.keys(window.__gz.outq()).map(k=>k.slice(0,8)+':'+window.__gz.outq()[k].length)"); r["DBG_states"]= A.eval_on_selector_all(".log .bubble.sent .st","els=>els.map(e=>e.dataset.st)")
    r["pair_A"]= wait_for(A,"()=>document.getElementById('bar').classList.contains('st-online')",12000)
    r["pair_B"]= wait_for(B,"()=>document.getElementById('bar').classList.contains('st-online')",12000)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); B.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2000)
    r["A_gotCoucou"]= wait_for(A,"()=>[...document.querySelectorAll('.log .bubble.recv .txt')].some(e=>e.textContent==='coucou')",10000)
    r["B_gotPreOpen"]= "avant ouverture" in B.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    d=dump(); r["linkMailbox_helloOnly"]= [m["mid"][0] for m in d.get(MB_LINK,[])]==["h"]
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); B.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(1500); d=dump()
    r["delivered_acked"]= all(x["d"] for x in d.get(MB_LINK,[])) and sum(1 for x in d.get(MB2,[]) if x["d"])>=2
    r["recon_mutualClosed"]= wait_for(A,"()=>!window.__gz.contacts()[0].recon",8000) and wait_for(B,"()=>!window.__gz.contacts()[0].recon && !window.__gz.contacts()[0].hello",8000)
    # ---- E has a copy of the link and opens it later: not added, warned, told ----
    ctxE,E=boot("eve",errsE)
    E.goto(f"http://127.0.0.1:{port}/?r=2#i="+link.split("#i=")[1]); E.wait_for_timeout(400)
    E.fill("#pwInput","password123"); E.click("#joinBtn"); entered(E, 1500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))")
    r["A_reuseWarned"]= wait_for(A,"()=>window.__gz.lastSys().some(x=>x.includes('Someone else just opened'))",10000)
    r["A_stillOneContact"]= A.evaluate("()=>window.__gz.contacts().length")==1 and A.evaluate("()=>window.__gz.contacts()[0].ck")==cb["ck"]
    E.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))")
    r["E_toldUsed"]= wait_for(E,"()=>window.__gz.lastSys().some(x=>x.includes('already been used'))",10000) and E.evaluate("()=>!!window.__gz.contacts()[0].dead")
    E.fill("#msgInput","hack"); E.press("#msgInput","Enter"); E.wait_for_timeout(1000); A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(1500)
    r["E_cannotReachA"]= "hack" not in A.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    d=dump(); r["linkMailbox_noMessages"]= all(m["mid"][0] in "hu" for m in d.get(MB_LINK,[]))   # hellos and 'used' only
    # ---- bare link key: a message deposited under the link key itself (no hello: an old client, or anyone
    # holding a copy of the link) is NOT shown and does not pair — a v3 link mailbox only ever carries hellos
    A.click("#sbNew"); A.wait_for_timeout(300); link2=A.eval_on_selector("#invLinkOut","e=>e.value")
    pl2=json.loads(base64.urlsafe_b64decode(link2.split("#i=")[1]+"==")); legacy=dict(pl2); legacy.pop("p",None)
    leg=base64.urlsafe_b64encode(json.dumps(legacy,separators=(",",":")).encode()).decode().rstrip("=")
    A.click("#joinBtn"); A.wait_for_timeout(1000); A.fill("#msgInput","pour l ancien"); A.press("#msgInput","Enter"); A.wait_for_timeout(600)
    ctxF,F=boot("fred",errsF)
    F.goto(f"http://127.0.0.1:{port}/?r=2#i="+leg); F.wait_for_timeout(400); F.fill("#pwInput","password123"); F.click("#joinBtn"); entered(F, 2500)
    F.fill("#msgInput","salut vieux"); F.press("#msgInput","Enter"); F.wait_for_timeout(1000)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2000)
    r["linkkey_msgIgnored"]= "salut vieux" not in A.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    r["linkkey_prekeyKept"]= A.evaluate("()=>{ const c=window.__gz.contacts().find(x=>x.ck==='"+pl2["n"]+"'); return !c || (!!c.pk && c.v3===1); }") if False else A.evaluate("()=>{ const l=window.__gz.contacts().filter(x=>x.v3===1 && x.pk); return l.length>=1 && !window.__gz.contacts().some(x=>x.name==='fred'); }")
    F.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); F.wait_for_timeout(2000)
    r["linkkey_queuedNotLeaked"]= "pour l ancien" not in F.eval_on_selector_all(".log .bubble.recv .txt","els=>els.map(e=>e.textContent)")
    # ---- A: lock / unlock keeps the bound contact and history ----
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(400); A.fill("#pwInput","password123"); A.click("#joinBtn"); entered(A)
    r["persist"]= A.evaluate("()=>{ const c=window.__gz.contacts().find(x=>x.name==='florian'); return !!c && c.v3===1 && !c.pk; }")
    r["errors"]= (errsA+errsB+errsE+errsF)[:4]
    b.close()
except Exception:
    traceback.print_exc()
finally:
    print('RESULTS')
    for k,v in r.items(): print(f'  {k}: {v}')
srv.shutdown()
