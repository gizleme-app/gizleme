# Rooms rejoin by themselves after failed or timed-out joins (cold relay), with backoff.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site34"); site.mkdir(exist_ok=True)
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
    subscribe(cb){ if(window.__failJoins>0){ window.__failJoins--; this.state="errored"; setTimeout(()=>cb&&cb("CHANNEL_ERROR"),10); return this; } this.state="joined"; this._poll=setInterval(()=>this._tick(),110); setTimeout(()=>cb&&cb("SUBSCRIBED"),10); return this; },
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
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), histOf:async()=>{ const R=A(); const l=await histLoad(histKeyOf(R)); return l.map(r=>r.mid+'|'+r.dir+'|'+(r.env&&r.env.t)); }, lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; } };
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
# ---- codec unit test straight from the app source (round trip + rejection of garbage) ----
import subprocess, re
_src=pathlib.Path(SRC+"app.js").read_text()
seg=_src[_src.index("const VOICE_RATE="):_src.index("let rec=null;")]
NODE=seg+r"""
const N=16000; const pcm=new Int16Array(N); for(let i=0;i<N;i++) pcm[i]=Math.round(9000*Math.sin(2*Math.PI*220*i/16000)+4000*Math.sin(2*Math.PI*1300*i/16000));
const packed=voicePack(pcm); const u=voiceUnpack(packed); let num=0, den=0; for(let i=0;i<N;i++){ const o=pcm[i]/32768, d=o-u.samples[i]; num+=o*o; den+=d*d; }
const snr=10*Math.log10(num/den);
const bad=voiceUnpack(new Uint8Array([1,2,3,4,5,6,7,8,9,10,11,12])); const trunc=voiceUnpack(packed.subarray(0,40));
const ds=voiceDownsample([new Float32Array(48000).fill(0.5)],48000);
console.log(JSON.stringify({snr:Math.round(snr), size:packed.length, bad:bad===null, trunc:trunc===null, ds:ds.length, dsv:ds[100]}));
"""
out=subprocess.run(["node","-e",NODE],capture_output=True,text=True)
try: codec=json.loads(out.stdout.strip())
except Exception: codec={"err":(out.stdout+out.stderr)[:300]}

r={}
import traceback
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); A=ctx.new_page(); errs=[]
    A.on("pageerror",lambda e:errs.append(str(e))); A.on("dialog",lambda d:d.accept())
    A.goto(f"http://127.0.0.1:{port}/"); A.wait_for_timeout(300)
    A.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); A.fill("#userInput","oguz"); A.fill("#pwInput","password123"); A.fill("#pw2Input","password123"); A.click("#joinBtn"); A.wait_for_timeout(1500)
    # the first two joins fail (cold relay): the app must not stay on "reconnecting…"
    A.evaluate("()=>{ window.__failJoins=2; }")
    A.click("#sbNew"); A.wait_for_timeout(300); A.click("#joinBtn"); A.wait_for_timeout(600)
    r["showsReconnecting"]= A.evaluate("()=>document.getElementById('bar').classList.contains('st-busy') && /reconnecting/.test(document.getElementById('statusText')?document.getElementById('statusText').textContent:document.querySelector('.status').textContent)")
    t0=time.time()
    ok=wait_for(A,"()=>{ const s=(document.getElementById('statusText')||document.querySelector('.status')).textContent; return !/reconnecting/.test(s) && /link not opened yet/i.test(s); }",15000)
    r["recoversByItself"]= ok; r["recoverSeconds"]= round(time.time()-t0,1)
    r["backoffOrder"]= r["recoverSeconds"]>=8 and r["recoverSeconds"]<=13   # 3 s + 6 s
    r["joinsLeft"]= A.evaluate("()=>window.__failJoins")==0
    # a message still goes out afterwards (channel usable)
    A.fill("#msgInput","après reconnexion"); A.press("#msgInput","Enter"); A.wait_for_timeout(800)
    r["sendsAfter"]= A.evaluate("()=>!!document.querySelector('.bubble.sent .txt')")
    r["errors"]= errs[:3]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1200:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
