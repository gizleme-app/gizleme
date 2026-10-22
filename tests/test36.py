# Mailbox forward secrecy: per-contact weekly one-way key chain — seeding, advancing, unreadable old weeks, holding, convergence.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site36"); site.mkdir(exist_ok=True)
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
HOOK='''const _gzAsk0=gzAsk; gzAsk=(o)=>{ window.__asks=(window.__asks||[]).concat([String(o.text||"")]); const pol=window.__askPolicy; let v=pol?pol(String(o.text||""),o):undefined; if(v===undefined) v= o.input ? (window.__promptValue!==undefined ? window.__promptValue : (o.def||"")) : true; if(v==="__dialog__") return _gzAsk0(o); return Promise.resolve(v); };   // tests: the house dialog answers like page.on("dialog") did — yes, or the prompt value; window.__askPolicy decides per question
window.__gz={contacts:()=>contactsLoad(),groups:()=>groupsLoad(),
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
    errsA=[]; errsB=[]; errsC=[]
    ctxA,A=boot("oguz",errsA)
    A.click("#sbNew"); A.wait_for_timeout(400); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    r["link_flagsChain"]= link_payload(link).get("f")==1
    E=A.evaluate("()=>window.__gz.epoch()")
    ctxB,B=boot("florian",errsB)
    B.goto(f"http://127.0.0.1:{port}/?r=1#i="+link.split("#i=")[1]); B.wait_for_timeout(400); unlock(B); B.wait_for_timeout(1500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2500)
    ca=contacts(A)[0]; cb=contacts(B)[0]
    r["chain_seededBothSides"]= bool(ca.get("kc")) and ca.get("kc")==cb.get("kc") and ca.get("kce")==E and cb.get("kce")==E and ca["ck"]==cb["ck"]
    r["chain_notFromCk"]= ca.get("kc")!=ca["ck"]
    # A goes away (lock); B writes → mailbox only; the stored item carries the epoch and A reads it on return
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(600)
    B.fill("#msgInput","chaîne ok ?"); B.press("#msgInput","Enter"); B.wait_for_timeout(1200)
    items=[x for box in mb_items().values() for x in box if x["mid"][0] not in "hunr"]
    r["mailbox_itemHasEpoch"]= len(items)>=1 and all(x["data"].get("ep")==E for x in items)
    unlock(A); A.click(".ct"); A.wait_for_timeout(2500)
    r["A_readsFromChain"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='chaîne ok ?')",8000)
    rc=[x for box in mb_items().values() for x in box if x["mid"][0]=="r"]
    r["receipts_useChain"]= wait_for(A,"()=>true",10) and (time.sleep(1.5) or all(x["data"].get("ep")==E for x in [x for box in mb_items().values() for x in box if x["mid"][0]=="r"]))
    # ---- the chain only moves forward: advancing throws old roots away, and they cannot come back ----
    kc0=ca["kc"]
    A.evaluate("([kc])=>{ const l=window.__gz.contacts(); l[0].kc=kc; l[0].kce=window.__gz.epoch()-5; window.__gz.save(l); }",[kc0])
    A.evaluate("()=>window.__gz.advance()"); A.wait_for_timeout(500)
    ca2=contacts(A)[0]; expected=A.evaluate("([kc,kce,ep])=>window.__gz.chainAt(kc,kce,ep)",[kc0,E-5,E-2])
    r["advance_toEminus2"]= ca2.get("kce")==E-2 and ca2.get("kc")==expected and ca2.get("kc")!=kc0
    r["old_rootUnreachable"]= A.evaluate("([kc,kce])=>window.__gz.chainAt(kc,kce,kce-1)",[ca2["kc"],ca2["kce"]]) is None
    r["same_keyAhead"]= A.evaluate("([kc,kce,ep])=>window.__gz.chainAt(kc,kce,ep)",[ca2["kc"],ca2["kce"],E+1])==A.evaluate("([kc,kce,ep])=>window.__gz.chainAt(kc,kce,ep)",[kc0,E-5,E+1])
    # restore A's real state (B still holds kce=E; chains agree on every epoch ≥ E anyway)
    r["stillDecryptsCurrent"]= A.evaluate("([kc,kce,ep])=>window.__gz.chainAt(kc,kce,ep)",[ca2["kc"],ca2["kce"],E])==A.evaluate("([kc,kce,ep])=>window.__gz.chainAt(kc,kce,ep)",[kc0,E-5,E])
    A.evaluate("([kc,kce])=>{ const l=window.__gz.contacts(); l[0].kc=kc; l[0].kce=kce; window.__gz.save(l); }",[kc0,E])   # back in step with B
    mbid=A.evaluate("([ck])=>window.__gz.mboxIdOf(ck)",[ca["ck"]])
    # ---- a message from a week this device no longer holds is skipped: not shown, and the cursor moves on ----
    A.evaluate("()=>window.__gz.leave()"); A.wait_for_timeout(500)           # A off the live channel: B's message goes to the mailbox only
    A.evaluate("()=>{ const l=window.__gz.contacts(); l[0].kce=window.__gz.epoch()+1; window.__gz.save(l); }")   # pretend this week's root is already gone
    B.fill("#msgInput","trop vieux"); B.press("#msgInput","Enter"); B.wait_for_timeout(1200)
    A.evaluate("()=>window.__gz.fetchAll()"); A.wait_for_timeout(2000)
    cur=A.evaluate("()=>window.__gz.mbts()").get(mbid,0); latest=max(datetime.datetime.fromisoformat(x["ts"]).timestamp()*1000 for box in mb_items().values() for x in box)
    r["unreadable_cursorMovesOn"]= cur>=latest-1
    A.evaluate("([kc,kce])=>{ const l=window.__gz.contacts(); l[0].kc=kc; l[0].kce=kce; window.__gz.save(l); }",[kc0,E])
    A.click(".ct"); A.wait_for_timeout(2000)
    r["unreadable_notShown"]= not A.evaluate("()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='trop vieux')")
    # ---- hold: a device that has not synced the chain yet must not lose the message ----
    A.evaluate("()=>window.__gz.leave()"); A.wait_for_timeout(500)
    A.evaluate("()=>{ const l=window.__gz.contacts(); delete l[0].kc; delete l[0].kce; window.__gz.save(l); }")   # chain unknown on this device
    B.fill("#msgInput","tu verras plus tard"); B.press("#msgInput","Enter"); B.wait_for_timeout(1200)
    A.evaluate("()=>window.__gz.fetchAll()"); A.wait_for_timeout(2000)
    cur2=A.evaluate("()=>window.__gz.mbts()").get(mbid,0); latest2=max(datetime.datetime.fromisoformat(x["ts"]).timestamp()*1000 for box in mb_items().values() for x in box)
    r["hold_cursorHeld"]= cur2<latest2-1
    A.click(".ct"); A.wait_for_timeout(1500)
    r["hold_notShownWithoutChain"]= not A.evaluate("()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='tu verras plus tard')")
    A.evaluate("([kc,kce])=>{ const l=window.__gz.contacts(); l[0].kc=kc; l[0].kce=kce; window.__gz.save(l); }",[kc0,E])   # the vault sync brings it
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2500)
    r["hold_readAfterSync"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='tu verras plus tard')",8000)
    # ---- wrong chain (two device pairs seeded at once): the message is kept, not skipped, until the vault converges ----
    A.evaluate("()=>window.__gz.leave()"); A.wait_for_timeout(500)
    A.evaluate("([kce])=>{ const l=window.__gz.contacts(); l[0].kc='zzzz'+'z'.repeat(39)+'='; l[0].kce=kce; window.__gz.save(l); }",[E])   # same week, another root (sorts after any real one)
    B.fill("#msgInput","mauvaise chaine"); B.press("#msgInput","Enter"); B.wait_for_timeout(1200)
    A.evaluate("()=>window.__gz.fetchAll()"); A.wait_for_timeout(2000)
    cur3=A.evaluate("()=>window.__gz.mbts()").get(mbid,0); latest3=max(datetime.datetime.fromisoformat(x["ts"]).timestamp()*1000 for box in mb_items().values() for x in box)
    r["wrongChain_cursorHeld"]= cur3<latest3-1
    A.click(".ct"); A.wait_for_timeout(1200)
    r["wrongChain_notShownYet"]= not A.evaluate("()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='mauvaise chaine')")
    m5=A.evaluate("([ck,kc,kce])=>window.__gz.merge({contacts:[{name:'oguz',ck,kc,kce,ts:1}]}).contacts.find(c=>c.ck===ck)",[ca["ck"],kc0,E])   # the vault brings B's root: smaller wins
    r["wrongChain_mergeConverges"]= m5.get("kc")==kc0
    A.evaluate("([kc,kce])=>{ const l=window.__gz.contacts(); l[0].kc=kc; l[0].kce=kce; window.__gz.save(l); }",[kc0,E])
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2500)
    r["wrongChain_readAfterMerge"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='mauvaise chaine')",8000)
    # ---- vault merge: the more advanced chain wins, a chain-less record never erases one ----
    m=A.evaluate("([ck,kc,kce])=>{ const out=window.__gz.merge({contacts:[{ck,name:'florian',kc,kce,ts:1}]}); return out.contacts.find(c=>c.ck===ck); }",[ca["ck"],"QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5MA==",E+4])
    r["merge_moreAdvancedWins"]= m.get("kce")==E+4 and m.get("kc")=="QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5MA=="
    m2=A.evaluate("([ck])=>{ const out=window.__gz.merge({contacts:[{ck,name:'florian',ts:1}]}); return out.contacts.find(c=>c.ck===ck); }",[ca["ck"]])
    r["merge_keepsChain"]= m2.get("kc")==kc0 and m2.get("kce")==E
    # ---- an older build on one side: no chain on either side, plain keys as before ----
    A.click("#sbNew"); A.wait_for_timeout(400); link2=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    pl=link_payload(link2); pl.pop("f",None); nof=base64.urlsafe_b64encode(json.dumps(pl,separators=(",",":")).encode()).decode().rstrip("=")
    ctxC,C=boot("carla",errsC)
    C.evaluate("()=>{ window.__noFsu=true; }")   # carla runs an older build: never offers a chain in presence
    C.goto(f"http://127.0.0.1:{port}/?r=5#i="+nof); C.wait_for_timeout(400); C.evaluate("()=>{ window.__noFsu=true; }"); unlock(C); C.wait_for_timeout(1500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2500)
    cA=[c for c in contacts(A) if c.get("name")=="carla"]; cC=contacts(C)
    r["mixed_noChain"]= len(cA)==1 and not cA[0].get("kc") and len(cC)==1 and not cC[0].get("kc")
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(500)
    C.fill("#msgInput","sans chaîne"); C.press("#msgInput","Enter"); C.wait_for_timeout(1200)
    plain=[x for box in mb_items().values() for x in box if x["mid"][0] not in "hunr" and "ep" not in x["data"]]
    r["mixed_plainKey"]= len(plain)>=1
    unlock(A); A.evaluate("()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>/carla/.test(x.textContent)).click(); }"); A.wait_for_timeout(2500)
    r["mixed_delivered"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='sans chaîne')",8000)
    r["errors"]= (errsA+errsB+errsC)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
