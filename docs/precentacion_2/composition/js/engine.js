/* Yumi · motor de la presentación.
   - Un mundo continuo (#world) con todas las escenas colocadas sobre un río.
   - Una gota (#token) viaja de parada en parada y la cámara la sigue.
   - El avance es por búsqueda (seek) del timeline "root": el controlador de HyperFrames mueve el tiempo,
     aquí se traduce a escena + nivel (fragmento) + movimiento de cámara. */
(function () {
  var W = 1920, H = 1080;
  var CFG = window.YUMI_CFG;           // escenas: {id, start, dur, cx, cy, levels, foci?, branch?}
  var HTML = window.YUMI_SCENE_HTML, FX = window.YUMI_SCENE_FX;
  var qs = new URLSearchParams(location.search);
  var EMBEDDED = window.parent !== window;
  var STATIC = qs.has("static") || !EMBEDDED;
  if (STATIC) document.documentElement.classList.add("static");

  var world = document.getElementById("world");
  var token = document.getElementById("token");
  var bgW = document.getElementById("bg-waves");
  var bgD = document.getElementById("bg-dots");
  var riverSvg = document.getElementById("river");

  /* ---------- fondo ---------- */
  bgW.style.backgroundImage = "linear-gradient(rgba(255,255,255,.035) 1.5px, transparent 1.5px), linear-gradient(90deg, rgba(255,255,255,.035) 1.5px, transparent 1.5px)";
  bgW.style.backgroundSize = "160px 160px";
  bgD.style.backgroundImage = "radial-gradient(circle, rgba(255,255,255,.16) 2px, transparent 3px)";
  bgD.style.backgroundSize = "320px 320px";

  /* ---------- escenas ---------- */
  var frames = {};
  CFG.forEach(function (S) {
    var f = document.getElementById("scene-" + S.id);
    frames[S.id] = f;
    f.style.left = S.cx - 960 + "px";
    f.style.top = S.cy - 540 + "px";
    f.classList.add("t-" + (S.theme || "dark"));
    if (S.glow) f.classList.add("glowb");
    f.innerHTML = HTML[S.id] || "";
    Array.prototype.forEach.call(f.querySelectorAll("*"), function (el) {
      el.__orig = el.getAttribute("style");
    });
    if (FX[S.id] && FX[S.id].wide) f.classList.add("wide");
    S.foci = S.foci || [[S.cx, S.cy]];
  });

  /* ---------- focos y río (solo la línea principal) ---------- */
  var MAIN = CFG.filter(function (s) { return !s.branch; });
  var FOCI = [];
  MAIN.forEach(function (S) {
    S.base = FOCI.length;
    S.foci.forEach(function (p) { FOCI.push(p); });
  });
  CFG.forEach(function (S) { if (S.branch) S.base = -1; });

  var NS = "http://www.w3.org/2000/svg";
  var SEGS = [];
  var riverG = document.createElementNS(NS, "g");
  riverSvg.appendChild(riverG);
  for (var i = 0; i < FOCI.length - 1; i++) {
    var a = FOCI[i], b = FOCI[i + 1], dx = (b[0] - a[0]) * 0.5;
    var d = "M" + a[0] + " " + a[1] + " C" + (a[0] + dx) + " " + a[1] + " " + (b[0] - dx) + " " + b[1] + " " + b[0] + " " + b[1];
    var base = document.createElementNS(NS, "path");
    base.setAttribute("d", d); base.setAttribute("fill", "none"); base.setAttribute("stroke", "rgba(143,143,143,.6)");
    base.setAttribute("stroke-width", "4"); base.setAttribute("stroke-linecap", "round"); base.setAttribute("stroke-dasharray", "14 18");
    riverG.appendChild(base);
    var prog = document.createElementNS(NS, "path");
    prog.setAttribute("d", d); prog.setAttribute("fill", "none"); prog.setAttribute("stroke", "#3A83F7");
    prog.setAttribute("stroke-width", "6"); prog.setAttribute("stroke-linecap", "round"); prog.setAttribute("stroke-opacity", ".9");
    riverG.appendChild(prog);
    var len = prog.getTotalLength();
    prog.style.strokeDasharray = len + " " + len;
    prog.style.strokeDashoffset = len;
    SEGS.push({ el: prog, len: len, done: false });
  }

  /* ---------- cámara ---------- */
  function camT(c) {
    return "translate(" + (W / 2 - c.cx * c.s) + "px," + (H / 2 - c.cy * c.s) + "px) scale(" + c.s + ")";
  }
  function bgT(c) {
    var x = -c.cx * 0.12 - 400, y = -c.cy * 0.12 - 400;
    return "translate(" + x + "px," + y + "px)";
  }
  function bgT2(c) {
    var x = -c.cx * 0.28 - 400, y = -c.cy * 0.28 - 400;
    return "translate(" + x + "px," + y + "px)";
  }
  function readCam() {
    var m = new DOMMatrix(getComputedStyle(world).transform);
    var s = m.a || 1;
    return { cx: (W / 2 - m.e) / s, cy: (H / 2 - m.f) / s, s: s };
  }
  function setCam(c) {
    world.style.transform = camT(c);
    bgW.style.transform = bgT(c);
    bgD.style.transform = bgT2(c);
  }
  function cancelAnims() {
    [world, bgW, bgD, token].forEach(function (e) { e.getAnimations().forEach(function (a) { a.cancel(); }); });
    SEGS.forEach(function (s) { s.el.getAnimations().forEach(function (a) { a.cancel(); }); });
  }
  function tokenPos() {
    var m = new DOMMatrix(getComputedStyle(token).transform);
    return [m.e, m.f];
  }

  var focusNow = 0;   // índice de foco actual (línea principal)
  var camNow = { cx: 0, cy: 0, s: 1 };

  function polylineBetween(i0, i1) {
    // puntos a lo largo del río entre dos focos (cualquier orden)
    var pts = [], lo = Math.min(i0, i1), hi = Math.max(i0, i1);
    for (var k = lo; k < hi; k++) {
      var s = SEGS[k], n = 18;
      for (var j = (k === lo ? 0 : 1); j <= n; j++) {
        var p = s.el.getPointAtLength((s.len * j) / n);
        pts.push([p.x, p.y]);
      }
    }
    if (i1 < i0) pts.reverse();
    return pts;
  }

  function flyMain(i0, i1, targetScale, ms) {
    cancelAnims();
    setRiver(1, false);
    var from = readCam();
    var pts = polylineBetween(i0, i1);
    var N = pts.length, n = Math.min(N, 40);
    var kfT = [], kfW = [], kfB = [], kfB2 = [];
    var to = { cx: FOCI[i1][0], cy: FOCI[i1][1], s: targetScale };
    var dist = Math.hypot(FOCI[i1][0] - FOCI[i0][0], FOCI[i1][1] - FOCI[i0][1]);
    var dip = dist > 2000 ? 0.5 : 0.18;
    for (var k = 0; k < n; k++) {
      var u = k / (n - 1);
      var idx = Math.round(u * (N - 1));
      var tp = pts[idx];
      var ucam = Math.max(0, u - 0.1 * Math.sin(Math.PI * u));
      var cp = pts[Math.round(ucam * (N - 1))];
      var s = (from.s + (to.s - from.s) * u) * (1 - dip * Math.sin(Math.PI * u));
      var cam = k === n - 1 ? to : { cx: cp[0], cy: cp[1], s: s };
      kfT.push({ transform: "translate(" + tp[0] + "px," + tp[1] + "px)" });
      kfW.push({ transform: camT(cam) });
      kfB.push({ transform: bgT(cam) });
      kfB2.push({ transform: bgT2(cam) });
    }
    var opts = { duration: ms, easing: "cubic-bezier(.45,.05,.2,1)" };
    token.style.opacity = "1";
    token.style.transform = "translate(" + pts[N - 1][0] + "px," + pts[N - 1][1] + "px)";
    token.animate(kfT, opts);
    setCam(to);
    world.animate(kfW, opts);
    bgW.animate(kfB, opts);
    bgD.animate(kfB2, opts);
    // río: dibuja o borra los tramos recorridos
    var lo = Math.min(i0, i1), hi = Math.max(i0, i1);
    for (var q = lo; q < hi; q++) {
      var sg = SEGS[q];
      var fwd = i1 > i0;
      var fromOff = fwd ? sg.len : 0, toOff = fwd ? 0 : sg.len;
      sg.el.style.strokeDashoffset = toOff;
      var steps = hi - lo, part = (q - lo) / steps;
      var order = fwd ? part : 1 - part - 1 / steps;
      sg.el.animate([{ strokeDashoffset: fromOff }, { strokeDashoffset: toOff }], { duration: ms * (1 / steps), delay: ms * order, easing: "linear", fill: "backwards" });
    }
    // la gota se disuelve al llegar
    gsap.killTweensOf(token);
    gsap.fromTo(token, { opacity: 1 }, { opacity: 0, duration: 0.45, delay: ms / 1000 * 0.9, ease: "power1.out" });
    camNow = to;
  }

  function flyFree(to, ms) {
    cancelAnims();
    setRiver(0, false);
    var from = readCam();
    var mid = { cx: (from.cx + to.cx) / 2, cy: (from.cy + to.cy) / 2, s: Math.min(from.s, to.s) * 0.45 };
    var easing = "cubic-bezier(.45,.05,.2,1)";
    setCam(to);
    world.animate([{ transform: camT(from) }, { transform: camT(mid) }, { transform: camT(to) }], { duration: ms, easing: easing });
    bgW.animate([{ transform: bgT(from) }, { transform: bgT(mid) }, { transform: bgT(to) }], { duration: ms, easing: easing });
    bgD.animate([{ transform: bgT2(from) }, { transform: bgT2(mid) }, { transform: bgT2(to) }], { duration: ms, easing: easing });
    token.style.opacity = "0";
    camNow = to;
  }

  function paintRiver(upTo) {
    SEGS.forEach(function (s, k) { s.el.style.strokeDashoffset = k < upTo ? 0 : s.len; });
  }

  /* ---------- contenido de cada escena ---------- */
  function resetFrame(S) {
    var f = frames[S.id];
    var all = f.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      gsap.killTweensOf(el);
      gsap.set(el, { clearProps: "all" });
      if (el.__orig == null) el.removeAttribute("style"); else el.setAttribute("style", el.__orig);
    }
  }
  function applyLevel(S, lv, imm) {
    var f = frames[S.id];
    var els = f.querySelectorAll("[data-frag]");
    for (var i = 0; i < els.length; i++) {
      var k = +els[i].getAttribute("data-frag");
      var show = lv >= k;
      gsap.killTweensOf(els[i]);
      if (imm) gsap.set(els[i], { opacity: show ? 1 : 0, y: 0 });
      else gsap.to(els[i], { opacity: show ? 1 : 0, y: show ? 0 : 26, duration: show ? 0.55 : 0.25, ease: "power2.out", delay: show ? 0.08 * (k % 3) : 0 });
    }
    var fx = FX[S.id];
    if (fx && fx.level) fx.level(f, lv, S.lvPrev == null ? 0 : S.lvPrev, imm);
    S.lvPrev = lv;
  }
  function activate(S, lv, imm) {
    var f = frames[S.id];
    resetFrame(S);
    var els = f.querySelectorAll("[data-frag]");
    if (els.length) gsap.set(els, { opacity: 0, y: 26 });
    S.lvPrev = 0;
    var tl = gsap.timeline();
    var anim = f.querySelectorAll("[data-anim]");
    if (!imm && anim.length) tl.from(anim, { opacity: 0, y: 34, duration: 0.55, stagger: 0.07, ease: "power2.out" }, 0);
    var fx = FX[S.id];
    if (fx && fx.enter && !imm) fx.enter(f, tl);
    else if (fx && fx.enter && imm) { var t2 = gsap.timeline(); fx.enter(f, t2); t2.progress(1); }
    gsap.killTweensOf(f);
    f.classList.add("is-active");
    gsap.fromTo(f, { opacity: 0 }, { opacity: 1, duration: imm ? 0 : 0.5, ease: "power1.out" });
    setRiver(S.base >= 0 && S.foci.length > 1 ? 0.6 : 0, imm);
    applyLevel(S, lv, true);
    if (!imm && lv > 0) applyLevel(S, lv, true);
    if (window.YumiBotFX) { window.YumiBotFX(f, imm); window.YumiAmbient(f, imm); }
  }
  function deactivate(S, imm) {
    var f = frames[S.id];
    if (!f.classList.contains("is-active")) return;
    gsap.killTweensOf(f);
    if (window.YumiKill) window.YumiKill(f);
    if (imm) { gsap.set(f, { opacity: 0 }); f.classList.remove("is-active"); return; }
    gsap.to(f, { opacity: 0, duration: 0.35, ease: "power1.out", onComplete: function () { f.classList.remove("is-active"); } });
  }
  function setRiver(v, imm) {
    gsap.killTweensOf(riverSvg);
    if (imm) gsap.set(riverSvg, { opacity: v }); else gsap.to(riverSvg, { opacity: v, duration: 0.5 });
  }

  /* ---------- estado y controlador ---------- */
  var state = { si: -1, lv: 0, init: false };
  function sceneAt(t) {
    for (var i = 0; i < CFG.length; i++) {
      if (t >= CFG[i].start && t < CFG[i].start + CFG[i].dur) return i;
    }
    return t >= CFG[CFG.length - 1].start ? CFG.length - 1 : 0;
  }
  function levelAt(S, t) {
    if (!S.frags || !S.frags.length) return 0;
    var lv = 0;
    for (var i = 0; i < S.frags.length; i++) if (t >= S.frags[i] - 1e-6) lv = i;
    return lv;
  }
  function focusOf(S, lv) {
    if (S.base < 0) return -1;
    return S.base + Math.min(lv, S.foci.length - 1);
  }
  function camFor(S, lv) {
    if (S.base >= 0) { var p = S.foci[Math.min(lv, S.foci.length - 1)]; return { cx: p[0], cy: p[1], s: 1 }; }
    return { cx: S.cx, cy: S.cy, s: 1 };
  }
  function distMs(a, b) {
    var d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    return Math.max(1300, Math.min(3000, 1000 + d * 0.24));
  }

  var pending = null;
  function apply(t, opts) {
    opts = opts || {};
    var si = sceneAt(t), S = CFG[si], lv = levelAt(S, t);
    var animate = !STATIC && !opts.static && state.init;

    if (!state.init) {
      // primer cuadro: sin animación
      setCam(camFor(S, lv));
      camNow = camFor(S, lv);
      token.style.opacity = "0";
      focusNow = Math.max(0, focusOf(S, lv));
      paintRiver(S.base >= 0 ? focusNow : 0);
      CFG.forEach(function (o) { deactivate(o, true); });
      activate(S, lv, true);
      state = { si: si, lv: lv, init: true };
      return;
    }
    if (si === state.si && lv === state.lv) return;

    var prevS = CFG[state.si];
    if (si === state.si) {
      // cambio de nivel dentro de la misma escena
      var f0 = focusOf(S, state.lv), f1 = focusOf(S, lv);
      if (S.foci.length > 1 && f0 !== f1) {
        if (animate) flyMain(f0, f1, 1, distMs(FOCI[f0], FOCI[f1]));
        else { setCam(camFor(S, lv)); paintRiver(f1); }
        focusNow = f1;
      }
      applyLevel(S, lv, !animate);
      state.lv = lv;
      return;
    }

    // cambio de escena
    if (pending) { clearTimeout(pending); pending = null; }
    CFG.forEach(function (o) { if (o !== S) deactivate(o, !animate); });
    var toCam = camFor(S, lv);
    var fromMain = prevS.base >= 0, toMain = S.base >= 0;
    if (animate) {
      var from = fromMain ? focusNow : -1, to = focusOf(S, lv), ms;
      if (fromMain && toMain) {
        ms = distMs(FOCI[from], FOCI[to]);
        flyMain(from, to, 1, ms);
      } else {
        ms = 1700;
        flyFree(toCam, ms);
      }
      if (toMain) focusNow = to;
      pending = setTimeout(function () { activate(S, lv, false); pending = null; }, ms * 0.82);
    } else {
      setCam(toCam);
      if (toMain) { focusNow = focusOf(S, lv); paintRiver(focusNow); }
      activate(S, lv, true);
    }
    state.si = si; state.lv = lv;
  }

  /* ---------- timeline raíz (el controlador de HyperFrames lo mueve por seek) ---------- */
  var TOTAL = CFG[CFG.length - 1].start + CFG[CFG.length - 1].dur;
  var root = gsap.timeline({ paused: true });
  root.to({}, { duration: TOTAL });
  window.__timelines = window.__timelines || {};
  CFG.forEach(function (S) { window.__timelines[S.id] = gsap.timeline({ paused: true }); });
  window.__timelines["root"] = root;
  root.eventCallback("onUpdate", function () { apply(root.time()); });
  window.__hfSetTime = function (t, o) { root.time(t); apply(t, o); };
  window.__hfCameraTransitionsEnabled = !STATIC;

  // primer cuadro
  var t0 = qs.get("t") != null ? parseFloat(qs.get("t")) : 0.3;
  root.time(t0);
  apply(t0, { static: true });

  /* ---------- enlaces a la aplicación real ---------- */
  var LIVE = "https://asistente-reclamos-emapa.vercel.app/reclamo";
  document.addEventListener("keydown", function (ev) {
    if ((ev.key === "l" || ev.key === "L") && !ev.ctrlKey && !ev.metaKey && !ev.altKey) window.open(LIVE, "_blank", "noopener");
  });
  document.addEventListener("click", function (e) {
    var b = e.target.closest && e.target.closest("#btn-live, #btn-live2");
    if (b) window.open(LIVE, "_blank", "noopener");
  });

  /* ---------- manifiesto de escenas para <hyperframes-slideshow> ---------- */
  function post() {
    parent.postMessage({
      source: "hf-preview", type: "timeline", durationInFrames: Math.round(TOTAL * 30),
      scenes: CFG.map(function (S) { return { id: S.id, start: S.start, duration: S.dur }; }),
    }, "*");
  }
  if (EMBEDDED) {
    if (document.readyState === "complete") setTimeout(post, 300);
    else window.addEventListener("load", function () { setTimeout(post, 300); });
  }
})();
