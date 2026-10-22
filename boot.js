// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// The first screen before app.js (v43). Which screen the device needs — unlock, log in, or the welcome — is known
// from what it already holds, so the card is shown at once, in the device's language, while the app itself
// (400 KB) still loads: the password can be typed meanwhile; the button wakes up with the app. The welcome and
// sign-up screens in French or Turkish wait for the app's full dictionary.
(function(){ try{
  var J=document.getElementById("join"); if(!J) return;
  var ls=window.localStorage, s=null; try{ s=JSON.parse(ls.getItem("gz-session")||"null"); }catch(e){}
  var pin=!!ls.getItem("gz-mkpin"), bio=!!ls.getItem("gz-mkbio");
  var mode=(s&&s.username) ? (pin?"unlock":"login") : pin ? "login" : (/[#&](i|g|room)=/.test(location.hash) ? "register" : "welcome");
  var lang=ls.getItem("gz-lang");
  if(lang!=="fr"&&lang!=="tr"&&lang!=="en"){ lang="en"; var pref=(navigator.languages&&navigator.languages.length)?navigator.languages:[navigator.language||""];
    for(var i=0;i<pref.length;i++){ var b=String(pref[i]||"").slice(0,2).toLowerCase(); if(b==="fr"||b==="tr"||b==="en"){ lang=b; break; } } }
  // the few words of these two screens (the same entries as i18n.js — a test keeps them equal)
  var D={fr:{"Gizleme is locked":"Gizleme est verrouillé","Welcome back, {name}.":"Content de te revoir, {name}.","Welcome back.":"Content de te revoir.","Unlock":"Déverrouiller",
      "Log out / switch account":"Se déconnecter / changer de compte","Forgot your password?":"Mot de passe oublié ?","Password":"Mot de passe","Username":"Identifiant","to log in":"pour te connecter",
      "Log in":"Se connecter","Log in to your Gizleme account from any device.":"Connecte-toi à ton compte Gizleme depuis n'importe quel appareil.","New here? Create an account":"Nouveau ici ? Créer un compte",
      "Unlock with {bio}":"Déverrouiller avec {bio}","fingerprint or face":"l'empreinte ou le visage"},
    tr:{"Gizleme is locked":"Gizleme kilitli","Welcome back, {name}.":"Tekrar hoş geldin, {name}.","Welcome back.":"Tekrar hoş geldin.","Unlock":"Kilidi aç",
      "Log out / switch account":"Çıkış yap / hesap değiştir","Forgot your password?":"Şifreni mi unuttun?","Password":"Şifre","Username":"Kullanıcı adı","to log in":"giriş için",
      "Log in":"Giriş yap","Log in to your Gizleme account from any device.":"Gizleme hesabına herhangi bir cihazdan giriş yap.","New here? Create an account":"Yeni misin? Hesap oluştur",
      "Unlock with {bio}":"{bio} ile kilidi aç","fingerprint or face":"parmak izi ya da yüz"}};
  var T=function(k){ return (D[lang]&&D[lang][k])||k; };
  var $=function(id){ return document.getElementById(id); };
  // the English stays on the element (data-en): the app's own translation pass starts from it, whatever is shown now
  var set=function(id,txt){ var e=$(id); if(!e) return; if(e.getAttribute("data-en")===null) e.setAttribute("data-en", e.textContent.trim()); e.textContent=txt; };
  var show=function(id,disp){ var e=$(id); if(e) e.style.display=disp; };
  if(mode==="register" || (mode==="welcome" && lang!=="en")) return;
  if(mode==="welcome"){   // English only: the texts are in the page already
    show("userField","none"); show("pwField","none"); show("pw2Field","none"); show("dispField","none"); show("ncTabs","none"); show("bioOptWrap","none");
    show("roomField","none"); show("backBtn","none"); show("iabNote","none"); show("lockHead","none"); show("forgotLink","none"); show("promises","grid"); show("switchLink","block");
    set("joinBtn","Create my account"); set("switchLink","I already have an account"); set("joinHint","");
  }
  if(mode==="unlock" || mode==="login"){
    show("userField", mode==="login"?"block":"none"); show("pwField","block"); show("pw2Field","none"); show("dispField","none"); show("ncTabs","none");
    show("bioOptWrap","none"); show("promises","none"); show("roomField","none"); show("backBtn","none"); show("iabNote","none");
    show("lockHead", mode==="unlock"?"block":"none"); show("forgotLink","block"); show("switchLink","block");
    set("pwLabel", T("Password")); set("forgotLink", T("Forgot your password?"));
    if(mode==="unlock"){
      set("lockHeadTitle", T("Gizleme is locked")); set("lockSub", (s&&s.display) ? T("Welcome back, {name}.").replace("{name}", s.display) : T("Welcome back."));
      set("joinBtn", T("Unlock")); set("switchLink", T("Log out / switch account")); set("joinHint", "");
      if(bio){ var bb=$("bioBtn"); if(bb){ bb.hidden=false; var apple=/iPhone|iPad|iPod|Macintosh/i.test(navigator.userAgent); set("bioLabel", T("Unlock with {bio}").replace("{bio}", apple?"Face ID / Touch ID":T("fingerprint or face"))); } }
    } else {
      set("userLabel", T("Username")); set("userSub", T("to log in")); set("joinBtn", T("Log in")); set("joinHint", T("Log in to your Gizleme account from any device.")); set("switchLink", T("New here? Create an account"));
      var u=$("userInput"); if(u && s && s.display && !u.value) u.value=s.display;
    }
  }
  var btn=$("joinBtn"); if(btn) btn.disabled=true;   // the app enables it once its handlers are in place
  document.documentElement.lang=lang;
  J.setAttribute("data-boot", mode);
}catch(e){} })();
