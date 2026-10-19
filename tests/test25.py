# Photos: chunked base64 (no "Maximum call stack size exceeded"), re-encoding to JPEG within the relay cap.
from playwright.sync_api import sync_playwright
import pathlib, http.server, socketserver, threading, os

# Paths: the app sources are the repository root (one level up); scratch files go to a temp dir.
import os as _os, pathlib as _pl, tempfile as _tf
SRC=str(_pl.Path(__file__).resolve().parents[1])+"/"
TMP=_os.environ.get("GZ_TEST_TMP") or (_tf.gettempdir()+"/gizleme-tests/"); _pl.Path(TMP).mkdir(parents=True, exist_ok=True)

def _ensure_images():
    # a 14 MB photo, a 5.7 MB PNG and a small jpeg — generated here (noise compresses badly, which is the point)
    from PIL import Image
    import numpy as np
    d=_pl.Path(TMP+"img"); d.mkdir(parents=True, exist_ok=True)
    rng=np.random.default_rng(7)
    if not (d/"big.jpg").exists(): Image.fromarray(rng.integers(0,256,(3000,4000,3),dtype=np.uint8)).save(d/"big.jpg", quality=95)
    if not (d/"mid.png").exists(): Image.fromarray(rng.integers(0,256,(1200,1600,3),dtype=np.uint8)).save(d/"mid.png")
    if not (d/"small.jpg").exists(): Image.fromarray((np.indices((400,600))[1]//3).astype(np.uint8).repeat(3).reshape(400,600,3)).save(d/"small.jpg", quality=80)
_ensure_images()
SMALL_SIZE=_os.path.getsize(TMP+"img/small.jpg")
site=pathlib.Path(TMP+"site25"); site.mkdir(exist_ok=True)
html=pathlib.Path(SRC+"index.html").read_text()
MOCK=r'''
window.__pstate={}; window.__blobs=[]; window.__toasts=[];
window.supabase={createClient:()=>({
  channel:()=>{ const c={ _cbs:{}, on(type,opts,cb){ this._cbs[type+":"+(opts&&opts.event)]=cb; return this; }, subscribe(cb){ setTimeout(()=>cb&&cb("SUBSCRIBED"),5); return this; },
    track(p){ this._me=p; return Promise.resolve("ok"); }, untrack(){ return Promise.resolve("ok"); }, send(){ return Promise.resolve("ok"); }, presenceState(){ return window.__pstate; }, unsubscribe(){} };
    window.__chan=c; return c; },
  storage:{from:()=>({getPublicUrl:(p)=>({data:{publicUrl:"http://127.0.0.1/"+p}})})},
  functions:{invoke:async(n,o)=>{ const b=(o&&o.body)||{};
    if(n==="gizleme-auth"&&b.action==="register") return {data:{ok:true,token:"t",username:b.username,display:b.display}};
    if(n==="gizleme-vault") return {data:{ok:true,abk:null,contacts:null,cver:0}};
    if(n==="gizleme-mbox"&&b.action==="putblob"){ let raw=0; try{ raw=atob(b.data).length; }catch(e){ raw=-1; } window.__blobs.push(raw); if(raw>2000000) return {data:{error:"too_big"}}; return {data:{ok:true,path:"p"+window.__blobs.length}}; }
    if(n==="gizleme-mbox") return {data:{ok:true,items:[]}};
    return {data:{ok:true,available:true,publicKey:"x"}}; }}
})};
'''
(site/"mock.js").write_text(MOCK)
import re as _re; html,_nsub=_re.subn(r'<script src="/vendor/supabase-[0-9.]+\.js"></script>','<script src="/mock.js"></script>',html); assert _nsub==1, "supabase-js script tag not found in index.html"
(site/"index.html").write_text(html)
_app=pathlib.Path(SRC+"app.js").read_text()
_app=_app[:_app.rstrip().rfind("})();")]+'window.__gz={b64,unb64,downscale,uploadImage}; const _toast=toast; window.__toastLog=[];\n})();\n'
# capture toasts: wrap the toast element's text changes
(site/"app.js").write_text(_app)
for f in ["watermark.png","watermark-eyes.png","icon-192.png","sw.js","manifest.webmanifest","icon-512.png","icon-maskable-512.png","i18n.js","logo-head.png","logo-word.png","logo-dot.png"]:
    (site/f).write_bytes(pathlib.Path(SRC+""+f).read_bytes())
(site/"vendor").mkdir(exist_ok=True)
for _v in _os.listdir(SRC+"vendor"):
    if _v.endswith(".js") and not _v.startswith("supabase") and not _v[0].isdigit(): (site/"vendor"/_v).write_bytes(_pl.Path(SRC+"vendor/"+_v).read_bytes())
os.chdir(site)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self,*a): pass
srv=socketserver.ThreadingTCPServer(("127.0.0.1",0),Q); port=srv.server_address[1]
threading.Thread(target=srv.serve_forever,daemon=True).start()

r={}
with sync_playwright() as pw:
    b=pw.chromium.launch(); ctx=b.new_context(viewport={"width":1000,"height":820}, locale="en-US"); p=ctx.new_page()
    errs=[]; p.on("pageerror",lambda e:errs.append(str(e)))
    p.on("dialog",lambda d: d.accept())
    p.goto(f"http://127.0.0.1:{port}/"); p.wait_for_timeout(300)
    # 1) base64 of a 1.5 MB buffer: used to overflow the call stack
    r["b64_bigBuffer"]= p.evaluate("()=>{ const u=new Uint8Array(1500000); for(let i=0;i<u.length;i++) u[i]=(i*7919+i%13)&255; try{ const s=window.__gz.b64(u); const back=window.__gz.unb64(s); return back.length===u.length && back[777]===u[777] && back[1499999]===u[1499999]; }catch(e){ return String(e); } }")
    r["b64_small_sameAsBtoa"]= p.evaluate("()=>{ const u=new Uint8Array([0,1,2,250,255,65,66]); return window.__gz.b64(u)===btoa(String.fromCharCode(...u)); }")
    r["b64_empty"]= p.evaluate("()=>window.__gz.b64(new Uint8Array(0))==='' ")
    # 2) a 14 MB photo and a 5.7 MB PNG are re-encoded under the relay cap; a small jpeg passes untouched
    CK=p.evaluate("()=>btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32))))")
    p.evaluate("([ck])=>localStorage.setItem('gz-contacts',JSON.stringify([{name:'Oz77',ck:ck,ts:Date.now()}]))",[CK])
    p.evaluate("()=>new Promise(res=>{ const t0=Date.now(); (function tick(){ const j=document.getElementById('join'), m=j && j.dataset.mode; if(m || Date.now()-t0>10000){ if(m==='welcome') document.getElementById('joinBtn').click(); res(m||''); } else setTimeout(tick,40); })(); })"); p.fill("#userInput","fille"); p.fill("#pwInput","password123"); p.fill("#pw2Input","password123"); p.click("#joinBtn"); p.wait_for_timeout(1800)
    p.click(".ct"); p.wait_for_timeout(500)
    for name,f in [("big",TMP+"img/big.jpg"),("midpng",TMP+"img/mid.png"),("small",TMP+"img/small.jpg")]:
        before=p.evaluate("()=>window.__blobs.length")
        p.set_input_files("#fileInput", f); p.wait_for_timeout(4000)
        blobs=p.evaluate("()=>window.__blobs"); st=p.eval_on_selector_all(".bubble.sent, .msg.sent, .sent","els=>els.map(e=>e.getAttribute('data-st')||(e.querySelector('.st')&&e.querySelector('.st').textContent)||'')")
        r[name+"_uploaded"]= len(blobs)==before+1 and 0<blobs[-1]<=2000000
        r[name+"_rawBytes"]= blobs[-1] if len(blobs)>before else None
    r["small_reencoded"]= r["small_rawBytes"] is not None and abs(r["small_rawBytes"]-(SMALL_SIZE+16))>=64 and r["small_rawBytes"]<60000   # always re-encoded: EXIF/GPS never leaves the phone
    r["states"]= p.evaluate("()=>[...document.querySelectorAll('.st')].map(e=>e.className+':'+e.textContent).slice(-3)")
    r["toast"]= p.eval_on_selector("#toast","e=>e.textContent") if p.query_selector("#toast") else ""
    r["noStackOverflow"]= not any("call stack" in e for e in errs) and "call stack" not in (r["toast"] or "")
    r["errors"]= errs[:3]
    print("RESULTS")
    for k,v in r.items(): print(f"  {k}: {v}")
    b.close()
srv.shutdown()
