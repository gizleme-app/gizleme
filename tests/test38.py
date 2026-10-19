# Groups: the creator renews the key or removes a member; the removed member is locked out of the new room and mailbox.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site38"); site.mkdir(exist_ok=True)
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
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), save:(l)=>contactsSave(l), chainAt:async(kc,kce,ep)=>{ const r=await chainRootAt(kc,kce,ep); return r?b64(r):null; }, advance:()=>advanceChains(), epoch:()=>epochNow(), mbts:()=>JSON.parse(JSON.stringify(_meta.mbts||{})), merge:(r)=>mergeContacts(r), fetchAll:()=>inboxPull(true), ident:()=>identLoad(), glink:()=>groupInviteLink(A()), group:()=>groupsLoad().find(g=>g.rid===A().rid), rotate:(pk)=>rotateGroup(A(),pk||null), chan:()=>groupChan(A()), forgeGk2:async()=>{ const R=A(); const mid=rid(); R.seen.add(mid); const signed=await signGroupEnv(R,{t:'gk2',g:'zzzzzzzz',e:'AA',w:{},x:[]},mid); return broadcastGroup(R,signed,mid); }, adopt:(id)=>identAdopt(id), ensure:()=>identEnsure().then(k=>k.pk), forge:async(name,tamper)=>{ const R=A(); const env={t:'txt',body:'je suis '+name}; const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const obj=Object.assign({},env,{mid,n:name}); const id=await identEnsure(); obj.pk=id.pk; obj.sig=b64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'}, id.priv, gsigData(R.rid, obj))); if(tamper) obj.body+='!'; return broadcastGroup(R, obj, mid); }, unsigned:async(name)=>{ const R=A(); const mid=rid(); if(!R.seen) R.seen=new Set(); R.seen.add(mid); const obj={t:'txt',body:'vieille version',mid,n:name}; const iv=crypto.getRandomValues(new Uint8Array(12)); const ct=await crypto.subtle.encrypt({name:'AES-GCM',iv},R.gkMsg,enc.encode(JSON.stringify(obj))); return R.channel.send({type:'broadcast',event:'msg',payload:{from:R.id,iv:b64(iv),ct:b64(ct),mid}}); }, lastSysAll:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; }, leave:()=>{ const R=A(); if(R) leaveRoom(R.code); }, mboxIdOf:(ck)=>mboxIdForSecret(ck), lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; } };
'''
_app=_app[:_app.rstrip().rfind("})();")]+HOOK+'})();\n'
(site/"app.js").write_text(_app)
(site/"vendor").mkdir(exist_ok=True)
for f in ["vendor/qrcode-1.4.4.js"]: (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
for f in ["watermark.png","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg","logo-head.png","logo-word.png","logo-dot.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
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
def texts(p): return p.evaluate("()=>[...document.querySelectorAll('.bubble.recv .txt')].map(e=>e.textContent)")
def syss(p): return p.evaluate("()=>window.__gz.lastSysAll()")
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs):
        ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    def join_link(p, link):
        p.goto(f"http://127.0.0.1:{port}/?r={os.urandom(2).hex()}"+link[link.index("#"):]); p.wait_for_timeout(400); unlock(p); p.wait_for_timeout(1500)
    errsA=[]; errsB=[]; errsC=[]; errsD=[]; errsE=[]
    ctxA,A=boot("oguz",errsA)
    A.click("#sbNew"); A.wait_for_timeout(300); A.click(".nctab[data-nc='group']"); A.wait_for_timeout(200); A.fill("#gnameInput","Les potes"); A.click("#joinBtn"); A.wait_for_timeout(1500)
    link=A.evaluate("()=>window.__gz.glink()"); g0=A.evaluate("()=>window.__gz.group()"); idA=A.evaluate("()=>window.__gz.ident()")
    r["creator_isAdmin"]= bool(g0.get("adm")) and g0["adm"]==idA["pk"] and ("adm" in json.loads(base64.urlsafe_b64decode(link.split("#g=")[1]+"==")))
    ctxB,B=boot("florian",errsB); join_link(B, link)
    ctxC,C=boot("eve",errsC); join_link(C, link)
    r["joined"]= all(wait_for(P,"()=>document.getElementById('bar').classList.contains('st-online') && window.__gz.room().group",10000) for P in (A,B,C))
    r["adminFromLink"]= B.evaluate("()=>window.__gz.group().adm")==idA["pk"]
    # the silent hi: A knows B's and C's keys without anyone writing
    r["hi_registersKeys"]= wait_for(A,"()=>{ const g=window.__gz.group(); const m=g.mem||{}; return Object.values(m).filter(x=>x.ek).length>=2; }",8000)
    idB=B.evaluate("()=>window.__gz.ident()"); idC=C.evaluate("()=>window.__gz.ident()")
    # members dialog: creator sees Remove buttons, a member does not
    A.click("#peerMeta"); A.wait_for_timeout(250); A.click("#ciMembers"); A.wait_for_timeout(800)
    r["dialog_creator"]= A.evaluate("()=>document.getElementById('memModal').classList.contains('show') && document.querySelectorAll('#memList .mem-row').length===3 && document.querySelectorAll('#memList .mx').length===2 && !document.getElementById('memRenew').hidden")
    B.click("#peerMeta"); B.wait_for_timeout(250); B.click("#ciMembers"); B.wait_for_timeout(800)
    r["dialog_member"]= B.evaluate("()=>document.querySelectorAll('#memList .mem-row').length===3 && document.querySelectorAll('#memList .mx').length===0 && document.getElementById('memRenew').hidden")
    B.click("#memClose")
    # a member cannot rotate; a forged key change is ignored and called out
    r["member_cannotRotate"]= (B.evaluate("()=>window.__gz.rotate(null)")==False) and B.evaluate("()=>window.__gz.group().gk")==A.evaluate("()=>window.__gz.group().gk")
    B.evaluate("()=>window.__gz.forgeGk2()"); B.wait_for_timeout(1500)
    r["forgedGk2_ignored"]= wait_for(A,"()=>window.__gz.lastSysAll().some(x=>/isn't the group's creator/.test(x))",4000) and A.evaluate("()=>window.__gz.group().gk")==g0["gk"]
    # ---- A removes eve ----
    gkOld=g0["gk"]; chanOld=A.evaluate("()=>window.__gz.chan()")
    A.evaluate("([pk])=>{ const rows=[...document.querySelectorAll('#memList .mem-row')]; const row=rows.find(x=>/eve/.test(x.textContent)); row.querySelector('.mx').click(); }",[idC["pk"]]); A.wait_for_timeout(2500)
    gA=A.evaluate("()=>window.__gz.group()")
    r["A_rotated"]= gA["gk"]!=gkOld and gA.get("rot")==1 and gA.get("prevGk")==gkOld and idC["pk"] in (gA.get("gone") or []) and idC["pk"] not in (gA.get("mem") or {})
    r["A_newChannel"]= wait_for(A,"([c])=>window.__gz.chan()!==c && /-/.test(window.__gz.chan().replace('ratchet-',''))",[chanOld],5000) if False else wait_for(A,"()=>window.__gz.chan()!=='"+chanOld+"'",5000)
    r["B_gotNewKey"]= wait_for(B,"([gk])=>window.__gz.group().gk===gk",8000) if False else wait_for(B,"()=>window.__gz.group().gk==='"+gA["gk"]+"'",8000)
    r["B_sysline"]= wait_for(B,"()=>window.__gz.lastSysAll().some(x=>/removed eve/.test(x))",4000)
    r["C_removed"]= wait_for(C,"()=>window.__gz.group().left===1 && document.getElementById('msgInput').disabled",8000) and wait_for(C,"()=>window.__gz.lastSysAll().some(x=>/removed you from this group/.test(x))",3000)
    r["C_keyUnchanged"]= C.evaluate("()=>window.__gz.group().gk")==gkOld
    # messages after the rotation: B reads, C and an old-link joiner don't
    A.click("#memClose"); A.fill("#msgInput","après rotation"); A.press("#msgInput","Enter"); A.wait_for_timeout(1500)
    r["B_readsAfter"]= wait_for(B,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='après rotation')",8000)
    r["C_blind"]= "après rotation" not in texts(C)
    C.evaluate("()=>{ document.getElementById('msgInput').disabled=false; }"); C.fill("#msgInput","je suis encore là"); C.press("#msgInput","Enter"); C.wait_for_timeout(1500)
    A.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); B.evaluate("()=>document.dispatchEvent(new Event('visibilitychange'))"); A.wait_for_timeout(2000)
    r["C_cannotWrite"]= "je suis encore là" not in texts(A) and "je suis encore là" not in texts(B)
    ctxD,D=boot("dan",errsD); join_link(D, link)   # the OLD link
    A.fill("#msgInput","encore un"); A.press("#msgInput","Enter"); A.wait_for_timeout(1500)
    r["oldLink_blind"]= "encore un" not in texts(D) and wait_for(B,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='encore un')",6000)
    # a fresh link carries the new key; a newcomer reads
    link2=A.evaluate("()=>window.__gz.glink()")
    r["newLink_newKey"]= json.loads(base64.urlsafe_b64decode(link2.split("#g=")[1]+"=="))["gk"]==gA["gk"]
    ctxE,E=boot("emma",errsE); join_link(E, link2)
    r["E_joined"]= wait_for(E,"()=>document.getElementById('bar').classList.contains('st-online')",8000)
    A.fill("#msgInput","bienvenue emma"); A.press("#msgInput","Enter"); A.wait_for_timeout(1500)
    r["E_reads"]= wait_for(E,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='bienvenue emma')",8000)
    # ---- B offline during a renewal: picks the new key up from the mailbox on return ----
    B.evaluate("()=>document.getElementById('sbLock').click()"); B.wait_for_timeout(600)
    A.click("#peerMeta"); A.wait_for_timeout(250); A.click("#ciMembers"); A.wait_for_timeout(600); A.click("#memRenew"); A.wait_for_timeout(2500); A.click("#memClose")
    gA2=A.evaluate("()=>window.__gz.group()"); r["renew_rot2"]= gA2.get("rot")==2 and gA2["gk"]!=gA["gk"]
    A.fill("#msgInput","après renouvellement"); A.press("#msgInput","Enter"); A.wait_for_timeout(1000)
    unlock(B); B.evaluate("()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>x.querySelector('.cn').textContent.trim()==='Les potes').click(); }"); B.wait_for_timeout(3000)
    r["B_offlineRenew_catchesUp"]= wait_for(B,"()=>window.__gz.group().gk==='"+gA2["gk"]+"'",10000)
    A.fill("#msgInput","tu es revenu"); A.press("#msgInput","Enter"); A.wait_for_timeout(1500)
    r["B_readsAfterCatchUp"]= wait_for(B,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='tu es revenu')",8000)
    r["errors"]= (errsA+errsB+errsC+errsD+errsE)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
