# v38 "expected features": deleting a message (for me; for everyone — our own, quiet envelope, only the author's
# message obeys, out of order and re-delivery handled, kept across a lock), search (chats by name, messages from
# local history with accents folded, a tap opens the chat at the message; ⋮ → Search inside a chat with next /
# previous) and drawn icons instead of emojis in the interface.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site54"); site.mkdir(exist_ok=True)
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
  camSettings:()=>{ const tr=call&&call.local&&call.local.getVideoTracks()[0]; return tr?tr.getSettings():null; }, instState:()=>localStorage.getItem('gz-install'), rid:()=>rid(), sendEnv:(env)=>{ const R=A(); return deliverOut(R, env, rid(), null, Date.now(), true); }, inb:(env,mid,own)=>{ const R=A(); onInbound(R, env, '', Date.now(), mid, !!own, false); }, delm:()=>JSON.parse(JSON.stringify(_meta.delm||{})) };
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
import traceback
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
SKIP="()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"
VIS="(id)=>{ const e=document.getElementById(id); if(!e) return false; const r=e.getBoundingClientRect(); return !e.closest('[hidden]') && getComputedStyle(e).display!=='none' && r.width>0 && r.height>0; }"
SHOTS=_os.environ.get("GZ_SHOTS")
def shot(P, name):
    if SHOTS: P.screenshot(path=SHOTS+"/"+name+".png")
def vis(P, i): return P.evaluate(VIS, i)
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(250)
def has(t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
def mid_of(P, t, cls): return P.evaluate("([t,c])=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.'+c)].find(x=>{ const e=x.querySelector(':scope > .txt'); return e && e.textContent===t; }); return b?b.dataset.mid:null; }",[t,cls])
GONE="(m)=>{ const b=document.querySelector('"+OPEN+" .bubble[data-mid=\"'+m+'\"]'); return !!b && b.classList.contains('gone') ? b.textContent : null; }"
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch()
    def boot(name, errs, w=1000, h=820, scheme="dark"):
        c=b.new_context(viewport={"width":w,"height":h},locale="en-US",color_scheme=scheme); c.add_init_script(NOINST); p=c.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300); p.evaluate(SKIP)
        p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return c,p
    errs=[]
    ctxA,A=boot("oguz",errs)
    # icons in the interface, not emojis (A's settings, and the welcome screen of a fresh context)
    EMO="(sel)=>[...document.querySelectorAll(sel)].map(e=>e.textContent).join('|').match(/\\p{Extended_Pictographic}/u)"
    r["no_ui_emoji"]= A.evaluate(EMO, ".logo .lock, .promise .pi, #copyLink, #qrScan, #bioBtn, #updGo, #themeToggle, .rb-x, #recCancel") is None
    r["promise_icons"]= A.evaluate("()=>document.querySelectorAll('.promise .pi svg use').length")==3
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    errsB=[]; ctxB,B=boot("serap",errsB,w=390,scheme="light")
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(2000)
    r["paired"]= wait_for(A,PAIRED,15000) and wait_for(B,PAIRED,15000)
    A.wait_for_timeout(500)
    # ---- 1. delete for everyone ----
    send(A,"secret plan"); wait_for(B,has("secret plan"),8000)
    m1=mid_of(A,"secret plan","sent")
    A.locator(OPEN+" .bubble.sent").last.click(button="right"); A.wait_for_timeout(200)
    r["menu_has_delete"]= vis(A,"rxDel")
    A.click("#rxDel"); A.wait_for_timeout(200)
    r["dialog_both_choices"]= vis(A,"delAll") and vis(A,"delMe")
    A.click("#delAll"); A.wait_for_timeout(800)
    r["sender_placeholder"]= "You deleted this message" in (A.evaluate(GONE, m1) or "")
    r["receiver_placeholder"]= wait_for(B,"()=>("+GONE+")("+json.dumps(m1)+")",8000) and "This message was deleted" in (B.evaluate(GONE, m1) or "")
    r["receiver_text_gone"]= not B.evaluate(has("secret plan"))
    hb=B.evaluate("()=>window.__gz.histOf()")
    r["receiver_history_rewritten"]= (m1+"|recv|gone") in hb and not any(x.startswith(m1+"|") and not x.endswith("|gone") for x in hb)
    B.click("#backHome"); B.wait_for_timeout(400)
    r["preview_deleted"]= B.evaluate("()=>{ const c=document.querySelector('.ct .cm'); return c.textContent==='This message was deleted' && !!c.querySelector('use[href=\"#i-ban\"]'); }")
    B.click(".ct"); B.wait_for_timeout(600)
    # ---- 2. only the author's own message obeys: B can't delete A's message ----
    send(A,"keep me"); wait_for(B,has("keep me"),8000); m2=mid_of(A,"keep me","sent")
    B.evaluate("([m])=>window.__gz.sendEnv({t:'del', m:m, body:'x'})",[m2]); A.wait_for_timeout(1500)
    r["forged_delete_ignored"]= A.evaluate(has("keep me")) and not A.evaluate(GONE, m2)
    # ---- 3. delete for me: a received message, gone from this device only ----
    send(A,"bonjour"); wait_for(B,has("bonjour"),8000); m3=mid_of(B,"bonjour","recv")
    B.locator(OPEN+" .bubble.recv").last.click(button="right"); B.wait_for_timeout(200)
    B.click("#rxDel"); B.wait_for_timeout(200)
    r["received_only_for_me"]= not vis(B,"delAll") and vis(B,"delMe")
    B.click("#delMe"); B.wait_for_timeout(600)
    r["for_me_removed_here"]= not B.evaluate(has("bonjour")) and not any(x.startswith(m3+"|") for x in B.evaluate("()=>window.__gz.histOf()"))
    r["for_me_kept_there"]= A.evaluate(has("bonjour"))
    B.evaluate("([m])=>window.__gz.inb({body:'bonjour again'}, m, false)",[m3]); B.wait_for_timeout(300)
    r["for_me_not_redelivered"]= not B.evaluate(has("bonjour again"))
    # ---- 4. a deletion arriving before its message ----
    mf=B.evaluate("()=>window.__gz.rid()")
    B.evaluate("([m,d])=>window.__gz.inb({t:'del', m:m}, d, false)",[mf, B.evaluate("()=>window.__gz.rid()")]); B.wait_for_timeout(200)
    B.evaluate("([m])=>window.__gz.inb({body:'late text'}, m, false)",[mf]); B.wait_for_timeout(500)
    r["out_of_order_never_shown"]= not B.evaluate(has("late text")) and bool(B.evaluate(GONE, mf))
    # ---- 5. the placeholder survives a lock ----
    B.evaluate("()=>document.getElementById('sbLock').click()"); B.wait_for_timeout(800)
    B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(1500); B.click(".ct"); B.wait_for_timeout(1200)
    r["after_lock"]= bool(B.evaluate(GONE, m1)) and not B.evaluate(has("secret plan")) and not B.evaluate(has("bonjour")) and B.evaluate(has("keep me"))
    shot(B,"54_deleted_light")
    # ---- 6. search the chats list ----
    send(B,"rendez-vous au café"); send(B,"Şükrü geliyor"); wait_for(A,has("Şükrü geliyor"),8000); A.wait_for_timeout(300)
    A.fill("#listSearch","cafe"); A.wait_for_timeout(900)
    sr=A.evaluate("()=>({rows:[...document.querySelectorAll('#contactList .ct')].length, none:(document.querySelector('#contactList .sr-none')||{}).textContent||'', hits:[...document.querySelectorAll('#searchResults .sr')].map(b=>b.querySelector('.sr-s').textContent), mark:(document.querySelector('#searchResults .sr mark')||{}).textContent||''})")
    r["search_messages"]= sr["rows"]==0 and sr["none"]=="No chats found" and len(sr["hits"])==1 and "rendez-vous au café" in sr["hits"][0] and sr["mark"]=="café"
    r["search_v"]=sr
    shot(A,"54_search_dark")
    A.fill("#listSearch","sukru"); A.wait_for_timeout(900)
    r["search_folds_turkish"]= A.evaluate("()=>(document.querySelector('#searchResults .sr mark')||{}).textContent")=="Şükrü"
    A.fill("#listSearch","secret"); A.wait_for_timeout(900)
    r["search_skips_deleted"]= A.evaluate("()=>document.querySelectorAll('#searchResults .sr').length")==0 and "No messages found" in A.eval_on_selector("#searchResults","e=>e.textContent")
    A.fill("#listSearch","sera"); A.wait_for_timeout(900)
    r["search_chats_by_name"]= A.evaluate("()=>{ const c=[...document.querySelectorAll('#contactList .ct')]; return c.length===1 && c[0].querySelector('.cn mark') && c[0].querySelector('.cn mark').textContent==='sera'; }")
    A.fill("#listSearch","cafe"); A.wait_for_timeout(900); A.click("#searchResults .sr"); A.wait_for_timeout(900)
    r["hit_opens_chat_at_message"]= A.evaluate("()=>!document.getElementById('app').classList.contains('home')") and A.evaluate("()=>{ const b=[...document.querySelectorAll('"+OPEN+" .bubble.recv')].find(x=>x.textContent.includes('rendez-vous')); if(!b) return false; const r=b.getBoundingClientRect(), l=document.querySelector('"+OPEN+"').getBoundingClientRect(); return r.top>=l.top-2 && r.bottom<=l.bottom+2; }")
    A.click("#listSearchX"); A.wait_for_timeout(400)
    r["search_cleared"]= A.evaluate("()=>document.querySelectorAll('#contactList .ct').length")>=1 and not vis(A,"searchResults")
    # ---- 7. search inside a chat ----
    A.click(".ct"); A.wait_for_timeout(600)
    for x in ["un café","deux cafés","pas de thé"]: send(A,x)
    A.click("#menuBtn"); A.wait_for_timeout(150); A.click("#mi-find"); A.wait_for_timeout(200)
    r["find_bar"]= vis(A,"findInput")
    A.locator("#findInput").press_sequentially("cafe", delay=20); A.wait_for_timeout(500)
    f1=A.evaluate("()=>({n:document.getElementById('findCount').textContent, cur:(document.querySelector('.bubble.find-cur .txt')||{}).textContent||'', hl:!!(window.CSS && CSS.highlights && CSS.highlights.has('gz-find')), hits:document.querySelectorAll('.bubble.find-hit').length})")
    r["find_hits"]= f1["n"]=="3 of 3" and f1["cur"]=="deux cafés" and f1["hits"]==3 and f1["hl"]
    r["find_v"]=f1
    A.click("#findUp"); A.wait_for_timeout(200)
    r["find_prev"]= A.eval_on_selector("#findCount","e=>e.textContent")=="2 of 3" and A.evaluate("()=>(document.querySelector('.bubble.find-cur .txt')||{}).textContent")=="un café"
    shot(A,"54_find_dark")
    A.keyboard.press("Escape"); A.wait_for_timeout(200)
    r["find_closed_clean"]= not vis(A,"findInput") and A.evaluate("()=>!document.querySelector('.bubble.find-hit,.bubble.find-cur') && !(window.CSS && CSS.highlights && CSS.highlights.has('gz-find'))")
    r["errors"]= (errs+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
