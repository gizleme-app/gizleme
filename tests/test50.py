# v32: the new composer (+ ↔ keyboard, camera and mic while empty, send once typed), the
# attachment panel (Photos · Camera · Location · Document · Poll · Event), documents (chunked, encrypted, opened
# as a download), polls and events with votes on both sides (persisting), and the .ics.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site50"); site.mkdir(exist_ok=True)
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
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install') };
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
import traceback, io, os as _os
from PIL import Image as _Img
def png(color):
    b=io.BytesIO(); _Img.new("RGB",(320,200),color).save(b,"PNG"); return b.getvalue()
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(300)
RECV="(t)=>[...document.querySelectorAll('.log:not([style*=\"display: none\"]) .bubble .txt')].some(e=>e.textContent===t)"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
OPEN=".log:not([style*=\"display: none\"])"
ORDER="()=>[...document.querySelector('.composer').children].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.id).join(',')"
POLL="()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.voteb')].filter(x=>x.querySelector('.poll')).pop(); if(!b) return null; return {q:b.querySelector('.pq').textContent, o:[...b.querySelectorAll('.po')].map(x=>[x.querySelector('.pt').textContent, +x.querySelector('.pn').textContent, x.classList.contains('on')]), f:b.querySelector('.pf').textContent}; }"
EVT="()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.voteb')].filter(x=>x.querySelector('.evt')).pop(); if(!b) return null; return {t:b.querySelector('.et').textContent, d:b.querySelector('.ed').textContent, l:(b.querySelector('.el')||{}).textContent||'', r:[...b.querySelectorAll('.po')].map(x=>[+x.querySelector('.pn').textContent, x.classList.contains('on')])}; }"
def tapOpt(P, kind, i):
    P.evaluate("([k,i])=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.voteb')].filter(x=>x.querySelector('.'+k)).pop(); b.querySelectorAll('.po')[i].click(); }",[kind,i]); P.wait_for_timeout(300)
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000):
        ctx=b.new_context(viewport={"width":w,"height":820},locale="en-US",accept_downloads=True); ctx.add_init_script("try{ localStorage.setItem('gz-exp-global','86400000'); }catch(e){}"); p=ctx.new_page()   # an account that chose 24 h (v41: off by default)
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    def open_link(P, link):
        P.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); P.wait_for_timeout(400); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(2000)
    errsA=[]; errsB=[]
    ctxA,A=boot("oguz",errsA)
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    ctxB,B=boot("serap",errsB,w=390)
    open_link(B, link)
    r["paired"]= wait_for(A,PAIRED,10000) and wait_for(B,PAIRED,10000)
    # ---- 1. the composer ----
    r["empty_order"]= B.evaluate(ORDER)=="plusBtn,msgField,attachBtn,micBtn"
    B.locator("#msgInput").press_sequentially("sa", delay=40)
    r["typed_order"]= B.evaluate(ORDER)=="plusBtn,msgField,sendBtn"
    B.press("#msgInput","Enter"); B.wait_for_timeout(400)
    r["after_send_mic_back"]= B.evaluate(ORDER)=="plusBtn,msgField,attachBtn,micBtn" and wait_for(A,"()=>("+RECV+")('sa')",8000)
    B.click("#plusBtn"); B.wait_for_timeout(300)
    r["plus_panel"]= B.is_visible("#plusPanel") and B.evaluate("()=>[...document.querySelectorAll('#plusPanel .tile')].map(x=>x.textContent.trim())")==["Photos","Camera","Location","Document","Poll","Event"]
    r["plus_becomes_keyboard"]= B.evaluate("()=>getComputedStyle(document.querySelector('#plusBtn .ic-kbd')).display!=='none' && getComputedStyle(document.querySelector('#plusBtn .ic-plus')).display==='none'")
    B.click("#plusBtn"); B.wait_for_timeout(300)
    r["keyboard_back"]= not B.is_visible("#plusPanel") and B.evaluate("()=>document.activeElement===document.getElementById('msgInput') && getComputedStyle(document.querySelector('#plusBtn .ic-plus')).display!=='none'")
    B.click("#plusBtn"); B.wait_for_timeout(200); B.click("#msgInput"); B.wait_for_timeout(200)
    r["tap_field_closes_panel"]= not B.is_visible("#plusPanel")
    # ---- 2. several photos at once ----
    A.set_input_files("#fileInput", files=[{"name":"a.png","mimeType":"image/png","buffer":png((200,40,40))},{"name":"b.png","mimeType":"image/png","buffer":png((40,200,40))}]); A.wait_for_timeout(2500)
    r["multi_photos"]= wait_for(B,"()=>document.querySelectorAll('"+OPEN+" .bubble.recv .tapview').length===2",10000)
    # ---- 4. a poll ----
    A.click("#plusBtn"); A.wait_for_timeout(200); A.click("#plusPanel [data-act=poll]"); A.wait_for_timeout(300)
    r["poll_modal"]= A.is_visible("#pollModal") and A.evaluate("()=>document.querySelectorAll('#pollOpts input').length")==2
    A.fill("#pollQ","Pizza or sushi?")
    ins=A.locator("#pollOpts input"); ins.nth(0).fill("Pizza"); ins.nth(1).press_sequentially("Sushi", delay=20)
    r["poll_grows"]= A.evaluate("()=>document.querySelectorAll('#pollOpts input').length")==3
    A.locator("#pollOpts input").nth(2).fill("Both")
    A.click("#pollSend"); A.wait_for_timeout(600)
    r["poll_sent"]= A.evaluate(POLL)=={"q":"Pizza or sushi?","o":[["Pizza",0,False],["Sushi",0,False],["Both",0,False]],"f":"No votes yet"}
    r["poll_received"]= wait_for(B,"()=>{ const p=("+POLL+")(); return p && p.q==='Pizza or sushi?' && p.o.length===3; }",8000)
    tapOpt(B,"poll",1)
    r["poll_vote_here"]= B.evaluate(POLL)["o"][1]==["Sushi",1,True]
    r["poll_vote_there"]= wait_for(A,"()=>{ const p=("+POLL+")(); return p.o[1][1]===1 && !p.o[1][2] && p.f==='1 vote'; }",8000)
    tapOpt(A,"poll",0)
    r["poll_two_votes"]= wait_for(B,"()=>{ const p=("+POLL+")(); return p.o[0][1]===1 && p.f==='2 votes'; }",8000)
    tapOpt(B,"poll",0)      # changes her mind: single choice, the newest vote counts
    r["poll_change_vote"]= wait_for(A,"()=>{ const p=("+POLL+")(); return p.o[0][1]===2 && p.o[1][1]===0 && p.o[0][2]; }",8000)
    r["poll_no_unread"]= A.evaluate("()=>window.__gz.unreadTotal()")==0
    B.evaluate("()=>document.getElementById('sbLock').click()"); B.wait_for_timeout(800)
    B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500); B.click(".ct"); B.wait_for_timeout(2000)
    p=B.evaluate(POLL); r["poll_after_relock"]= bool(p) and p["o"][0]==["Pizza",2,True] and p["o"][1]==["Sushi",0,False]
    r["poll_v"]=p
    # ---- 5. an event ----
    A.click("#plusBtn"); A.wait_for_timeout(200); A.click("#plusPanel [data-act=event]"); A.wait_for_timeout(300)
    r["evt_modal"]= A.is_visible("#evtModal") and A.evaluate("()=>!!document.getElementById('evtDate').value && !!document.getElementById('evtTime').value")
    A.fill("#evtTi","Dîner"); A.fill("#evtLoc","Chez nous"); A.click("#evtSend"); A.wait_for_timeout(600)
    e=A.evaluate(EVT); r["evt_sent"]= bool(e) and e["t"]=="Dîner" and e["l"]=="Chez nous" and ("–" in e["d"] or "→" in e["d"])   # "→" when the default hour runs past midnight; r["evt_v"]=e
    r["evt_received"]= wait_for(B,"()=>{ const e=("+EVT+")(); return e && e.t==='Dîner'; }",8000)
    tapOpt(B,"evt",0)
    r["evt_going_there"]= wait_for(A,"()=>{ const e=("+EVT+")(); return e.r[0][0]===1 && e.r[1][0]===0; }",8000)
    with B.expect_download(timeout=8000) as dl: B.locator(OPEN+" .bubble.voteb .ics").last.click()
    ics=open(dl.value.path(),encoding="utf-8").read()
    r["evt_ics"]= "SUMMARY:Dîner" in ics and "LOCATION:Chez nous" in ics and "DTSTART:" in ics and ics.startswith("BEGIN:VCALENDAR")
    r["preview_rich"]= wait_for(A,"()=>[...document.querySelectorAll('.ct .cm')].some(e=>e.textContent.includes('Dîner') && !!e.querySelector('use[href=\"#i-calendar\"]'))",5000)
    # ---- 6. documents (last: the big upload makes the test relay slow for a while) ----
    small=("Gizleme notes "*220).encode()
    A.set_input_files("#docInput", files=[{"name":"notes.txt","mimeType":"text/plain","buffer":small}]); A.wait_for_timeout(1500)
    r["doc_sent"]= A.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.sent.docb')].pop(); return !!b && b.querySelector('.doc-n').textContent==='notes.txt' && b.querySelector('.st').dataset.st!=='failed'; }")
    r["doc_received"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.recv.docb')].pop(); return !!b && b.querySelector('.doc-n').textContent==='notes.txt' && /kB/.test(b.querySelector('.cl-s').textContent) && b.querySelector('.doc-ico').textContent==='TXT'; }",10000)
    B.wait_for_timeout(800)
    with B.expect_download(timeout=10000) as dl: B.locator(OPEN+" .bubble.recv.docb .cl-btn").last.click()
    d=dl.value; r["doc_open_download"]= d.suggested_filename=="notes.txt" and open(d.path(),"rb").read()==small
    big=_os.urandom(3*1024*1024+123)
    A.set_input_files("#docInput", files=[{"name":"big.bin","mimeType":"application/octet-stream","buffer":big}]); A.wait_for_timeout(4000)
    r["doc_big_received"]= wait_for(B,"()=>[...document.querySelectorAll('"+OPEN+" .bubble.recv.docb .doc-n')].some(e=>e.textContent==='big.bin')",15000)
    with RLOCK: nblobs=len(BLOBS)
    r["doc_chunked"]= nblobs>=2+1+2   # 2 photos + small doc + big doc in 2 pieces
    B.wait_for_timeout(1500)
    with B.expect_download(timeout=15000) as dl: B.locator(OPEN+" .bubble.recv.docb .cl-btn").last.click()
    d=dl.value; r["doc_big_roundtrip"]= open(d.path(),"rb").read()==big
    A.set_input_files("#docInput", files=[{"name":"huge.bin","mimeType":"application/octet-stream","buffer":b"\0"*(10*1024*1024+1)}]); A.wait_for_timeout(500)
    r["doc_limit"]= "10 MB" in A.eval_on_selector("#toast","e=>e.textContent")
    r["errors"]= (errsA+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
