/* Yumi · escenas (estilo OpenAI + shadcn/ui). Cada escena es HTML en un lienzo de 1920×1080 y un par de efectos (entrada y niveles).
   Los colores salen de variables de tema (.t-dark, .t-ink, .t-light, .t-warm, .t-cool) definidas en css/deck.css. */
(function () {
  var DROP_PATH = "M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z";
  var uid = 0;
  function dropSvg(size, id) {
    id = id || "gd" + uid++;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" aria-hidden="true">' +
      '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#9CCBFC"/><stop offset="1" stop-color="#3A83F7"/></linearGradient></defs>' +
      '<path d="' + DROP_PATH + '" fill="url(#' + id + ')"/>' +
      '<ellipse cx="9.3" cy="14.2" rx="1.1" ry="2.1" fill="#fff" opacity=".6" transform="rotate(18 9.3 14.2)"/></svg>';
  }
  // icono que toma el color del tema (acento) o uno fijo
  function ico(n, s, sw, col) {
    return '<span class="ico" style="color:' + (col || "var(--acc)") + '">' + I(n, s, "currentColor", sw || 1.8) + "</span>";
  }
  function icf(n, s, sw) { return ico(n, s, sw, "var(--fg)"); }
  function tag(n, t, extra) {
    return '<div class="tag abs" data-anim style="left:96px;top:64px;' + (extra || "") + '">' + n + " · " + t + "</div>";
  }
  function disc(icon, size, cls, style, col) {
    return '<div class="disc ' + (cls || "") + '" style="width:' + size + "px;height:" + size + "px;" + (style || "") + '">' +
      ico(icon, Math.round(size * 0.5), 1.7, col) + "</div>";
  }
  function pt(cx, cy, r, deg) {
    var a = (deg * Math.PI) / 180;
    return [Math.round(cx + r * Math.cos(a)), Math.round(cy + r * Math.sin(a))];
  }

  // Yumi, el robot: x,y = esquina del cuadro; w = ancho; pose; say = texto del globo (bx,by = posición del globo dentro del cuadro; tail = bl|br|ll|rr)
  function bot(o) {
    var w = o.w, head = !!o.head, h = Math.round(w * (head ? 262 / 276 : 470 / 400));
    var id = "yb" + uid++;
    var r = '<div class="yb"' + (o.frag != null ? ' data-frag="' + o.frag + '"' : "") + (o.id ? ' id="' + o.id + '"' : "") + ' data-pose="' + (o.pose || "idle") + '" data-delay="' + (o.d == null ? 0.6 : o.d) + '"' + (o.pop === false ? ' data-pop="0"' : "") +
      ' style="left:' + o.x + "px;top:" + o.y + "px;width:" + w + "px;height:" + h + 'px"><div class="ybi">' +
      window.YumiRobot.svg({ id: id, pose: o.pose || "idle", width: w, height: h, crop: head ? "head" : "" }) + "</div>";
    if (o.say) r += '<div class="bubble ' + (o.tail || "bl") + '"' + (o.sayId ? ' id="' + o.sayId + '"' : "") + ' style="left:' + o.bx + "px;top:" + o.by + "px;" + (o.tv ? "--tl:" + o.tv + "px;--tr:" + o.tv + "px;" : "") + "transform-origin:" + (o.to || "30% 100%") + '">' + o.say + "</div>";
    return r + "</div>";
  }
  function blobs() {
    return '<div class="blob" data-float="46" style="left:-220px;top:520px"></div><div class="blob" data-float="-54" style="left:1240px;top:-320px"></div>';
  }

  var H = {}; // html por escena
  var FX = {}; // efectos por escena

  /* ============ 1 · Portada ============ */
  H.portada =
    '<div class="tag abs" data-anim style="left:96px;top:244px">Asistente de reclamos con IA</div>' +
    '<div class="abs title big" data-anim style="left:96px;top:340px;width:1040px;font-size:144px">Un reclamo.<br><span class="grad" data-shimmer="1">3 a 5 minutos.</span></div>' +
    '<div class="abs sub" data-anim style="left:96px;top:700px;width:960px;font-size:42px">Atención de reclamos con Yumi<br>con revisión y aprobación humana</div>' +
    '<div class="abs" id="pt-ripples" style="left:1330px;top:760px;width:0;height:0">' +
      '<div class="rip abs" style="left:-250px;top:-70px;width:500px;height:140px;border-radius:50%;border:5px solid #63A8F8;opacity:0"></div>' +
      '<div class="rip abs" style="left:-250px;top:-70px;width:500px;height:140px;border-radius:50%;border:5px solid #63A8F8;opacity:0"></div>' +
      '<div class="rip abs" style="left:-250px;top:-70px;width:500px;height:140px;border-radius:50%;border:5px solid #63A8F8;opacity:0"></div></div>' +
    '<div class="abs" id="pt-drop" style="left:1100px;top:230px;width:460px;height:540px">' + bot({ x: 0, y: 0, w: 460, pose: "wave", d: 1.1, pop: false, say: "Hola, soy Yumi", bx: 290, by: -50, tail: "bl", tv: 40, to: "10% 100%" }) + "</div>" +
    '<div class="abs title" data-anim style="left:1070px;top:850px;width:520px;text-align:center;font-size:120px;letter-spacing:.08em">YUMI</div>';
  FX.portada = {
    enter: function (f, tl) {
      tl.fromTo(f.querySelector("#pt-drop"), { y: -760, opacity: 0, scaleY: 1.25 }, { y: 0, opacity: 1, scaleY: 1, duration: 0.9, ease: "bounce.out" }, 0.2);
      var rips = f.querySelectorAll(".rip");
      for (var i = 0; i < rips.length; i++) {
        tl.fromTo(rips[i], { scale: 0.15, opacity: 0.9 }, { scale: 1.25, opacity: 0, duration: 2.2, ease: "power1.out", repeat: 3 }, 1.0 + i * 0.7);
      }
    },
  };

  /* ============ 2 · El dolor ============ */
  (function () {
    var dow = "";
    ["L", "M", "M", "J", "V", "S", "D"].forEach(function (L, i) {
      dow += '<div class="abs" style="left:' + (33 + i * 108) + 'px;top:116px;width:96px;text-align:center;font-size:26px;font-weight:500;color:var(--g400)">' + L + "</div>";
    });
    var cells = "";
    for (var d = 1; d <= 5; d++) {
      var col = (d - 1) % 7, row = Math.floor((d - 1) / 7);
      cells += '<div class="dcell abs" data-d="' + d + '" style="left:' + (33 + col * 108) + "px;top:" + (166 + row * 122) + 'px;width:96px;height:84px;border-radius:20px;background:#F1F1F1;display:flex;align-items:center;justify-content:center;font-size:44px;font-weight:600;color:#181818;letter-spacing:-.03em">' + d + "</div>";
    }
    var tabs = "";
    for (var k = 0; k < 6; k++) {
      tabs += '<div class="abs mono" style="left:' + (8 + k * 146) + 'px;top:8px;width:138px;height:58px;border-radius:16px;background:#fff;border:1.5px solid var(--cardline);display:flex;align-items:center;justify-content:center;gap:8px;font-size:24px;color:var(--g500)">' + ico("globe", 28, 1.9, "var(--g400)") + "Pestaña</div>";
    }
    H.dolor =
      tag("01", "El punto de partida") +
      '<div class="abs title" data-anim style="left:96px;top:160px;width:880px;font-size:100px">Un reclamo toma de<br><span class="warn">3 a 5 días</span></div>' +
      '<div class="abs sub" data-anim style="left:96px;top:412px;width:880px;font-size:42px">desde que se realizaron<br>las inspecciones</div>' +
      '<div class="abs panel" data-anim style="left:1010px;top:110px;width:810px;height:540px">' +
        '<div class="abs lab" style="left:36px;top:30px;display:flex;align-items:center;gap:16px;font-size:36px">' + icf("calendar", 46) + "Después de las inspecciones</div>" +
        dow + cells +
        '<div class="abs center" style="left:573px;top:166px;width:96px;height:84px;border-radius:20px;border:2px dashed var(--g200)">' + ico("clock", 44, 1.8, "var(--g400)") + "</div>" +
        '<div class="abs" style="left:36px;top:440px;width:740px;display:flex;gap:40px;font-size:30px;font-weight:500;color:var(--g500)"><span style="display:flex;align-items:center;gap:12px"><b style="width:22px;height:22px;border-radius:7px;background:#181818;display:block"></b>mínimo 3 días</span><span style="display:flex;align-items:center;gap:12px"><b style="width:22px;height:22px;border-radius:7px;background:#EE7C37;display:block"></b>hasta 5 días</span></div>' +
      "</div>" +
      '<div class="abs" data-frag="1" style="left:96px;top:560px;width:888px;height:74px;border-radius:24px;background:#EBEBEB">' + tabs + "</div>" +
      '<div class="abs lab" data-frag="1" style="left:96px;top:664px;width:900px;font-size:46px;display:flex;align-items:center;gap:18px">' + icf("monitor", 54) + "Varias pestañas para resolver un reclamo</div>" +
      '<div class="abs" data-frag="2" style="left:1010px;top:700px;width:810px;height:300px;display:flex;align-items:center;gap:40px">' +
        '<div class="stat" id="dl-n" style="font-size:230px">3</div><div class="lab" style="font-size:38px;line-height:1.12">documentos por reclamo<br><span style="color:var(--mut);font-weight:500">informe, conciliación<br>y resolución</span></div></div>' +
      bot({ x: 96, y: 800, w: 230, pose: "think", frag: 1, d: 0.3, say: "Tanto trabajo manual…", bx: 250, by: 96, tail: "ll" });
    FX.dolor = {
      level: function (f, l, prev, imm) {
        var n = f.querySelector("#dl-n");
        if (!n) return;
        if (n.__o) gsap.killTweensOf(n.__o);
        if (l >= 2 && !imm && prev < 2) {
          var o = (n.__o = { v: 0 });
          gsap.to(o, { v: 3, duration: 1.1, ease: "power2.out", delay: 0.2, onUpdate: function () { n.textContent = Math.round(o.v); } });
        } else n.textContent = "3";
      },
      enter: function (f, tl) {
        var c = f.querySelectorAll(".dcell");
        for (var i = 0; i < c.length; i++) {
          var d = +c[i].getAttribute("data-d");
          tl.to(c[i], { backgroundColor: d <= 3 ? "#181818" : "#EE7C37", color: d <= 3 ? "#FFFFFF" : "#181818", duration: 0.25, ease: "power2.out" }, 0.5 + i * 0.12);
        }
      },
    };
  })();

  /* ============ 3 · El riesgo ============ */
  (function () {
    var ticks = "";
    for (var i = 0; i < 30; i++) {
      ticks += '<div class="tick abs" style="left:' + i * 54 + 'px;top:0;width:40px;height:120px;border-radius:12px;background:rgba(255,255,255,.14)"></div>';
    }
    H.riesgo =
      tag("02", "El riesgo") +
      '<div class="abs title" data-anim style="left:96px;top:160px;width:1560px;font-size:108px">A los 30 días hábiles, el reclamo se declara <span class="bad">fundado</span></div>' +
      '<div class="abs" data-anim style="left:150px;top:560px;width:1620px;height:120px">' + ticks + "</div>" +
      '<div class="abs lab" data-anim style="left:150px;top:710px">Día 1</div>' +
      '<div class="abs lab" data-anim style="left:1620px;top:710px;width:150px;text-align:right">Día 30</div>' +
      '<div class="abs" id="rk-clock" data-anim style="left:150px;top:430px">' + ico("hourglass", 100, 1.6, "var(--fg)") + "</div>" +
      '<div class="abs" id="rk-stamp" style="left:500px;top:760px;width:920px;height:240px;border:12px solid #FA423E;border-radius:32px;display:flex;flex-direction:column;align-items:center;justify-content:center;transform:rotate(-4deg);opacity:0;background:#111;box-shadow:0 40px 100px rgba(0,0,0,.6)">' +
        '<div style="font-size:150px;font-weight:700;color:#FA423E;letter-spacing:-.03em;line-height:1">FUNDADO</div>' +
        '<div style="font-size:44px;font-weight:600;color:#fff;margin-top:6px;letter-spacing:-.025em">por silencio administrativo</div></div>' +
      bot({ x: 110, y: 772, w: 250, pose: "think", d: 0.6 });
    FX.riesgo = {
      enter: function (f, tl) {
        var t = f.querySelectorAll(".tick");
        tl.set(t, { backgroundColor: "rgba(255,255,255,.14)" }, 0);
        tl.set(f.querySelector("#rk-stamp"), { opacity: 0, scale: 1.6 }, 0);
      },
      level: function (f, l, prev, imm) {
        var t = f.querySelectorAll(".tick");
        var stamp = f.querySelector("#rk-stamp");
        gsap.killTweensOf(t);
        gsap.killTweensOf(stamp);
        if (l >= 1) {
          if (imm) {
            gsap.set(t, { backgroundColor: "#FA423E" });
            gsap.set(stamp, { opacity: 1, scale: 1 });
          } else {
            for (var i = 0; i < t.length; i++) {
              gsap.to(t[i], { backgroundColor: i < 5 ? "#53B559" : i < 20 ? "#EE7C37" : "#FA423E", duration: 0.25, delay: i * 0.045, ease: "none" });
            }
            gsap.fromTo(stamp, { opacity: 0, scale: 1.7 }, { opacity: 1, scale: 1, duration: 0.35, delay: 1.7, ease: "back.out(2.4)" });
          }
        } else {
          gsap.set(t, { backgroundColor: "rgba(255,255,255,.14)" });
          gsap.set(stamp, { opacity: 0, scale: 1.6 });
        }
      },
    };
  })();

  /* ============ 4 · Presentamos a Yumi ============ */
  (function () {
    function doc(y, icon, label) {
      return '<div class="panel abs" data-frag="1" style="left:1160px;top:' + y + 'px;width:664px;height:118px;display:flex;align-items:center;gap:24px;padding:0 28px;border-radius:28px">' +
        '<span style="width:68px;height:68px;border-radius:20px;background:#F3F3F3;display:flex;align-items:center;justify-content:center;flex:none">' + ico(icon, 40, 1.8, "#181818") + "</span>" +
        '<span class="lab" style="font-size:40px;line-height:1.1;flex:1">' + label + "</span>" +
        '<span class="mono" style="height:42px;padding:0 14px;border-radius:12px;background:#E8F3FE;color:#1F4E94;font-size:26px;font-weight:600;display:flex;align-items:center">Word</span></div>';
    }
    H.solucion =
      blobs() + tag("03", "La solución") +
      '<div class="abs title" data-anim style="left:96px;top:150px;width:1700px;font-size:112px">Yumi prepara el expediente.<br>La persona decide.</div>' +
      '<div class="abs panel" data-anim style="left:96px;top:540px;width:260px;height:260px;border-radius:40px;text-align:center"><div class="abs center" style="left:0;top:48px;width:260px">' + ico("mail", 92, 1.7, "#181818") + '</div><div class="abs lab" style="left:0;top:172px;width:260px">Reclamo</div></div>' +
      '<div class="abs" data-anim style="left:384px;top:622px">' + ico("arrow-right", 96, 1.7, "#181818") + "</div>" +
      '<div class="abs" id="sl-yumi" data-anim style="left:520px;top:420px;width:340px;height:560px;text-align:center">' + bot({ x: -20, y: 0, w: 380, pose: "present", d: 0.5 }) +
        '<div class="abs title" style="left:0;top:452px;width:340px;font-size:64px">Yumi</div>' +
        '<div class="abs mono" style="left:0;top:522px;width:340px;font-size:26px;color:var(--g500)">asistente con IA</div></div>' +
      '<div class="abs" data-frag="1" style="left:884px;top:622px">' + ico("arrow-right", 96, 1.7, "#181818") + "</div>" +
      doc(470, "file-text", "Informe de atención") +
      doc(598, "handshake", "Propuesta de conciliación") +
      doc(726, "gavel", "Resolución") +
      '<div class="abs pill dk" data-frag="1" style="left:1160px;top:880px;height:84px;padding:0 38px;font-size:40px">' + ico("user-check", 44, 1.9, "var(--bg)") + "Revisa y aprueba</div>";
    FX.solucion = {
      level: function (f, l, prev, imm) {
        var b = f.querySelector("#sl-yumi .yb");
        if (b && window.YumiBotPose) window.YumiBotPose(b, l >= 1 ? "cheer" : "present", imm ? 0 : 0.45);
      },
    };
  })();

  /* ============ 5 · El recorrido ============ */
  (function () {
    // centros locales de cada parada (offset respecto a la primera)
    var OFF = [[0, 0], [1500, -400], [3000, 0], [4500, -400], [6000, 0]];
    function loc(k) { return [960 + OFF[k][0], 540 + OFF[k][1]]; }
    // Proceso central: ingreso, atención, conciliación y resolución.
    var steps = [
      { icon: "mail", t: "Ingreso del reclamo", pill: "Sistema comercial", n: "01", pc: "acc" },
      { icon: "scan-search", t: "Atención del reclamo", pill: "Inspecciones y análisis", n: "02", pc: "amber-bg" },
      { icon: "handshake", t: "Conciliación del reclamo", pill: "Propuesta de la empresa", n: "03", pc: "acc" },
      { icon: "gavel", t: "Resolución del reclamo", pill: "Atención y conciliación", n: "04", pc: "acc" }
    ];
    var POS = ["left", "think", "present", "cheer"];
    var SAY = ["Se registra el reclamo en el sistema", "Analizo y preparo el informe", "Propongo con base en la atención", "Redacto la resolución"];
    var h = '<div class="strip" style="left:-300px;top:-900px;width:8300px;height:3000px;z-index:0"></div>';
    h += '<div class="tag abs" data-anim style="left:96px;top:64px;z-index:1">04 · El recorrido de un reclamo</div>';
    h += '<div class="abs title" data-anim style="left:96px;top:140px;width:1300px;font-size:80px;z-index:1">Cuatro etapas</div>';
    for (var k = 0; k < steps.length; k++) {
      var c = loc(k), s = steps[k];
      h += '<div class="abs stop" data-stop="' + k + '" style="left:' + (c[0] - 330) + "px;top:" + (c[1] - 285) + 'px;width:660px;height:660px;text-align:center;z-index:1">';
      h += '<div class="mono" style="font-size:32px;color:var(--mut)">Etapa ' + s.n + "</div>";
      h += '<div class="disc" style="width:300px;height:300px;margin:26px auto 0;border-radius:30%">' + ico(s.icon, 150, 1.6) + "</div>";
      h += '<div class="lab" style="margin:36px auto 0;font-size:44px;line-height:1.08;width:600px">' + s.t + "</div>";
      if (s.pill) h += '<div class="pill ' + s.pc + '" style="margin-top:24px;font-size:44px">' + s.pill + "</div>";
      h += "</div>";
      h += bot({ x: c[0] - (k === 1 ? 920 : 610), y: c[1] - 172, w: 230, pose: POS[k], frag: k, d: 0.4, say: SAY[k], bx: (k === 1 ? 0 : -50), by: -104, tail: "bl", tv: (k === 1 ? 70 : 120), to: "40% 100%" });
    }
    // Ejemplos de medios probatorios durante la atención.
    var c2 = loc(1);
    var mini = ["gauge", "receipt", "power", "wallet", "house", "map-pin"];
    for (var m = 0; m < 6; m++) {
      var ang = (m * 60 * Math.PI) / 180;
      var p = [Math.round(c2[0] + 500 * Math.cos(ang)), Math.round(c2[1] - 110 + 170 * Math.sin(ang))];
      h += '<div class="abs minimedio" style="left:' + (p[0] - 42) + "px;top:" + (p[1] - 42) + 'px;width:84px;height:84px;z-index:1">' + ico(mini[m], 84, 1.6, "var(--g500)") + "</div>";
    }
    // total
    var c5 = loc(4);
    h += '<div class="abs" data-stop="4" data-frag="4" style="left:' + (c5[0] - 700) + "px;top:" + (c5[1] - 400) + 'px;width:1400px;height:800px;text-align:center;z-index:1">';
    h += '<div class="tag" style="margin:0 auto">Tiempo de atención con Yumi</div>';
    h += '<div class="stat" style="font-size:300px;margin-top:80px;color:var(--fg)"><span>3 a 5</span><span style="font-size:140px;color:var(--mut)"> min</span></div>';
    h += '<div class="sub" style="margin-top:32px">para el análisis y la elaboración de documentos</div>';
    h += '<div class="abs note" style="left:100px;top:660px;width:1200px;font-size:36px">Con las inspecciones realizadas y revisión humana</div>';
    h += "</div>";
    h += bot({ x: c5[0] + 500, y: c5[1] - 90, w: 270, pose: "cheer", frag: 4, d: 0.5, say: "¡De 3 a 5 minutos!", bx: -40, by: -104, tail: "bl", tv: 110, to: "40% 100%" });
    H.recorrido = h;
    FX.recorrido = {
      wide: true,
      level: function (f, l, prev, imm) {
        var stops = f.querySelectorAll(".stop");
        for (var i = 0; i < stops.length; i++) {
          var disc = stops[i].querySelector(".disc");
          if (i <= l) disc.classList.add("on"); else disc.classList.remove("on");
        }
      },
    };
  })();

  /* ============ 6 · Los medios probatorios ============ */
  (function () {
    var items = [
      ["gauge", "Tarjeta de lecturas"],
      ["receipt", "Récord de facturación"],
      ["power", "Cortes y reaperturas"],
      ["wallet", "Saldo detalle"],
      ["house", "Inspección interna"],
      ["map-pin", "Inspección externa"],
    ];
    var cx = 1340, cy = 565;
    var h = blobs() + tag("05", "Los medios probatorios") +
      '<div class="abs title" data-anim style="left:96px;top:170px;width:700px;font-size:84px">Yumi analiza los medios que hoy se revisan <span style="color:#FFC08A">a mano</span></div>' +
      '<div class="abs" data-anim style="left:' + (cx - 160) + "px;top:" + (cy - 190) + 'px;width:320px;height:320px;border-radius:50%;background:radial-gradient(circle,rgba(255,255,255,.35),rgba(255,255,255,0) 66%);display:flex;align-items:center;justify-content:center">' + dropSvg(220, "gmd") + "</div>";
    for (var i = 0; i < 6; i++) {
      var ang = -90 + i * 60;
      var rx = 470, ry = 325;
      var x = Math.round(cx + rx * Math.cos((ang * Math.PI) / 180));
      var y = Math.round(cy - 30 + ry * Math.sin((ang * Math.PI) / 180));
      h += '<div class="abs medio" data-anim data-float="9" style="left:' + (x - 160) + "px;top:" + (y - 95) + 'px;width:320px;text-align:center">' +
        '<div class="disc" style="width:150px;height:150px;margin:0 auto">' + ico(items[i][0], 80, 1.7, "#fff") + "</div>" +
        '<div class="lab sm" style="margin-top:12px;line-height:1.05">' + items[i][1] + "</div>" +
        '<div class="chk abs center" data-frag="1" style="left:206px;top:-8px;width:60px;height:60px;border-radius:50%;background:#53B559">' + ico("check", 40, 3, "#fff") + "</div></div>";
    }
    h += bot({ x: 100, y: 560, w: 380, pose: "point", d: 0.6, say: "Analizo los medios probatorios aplicables", bx: 30, by: -110, tail: "bl", tv: 150, to: "40% 100%" });
    H.medios = h;
  })();

  /* ============ 7 · La norma ============ */
  (function () {
    var chips = "";
    for (var i = 0; i < 4; i++) {
      chips += '<div class="abs chip" style="left:0;top:' + i * 96 + 'px;width:230px;height:76px;border-radius:18px;background:#E8F3FE;border:2px solid #A4CDFB;display:flex;align-items:center;gap:14px;padding:0 20px;font-size:38px;font-weight:600;color:#1F4E94">' + ico("scroll-text", 40, 1.8, "#1F4E94") + "Art.</div>";
    }
    H.normativa =
      tag("06", "La norma") +
      '<div class="abs title" data-anim style="left:96px;top:150px;width:1560px;font-size:92px">Cada hallazgo se contrasta con el reglamento de <span class="hl">SUNASS</span></div>' +
      '<div class="abs" data-anim style="left:96px;top:600px;width:260px;text-align:center">' + disc("file-text", 220, "", "margin:0 auto") + '<div class="lab sm" style="margin-top:20px">Reglamento</div></div>' +
      '<div class="abs" data-anim style="left:400px;top:650px">' + ico("arrow-right", 90, 1.7, "var(--fg)") + "</div>" +
      '<div class="abs" id="nm-chips" data-anim style="left:520px;top:560px;width:240px;height:380px">' + chips + "</div>" +
      '<div class="abs" data-anim style="left:790px;top:650px">' + ico("arrow-right", 90, 1.7, "var(--fg)") + "</div>" +
      '<div class="abs" data-anim style="left:900px;top:560px;width:300px;text-align:center">' + disc("database", 240, "on", "margin:0 auto") + '<div class="lab sm" style="margin-top:20px">Base vectorial</div></div>' +
      '<div class="abs panel" data-frag="1" style="left:880px;top:390px;width:340px;height:110px;display:flex;align-items:center;gap:20px;padding:0 24px;border-color:#EE7C37;background:#FBE8DB">' + ico("triangle-alert", 56, 1.9, "#D25E28") + '<span class="lab" style="font-size:42px">Hallazgo</span></div>' +
      '<div class="abs" data-frag="1" style="left:1250px;top:650px">' + ico("arrow-right", 90, 1.7, "var(--fg)") + "</div>" +
      '<div class="abs panel" data-frag="1" style="left:1380px;top:520px;width:420px;height:400px">' +
        '<div class="abs center" style="left:0;top:30px;width:420px;gap:18px">' + ico("book-open", 64, 1.8) + '<span class="lab" style="font-size:42px">Artículo citado</span></div>' +
        '<div class="abs" style="left:40px;top:150px;width:340px;height:22px;border-radius:11px;background:rgba(0,0,0,.16)"></div>' +
        '<div class="abs" style="left:40px;top:200px;width:300px;height:22px;border-radius:11px;background:rgba(0,0,0,.09)"></div>' +
        '<div class="abs" style="left:40px;top:250px;width:320px;height:22px;border-radius:11px;background:rgba(0,0,0,.09)"></div>' +
        '<div class="abs pill ok" style="left:40px;top:310px;font-size:34px">' + ico("check", 36, 3, "#3A843F") + "Fundamenta</div></div>" +
      bot({ x: 1650, y: 68, w: 200, pose: "present", d: 0.4 });
    FX.normativa = {
      enter: function (f, tl) {
        var c = f.querySelectorAll(".chip");
        if (c.length) tl.from(c, { x: -120, opacity: 0, duration: 0.4, stagger: 0.12, ease: "power2.out" }, 0.5);
      },
    };
  })();

  /* ============ 8 · Dónde corre ============ */
  (function () {
    H.corre =
      tag("07", "Dónde corre") +
      '<div class="abs title" data-anim style="left:96px;top:140px;width:1700px;font-size:104px">En su servidor o en la nube.<br><span class="hl">Usted elige.</span></div>' +
      '<div class="abs" id="cr-toggle" data-anim style="left:96px;top:392px;width:560px;height:96px;border-radius:999px;background:#EBEBEB">' +
        '<div id="cr-knob" class="abs" style="left:8px;top:8px;width:268px;height:80px;border-radius:999px;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.14)"></div>' +
        '<div class="abs lab" style="left:8px;top:0;width:268px;height:96px;display:flex;align-items:center;justify-content:center;font-size:40px">Local</div>' +
        '<div class="abs lab" style="left:284px;top:0;width:268px;height:96px;display:flex;align-items:center;justify-content:center;font-size:40px">Nube</div></div>' +
      '<div class="abs panel" id="cr-local" style="left:96px;top:540px;width:860px;height:440px;border-radius:36px" data-anim>' +
        '<div class="abs" style="left:48px;top:44px;display:flex;align-items:center;gap:28px">' + ico("server", 150, 1.5, "#181818") + '<span style="position:relative;display:inline-block;width:110px;height:110px"><span class="lk-open abs" style="left:0;top:4px">' + ico("lock-open", 104, 1.7, "#8F8F8F") + '</span><span class="lk-closed abs" style="left:0;top:4px;opacity:0">' + ico("lock", 104, 1.7, "#3A843F") + "</span></span></div>" +
        '<div class="abs title" style="left:48px;top:236px;font-size:68px">Local</div>' +
        '<div class="abs lab" style="left:48px;top:326px;width:780px;font-size:44px;color:var(--g600)">Los datos del reclamo no salen de su empresa</div></div>' +
      '<div class="abs panel" id="cr-cloud" style="left:984px;top:540px;width:840px;height:440px;border-radius:36px" data-anim>' +
        '<div class="abs" style="left:48px;top:44px">' + ico("cloud", 150, 1.5, "#181818") + "</div>" +
        '<div class="abs title" style="left:48px;top:236px;font-size:68px">Nube</div>' +
        '<div class="abs lab" style="left:48px;top:326px;width:740px;font-size:44px;color:var(--g600)">Proveedores externos, con su propia clave</div></div>' +
      bot({ x: 1580, y: 262, w: 220, pose: "left", d: 0.7, say: "Local o nube: tú eliges", bx: -540, by: 66, tail: "rr", to: "100% 50%" });
    FX.corre = {
      level: function (f, l, prev, imm) {
        var knob = f.querySelector("#cr-knob"), loc = f.querySelector("#cr-local"), cld = f.querySelector("#cr-cloud");
        var open = f.querySelector(".lk-open"), closed = f.querySelector(".lk-closed");
        var d = imm ? 0 : 0.6;
        gsap.killTweensOf([knob, loc, cld, open, closed]);
        if (l >= 1) {
          gsap.to(knob, { x: 0, duration: d, ease: "power2.inOut" });
          gsap.to(loc, { borderColor: "#181818", boxShadow: "0 0 0 8px rgba(24,24,24,.10)", duration: d });
          gsap.to(cld, { opacity: 0.4, duration: d });
          gsap.to(open, { opacity: 0, duration: d });
          gsap.to(closed, { opacity: 1, duration: d, delay: imm ? 0 : 0.2 });
        } else {
          gsap.to(knob, { x: 276, duration: d, ease: "power2.inOut" });
          gsap.to(loc, { borderColor: "#E8E8E8", boxShadow: "0 1px 3px rgba(0,0,0,.07)", duration: d });
          gsap.to(cld, { opacity: 1, duration: d });
          gsap.to(open, { opacity: 1, duration: d });
          gsap.to(closed, { opacity: 0, duration: d });
        }
      },
    };
  })();

  /* ============ 9 · SYSCO y Yumi: cuatro etapas del reclamo ============ */
  H.demo = window.YumiDemo.html(bot);
  FX.demo = window.YumiDemo.fx;

  /* ============ 10 · La ruta del piloto ============ */
  (function () {
    function step(i, x, hgt, icon, t1, t2) {
      return '<div class="abs panel" ' + (i === 0 ? "data-anim" : 'data-frag="' + i + '"') + ' style="left:' + x + "px;top:" + (940 - hgt) + "px;width:540px;height:" + hgt + 'px;border-radius:36px 36px 0 0">' +
        '<div class="abs center" style="left:0;top:40px;width:540px">' + ico(icon, 110, 1.6, "#181818") + "</div>" +
        '<div class="abs lab" style="left:24px;top:190px;width:492px;text-align:center;font-size:46px;line-height:1.1">' + t1 + "</div>" +
        (t2 ? '<div class="abs pill amber-bg" style="left:150px;top:' + (hgt - 110) + 'px;font-size:40px">' + t2 + "</div>" : "") + "</div>";
    }
    H.piloto =
      tag("09", "La ruta") +
      '<div class="abs title" data-anim style="left:96px;top:140px;width:1700px;font-size:108px">Un piloto en <span class="hl">tres peldaños</span></div>' +
      step(0, 96, 440, "git-merge", "En paralelo, sin tocar su proceso", "2 meses") +
      step(1, 690, 560, "plug", "Escribe en su sistema comercial", "") +
      step(2, 1284, 680, "zap", "Reclamos simples en automático", "") +
      bot({ x: 1462, y: 36, w: 188, pose: "cheer", frag: 2, d: 0.2 });
  })();

  /* ============ 11 · Cierre ============ */
  H.cierre =
    '<div class="tag abs" data-anim style="left:96px;top:90px">Siguiente paso</div>' +
    '<div class="abs title" data-anim style="left:96px;top:176px;width:980px;font-size:112px">Pilotemos con<br><span class="grad" data-shimmer="1">20 expedientes</span><br>de su EPS</div>' +
    '<div class="abs" data-anim style="left:96px;top:600px"><button class="btn-live" id="btn-live2">Abrir Yumi en vivo ' + I("external-link", 46, "#0A0A0A", 2.2) + "</button></div>" +
    '<div class="abs" data-anim style="left:96px;top:834px;width:980px"><div class="lab" style="font-size:36px">Darick Gerald Herrera Castillo</div><div class="lab" style="font-size:36px;margin-top:6px">Jhon Dalton Huamán Quintana</div><div class="mono" style="font-size:26px;color:var(--g400);margin-top:10px">FISI · Universidad Nacional de San Martín</div></div>' +
    '<div class="abs" data-anim style="left:1100px;top:150px;width:724px;height:860px;border-radius:52px;overflow:hidden;background:radial-gradient(800px 640px at 8% 104%, #F6C543 0%, rgba(246,197,67,0) 62%), radial-gradient(900px 700px at 100% -4%, #F077AF 0%, rgba(240,119,175,0) 64%), radial-gradient(760px 600px at 56% 70%, #EE7C37 0%, rgba(238,124,55,0) 68%), #F6B58C">' +
      ["file-text|Informe de atención|Listo", "handshake|Propuesta de conciliación|Lista", "gavel|Resolución|Lista"].map(function (r, i) {
        var p = r.split("|");
        return '<div class="abs panel" style="left:72px;top:' + (104 + i * 178) + 'px;width:600px;height:150px;display:flex;align-items:center;gap:22px;padding:0 26px;background:#fff;border-color:#fff;color:#181818">' +
          '<span style="width:76px;height:76px;border-radius:22px;background:#F3F3F3;display:flex;align-items:center;justify-content:center;flex:none">' + ico(p[0], 40, 1.8, "#181818") + "</span>" +
          '<span class="lab" style="flex:1;font-size:36px;color:#181818">' + p[1] + "</span>" +
          '<span class="pill ok" style="height:42px;padding:0 16px;font-size:26px;gap:8px">' + ico("circle-check", 26, 2, "#3A843F") + p[2] + "</span></div>";
      }).join("") +
      '<div class="abs pill" style="left:72px;top:682px;height:96px;padding:0 40px;font-size:50px;background:#181818;color:#fff">3 a 5 minutos</div></div>' +
    bot({ x: 1560, y: 744, w: 270, pose: "wave", d: 1.0, say: "¿Empezamos?", bx: -250, by: 8, tail: "rr", to: "100% 50%" });
  FX.cierre = {};

  /* ============ Ramas ============ */
  (function () {
    function node(x, y, icon, t) {
      var d = icon === "bot"
        ? '<div class="disc" style="width:170px;height:170px;margin:0 auto;position:relative;overflow:visible;border-radius:30%">' + bot({ x: 10, y: 14, w: 150, head: true, pose: "idle", d: 0.5 }) + "</div>"
        : disc(icon, 170, "", "margin:0 auto");
      return '<div class="abs" data-anim style="left:' + (x - 150) + "px;top:" + y + 'px;width:300px;text-align:center">' + d + '<div class="lab sm" style="margin-top:16px;line-height:1.1">' + t + "</div></div>";
    }
    function arr(x, y) { return '<div class="abs" data-anim style="left:' + x + "px;top:" + y + 'px">' + ico("arrow-right", 70, 1.7, "var(--fg)") + "</div>"; }
    H.arquitectura =
      tag("+", "Arquitectura") +
      '<div class="abs title" data-anim style="left:96px;top:140px;width:1700px;font-size:84px">Por dentro: agentes, normativa y modelos</div>' +
      node(250, 360, "monitor", "Panel web") + arr(410, 410) +
      node(660, 360, "server", "Servicio API") + arr(820, 410) +
      node(1070, 360, "bot", "Agentes") + arr(1230, 410) +
      node(1480, 360, "brain", "Modelo local o nube") +
      node(660, 720, "plug", "Sistema comercial") + node(1070, 720, "database", "Normativa vectorial") +
      '<div class="abs" data-anim style="left:625px;top:640px">' + ico("arrow-down", 70, 1.7, "var(--fg)") + "</div>" +
      '<div class="abs" data-anim style="left:1035px;top:640px">' + ico("arrow-down", 70, 1.7, "var(--fg)") + "</div>";
  })();

  window.YUMI_SCENE_HTML = H;
  window.YUMI_SCENE_FX = FX;
})();
