// Gizleme — Copyright (C) 2026 Oğuz Seran — SPDX-License-Identifier: AGPL-3.0-only — see LICENSE
// iPhone display mode, read before the page is drawn. iOS 26 installed web apps (WebKit bug 301994) can paint a
// band over the bottom of the screen when the page is laid out under the status bar (viewport-fit=cover with a
// translucent status bar). "Compatibility" lays the page out inside the safe area instead, under an opaque status
// bar. It is the default in the app installed on an iPhone / iPad; Settings (iPhone only) or ?sbtest=1 / ?sbtest=0
// in the address choose explicitly ("compat" / "std", kept on the device).
(function(){ try{
  var m=/[?&]sbtest=(0|1)(?:&|$)/.exec(location.search);
  if(m) localStorage.setItem("gz-sbmode", m[1]==="1" ? "compat" : "std");
  var mode=localStorage.getItem("gz-sbmode");
  if(mode!=="compat" && mode!=="std"){
    var ua=navigator.userAgent, ios=/iphone|ipad|ipod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints>1);
    var inst=navigator.standalone===true || !!(window.matchMedia && matchMedia("(display-mode: standalone)").matches);
    mode= ios && inst ? "compat" : "std";
  }
  if(mode!=="compat") return;
  document.documentElement.classList.add("sb-compat");
  var v=document.querySelector('meta[name="viewport"]'); if(v) v.setAttribute("content","width=device-width, initial-scale=1, interactive-widget=resizes-content");
  var th=localStorage.getItem("vesper-theme"), dark= th ? th==="dark" : !!(window.matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  var s=document.querySelector('meta[name="apple-mobile-web-app-status-bar-style"]'); if(s) s.setAttribute("content", dark ? "black" : "default");
}catch(e){} })();
