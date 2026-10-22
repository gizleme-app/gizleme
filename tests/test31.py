# Calls: real WebRTC between separate browser contexts. The test server emulates the Realtime relay
# (presence + broadcast per room) so two or three Gizleme instances pair for real and signal through
# their encrypted channel; media devices are Chromium's fake camera/mic.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os, json, time, urllib.parse

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)
site=pathlib.Path(TMP+"site31"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__notify=[]; window.__MBOX={}; window.__vault={abk:null,contacts:null,cver:0};
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
    if(n==="gizleme-mbox"&&b.action==="get") return {data:{ok:true,items:[]}};
    if(n==="gizleme-mbox") return {data:{ok:true}};
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
  setIce:(l)=>{ _iceCache={servers:l,exp:Date.now()+1e9}; }, room:()=>{ const R=A(); return R?{paired:R.paired,group:R.group,gcall:R.gcall?R.gcall.cid:null}:null; } };
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

RELAY={}; RLOCK=threading.Lock()
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

r={}
import traceback
try:
 with sync_playwright() as pw:
     b=pw.chromium.launch(args=["--use-fake-device-for-media-stream","--use-fake-ui-for-media-stream","--autoplay-policy=no-user-gesture-required"])
     CK=None; errsA=[]; errsB=[]
     def boot(name, display, contactName, ck, errs):
         ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US", permissions=["camera","microphone"]); p=ctx.new_page()
         p.on("pageerror",lambda e:errs.append(str(e))); p.on("dialog",lambda d:d.accept())
         p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
         p.evaluate("([ck,nm])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:nm,ck:ck,ts:Date.now()}]))",[ck,contactName])
         p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput",name); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1500)
         p.evaluate("()=>window.__gz.setIce([])")
         return ctx,p
     ctxA,A=boot("oguz","oguz","Florian",None if False else (CK:=__import__("base64").b64encode(os.urandom(32)).decode()),errsA)
     ctxB,B=boot("florian","florian","Oguz",CK,errsB)
     A.click(".ct"); B.click(".ct")
     r["pair_A"]= wait_for(A,"()=>document.getElementById('bar').classList.contains('st-online')",12000)
     r["pair_B"]= wait_for(B,"()=>document.getElementById('bar').classList.contains('st-online')",12000)
     r["callButtons"]= A.is_visible("#callBtn") and A.is_visible("#videoBtn") and B.is_visible("#callBtn")
     # ---- audio call A → B, B accepts ----
     A.click("#callBtn")
     r["A_callUI"]= wait_for(A,"()=>!document.getElementById('callUI').hidden",5000)
     r["B_incoming"]= wait_for(B,"()=>!document.getElementById('callUI').hidden && !document.getElementById('callIncoming').hidden",8000)
     r["B_incomingText"]= B.eval_on_selector("#callStatus","e=>e.textContent")
     r["B_callerName"]= B.eval_on_selector("#callName","e=>e.textContent")
     r["A_ringing"]= wait_for(A,"()=>document.getElementById('callStatus').textContent==='Ringing…'",5000)
     B.evaluate("()=>document.getElementById('callAccept').click()")
     r["connected"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s&&s.live&&s.peers.some(p=>p.connected); }",15000) and wait_for(B,"()=>{ const s=window.__gz.callState(); return s&&s.live&&s.peers.some(p=>p.connected); }",8000)
     r["timerShown"]= wait_for(A,"()=>/^\\d\\d:\\d\\d$/.test(document.getElementById('callStatus').textContent)",4000)
     r["B_hasRemoteAudio"]= wait_for(B,"()=>{ const s=window.__gz.callState(); return s&&s.peers[0]&&s.peers[0].tracks.includes('audio'); }",5000)
     r["audioOnly_noVideoTracks"]= A.evaluate("()=>{ const s=window.__gz.callState(); return s.localVideo===0 && !s.video; }")
     A.click("#callMute"); A.wait_for_timeout(200)
     r["mute"]= A.evaluate("()=>window.__gz.callState().localAudioOn===false") and A.eval_on_selector("#callMute","e=>e.classList.contains('on')")
     A.wait_for_timeout(1200)
     A.click("#callEnd")
     r["hangup_bothClosed"]= wait_for(A,"()=>document.getElementById('callUI').hidden && !window.__gz.callState()",4000) and wait_for(B,"()=>document.getElementById('callUI').hidden && !window.__gz.callState()",5000)
     r["hangup_lines"]= [A.eval_on_selector_all(".log .sys","els=>els.map(e=>e.textContent).filter(x=>x.includes('📞')).pop()"), B.eval_on_selector_all(".log .sys","els=>els.map(e=>e.textContent).filter(x=>x.includes('📞')).pop()")]
     # ---- video call B → A ----
     B.click("#videoBtn")
     r["A_incomingVideo"]= wait_for(A,"()=>!document.getElementById('callIncoming').hidden && document.getElementById('callStatus').textContent==='Encrypted video call'",8000)
     A.evaluate("()=>document.getElementById('callAccept').click()")
     r["video_connected"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s&&s.live&&s.video&&s.peers.some(p=>p.connected); }",15000)
     r["video_remoteTrack"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s.peers[0]&&s.peers[0].tracks.includes('video') && !document.querySelector('#callStage .peer').classList.contains('audio'); }",8000)
     r["video_localPreview"]= A.evaluate("()=>!document.getElementById('callLocal').hidden && !document.getElementById('callCam').hidden")
     A.click("#callCam"); A.wait_for_timeout(200)
     r["video_camOff"]= A.evaluate("()=>document.getElementById('callLocal').hidden && document.getElementById('callCam').classList.contains('on')")
     B.click("#callEnd")
     r["video_closed"]= wait_for(A,"()=>document.getElementById('callUI').hidden",5000) and wait_for(B,"()=>document.getElementById('callUI').hidden",3000)
     r["video_line"]= A.eval_on_selector_all(".log .sys","els=>els.map(e=>e.textContent).filter(x=>x.includes('Video call')).pop()")
     # ---- declined ----
     A.click("#callBtn"); wait_for(B,"()=>!document.getElementById('callIncoming').hidden",8000); B.click("#callDecline")
     r["declined"]= wait_for(A,"()=>document.getElementById('callUI').hidden",5000) and "declined" in (A.eval_on_selector_all(".log .sys","els=>els.map(e=>e.textContent).pop()") or "")
     # ---- the contact is offline: push "X is calling you", invitation sent when they show up ----
     ctxB.close(); A.wait_for_timeout(1500)
     r["B_gone_offline"]= wait_for(A,"()=>document.getElementById('bar').classList.contains('st-offline')",8000)
     A.evaluate("()=>{ window.__notify.length=0; }")
     A.click("#callBtn")
     r["offline_reaching"]= wait_for(A,"()=>document.getElementById('callStatus').textContent==='Reaching them…'",3000)
     r["offline_pushCall"]= wait_for(A,"()=>window.__notify.some(n=>n.kind==='call' && !n.body && !/Oguz/i.test(JSON.stringify(n)))",4000)   # no name on the wire: the receiving device adds it
     errsB2=[]; ctxB2,B2=boot("florian2","florian2","Oguz",CK,errsB2); B2.click(".ct")
     r["offline_thenRings"]= wait_for(B2,"()=>!document.getElementById('callIncoming').hidden",15000)
     B2.evaluate("()=>document.getElementById('callAccept').click()")
     r["offline_thenConnected"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s&&s.live; }",15000)
     A.click("#callEnd"); wait_for(B2,"()=>document.getElementById('callUI').hidden",5000)
     # ---- group call: A starts, B2 and C join (mesh), C leaves, A leaves ----
     GK=__import__("base64").b64encode(os.urandom(32)).decode(); RID="grp"+os.urandom(6).hex()
     errsC=[]; ctxC,C=boot("claire","claire","Oguz",CK,errsC)
     for P in (A,B2,C):
         P.evaluate("([rid,gk])=>localStorage.setItem('gz-groups',JSON.stringify([{rid,gk,name:'Les potes',ts:Date.now()}]))",[RID,GK])
         P.evaluate("()=>document.getElementById('sbLock').click()"); P.wait_for_timeout(300); P.fill("#pwInput","password123"); P.click("#joinBtn"); P.wait_for_timeout(1200)
         P.evaluate("()=>window.__gz.setIce([])")
         P.evaluate("()=>{ const rows=[...document.querySelectorAll('.ct')]; rows.find(x=>x.querySelector('.cn').textContent.trim()==='Les potes').click(); }"); P.wait_for_timeout(600)
     r["group_open"]= all(wait_for(P,"()=>document.getElementById('bar').classList.contains('st-online') && window.__gz.room().group",10000) for P in (A,B2,C))
     A.click("#callBtn")
     r["group_A_waiting"]= wait_for(A,"()=>document.getElementById('callStatus').textContent==='Waiting for others…'",5000)
     r["group_B_banner"]= wait_for(B2,"()=>!document.getElementById('callBanner').hidden && document.getElementById('callBannerText').textContent.includes('oguz')",8000)
     B2.click("#callBannerJoin")
     r["group_AB_connected"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s&&s.peers.length===1&&s.peers[0].connected; }",15000) and wait_for(B2,"()=>{ const s=window.__gz.callState(); return s&&s.peers.length===1&&s.peers[0].connected; }",8000)
     r["group_C_banner"]= wait_for(C,"()=>!document.getElementById('callBanner').hidden",8000)
     C.click("#callBannerJoin")
     r["group_mesh3"]= all(wait_for(P,"()=>{ const s=window.__gz.callState(); return s&&s.peers.length===2&&s.peers.every(p=>p.connected); }",20000) for P in (A,B2,C))
     r["group_status"]= wait_for(A,"()=>/3 in the call/.test(document.getElementById('callStatus').textContent)",4000)
     C.click("#callEnd")
     r["group_C_left"]= wait_for(A,"()=>{ const s=window.__gz.callState(); return s&&s.peers.length===1; }",8000) and wait_for(B2,"()=>{ const s=window.__gz.callState(); return s&&s.peers.length===1; }",8000) and C.evaluate("()=>document.getElementById('callUI').hidden")
     r["group_C_bannerBack"]= wait_for(C,"()=>!document.getElementById('callBanner').hidden",8000)
     A.click("#callEnd")
     r["group_B_alone"]= wait_for(B2,"()=>{ const s=window.__gz.callState(); return s&&s.peers.length===0 && document.getElementById('callStatus').textContent==='Waiting for others…'; }",8000)
     B2.click("#callEnd")
     r["group_over_bannerGone"]= wait_for(C,"()=>document.getElementById('callBanner').hidden",8000) and wait_for(A,"()=>document.getElementById('callBanner').hidden",8000)
     r["errors"]= (errsA+errsB+errsB2+errsC)[:4]
     b.close()
except Exception:
    traceback.print_exc()
finally:
    print('RESULTS')
    for k,v in r.items(): print(f'  {k}: {v}')
srv.shutdown()
