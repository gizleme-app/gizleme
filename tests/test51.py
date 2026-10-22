# v34: an installed iPhone app on iOS 26 is told a viewport of the screen minus the status bar and gets a system
# band over the bottom of the screen (WebKit 301994): the app never sizes itself under that band, stops keeping
# the home-indicator space above it, and gives the band the message bar's colour — only in that case; the text
# size setting scales the app, with fields kept at 16 px or more.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site51"); site.mkdir(exist_ok=True)
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
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install') };
'''
_app=_app[:_app.rstrip().rfind("})();")]+HOOK+'})();\n'
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark.webp","watermark-eyes.webp","logo-head.webp","logo-word.webp","boot.js","sb.js","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","hero.jpg","logo-head.png","logo-word.png","logo-dot.png","call-icon.png","call-badge.png","sb.js"]:
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
# a home-screen app on iOS 26: standalone, content under the status bar (62 px), screen 62 px taller than the viewport
IOS26="""Object.defineProperty(navigator,'standalone',{get:()=>true});
  const _sh=()=>window.innerHeight+62; Object.defineProperty(screen,'height',{get:_sh}); Object.defineProperty(screen,'width',{get:()=>window.innerWidth});
  document.addEventListener('DOMContentLoaded',()=>{ const st=document.createElement('style'); st.textContent='div[style*="safe-area-inset-top"]{padding-top:62px !important;padding-bottom:34px !important}'; document.head.appendChild(st); });"""
# the same, but the page stops above the home indicator (no bottom safe area): the extra height would be hidden, so no
NOBOTTOM=IOS26.replace("padding-bottom:34px","padding-bottom:0px")
SAFEONLY="""Object.defineProperty(navigator,'standalone',{get:()=>true});
  document.addEventListener('DOMContentLoaded',()=>{ const st=document.createElement('style'); st.textContent='div[style*="safe-area-inset-top"]{padding-top:62px !important}'; document.head.appendChild(st); });"""
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs, init=None, w=390, h=780):
        ctx=b.new_context(viewport={"width":w,"height":h},locale="en-US")
        if init: ctx.add_init_script(init)
        p=ctx.new_page(); p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    errs=[]
    ctxI,I=boot("ines",errs,init=IOS26)
    g=I.evaluate("()=>({app:document.getElementById('app').getBoundingClientRect().height, body:document.body.style.height, ih:innerHeight, gap:document.documentElement.classList.contains('ios-gap'), pad:getComputedStyle(document.querySelector('.composer')).paddingBottom, bg:getComputedStyle(document.documentElement).backgroundColor, surf:getComputedStyle(document.querySelector('.composer')).backgroundColor})")
    r["ios26_not_extended"]= g["app"]==g["ih"] and g["body"]==""     # the band at the bottom is drawn over the page: never size under it
    r["ios26_gap_mode"]= g["gap"] and g["pad"]=="10px" and g["bg"]==g["surf"]
    r["ios26_v"]=g
    ctxI.close()
    ctxX,X=boot("xena",errs,init=NOBOTTOM)
    g=X.evaluate("()=>({app:document.getElementById('app').getBoundingClientRect().height, ih:innerHeight})")
    r["no_bottom_inset_unchanged"]= g["app"]==g["ih"]
    ctxX.close()
    # the same standalone app with a correct viewport (screen = viewport): nothing changes
    ctxN,N=boot("nora",errs,init=SAFEONLY)
    g=N.evaluate("()=>({app:document.getElementById('app').getBoundingClientRect().height, body:document.body.style.height, ih:innerHeight, gap:document.documentElement.classList.contains('ios-gap')})")
    r["normal_unchanged"]= g["app"]==g["ih"] and g["body"]=="" and not g["gap"]
    ctxN.close()
    # a browser tab (not installed): never
    ctxB,B=boot("bora",errs)
    g=B.evaluate("()=>({app:document.getElementById('app').getBoundingClientRect().height, ih:innerHeight, gap:document.documentElement.classList.contains('ios-gap')})")
    r["browser_unchanged"]= g["app"]==g["ih"] and not g["gap"]
    # ---- text size ----
    B.evaluate("()=>document.getElementById('sbSettings').click()"); B.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); B.wait_for_timeout(300)
    r["text_default"]= B.evaluate("()=>document.getElementById('textSize').value")=="1" and B.evaluate("()=>getComputedStyle(document.documentElement).fontSize")=="16px"
    B.select_option("#textSize","1.25"); B.wait_for_timeout(200)
    r["text_larger"]= B.evaluate("()=>getComputedStyle(document.documentElement).fontSize")=="20px" and B.evaluate("()=>localStorage.getItem('gz-textsize')")=="1.25"
    B.reload(); B.wait_for_timeout(500)
    r["text_kept_after_reload"]= B.evaluate("()=>getComputedStyle(document.documentElement).fontSize")=="20px"
    B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500)
    B.evaluate("()=>{ localStorage.setItem('gz-textsize','0.9'); }"); B.reload(); B.wait_for_timeout(500); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500)
    r["small_fields_stay_16"]= B.evaluate("()=>getComputedStyle(document.documentElement).fontSize")=="14.4px" and B.evaluate("()=>parseFloat(getComputedStyle(document.getElementById('msgInput')).fontSize)")>=16
    B.evaluate("()=>{ localStorage.setItem('gz-textsize','7'); }"); B.reload(); B.wait_for_timeout(500)
    r["bad_value_ignored"]= B.evaluate("()=>getComputedStyle(document.documentElement).fontSize")=="16px"
    # ---- iPhone display: compatibility mode (sb.js) ----
    IPHONE="Mozilla/5.0 (iPhone; CPU iPhone OS 26_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.5 Mobile/15E148 Safari/604.1"
    cP=b.new_context(viewport={"width":390,"height":780},locale="en-US",user_agent=IPHONE,color_scheme="dark"); P=cP.new_page(); P.on("pageerror",lambda e:errs.append(str(e)))
    P.goto(f"http://127.0.0.1:{port}/?sbtest=1"); P.wait_for_timeout(500)
    m=P.evaluate("()=>({cls:document.documentElement.classList.contains('sb-compat'), vp:document.querySelector('meta[name=viewport]').content, sb:document.querySelector('meta[name=apple-mobile-web-app-status-bar-style]').content, ls:localStorage.getItem('gz-sbmode')})")
    r["sb_link_turns_on"]= m["cls"] and "viewport-fit" not in m["vp"] and m["sb"]=="black" and m["ls"]=="compat"
    P.goto(f"http://127.0.0.1:{port}/"); P.wait_for_timeout(400)
    r["sb_kept"]= P.evaluate("()=>document.documentElement.classList.contains('sb-compat')")
    P.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); P.fill("#userInput","ipek"); P.fill("#pwInput","password123"); P.fill("#pw2Input","password123"); P.click("#joinBtn"); P.wait_for_timeout(1500)
    P.evaluate("()=>document.querySelectorAll('.modal.show').forEach(x=>x.classList.remove('show'))")
    P.evaluate("()=>document.getElementById('sbSettings').click()"); P.evaluate("()=>document.querySelector('#settingsModal [data-go=chats]').click()"); P.wait_for_timeout(300)
    r["sb_setting_on_iphone"]= P.is_visible("#sbRow") and P.evaluate("()=>document.getElementById('sbSel').value")=="compat" and "iOS 26.5" in P.eval_on_selector("#sbInfo","e=>e.textContent")
    r["sb_info_v"]= P.eval_on_selector("#sbInfo","e=>e.textContent")
    P.select_option("#sbSel","std"); P.wait_for_timeout(2600)
    r["sb_setting_turns_off"]= P.evaluate("()=>!document.documentElement.classList.contains('sb-compat') && /viewport-fit=cover/.test(document.querySelector('meta[name=viewport]').content) && localStorage.getItem('gz-sbmode')==='std'")
    cP.close()
    # v36: on by default in the app installed on an iPhone / iPad; Safari tabs and other phones keep the standard layout
    def sbmode(ua, inst, pre=None, q=""):
        c=b.new_context(viewport={"width":390,"height":780},locale="en-US",user_agent=ua)
        if inst: c.add_init_script("Object.defineProperty(navigator,'standalone',{get:()=>true});")
        if pre: c.add_init_script("try{ if(!sessionStorage.getItem('x')){ sessionStorage.setItem('x','1'); localStorage.setItem('gz-sbmode','"+pre+"'); } }catch(e){}")
        pg=c.new_page(); pg.on("pageerror",lambda e:errs.append(str(e))); pg.goto(f"http://127.0.0.1:{port}/"+q); pg.wait_for_timeout(400)
        m=pg.evaluate("()=>({on:document.documentElement.classList.contains('sb-compat'), cover:/viewport-fit=cover/.test(document.querySelector('meta[name=viewport]').content), ls:localStorage.getItem('gz-sbmode')})")
        c.close(); return m
    ANDROID="Mozilla/5.0 (Linux; Android 15; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Mobile Safari/537.36"
    m1=sbmode(IPHONE,True); m2=sbmode(IPHONE,False); m3=sbmode(ANDROID,True); m4=sbmode(IPHONE,True,pre="std"); m5=sbmode(IPHONE,True,q="?sbtest=0")
    r["sb_default_installed_iphone"]= m1["on"] and not m1["cover"] and m1["ls"] is None
    r["sb_default_safari_iphone_off"]= not m2["on"] and m2["cover"]
    r["sb_default_android_off"]= not m3["on"] and m3["cover"]
    r["sb_explicit_standard_kept"]= not m4["on"] and m4["cover"] and m4["ls"]=="std"
    r["sb_link_off_stored"]= not m5["on"] and m5["ls"]=="std"
    r["sb_v"]=[m1,m2,m3,m4,m5]
    r["sb_row_hidden_elsewhere"]= not B.evaluate("()=>{ const e=document.getElementById('sbRow'); return !!e && !e.hidden; }")
    r["errors"]= errs[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
