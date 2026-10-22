# Reactions and replies: double tap (touch) / double click opens the emoji picker; a reaction travels encrypted,
# toggles and replaces, never becomes a bubble or an unread; swipe right (or ↩) quotes a message; a tap on the
# quote jumps to the original; everything survives a lock/unlock.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site42"); site.mkdir(exist_ok=True)
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
r={}
import traceback
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs, touch=False):
        ctx=b.new_context(viewport={"width":390 if touch else 1000,"height":820}, locale="en-US", has_touch=touch, is_mobile=touch); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    errsA=[]; errsB=[]
    ctxA,A=boot("oguz",errsA)
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    ctxB,B=boot("florian",errsB,touch=True)
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(2500)
    r["paired"]= wait_for(A,"()=>{ const x=window.__gz.room(); return x && x.paired; }",10000) and wait_for(B,"()=>{ const x=window.__gz.room(); return x && x.paired; }",10000)
    A.fill("#msgInput","salut toi"); A.press("#msgInput","Enter")
    r["B_got"]= wait_for(B,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='salut toi')",8000)
    nA0=A.evaluate("()=>document.querySelectorAll('.log .bubble').length")
    # ---- double tap (touch) on the received message opens the picker; the second tap is swallowed (no zoom)
    r["dtap_prevented"]= B.evaluate(DTAP,[RECV,0])=="prevented"
    r["picker_open"]= wait_for(B,"()=>!document.getElementById('rxPick').hidden",2000)
    r["picker_items"]= B.evaluate("()=>[document.querySelectorAll('#rxQuick button').length, !!document.getElementById('rxMore'), !!document.getElementById('rxReply')]")==[6,True,True]
    r["picker_inViewport"]= B.evaluate("()=>{ const r=document.getElementById('rxPick').getBoundingClientRect(); return r.left>=0 && r.right<=innerWidth && r.top>=0 && r.bottom<=innerHeight; }")
    B.click("#rxQuick button[data-e='❤️']"); B.wait_for_timeout(300)
    r["picker_closed"]= B.evaluate("()=>document.getElementById('rxPick').hidden")
    r["B_chip"]= chips(B,RECV)==["❤️*"]
    r["A_chip"]= wait_for(A,"()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); const c=b&&b.querySelector('.reacts .rx'); return !!c && c.textContent==='❤️' && !c.classList.contains('mine'); }",8000)
    r["A_noNewBubble"]= A.evaluate("()=>document.querySelectorAll('.log .bubble').length")==nA0
    # ---- tapping my own chip takes it back, on both sides
    B.click(RECV+" .reacts .rx"); B.wait_for_timeout(300)
    r["B_removed"]= chips(B,RECV)==[]
    r["A_removed"]= wait_for(A,"()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); return !b.querySelector('.reacts .rx'); }",8000)
    # ---- double click (mouse) on the computer side; ＋ shows the full grid; a second choice replaces the first
    A.fill("#msgInput","et toi ?"); A.press("#msgInput","Enter"); wait_for(B,"()=>[...document.querySelectorAll('.bubble.recv .txt')].some(e=>e.textContent==='et toi ?')",8000)
    B.evaluate("()=>{}")
    A.dblclick(SENT+":last-of-type .txt") if False else A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); b.querySelector('.txt').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); }")
    r["A_picker_dblclick"]= wait_for(A,"()=>!document.getElementById('rxPick').hidden",2000)
    A.click("#rxMore"); A.wait_for_timeout(150)
    r["grid_shown"]= A.evaluate("()=>!document.getElementById('rxGrid').hidden && document.querySelectorAll('#rxGrid button').length")==32
    A.click("#rxGrid button[data-e='🔥']"); A.wait_for_timeout(300)
    A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); b.querySelector('.txt').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); }"); A.wait_for_timeout(700)
    r["picker_marksMine"]= A.evaluate("()=>{ const g=document.getElementById('rxGrid'); return !![...document.querySelectorAll('#rxPick button.on')].find(x=>x.dataset.e==='🔥'); }")
    A.click("#rxQuick button[data-e='😂']"); A.wait_for_timeout(300)
    r["A_replaced"]= chips(A,SENT)==["😂*"]
    r["B_sees_replaced"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll('.bubble.recv')].pop(); const cs=[...b.querySelectorAll('.reacts .rx')].map(c=>c.textContent); return cs.length===1 && cs[0]==='😂'; }",8000)
    # two people, same emoji → "😂 2"
    B.evaluate(DTAP,[RECV,1]); wait_for(B,"()=>!document.getElementById('rxPick').hidden",2000); B.click("#rxQuick button[data-e='😂']"); B.wait_for_timeout(300)
    r["count_two"]= chips(B,RECV)==["😂 2*"] and wait_for(A,"()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); const c=b.querySelector('.reacts .rx'); return !!c && c.textContent==='😂 2' && c.classList.contains('mine'); }",8000)
    # ---- outside tap and Escape close the picker
    B.evaluate(DTAP,[RECV,0]); wait_for(B,"()=>!document.getElementById('rxPick').hidden",2000)
    B.evaluate("()=>document.getElementById('bar').dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}))"); B.wait_for_timeout(100)
    r["outside_closes"]= B.evaluate("()=>document.getElementById('rxPick').hidden")
    # ---- swipe right: a short or vertical drag does nothing; a real swipe opens the reply bar
    B.evaluate(TOUCH,[RECV,0,[[10,0],[25,2],[35,2]]]); B.wait_for_timeout(300)
    r["short_swipe_nothing"]= B.evaluate("()=>document.getElementById('replyBar').hidden")
    B.evaluate(TOUCH,[RECV,0,[[2,20],[4,60],[10,120]]]); B.wait_for_timeout(300)
    r["vertical_nothing"]= B.evaluate("()=>document.getElementById('replyBar').hidden")
    B.evaluate(TOUCH,[RECV,0,[[20,1],[45,2],[70,3],[95,3]]]); B.wait_for_timeout(350)
    r["swipe_opens_reply"]= B.evaluate("()=>!document.getElementById('replyBar').hidden")
    r["reply_bar_text"]= B.evaluate("()=>[document.getElementById('rbName').textContent, document.getElementById('rbText').textContent]")==["Replying to oguz","salut toi"]
    r["bubble_back_in_place"]= B.evaluate("()=>{ const b=document.querySelectorAll(\"" + RECV + "\")[0]; return !b.style.transform && !b.classList.contains('swiping'); }")
    B.fill("#msgInput","oui ça va"); B.press("#msgInput","Enter"); B.wait_for_timeout(500)
    r["reply_bar_cleared"]= B.evaluate("()=>document.getElementById('replyBar').hidden")
    r["B_quote"]= B.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); const q=b.querySelector('.quote'); return q?[q.querySelector('.qn').textContent,q.querySelector('.qs').textContent, b.querySelector('.txt').textContent]:null; }")==["oguz","salut toi","oui ça va"]
    r["A_quote"]= wait_for(A,"()=>{ const b=[...document.querySelectorAll('.bubble.recv')].pop(); const q=b&&b.querySelector('.quote'); return !!q && q.querySelector('.qn').textContent==='You' && q.querySelector('.qs').textContent==='salut toi' && b.querySelector('.txt').textContent==='oui ça va'; }",8000)
    # a tap on the quote jumps to the original and highlights it
    A.click(".log .bubble.recv .quote"); A.wait_for_timeout(150)
    r["jump_flash"]= A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.sent')].find(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='salut toi'); return !!b && b.classList.contains('flash'); }")
    # ---- ↩ in the picker (computer): reply to their message
    A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.recv')].pop(); b.querySelector('.txt').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); }"); A.wait_for_timeout(200)
    A.click("#rxReply"); A.wait_for_timeout(200)
    r["reply_button"]= A.evaluate("()=>!document.getElementById('replyBar').hidden && document.getElementById('rbName').textContent==='Replying to florian' && document.getElementById('rbText').textContent==='oui ça va'")
    A.click("#rbCancel"); A.wait_for_timeout(100)
    r["cancel_reply"]= A.evaluate("()=>document.getElementById('replyBar').hidden")
    A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.sent')].pop(); b.querySelector('.txt').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); }"); A.wait_for_timeout(200)
    A.click("#rxReply"); A.wait_for_timeout(150)
    r["reply_own"]= A.evaluate("()=>document.getElementById('rbName').textContent")=="Replying to your message"
    A.fill("#msgInput","je me cite"); A.press("#msgInput","Enter")
    r["B_sees_selfquote"]= wait_for(B,"()=>{ const b=[...document.querySelectorAll('.bubble.recv')].pop(); const q=b&&b.querySelector('.quote'); return !!q && q.querySelector('.qn').textContent==='oguz' && q.querySelector('.qs').textContent==='et toi ?'; }",8000)
    # ---- reactions never count as unread, never become a chat-list preview
    B.click("#backHome"); B.wait_for_timeout(300)
    prevB=B.eval_on_selector(".ct .cm","e=>e.textContent")
    A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.recv')].pop(); b.querySelector('.txt').dispatchEvent(new MouseEvent('dblclick',{bubbles:true})); }"); A.wait_for_timeout(200); A.click("#rxQuick button[data-e='👍']")
    B.wait_for_timeout(2500)
    pv=B.eval_on_selector(".ct .cm","e=>e.textContent"); r["preview_not_reaction"]= "👍" not in pv and "je me cite" in pv; r["preview_v"]=pv
    r["no_unread_for_reaction"]= B.evaluate("()=>!document.querySelector('.ct .ubadge, .ct .badge')")
    # control: a real message on the closed chat does show the badge (so the check above means something)
    A.fill("#msgInput","un vrai message"); A.press("#msgInput","Enter")
    r["control_unread_message"]= wait_for(B,"()=>!!document.querySelector('.ct .ubadge')",8000)
    # ---- after lock / unlock (history): chips and quotes are back
    A.evaluate("()=>document.getElementById('sbLock').click()"); A.wait_for_timeout(400); A.fill("#pwInput","password123"); A.click("#joinBtn"); A.wait_for_timeout(1500); A.click(".ct"); A.wait_for_timeout(1000)
    r["hist_chips"]= A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.sent')].find(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='et toi ?'); return b?[...b.querySelectorAll('.reacts .rx')].map(c=>c.textContent+(c.classList.contains('mine')?'*':'')):null; }")==["😂 2*"]
    r["hist_quote"]= A.evaluate("()=>{ const b=[...document.querySelectorAll('.bubble.recv')].find(x=>x.querySelector('.txt') && x.querySelector('.txt').textContent==='oui ça va'); const q=b&&b.querySelector('.quote'); return q?q.querySelector('.qn').textContent+'|'+q.querySelector('.qs').textContent:null; }")=="You|salut toi"
    r["hist_noReactionBubbles"]= A.evaluate("()=>![...document.querySelectorAll('.log .bubble .txt')].some(e=>/^(❤️|😂|🔥|👍)$/.test(e.textContent))")
    r["errors"]= (errsA+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
