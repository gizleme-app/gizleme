# Groups: every message signed by its author's identity key; spoofed names and tampered messages flagged; identity key in the vault.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site37"); site.mkdir(exist_ok=True)
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
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), save:(l)=>contactsSave(l), chainAt:async(kc,kce,ep)=>{ const r=await chainRootAt(kc,kce,ep); return r?b64(r):null; }, advance:()=>advanceChains(), epoch:()=>epochNow(), mbts:()=>JSON.parse(JSON.stringify(_meta.mbts||{})), merge:(r)=>mergeContacts(r), fetchAll:()=>inboxPull(true), ident:()=>identLoad(), adopt:(id)=>identAdopt(id), ensure:()=>identEnsure().then(k=>k.pk), forge:async(name,tamper)=>{ const R=A(); const env={t:'txt',body:'je suis '+name}; const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const obj=Object.assign({},env,{mid,n:name,sts:Date.now()}); const id=await identEnsure(); obj.pk=id.pk; obj.sig=b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'}, id.priv, gsigData(R.rid, obj))); if(tamper) obj.body+='!'; return broadcastGroup(R, obj, mid); }, unsigned:async(name)=>{ const R=A(); const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const obj={t:'txt',body:'vieille version',mid,n:name}; const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:'AES-GCM',iv},R.gkMsg,enc.encode(JSON.stringify(obj))); return R.channel.send({type:'broadcast',event:'msg',payload:{from:R.id,iv:b64(iv),ct:b64(ct),mid}}); }, lastSysAll:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; }, leave:()=>{ const R=A(); if(R) leaveRoom(R.code); }, mboxIdOf:(ck)=>mboxIdForSecret(ck), lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; } };
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
def unlock(p):
    p.fill("#pwInput","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
def bubbles(p): return p.evaluate("()=>[...document.querySelectorAll('.bubble.recv')].map(d=>({who:(d.querySelector('.who')||{}).textContent||'', cls:(d.querySelector('.who')||{}).className||'', txt:(d.querySelector('.txt')||{}).textContent||''}))")
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    GK=base64.b64encode(os.urandom(32)).decode(); RID="grp"+os.urandom(6).hex()
    def boot(name, errs):
        ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        p.evaluate("([rid,gk])=>localStorage.setItem('gz-groups',JSON.stringify([{rid,gk,name:'Les potes',ts:Date.now()}]))",[RID,GK])
        p.evaluate("()=>document.getElementById('sbLock').click()"); p.wait_for_timeout(300); unlock(p)
        p.evaluate("()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>x.querySelector('.cn').textContent.trim()==='Les potes').click(); }"); p.wait_for_timeout(800)
        return ctx,p
    errsA=[]; errsB=[]; errsC=[]
    ctxA,A=boot("oguz",errsA); ctxB,B=boot("florian",errsB); ctxC,C=boot("eve",errsC)
    r["group_open"]= all(wait_for(P,"()=>document.getElementById('bar').classList.contains('st-online') && window.__gz.room().group",10000) for P in (A,B,C))
    # ---- B writes: signed, A shows ✓ and records B's key ----
    B.fill("#msgInput","salut la bande"); B.press("#msgInput","Enter"); B.wait_for_timeout(1500)
    bb=bubbles(A)
    r["signed_badgeOk"]= any(x["txt"]=="salut la bande" and "vf-ok" in x["cls"] and x["who"].startswith("florian") and "✓" not in x["who"] for x in bb)   # v44: no tick when all is well
    idB=B.evaluate("()=>window.__gz.ident()"); r["ident_created"]= bool(idB and idB.get("pk") and idB.get("sk"))
    gA=A.evaluate("()=>window.__gz.groups()[0]"); r["memberKeyRecorded"]= bool(gA.get("mem")) and any(v.get("n")=="florian" for v in gA["mem"].values()) and idB["pk"] in gA["mem"]
    # ---- reactions and replies in the group: signed like messages, counted per member ----
    DBL="()=>{ const b=[...document.querySelectorAll('.log .bubble.recv')].filter(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='salut la bande').pop(); b.querySelector('.txt').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); }"
    A.evaluate(DBL); A.wait_for_timeout(200); A.click("#rxQuick button[data-e='👍']")
    C.wait_for_timeout(300); C.evaluate(DBL); C.wait_for_timeout(200); C.click("#rxQuick button[data-e='👍']")
    r["grp_react_count"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll('.log .bubble.sent')].filter(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='salut la bande').pop(); const c=b&&b.querySelector('.reacts .rx'); return !!c && c.textContent==='👍 2' && /oguz/.test(c.title) && /claire|camille|C|eve/i.test(c.title); }",8000)
    r["grp_react_titles"]= B.evaluate("()=>{ const b=[...document.querySelectorAll('.log .bubble.sent')].filter(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='salut la bande').pop(); const c=b&&b.querySelector('.reacts .rx'); return c?c.title:null; }")
    r["grp_react_seenByOther"]= wait_for(C,"()=>{ const b=[...document.querySelectorAll('.log .bubble.recv')].filter(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='salut la bande').pop(); const c=b&&b.querySelector('.reacts .rx'); return !!c && c.textContent==='👍 2' && c.classList.contains('mine'); }",8000)
    A.evaluate(DBL); A.wait_for_timeout(200); A.click("#rxReply"); A.wait_for_timeout(150)
    r["grp_reply_bar"]= A.evaluate("()=>document.getElementById('rbName').textContent")=="Replying to florian"
    A.fill("#msgInput","bien dit"); A.press("#msgInput","Enter")
    r["grp_reply_quote_B"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll('.log .bubble.recv')].pop(); const q=b&&b.querySelector('.quote'); return !!q && q.querySelector('.qn').textContent==='You' && q.querySelector('.qs').textContent==='salut la bande'; }",8000)
    r["grp_reply_quote_C"]= wait_for(C,"()=>{ const b=[...document.querySelectorAll('.log .bubble.recv')].pop(); const q=b&&b.querySelector('.quote'); return !!q && q.querySelector('.qn').textContent==='florian' && q.querySelector('.qs').textContent==='salut la bande'; }",8000)
    # ---- C signs with its own key but claims florian's name → "different key" ----
    C.evaluate("()=>window.__gz.forge('florian',false)"); C.wait_for_timeout(1500)
    bb=bubbles(A)
    r["spoof_flagged"]= any(x["txt"]=="je suis florian" and "vf-bad" in x["cls"] and "different key" in x["who"] for x in bb)
    r["spoof_sysline"]= wait_for(A,"()=>window.__gz.lastSysAll().some(x=>/signing with a different key/.test(x))",4000)
    # ---- a tampered message (valid key, altered body) → "bad signature" ----
    C.evaluate("()=>window.__gz.forge('eve',true)"); C.wait_for_timeout(1500)
    bb=bubbles(A)
    r["tamper_flagged"]= any(x["txt"]=="je suis eve!" and "vf-bad" in x["cls"] and "bad signature" in x["who"] for x in bb)
    r["tamper_sysline"]= wait_for(A,"()=>window.__gz.lastSysAll().some(x=>/broken signature/.test(x))",4000)
    # ---- C's honest message under its own name → ✓ ----
    C.fill("#msgInput","c'est bien moi"); C.press("#msgInput","Enter"); C.wait_for_timeout(1500)
    r["honest_ok"]= any(x["txt"]=="c'est bien moi" and "vf-ok" in x["cls"] and x["who"].startswith("eve") for x in bubbles(A))
    # ---- an older build (no signature): shown without a badge, no alarm ----
    C.evaluate("()=>window.__gz.unsigned('eve')"); C.wait_for_timeout(1500)
    r["unsigned_noBadge"]= any(x["txt"]=="vieille version" and "vf-" not in x["cls"] for x in bubbles(A))
    # ---- mailbox path: A away, B writes, A back → badge from the stored copy; history keeps the verdicts ----
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(600)
    B.fill("#msgInput","pendant ton absence"); B.press("#msgInput","Enter"); B.wait_for_timeout(1200)
    unlock(A); A.evaluate("()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>x.querySelector('.cn').textContent.trim()==='Les potes').click(); }"); A.wait_for_timeout(2500)
    bb=bubbles(A)
    r["mailbox_signedOk"]= wait_for(A,"()=>[...document.querySelectorAll('.bubble.recv')].some(d=>(d.querySelector('.txt')||{}).textContent==='pendant ton absence' && d.querySelector('.who.vf-ok'))",8000)
    r["history_keepsVerdicts"]= any(x["txt"]=="je suis florian" and "vf-bad" in x["cls"] for x in bb) and any(x["txt"]=="salut la bande" and "vf-ok" in x["cls"] for x in bb)
    # ---- identity persists across lock/unlock and rides the vault ----
    r["ident_persists"]= B.evaluate("()=>window.__gz.ident().pk")==idB["pk"]
    v=B.evaluate("()=>window.__vault.contacts"); r["ident_inVault"]= bool(v)   # encrypted blob exists (content is checked by the next device below)
    # a second device of florian restores the same identity from the vault
    ctxB2=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); B2=ctxB2.new_page(); B2.goto(f"http://127.0.0.1:{port}/?r=9"); B2.wait_for_timeout(300)
    B2.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); B2.fill("#userInput","flo2"); B2.fill("#pwInput","password123"); B2.fill("#pw2Input","password123"); B2.click("#joinBtn"); B2.wait_for_timeout(2500)
    # the vault merge converges every device on the oldest identity: an older remote replaces ours, a newer one does not
    newer=B2.evaluate("async()=>{ const kp=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},true,['sign','verify']); const b=x=>btoa(String.fromCharCode(...new Uint8Array(x))); return {pk:b(await crypto.subtle.exportKey('raw',kp.publicKey)), sk:b(await crypto.subtle.exportKey('pkcs8',kp.privateKey)), ts:Date.now()+100000}; }")
    older=dict(newer); older["ts"]=1
    B2.evaluate("()=>window.__gz.ensure()"); B2.wait_for_timeout(300); mine=B2.evaluate("()=>window.__gz.ident()")
    r["ident_newerRemoteIgnored"]= (not B2.evaluate("([id])=>window.__gz.adopt(id)",[newer])) and B2.evaluate("()=>window.__gz.ident().pk")==mine["pk"]
    r["ident_olderRemoteAdopted"]= B2.evaluate("([id])=>window.__gz.adopt(id)",[older]) and B2.evaluate("()=>window.__gz.ident().pk")==older["pk"]
    r["errors"]= (errsA+errsB+errsC)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
