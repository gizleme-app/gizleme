# v41 urgent fixes: a long history opens without a per-bubble scroll (one scroll at the end), a burst of photos
# stays in the chat it was started in even if you switch, a message written offline waits on the device and
# leaves on its own when the network is back (header says so), the delete-account dialog's Cancel works and
# Escape closes dialogs, a notification can only open the app on a chat (never an invite link) and an invite
# opened while already signed in asks first, no disappearing timer on a new account and the sender is told
# when a photo goes view-once, links in messages are clickable after confirming the site, the unlock label
# is translated on Android.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site57"); site.mkdir(exist_ok=True)
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
  outq:()=>JSON.parse(JSON.stringify(_meta.outq||{})), histOf:async()=>{ const R=A(); const l=await histLoad(histKeyOf(R)); return l.map(r=>r.mid+'|'+r.dir+'|'+(r.env&&r.env.t)); }, lastSys:()=>{ const R=A(); return R&&R.logEl?[...R.logEl.querySelectorAll('.sys')].map(e=>e.textContent):[]; },
  merge:(x)=>JSON.parse(JSON.stringify(mergeContacts(x))), soundMode:()=>soundMode(), unreadTotal:()=>unreadTotal(), checkUpdate:()=>checkUpdate(true), openCk:(ck)=>openContact(ck,'x'), inbox:()=>inboxPull(true),
  editsFrom:(g,past)=>[...editsFrom({group:g},past)].map(([k,v])=>[k,v.x]), onEdit:(env,own,ts)=>{ const R=A(); onEditEnv(R,env,'x',ts||Date.now(),rid(),!!own); },
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install'), rid:()=>rid(), sendEnv:(env)=>{ const R=A(); return deliverOut(R, env, rid(), null, Date.now(), true); }, inb:(env,mid,own)=>{ const R=A(); onInbound(R, env, '', Date.now(), mid, !!own, false); }, delm:()=>JSON.parse(JSON.stringify(_meta.delm||{})), localTracks:()=>call&&call.local?call.local.getTracks().map(t=>t.kind):[], qual:(s)=>qualSample(s), live:()=>!!(call&&call.t1), histSave:(rec)=>histSave(histKeyOf(A()),rec), bioLabel:()=>bioLabel(), expG:()=>expGlobal(), outqAll:()=>JSON.parse(JSON.stringify(_meta.outq||{})) };
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
import traceback, io
from PIL import Image as _Img
def png(color):
    b=io.BytesIO(); _Img.new("RGB",(320,200),color).save(b,"PNG"); return b.getvalue()
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
SKIP="()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"
VIS="(id)=>{ const e=document.getElementById(id); if(!e) return false; const r=e.getBoundingClientRect(); return !e.closest('[hidden]') && getComputedStyle(e).display!=='none' && r.width>0 && r.height>0; }"
def vis(P, i): return P.evaluate(VIS, i)
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
def has(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
def hist(P): return P.evaluate("()=>window.__gz.histOf()")
SW=pathlib.Path(SRC+"sw.js").read_text(); import re as _re
SAFE=_re.search(r"function safeTarget\(u\) \{.*?\n\}", SW, _re.S).group(0)
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
    cA,A=ctxp(w=1000,h=820); register(A,"oguz")
    r["new_account_no_timer"]= A.evaluate("()=>window.__gz.expG()")==0
    r["bio_label_fr"]= None   # filled below with an Android/French context
    # ---- service worker: what a notification may open ----
    sv=A.evaluate("(src)=>{ const self={location:{origin:location.origin}}; const f=new Function('self', src+'; return safeTarget;')(self); const o=location.origin; return [f(o+'/#i=abc'), f(o+'/#n=k1'), f('https://evil.example/'), f(o+'/privacy.html'), f(o+'/#g=xyz'), f(null)].map(u=>u.replace(o,'')); }", SAFE)
    r["sw_opens_only_app"]= sv==["/","/#n=k1","/","/","/","/"]
    r["sw_v"]=sv
    # ---- pair A with B and C ----
    l1=invite(A); cB,B=ctxp(scheme="light",dialogs=False); cB.add_init_script("window.__askPolicy=(t)=>/example\\.com/.test(t)?false:undefined;"); register(B,"serap"); open_link(B,l1)
    r["pairedB"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    l2=invite(A); cC,C=ctxp(); register(C,"can"); open_link(C,l2)
    r["pairedC"]= wait_for(A,PAIRED,15000) and wait_for(C,PAIRED,15000)
    A.wait_for_timeout(500)
    # ---- 1. a burst of photos stays in the chat it started in ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(300)
    A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()"); A.wait_for_timeout(700)
    A.set_input_files("#fileInput", files=[{"name":"a.png","mimeType":"image/png","buffer":png((200,40,40))},{"name":"b.png","mimeType":"image/png","buffer":png((40,200,40))},{"name":"c.png","mimeType":"image/png","buffer":png((40,40,200))}])
    A.wait_for_timeout(120); A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('can')).click()")   # switch mid-burst
    r["burst_all_to_first_chat"]= wait_for(B,"async()=>(await window.__gz.histOf()).filter(x=>x.endsWith('|recv|img')).length===3",30000) and C.wait_for_timeout(1500) is None and len([x for x in hist(C) if x.endswith("|recv|img")])==0
    r["burst_v"]=[len([x for x in hist(B) if x.endswith("|recv|img")]), len([x for x in hist(C) if x.endswith("|recv|img")])]
    # ---- 2. links in messages ----
    A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()"); A.wait_for_timeout(500)
    send(A,"regarde https://example.com/x, ok")
    r["link_rendered"]= wait_for(B,"()=>{ const a=document.querySelector('"+OPEN+" .bubble.recv .txt a.lnk'); return !!a && a.getAttribute('href')==='https://example.com/x' && a.textContent==='https://example.com/x' && a.closest('.txt').textContent==='regarde https://example.com/x, ok' && a.rel.includes('noopener'); }",8000)
    B.click(OPEN+" .bubble.recv .txt a.lnk"); B.wait_for_timeout(400)
    r["link_asks_first"]= any("example.com" in m for m in B.evaluate("()=>window.__asks||[]")) and len(cB.pages)==1 and B.url.startswith(f"http://127.0.0.1:{port}/")
    # ---- 3. offline: the message waits and goes by itself ----
    cB.set_offline(True); B.wait_for_timeout(300)
    r["offline_header"]= wait_for(B,"()=>document.getElementById('statusText').textContent==='you\\'re offline' && document.getElementById('bar').classList.contains('st-offline')",4000)
    send(B,"hors ligne"); B.wait_for_timeout(1200)
    st=B.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.sent')].pop(); return b && b.querySelector('.st').dataset.st; }")
    r["offline_pending_not_failed"]= st=="pending" and any(x.endswith("|sent|undefined") or x.endswith("|sent|txt") for x in hist(B)) and B.evaluate("()=>Object.values(window.__gz.outqAll()).flat().length")==1
    r["offline_toast"]= "offline" in B.eval_on_selector("#toast","e=>e.textContent")
    B.reload(); B.wait_for_timeout(600); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500); B.click(".ct"); B.wait_for_timeout(900)
    r["offline_survives_reload"]= B.evaluate(has("hors ligne")) and B.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.sent')].pop(); return b && b.querySelector('.st').dataset.st; }")=="pending"
    cB.set_offline(False); B.wait_for_timeout(500)
    r["offline_sent_when_back"]= wait_for(A,has("hors ligne"),20000) and wait_for(B,"()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.sent')].pop(); return b && b.querySelector('.st').dataset.st!=='pending'; }",10000) and B.evaluate("()=>Object.values(window.__gz.outqAll()).flat().length")==0
    r["online_header_back"]= wait_for(B,"()=>document.getElementById('statusText').textContent!=='you\\'re offline'",4000)
    # ---- 4. the delete-account dialog ----
    A.evaluate("()=>document.getElementById('sbSettings').click()"); A.evaluate("()=>document.querySelector('#settingsModal [data-go=account]').click()"); A.wait_for_timeout(200)
    A.evaluate("()=>document.getElementById('delAcctBtn').click()"); A.wait_for_timeout(200)
    r["del_dialog_open"]= A.evaluate("()=>document.getElementById('delModal').classList.contains('show')")
    A.click("#delCancel"); A.wait_for_timeout(200)
    r["del_cancel_works"]= not A.evaluate("()=>document.getElementById('delModal').classList.contains('show')")
    A.evaluate("()=>document.getElementById('sbSettings').click()"); A.evaluate("()=>document.querySelector('#settingsModal [data-go=account]').click()"); A.evaluate("()=>document.getElementById('delAcctBtn').click()"); A.wait_for_timeout(200)
    A.keyboard.press("Escape"); A.wait_for_timeout(200)
    r["del_escape_closes"]= not A.evaluate("()=>document.getElementById('delModal').classList.contains('show')")
    r["ids_unique"]= A.evaluate("()=>{ const ids=[...document.querySelectorAll('[id]')].map(e=>e.id); return ids.filter((x,i)=>ids.indexOf(x)!==i); }")==[]
    # ---- 5. an invite link opened while already signed in asks first ----
    l3=invite(A)
    cD,D=ctxp(dialogs=False); cD.add_init_script("window.__askPolicy=()=>false;"); register(D,"deniz")
    D.goto(f"http://127.0.0.1:{port}/?r=1"+l3[l3.index("#"):]); D.wait_for_timeout(400); D.fill("#pwInput","password123"); D.click("#joinBtn"); D.wait_for_timeout(1500)
    r["invite_asks_when_signed_in"]= any("invites you" in m for m in D.evaluate("()=>window.__asks||[]")) and D.evaluate("()=>window.__gz.contacts().length")==0
    cE,E=ctxp(dialogs=False)
    E.goto(f"http://127.0.0.1:{port}/?r=1"+l3[l3.index("#"):]); E.wait_for_timeout(400); E.evaluate(SKIP); E.fill("#userInput","ece"); E.fill("#pwInput","password123"); E.fill("#pw2Input","password123"); E.click("#joinBtn"); E.wait_for_timeout(2000)
    r["invite_no_question_after_signup"]= not any("invites you" in m for m in E.evaluate("()=>window.__asks||[]")) and E.evaluate("()=>window.__gz.contacts().length")==1
    # ---- 6. a photo under a timer tells the sender ----
    A.evaluate("()=>document.getElementById('backHome').click()"); A.wait_for_timeout(200); A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()"); A.wait_for_timeout(500)
    A.evaluate("()=>document.getElementById('expBtn').click()"); A.wait_for_timeout(200); A.evaluate("()=>document.querySelector('#expMenu button[data-v=\"300000\"]').click()"); A.wait_for_timeout(500)
    A.set_input_files("#fileInput", files=[{"name":"d.png","mimeType":"image/png","buffer":png((90,90,90))}]); A.wait_for_timeout(600)
    r["once_photo_told"]= "viewed once" in A.eval_on_selector("#toast","e=>e.textContent")
    # ---- 7. a long history opens fast (one scroll at the end) ----
    A.evaluate("()=>document.querySelector('#expMenu button[data-v=\"0\"]')") ; A.evaluate("()=>document.getElementById('expBtn').click()"); A.wait_for_timeout(150); A.evaluate("()=>document.querySelector('#expMenu button[data-v=\"0\"]').click()"); A.wait_for_timeout(400)
    A.evaluate("()=>{ const t0=Date.now()-3600e3; const ps=[]; for(let i=0;i<1500;i++) ps.push(window.__gz.histSave({dir:i%2?'sent':'recv', env:{body:'ligne '+i}, ts:t0+i*1000, mid:'h'+i+'x'+Math.random().toString(36).slice(2,8)})); return Promise.all(ps); }"); A.wait_for_timeout(1500)
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(800); A.fill("#pwInput","password123"); A.click("#joinBtn"); A.wait_for_timeout(1500)
    t0=time.time(); A.evaluate("()=>[...document.querySelectorAll('.ct')].find(e=>e.textContent.includes('serap')).click()")
    ok=wait_for(A,"()=>document.querySelectorAll('"+OPEN+" .bubble').length>=140",40000); dt=time.time()-t0   # the last 150 records (two of them timer lines, not bubbles)
    atb=wait_for(A,"()=>{ const l=document.querySelector('"+OPEN+"'); return (l.scrollHeight-l.scrollTop-l.clientHeight)<80 && !l._bulk; }",3000)
    r["long_history_opens"]= ok and dt<15 and atb
    # v43: the last 150 at once, the rest by pages from the top (the button, or scrolling up)
    pages=0
    while pages<15 and A.evaluate("()=>!!document.querySelector('"+OPEN+" .older')"):
        A.evaluate("()=>document.querySelector('"+OPEN+" .older').click()"); pages+=1; A.wait_for_timeout(150)
    n_all=A.evaluate("()=>document.querySelectorAll('"+OPEN+" .bubble').length")
    r["long_history_pages"]= pages>=9 and n_all>=1500 and not A.evaluate("()=>!!document.querySelector('"+OPEN+" .older')")
    r["long_history_v"]={"s":round(dt,1),"atBottom":atb,"pages":pages,"n":n_all}
    # ---- 8. the unlock label on Android, in French ----
    cF,F=ctxp(locale="fr-FR", ua="Mozilla/5.0 (Linux; Android 15; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36"); register(F,"fatma")
    r["bio_label_fr"]= F.evaluate("()=>window.__gz.bioLabel()")=="l'empreinte ou le visage"
    r["bio_label_v"]= F.evaluate("()=>[window.__gz.bioLabel(), document.documentElement.lang, navigator.userAgent.slice(0,40)]")
    r["errors"]= errs[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
