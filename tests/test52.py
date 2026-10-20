# v36 "readability and calm": darker accent fills in dark mode (white text ≥ 4.5:1), short system lines in the
# UI font on a soft pill, a quieter chat header (no brand, no shield, no logo), the message menu with emojis on
# top and labelled actions below, a big "Chats" title with a gear and no duplicate + on phones, a colour of its
# own for every contact (the same on both sides), grouped bubbles and a ↓ button with the count of new
# messages, and an incoming call screen with labelled buttons.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse, datetime, base64

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site52"); site.mkdir(exist_ok=True)
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
import traceback
OPEN=".log:not([style*=\"display: none\"])"
PAIRED="()=>{ const x=window.__gz.room(); return x && x.paired; }"
NOINST="try{ localStorage.setItem('gz-install', JSON.stringify({n:0,next:0,never:true})); }catch(e){}"
AUTO=r"""((ck)=>{ const hx={violet:'#7c3aed',indigo:'#4f46e5',blue:'#2563eb',sky:'#0369a1',teal:'#0f766e',green:'#15803d',lime:'#4d7c0f',amber:'#b45309',orange:'#c2410c',red:'#dc2626',pink:'#db2777',slate:'#475569'};
  const ks=Object.keys(hx); let h=0; for(const ch of ck) h=(h*31+ch.charCodeAt(0))>>>0; const c=hx[ks[h%ks.length]]; return 'rgb('+[1,3,5].map(i=>parseInt(c.slice(i,i+2),16)).join(', ')+')'; })"""
def send(P, txt): P.fill("#msgInput",txt); P.press("#msgInput","Enter"); P.wait_for_timeout(200)
def has(P, t): return "()=>[...document.querySelectorAll('"+OPEN+" .bubble .txt')].some(e=>e.textContent==="+json.dumps(t)+")"
ACTS="()=>[...document.querySelectorAll('#rxPick .rx-act')].filter(e=>!e.hidden && getComputedStyle(e).display!=='none').map(e=>e.textContent.trim())"
SHOTS=_os.environ.get("GZ_SHOTS")
def shot(P, name):
    if SHOTS: P.screenshot(path=SHOTS+"/"+name+".png")
try:
 with sync_playwright() as pw:
    b=pw.chromium.launch(args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream","--autoplay-policy=no-user-gesture-required"])
    def boot(name, errs, w=1000, h=820, scheme="dark"):
        ctx=b.new_context(viewport={"width":w,"height":h},locale="en-US",color_scheme=scheme); ctx.add_init_script(NOINST); p=ctx.new_page()
        p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
        p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
        p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
        return ctx,p
    errsA=[]; errsB=[]
    ctxA,A=boot("oguz",errsA)
    # ---- the list header ----
    hd=A.evaluate("()=>{ const s=document.querySelector('.sb-head > span:first-child'), cs=getComputedStyle(s); return {t:s.textContent.trim(), fs:cs.fontSize, tt:cs.textTransform, w:document.getElementById('sbSettings').getBoundingClientRect().width, gear:document.querySelector('#sbSettings use').getAttribute('href')}; }")
    r["list_title_big"]= hd["t"]=="Chats" and hd["fs"]=="18.4px" and hd["tt"]=="none" and hd["w"]>=34   # v40: beside a chat the title uses the title size and hd["gear"]=="#i-gear"
    r["list_title_v"]= hd
    r["desktop_keeps_plus"]= A.is_visible("#sbNew")
    A.click("#sbNew"); A.wait_for_timeout(300); link=A.eval_on_selector("#invLinkOut","e=>e.value"); A.click("#joinBtn"); A.wait_for_timeout(800)
    ctxB,B=boot("serap",errsB,w=390,scheme="light")
    B.goto(f"http://127.0.0.1:{port}/?r=1"+link[link.index("#"):]); B.wait_for_timeout(400); B.fill("#pwInput","password123"); B.click("#joinBtn"); B.wait_for_timeout(2000)
    r["paired"]= wait_for(A,PAIRED,10000) and wait_for(B,PAIRED,10000)
    A.wait_for_timeout(800)
    # ---- 1. contrast: the accent behind white text is darker in dark mode ----
    r["dark_accent_fill"]= A.evaluate("()=>getComputedStyle(document.documentElement).getPropertyValue('--accent-bg').trim()")=="#5b5bd6"
    r["light_accent_fill"]= B.evaluate("()=>getComputedStyle(document.documentElement).getPropertyValue('--accent-bg').trim()")=="#4338ca"
    send(A,"un"); send(A,"deux")
    r["dark_sent_bubble"]= A.evaluate("()=>{ const l=[...document.querySelectorAll('"+OPEN+" .bubble.sent')]; return getComputedStyle(l[l.length-1]).backgroundColor; }")=="rgb(91, 91, 214)"
    # ---- 2. system lines: short, UI font, soft pill ----
    sa=A.evaluate("()=>window.__gz.lastSys()"); sb=B.evaluate("()=>window.__gz.lastSys()")
    lock=[x for x in sa+sb if "encrypted" in x or "Invite link" in x]
    r["sys_short"]= any("opened your link · end-to-end encrypted" in x for x in sa) and any(x.startswith("End-to-end encrypted with") for x in sb) and all(len(x)<=64 and "—" not in x for x in lock)
    r["sys_lock_icon"]= B.evaluate("()=>[...document.querySelectorAll('.sys')].some(e=>e.textContent.startsWith('End-to-end') && e.querySelector('use[href=\"#i-lock\"]'))")   # v38: a drawn lock, not 🔒
    r["sys_v"]= lock
    st=A.evaluate("()=>{ const e=document.querySelector('"+OPEN+" .sys'), cs=getComputedStyle(e); return {f:cs.fontFamily, bg:cs.backgroundColor, rad:cs.borderTopLeftRadius}; }")
    r["sys_pill_ui_font"]= "IBM Plex Sans" in st["f"] and "mono" not in st["f"].lower() and st["bg"] not in ("rgba(0, 0, 0, 0)","transparent") and st["rad"]=="14px"
    # ---- 3. the chat header: name, status, no brand / shield / logo ----
    h3=A.evaluate("()=>({brand:getComputedStyle(document.getElementById('chatBrand')).display, shield:getComputedStyle(document.getElementById('verifyBtn')).display, logo:!!document.querySelector('.peer-logo'), sf:getComputedStyle(document.querySelector('.bar .status')).fontFamily, verifyInMenu:!!document.getElementById('ciVerify')})")
    r["header_calm"]= h3["brand"]=="none" and h3["shield"]=="none" and not h3["logo"] and "IBM Plex Sans" in h3["sf"] and h3["verifyInMenu"]
    # ---- 11a. bubbles from the same side are grouped ----
    r["grouped"]= A.evaluate("()=>{ const l=[...document.querySelectorAll('"+OPEN+" .bubble.sent')]; const cs=getComputedStyle(l[l.length-1]); return cs.marginTop==='-5px' && cs.borderTopRightRadius==='6px'; }")
    # ---- 8. the message menu: emojis on top, labelled actions below ----
    A.locator(OPEN+" .bubble.sent").last.click(button="right"); A.wait_for_timeout(250)
    g=A.evaluate("()=>{ const p=document.getElementById('rxPick'), top=p.querySelector('.rx-top').getBoundingClientRect(), acts=p.querySelector('.rx-acts').getBoundingClientRect(), r=p.getBoundingClientRect(); return {vis:!p.hidden, below:acts.top>=top.bottom-1, inView:r.top>=0 && r.bottom<=innerHeight && r.left>=0 && r.right<=innerWidth, emojis:p.querySelectorAll('#rxQuick button').length}; }")
    r["menu_layout"]= g["vis"] and g["below"] and g["inView"] and g["emojis"]>=5
    r["menu_own_text"]= A.evaluate(ACTS)==["Reply","Edit","Copy","Delete"]
    shot(A,"52_menu_dark")
    A.click("#rxCopy"); A.wait_for_timeout(200)
    r["menu_closes"]= A.evaluate("()=>document.getElementById('rxPick').hidden")
    send(B,"salut")
    wait_for(A,has(A,"salut"),8000)
    A.locator(OPEN+" .bubble.recv").last.click(button="right"); A.wait_for_timeout(250)
    r["menu_their_text"]= A.evaluate(ACTS)==["Reply","Copy","Delete"]
    A.keyboard.press("Escape"); A.mouse.click(5,400); A.wait_for_timeout(200)
    # ---- 10. a colour of its own for every contact, the same on both sides ----
    ca=A.evaluate("()=>{ const c=window.__gz.contacts().find(x=>!x.into); return {ck:c.ck, cl:c.cl||null, list:getComputedStyle(document.querySelector('.ct .ava')).backgroundColor, head:getComputedStyle(document.getElementById('peerAvatar')).backgroundColor, want:"+AUTO+"(c.ck)}; }")
    cb=B.evaluate("()=>{ const c=window.__gz.contacts().find(x=>!x.into); return {ck:c.ck, head:getComputedStyle(document.getElementById('peerAvatar')).backgroundColor}; }")
    r["auto_colour"]= ca["cl"] is None and ca["list"]==ca["want"] and ca["head"]==ca["want"]
    r["auto_colour_both_sides"]= ca["ck"]==cb["ck"] and cb["head"]==ca["want"]
    r["auto_colour_v"]= [ca["want"], ca["list"], ca["head"], cb["head"]]
    # ---- 11b. scrolled up: ↓ with the number of new messages ----
    for i in range(28): A.fill("#msgInput","ligne %d"%i); A.press("#msgInput","Enter"); A.wait_for_timeout(60)
    wait_for(B,has(B,"ligne 27"),15000); B.wait_for_timeout(300)
    r["jump_hidden_at_bottom"]= not B.is_visible("#jumpBtn")
    B.evaluate("()=>{ const l=document.querySelector('"+OPEN+"'); l.scrollTop=0; l.dispatchEvent(new Event('scroll')); }"); B.wait_for_timeout(300)
    r["jump_shows_when_up"]= B.is_visible("#jumpBtn") and not B.is_visible("#jumpCount")
    send(A,"nouveau 1"); send(A,"nouveau 2")
    r["jump_counts_new"]= wait_for(B,"()=>!document.getElementById('jumpCount').hidden && document.getElementById('jumpCount').textContent==='2'",8000)
    r["jump_stays_up"]= B.evaluate("()=>{ const l=document.querySelector('"+OPEN+"'); return l.scrollTop<200; }")
    shot(B,"52_jump_light")
    B.click("#jumpBtn"); B.wait_for_timeout(700)
    r["jump_goes_down"]= B.evaluate("()=>{ const l=document.querySelector('"+OPEN+"'); return (l.scrollHeight-l.scrollTop-l.clientHeight)<60; }") and not B.is_visible("#jumpBtn")
    # ---- 9. on a phone the round + is the only "new chat" button ----
    B.click("#backHome"); B.wait_for_timeout(400)
    r["phone_one_plus"]= not B.is_visible("#sbNew") and B.is_visible("#fabNew")
    shot(B,"52_list_light")
    B.click(".ct"); B.wait_for_timeout(800)
    # ---- 14. the incoming call: labelled buttons, status, the caller's avatar breathing ----
    B.click("#callBtn"); B.wait_for_timeout(300)
    r["outgoing_ringing"]= B.evaluate("()=>document.getElementById('callUI').classList.contains('ringing')")
    r["incoming_shown"]= wait_for(A,"()=>!document.getElementById('callIncoming').hidden",8000)
    A.wait_for_timeout(300)
    ic=A.evaluate("()=>({st:document.getElementById('callStatus').textContent, labels:[...document.querySelectorAll('#callIncoming .cact:not([hidden]) span')].map(e=>e.textContent), ring:document.getElementById('callUI').classList.contains('ringing'), anim:(()=>{ const p=document.querySelector('#callUI .call-stage .pav'); return p?getComputedStyle(p).animationName:null; })()})")
    r["incoming_labels"]= ic["labels"]==["Decline","Accept"] and A.is_visible("#callIncoming .cact span")
    r["incoming_status"]= ic["st"]=="Encrypted voice call"
    r["incoming_pulse"]= ic["ring"] and ic["anim"]=="pavPulse"
    r["incoming_v"]= ic
    shot(A,"52_incoming_dark")
    A.evaluate("()=>document.getElementById('callAccept').click()")
    r["live_stops_pulse"]= wait_for(A,"()=>{ const c=window.__gz.callState(); return c && c.live; }",12000) and wait_for(A,"()=>!document.getElementById('callUI').classList.contains('ringing')",3000)
    A.evaluate("()=>document.getElementById('callEnd').click()"); A.wait_for_timeout(800)
    r["after_call_clean"]= A.evaluate("()=>!document.getElementById('callUI').classList.contains('ringing')") and B.evaluate("()=>!document.getElementById('callUI').classList.contains('ringing')")
    r["errors"]= (errsA+errsB)[:4]
    b.close()
except Exception as e:
    r["exception"]=traceback.format_exc()[-1500:]
print("RESULTS")
for k,v in r.items(): print(" ",k+":",v)
