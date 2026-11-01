/* Animaciones de la mascota Yumi: entrada, flotación, gestos y globos.
   Los movimientos se aplican al símbolo completo, sin alterar sus cintas. */
(function () {
  var PO = window.YumiRobot.POSES;
  function parts(b) {
    var symbol = b.querySelector(".yumi-symbol");
    return {
      symbol: symbol, gesture: b.querySelector(".yumi-gesture"),
      voice: b.querySelector(".yumi-voice"), dots: b.querySelector(".bot-dots"),
      origin: symbol ? symbol.getAttribute("data-origin") : "200 235"
    };
  }
  function applyPose(p, P, d) {
    if (p.symbol) {
      gsap.killTweensOf(p.symbol);
      var values = { rotation: P.tilt, x: P.x, scale: P.scale, svgOrigin: p.origin, ease: "power2.out" };
      if (d > 0) { values.duration = d; gsap.to(p.symbol, values); }
      else gsap.set(p.symbol, values);
    }
    if (p.dots) {
      gsap.killTweensOf(p.dots);
      if (d > 0) gsap.to(p.dots, { opacity: P.dots ? 1 : 0, duration: d });
      else gsap.set(p.dots, { opacity: P.dots ? 1 : 0 });
    }
  }
  function gesture(p, name, delay) {
    if (!p.gesture) return;
    gsap.killTweensOf(p.gesture);
    gsap.set(p.gesture, { rotation: 0, y: 0, scale: 1, svgOrigin: p.origin });
    if (name === "wave") {
      gsap.to(p.gesture, { rotation: -8, svgOrigin: p.origin, duration: 0.26, yoyo: true, repeat: 60, ease: "sine.inOut", delay: delay + 0.6 });
    } else if (name === "cheer") {
      gsap.to(p.gesture, { y: -8, scale: 1.04, svgOrigin: p.origin, duration: 0.4, yoyo: true, repeat: 5, ease: "sine.inOut", delay: delay });
    }
  }
  window.YumiBotPose = function (b, name, d) {
    if (!b || !PO[name]) return;
    var p = parts(b), duration = d == null ? 0.45 : d;
    b.setAttribute("data-curpose", name);
    applyPose(p, PO[name], duration);
    gesture(p, name, duration);
  };
  function talk(p, delay, dur) {
    if (!p.voice) return;
    var n = Math.max(2, Math.floor(dur / 0.15));
    gsap.timeline({ delay: delay })
      .set(p.voice, { scale: 1, svgOrigin: p.origin })
      .to(p.voice, { scale: 1.025, svgOrigin: p.origin, duration: 0.15, yoyo: true, repeat: n, ease: "sine.inOut" })
      .set(p.voice, { scale: 1 });
  }
  window.YumiBotFX = function (f, imm) {
    var list = f.querySelectorAll(".yb");
    for (var i = 0; i < list.length; i++) {
      var b = list[i], inner = b.querySelector(".ybi");
      if (!inner) continue;
      var name = b.getAttribute("data-pose") || "idle";
      var d = +(b.getAttribute("data-delay") || 0.5), P = PO[name] || PO.idle, p = parts(b);
      b.setAttribute("data-curpose", name);
      applyPose(p, P, 0);
      var svg = inner.querySelector("svg");
      if (!imm && b.getAttribute("data-pop") !== "0") {
        gsap.fromTo(inner, { scale: 0.3, opacity: 0, transformOrigin: "50% 100%" }, { scale: 1, opacity: 1, duration: 0.7, ease: "back.out(1.8)", delay: d });
      }
      gsap.to(svg, { y: -10, duration: 1.05 + (i % 3) * 0.15, ease: "sine.inOut", yoyo: true, repeat: 60, delay: imm ? 0 : d });
      gesture(p, name === "wave" || b.getAttribute("data-wave") === "1" ? "wave" : name, d);
      var bub = b.querySelector(".bubble");
      if (bub) {
        if (imm) gsap.set(bub, { opacity: 1, scale: 1 });
        else {
          gsap.fromTo(bub, { opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1, duration: 0.4, ease: "back.out(2)", delay: d + 0.6 });
          talk(p, d + 0.7, 1.4);
        }
      }
    }
  };
  // calma generalizada: flotar y brillar (para cualquier elemento con data-float / data-shimmer)
  window.YumiAmbient = function (f, imm) {
    var fl = f.querySelectorAll("[data-float]");
    for (var i = 0; i < fl.length; i++) {
      var amp = +fl[i].getAttribute("data-float") || 8;
      gsap.to(fl[i], { y: "-=" + amp, duration: 2.2 + (i % 4) * 0.5, ease: "sine.inOut", yoyo: true, repeat: 30, delay: 2.2 + (i % 5) * 0.2 });
    }
    var sh = f.querySelectorAll("[data-shimmer]");
    for (var j = 0; j < sh.length; j++) {
      gsap.fromTo(sh[j], { backgroundPosition: "0% 0%" }, { backgroundPosition: "100% 0%", duration: 3.2, ease: "sine.inOut", yoyo: true, repeat: 14, delay: 0.8 });
    }
  };
  window.YumiKill = function (f) {
    gsap.killTweensOf(f.querySelectorAll(".yb, .yb *, [data-float], [data-shimmer]"));
  };
})();
