// Gizleme — end-to-end encrypted messaging in the browser. https://gizleme.com
// Copyright (C) 2026 Oğuz Seran
// SPDX-License-Identifier: AGPL-3.0-only
// This program is free software: you can redistribute it and/or modify it under the terms of the GNU Affero
// General Public License as published by the Free Software Foundation, version 3. It is distributed WITHOUT
// ANY WARRANTY; see the LICENSE file for details.
// Show the reader's language first (the sections are :target-driven; this just picks the default anchor).
(function(){
  if(location.hash==="#fr"||location.hash==="#en"||location.hash==="#tr") return;
  var L=["en","fr","tr"], pick="en", saved=null; try{ saved=localStorage.getItem("gz-lang"); }catch(e){}
  if(L.indexOf(saved)>=0) pick=saved;
  else { var pref=(navigator.languages&&navigator.languages.length)?navigator.languages:[navigator.language||""];
    for(var i=0;i<pref.length;i++){ var b=String(pref[i]||"").slice(0,2).toLowerCase(); if(L.indexOf(b)>=0){ pick=b; break; } } }
  location.replace("#"+pick);
})();
