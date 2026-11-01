/* Yumi · escenas. Cada escena es HTML en un lienzo de 1920×1080 y un par de efectos (entrada y niveles). */
(function () {
  var DROP_PATH = "M12 22a7 7 0 0 0 7-7c0-2-1-3.9-3-5.5s-3.5-4-4-6.5c-.5 2.5-2 4.9-4 6.5C6 11.1 5 13 5 15a7 7 0 0 0 7 7z";
  var uid = 0;
  function dropSvg(size, id) {
    id = id || "gd" + uid++;
    return '<svg width="' + size + '" height="' + size + '" viewBox="0 0 24 24" aria-hidden="true">' +
      '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8ef0fa"/><stop offset="1" stop-color="#0284c7"/></linearGradient></defs>' +
      '<path d="' + DROP_PATH + '" fill="url(#' + id + ')" stroke="#e8f6fb" stroke-width=".3"/>' +
      '<ellipse cx="9.3" cy="14.2" rx="1.1" ry="2.1" fill="#e8f6fb" opacity=".55" transform="rotate(18 9.3 14.2)"/></svg>';
  }
  function eyebrow(n, t) {
    return '<div class="eyebrow abs" data-anim style="left:96px;top:72px">' + n + ' · ' + t + '</div>';
  }
  function disc(icon, size, color, cls, style) {
    return '<div class="disc ' + (cls || "") + '" style="width:' + size + 'px;height:' + size + 'px;' + (style || "") + '">' +
      I(icon, Math.round(size * 0.5), color || "#5ee0f0", 1.7) + "</div>";
  }
  function pt(cx, cy, r, deg) {
    var a = (deg * Math.PI) / 180;
    return [Math.round(cx + r * Math.cos(a)), Math.round(cy + r * Math.sin(a))];
  }

  var H = {}; // html por escena
  var FX = {}; // efectos por escena

  /* ============ 1 · Portada ============ */
  H.portada =
    '<div class="abs" data-anim style="left:96px;top:64px;width:470px;height:134px;background:#fff;border-radius:28px;display:flex;align-items:center;justify-content:center"><img src="assets/logo-emapa.png" alt="Agua San Martín" style="width:390px;height:auto"></div>' +
    '<div class="abs eyebrow" data-anim style="left:96px;top:300px">Asistente de reclamos con IA</div>' +
    '<div class="abs title big" data-anim style="left:96px;top:370px;width:1000px">Un reclamo.<br><span class="aqua">66 segundos.</span></div>' +
    '<div class="abs sub" data-anim style="left:96px;top:690px;width:900px">Caso EMAPA San Martín<br>Propuesta para una EPS de Piura</div>' +
    '<div class="abs" id="pt-ripples" style="left:1250px;top:700px;width:0;height:0">' +
      '<div class="rip abs" style="left:-250px;top:-70px;width:500px;height:140px;border-radius:50%;border:5px solid #5ee0f0;opacity:0"></div>' +
      '<div class="rip abs" style="left:-250px;top:-70px;width:500px;height:140px;border-radius:50%;border:5px solid #5ee0f0;opacity:0"></div>' +
      '<div class="rip abs" style="left:-250px;top:-70px;width:500px;height:140px;border-radius:50%;border:5px solid #5ee0f0;opacity:0"></div></div>' +
    '<div class="abs" id="pt-drop" style="left:990px;top:190px;width:520px;height:520px">' + dropSvg(520, "gdp") + "</div>" +
    '<div class="abs" data-anim style="left:990px;top:790px;width:520px;text-align:center;font-size:150px;font-weight:800;letter-spacing:.12em;color:#e8f6fb">YUMI</div>';
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
    var cells = "";
    for (var d = 1; d <= 11; d++) {
      var col = (d - 1) % 4, row = Math.floor((d - 1) / 4);
      cells += '<div class="dcell abs" data-d="' + d + '" style="left:' + (28 + col * 180) + 'px;top:' + (136 + row * 134) + 'px;width:164px;height:118px;border-radius:22px;border:3px dashed rgba(232,246,251,.35);display:flex;align-items:center;justify-content:center;font-size:56px;font-weight:800;color:#e8f6fb">' + d + "</div>";
    }
    var tabs = "";
    for (var k = 0; k < 6; k++) {
      tabs += '<div class="tab abs" data-frag="1" style="left:' + k * 148 + 'px;top:0;width:138px;height:150px;border-radius:24px 24px 0 0;background:#e0f2fe;display:flex;align-items:center;justify-content:center">' + I("globe", 64, "#0369a1", 1.8) + "</div>";
    }
    H.dolor =
      eyebrow("01", "El punto de partida") +
      '<div class="abs title" data-anim style="left:96px;top:170px;width:880px">Un reclamo toma de <span class="amber">5 a 11 días</span></div>' +
      '<div class="abs panel" data-anim style="left:1030px;top:120px;width:780px;height:600px">' +
        '<div class="abs center" style="left:28px;top:24px;width:724px;height:84px;border-radius:24px;background:rgba(94,224,240,.16);gap:20px">' + I("calendar", 52, "#5ee0f0", 1.8) + '<span class="lab" style="font-size:44px">Días naturales</span></div>' +
        cells +
        '<div class="abs center" style="left:568px;top:404px;width:164px;height:118px">' + I("clock", 84, "#5ee0f0", 1.6) + "</div>" +
      "</div>" +
      '<div class="abs" style="left:96px;top:640px;width:900px;height:360px">' +
        '<div class="abs" style="left:0;top:0;width:888px;height:150px">' + tabs + "</div>" +
        '<div class="abs panel" data-frag="1" style="left:0;top:150px;width:888px;height:140px;border-radius:0 0 36px 36px;display:flex;align-items:center;padding:0 40px;gap:28px">' + I("monitor", 64, "#5ee0f0", 1.7) + '<span class="lab" style="font-size:46px">6 pestañas de SYSCO por reclamo</span></div>' +
      "</div>" +
      '<div class="abs" data-frag="2" style="left:1030px;top:770px;width:780px;height:250px;display:flex;align-items:center;gap:36px">' +
        '<div class="stat" style="font-size:210px">305</div><div class="lab" style="font-size:42px;line-height:1.15">reclamos al mes<br>(estimado en<br>EMAPA)</div></div>';
    FX.dolor = {
      enter: function (f, tl) {
        var c = f.querySelectorAll(".dcell");
        for (var i = 0; i < c.length; i++) {
          var d = +c[i].getAttribute("data-d");
          var amber = d <= 5;
          tl.to(c[i], { backgroundColor: amber ? "#f5b835" : "rgba(255,107,107,.85)", color: "#052b45", borderStyle: "solid", borderColor: amber ? "#f5b835" : "#ff6b6b", duration: 0.25, ease: "power2.out" }, 0.5 + i * 0.12);
        }
      },
    };
  })();

  /* ============ 3 · El riesgo ============ */
  (function () {
    var ticks = "";
    for (var i = 0; i < 30; i++) {
      ticks += '<div class="tick abs" style="left:' + i * 54 + 'px;top:0;width:40px;height:120px;border-radius:12px;background:rgba(232,246,251,.22)"></div>';
    }
    H.riesgo =
      eyebrow("02", "El riesgo") +
      '<div class="abs title" data-anim style="left:96px;top:170px;width:1500px">A los 30 días hábiles, el reclamo se declara <span class="coral">fundado</span></div>' +
      '<div class="abs" data-anim style="left:150px;top:560px;width:1620px;height:120px">' + ticks + "</div>" +
      '<div class="abs lab" data-anim style="left:150px;top:710px">Día 1</div>' +
      '<div class="abs lab" data-anim style="left:1620px;top:710px;width:150px;text-align:right">Día 30</div>' +
      '<div class="abs" id="rk-clock" data-anim style="left:150px;top:420px">' + I("hourglass", 100, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs" id="rk-stamp" style="left:520px;top:760px;width:880px;height:240px;border:12px solid #ff6b6b;border-radius:28px;display:flex;flex-direction:column;align-items:center;justify-content:center;transform:rotate(-4deg);opacity:0;background:rgba(5,43,69,.85)">' +
        '<div style="font-size:150px;font-weight:800;color:#ff6b6b;letter-spacing:.04em;line-height:1">FUNDADO</div>' +
        '<div style="font-size:44px;font-weight:700;color:#e8f6fb;margin-top:6px">por silencio administrativo</div></div>';
    FX.riesgo = {
      enter: function (f, tl) {
        var t = f.querySelectorAll(".tick");
        tl.set(t, { backgroundColor: "rgba(232,246,251,.22)" }, 0);
        tl.set(f.querySelector("#rk-stamp"), { opacity: 0, scale: 1.6 }, 0);
      },
      level: function (f, l, prev, imm) {
        var t = f.querySelectorAll(".tick");
        var stamp = f.querySelector("#rk-stamp");
        gsap.killTweensOf(t);
        gsap.killTweensOf(stamp);
        if (l >= 1) {
          if (imm) {
            gsap.set(t, { backgroundColor: "#ff6b6b" });
            gsap.set(stamp, { opacity: 1, scale: 1 });
          } else {
            for (var i = 0; i < t.length; i++) {
              gsap.to(t[i], { backgroundColor: i < 5 ? "#3fd17a" : i < 20 ? "#f5b835" : "#ff6b6b", duration: 0.25, delay: i * 0.045, ease: "none" });
            }
            gsap.fromTo(stamp, { opacity: 0, scale: 1.7 }, { opacity: 1, scale: 1, duration: 0.35, delay: 1.7, ease: "back.out(2.4)" });
          }
        } else {
          gsap.set(t, { backgroundColor: "rgba(232,246,251,.22)" });
          gsap.set(stamp, { opacity: 0, scale: 1.6 });
        }
      },
    };
  })();

  /* ============ 4 · Presentamos a Yumi ============ */
  (function () {
    function doc(y, icon, label) {
      return '<div class="panel abs" data-frag="1" style="left:1300px;top:' + y + 'px;width:520px;height:150px;display:flex;align-items:center;gap:26px;padding:0 30px">' +
        I(icon, 74, "#5ee0f0", 1.7) + '<span class="lab" style="font-size:38px;line-height:1.1;flex:1">' + label + '</span>' +
        '<span style="width:54px;height:54px;border-radius:12px;background:#2b6fd1;color:#fff;font-weight:800;font-size:34px;display:flex;align-items:center;justify-content:center">W</span></div>';
    }
    H.solucion =
      eyebrow("03", "La solución") +
      '<div class="abs title" data-anim style="left:96px;top:160px;width:1700px">Yumi prepara el expediente.<br><span class="aqua">La persona decide.</span></div>' +
      '<div class="abs" data-anim style="left:96px;top:520px;width:300px;text-align:center">' + disc("mail", 220, "#e8f6fb", "", "margin:0 auto") + '<div class="lab" style="margin-top:26px">Reclamo</div></div>' +
      '<div class="abs" data-anim style="left:420px;top:600px">' + I("arrow-right", 120, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs" id="sl-yumi" style="left:620px;top:440px;width:420px;text-align:center">' +
        '<div style="width:420px;height:420px;border-radius:50%;background:radial-gradient(circle,rgba(94,224,240,.4),rgba(94,224,240,0) 66%);display:flex;align-items:center;justify-content:center">' + dropSvg(300, "gsl") + "</div>" +
        '<div class="lab" style="font-size:54px;margin-top:-6px;letter-spacing:.1em">YUMI</div></div>' +
      '<div class="abs" data-frag="1" style="left:1060px;top:600px">' + I("arrow-right", 120, "#5ee0f0", 1.6) + "</div>" +
      doc(400, "file-text", "Informe de atención") +
      doc(580, "handshake", "Propuesta de conciliación") +
      doc(760, "gavel", "Resolución") +
      '<div class="abs pill aqua-bg" data-frag="1" style="left:1300px;top:940px">' + I("user-check", 44, "#052b45", 2) + "Revisa y aprueba</div>";
    FX.solucion = {
      level: function () {},
    };
  })();

  /* ============ 5 · El recorrido ============ */
  (function () {
    // centros locales de cada parada (offset respecto a la primera)
    var OFF = [[0, 0], [1500, -400], [3000, 0], [4500, -400], [6000, 0], [7500, -200]];
    function loc(k) { return [960 + OFF[k][0], 540 + OFF[k][1]]; }
    var steps = [
      { icon: "search", t: "Buscar el reclamo", pill: "SYSCO", n: "00" },
      { icon: "target", t: "Definir objetivos", pill: "4,2 s", n: "01" },
      { icon: "scan-search", t: "Analizar las pruebas", pill: "52,8 s", n: "02" },
      { icon: "handshake", t: "Proponer conciliación", pill: "4,2 s", n: "03" },
      { icon: "gavel", t: "Redactar resolución", pill: "4,8 s", n: "04" },
    ];
    var h = "";
    h += '<div class="abs eyebrow" data-anim style="left:96px;top:72px">04 · El recorrido de un reclamo</div>';
    h += '<div class="abs title" data-anim style="left:96px;top:140px;width:760px;font-size:76px">Cinco paradas, una sola gota</div>';
    for (var k = 0; k < 5; k++) {
      var c = loc(k), s = steps[k];
      h += '<div class="abs stop" data-stop="' + k + '" style="left:' + (c[0] - 320) + 'px;top:' + (c[1] - 285) + 'px;width:640px;height:600px;text-align:center">';
      h += '<div class="eyebrow" style="font-size:34px">Parada ' + s.n + "</div>";
      h += '<div class="disc" style="width:300px;height:300px;margin:30px auto 0">' + I(s.icon, 150, "#5ee0f0", 1.6) + "</div>";
      h += '<div class="lab" style="margin-top:40px;font-size:48px">' + s.t + "</div>";
      h += '<div class="pill ' + (k === 2 ? "amber-bg" : "aqua-bg") + '" style="margin-top:26px;font-size:46px">' + s.pill + "</div>";
      h += "</div>";
    }
    // seis iconos pequeños alrededor de la parada 2
    var c2 = loc(2);
    var mini = ["gauge", "receipt", "power", "wallet", "house", "map-pin"];
    for (var m = 0; m < 6; m++) {
      var ang = (m * 60 * Math.PI) / 180;
      var p = [Math.round(c2[0] + 470 * Math.cos(ang)), Math.round(c2[1] - 59 + 175 * Math.sin(ang))];
      h += '<div class="abs minimedio" style="left:' + (p[0] - 42) + 'px;top:' + (p[1] - 42) + 'px;width:84px;height:84px;opacity:.9">' + I(mini[m], 84, "#e8f6fb", 1.6) + "</div>";
    }
    // total
    var c5 = loc(5);
    h += '<div class="abs" data-stop="5" style="left:' + (c5[0] - 700) + 'px;top:' + (c5[1] - 400) + 'px;width:1400px;height:800px;text-align:center">';
    h += '<div class="eyebrow">Suma de las paradas</div>';
    h += '<div class="stat" style="font-size:420px;margin-top:10px">66<span style="font-size:200px"> s</span></div>';
    h += '<div class="sub" style="margin-top:10px">de procesamiento por reclamo</div>';
    h += '<div class="abs" style="left:100px;top:700px;width:1200px;height:34px;border-radius:17px;overflow:hidden;display:flex">' +
      '<div style="width:' + (4.2 / 66 * 100) + '%;background:#5ee0f0"></div><div style="width:' + (52.8 / 66 * 100) + '%;background:#f5b835"></div><div style="width:' + (4.2 / 66 * 100) + '%;background:#5ee0f0"></div><div style="width:' + (4.8 / 66 * 100) + '%;background:#3fd17a"></div></div>';
    h += "</div>";
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
    var cx = 1390, cy = 565;
    var h = eyebrow("05", "Las pruebas") +
      '<div class="abs title" data-anim style="left:96px;top:170px;width:660px;font-size:74px">Yumi lee las seis pruebas que hoy se revisan <span class="aqua">a mano</span></div>' +
      '<div class="abs" data-anim style="left:' + (cx - 160) + 'px;top:' + (cy - 190) + 'px;width:320px;height:320px;border-radius:50%;background:radial-gradient(circle,rgba(94,224,240,.4),rgba(94,224,240,0) 66%);display:flex;align-items:center;justify-content:center">' + dropSvg(220, "gmd") + "</div>";
    for (var i = 0; i < 6; i++) {
      var p = pt(cx, cy, 1, 0);
      var ang = -90 + i * 60;
      var rx = 470, ry = 325;
      var x = Math.round(cx + rx * Math.cos((ang * Math.PI) / 180));
      var y = Math.round(cy - 30 + ry * Math.sin((ang * Math.PI) / 180));
      h += '<div class="abs medio" data-anim style="left:' + (x - 160) + 'px;top:' + (y - 95) + 'px;width:320px;text-align:center">' +
        '<div class="disc" style="width:150px;height:150px;margin:0 auto">' + I(items[i][0], 80, "#5ee0f0", 1.7) + "</div>" +
        '<div class="lab sm" style="margin-top:12px;line-height:1.05">' + items[i][1] + "</div>" +
        '<div class="chk abs center" data-frag="1" style="left:206px;top:-8px;width:60px;height:60px;border-radius:50%;background:#3fd17a">' + I("check", 40, "#052b45", 3) + "</div></div>";
    }
    H.medios = h;
  })();

  /* ============ 7 · La norma ============ */
  (function () {
    var chips = "";
    for (var i = 0; i < 4; i++) {
      chips += '<div class="abs chip" style="left:0;top:' + i * 96 + 'px;width:230px;height:76px;border-radius:18px;background:rgba(94,224,240,.16);border:3px solid rgba(94,224,240,.5);display:flex;align-items:center;gap:14px;padding:0 20px;font-size:38px;font-weight:700">' + I("scroll-text", 40, "#5ee0f0", 1.8) + "Art.</div>";
    }
    H.normativa =
      eyebrow("06", "La norma") +
      '<div class="abs title" data-anim style="left:96px;top:150px;width:1500px;font-size:80px">Cada hallazgo se contrasta con el reglamento de <span class="aqua">SUNASS</span></div>' +
      '<div class="abs" data-anim style="left:96px;top:600px;width:260px;text-align:center">' + disc("file-text", 220, "#e8f6fb", "", "margin:0 auto") + '<div class="lab sm" style="margin-top:20px">Reglamento</div></div>' +
      '<div class="abs" data-anim style="left:400px;top:640px">' + I("arrow-right", 90, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs" id="nm-chips" data-anim style="left:520px;top:560px;width:240px;height:380px">' + chips + "</div>" +
      '<div class="abs" data-anim style="left:790px;top:640px">' + I("arrow-right", 90, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs" data-anim style="left:900px;top:560px;width:300px;text-align:center">' + disc("database", 240, "#5ee0f0", "on", "margin:0 auto") + '<div class="lab sm" style="margin-top:20px">Base vectorial</div></div>' +
      '<div class="abs panel" data-frag="1" style="left:880px;top:390px;width:340px;height:110px;display:flex;align-items:center;gap:20px;padding:0 24px;border-color:#f5b835;background:rgba(245,184,53,.18)">' + I("triangle-alert", 56, "#f5b835", 1.9) + '<span class="lab" style="font-size:42px">Hallazgo</span></div>' +
      '<div class="abs" data-frag="1" style="left:1250px;top:640px">' + I("arrow-right", 90, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs panel solid" data-frag="1" style="left:1380px;top:520px;width:420px;height:400px;border-color:#3fd17a">' +
        '<div class="abs center" style="left:0;top:30px;width:420px;gap:18px">' + I("book-open", 64, "#3fd17a", 1.8) + '<span class="lab" style="font-size:44px">Artículo citado</span></div>' +
        '<div class="abs" style="left:40px;top:150px;width:340px;height:22px;border-radius:11px;background:rgba(232,246,251,.55)"></div>' +
        '<div class="abs" style="left:40px;top:200px;width:300px;height:22px;border-radius:11px;background:rgba(232,246,251,.35)"></div>' +
        '<div class="abs" style="left:40px;top:250px;width:320px;height:22px;border-radius:11px;background:rgba(232,246,251,.35)"></div>' +
        '<div class="abs pill leaf-bg" style="left:40px;top:310px;font-size:34px">' + I("check", 36, "#052b45", 3) + "Fundamenta</div></div>";
    FX.normativa = {
      enter: function (f, tl) {
        var c = f.querySelectorAll(".chip");
        if (c.length) tl.from(c, { x: -120, opacity: 0, duration: 0.4, stagger: 0.12, ease: "power2.out" }, 0.5);
      },
    };
  })();

  /* ============ 8 · El veredicto ============ */
  (function () {
    function obj(i, y, det) {
      return '<div class="panel abs" data-anim style="left:96px;top:' + y + 'px;width:620px;height:130px;display:flex;align-items:center;gap:20px;padding:0 26px">' +
        I("target", 58, "#5ee0f0", 1.8) + '<span class="lab" style="font-size:40px;flex:1;white-space:nowrap">Objetivo ' + i + "</span>" +
        (det ? '<span style="font-size:26px;font-weight:800;background:#ff6b6b;color:#052b45;border-radius:10px;padding:6px 12px">determinante</span>' : "") + "</div>";
    }
    function res(y, txt, cls) {
      return '<div class="abs pill ' + cls + '" data-anim style="left:780px;top:' + y + 'px;font-size:34px;padding:14px 26px">' + txt + "</div>";
    }
    H.veredicto =
      eyebrow("07", "La confianza") +
      '<div class="abs title" data-anim style="left:96px;top:130px;width:1700px">El veredicto no lo decide <span class="aqua">la IA</span></div>' +
      obj(1, 330, true) + obj(2, 490, false) + obj(3, 650, false) +
      '<div class="abs" data-anim style="left:672px;top:300px;width:80px;height:520px"></div>' +
      res(352, "procede", "leaf-bg") + res(512, "sin corrección", "line") + res(672, "no evaluable", "line") +
      '<div class="abs" data-anim style="left:1070px;top:330px;width:120px;height:120px;display:flex;align-items:center;justify-content:center">' + I("sparkles", 100, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs lab sm" data-anim style="left:1020px;top:455px;width:220px;text-align:center;font-size:32px">El modelo<br>evalúa</div>' +
      '<div class="abs panel solid" data-frag="1" style="left:1240px;top:300px;width:580px;height:500px;border-color:#5ee0f0">' +
        '<div class="abs center" style="left:0;top:30px;width:580px;gap:16px">' + I("scale", 64, "#5ee0f0", 1.8) + '<span class="lab" style="font-size:44px">Regla fija</span></div>' +
        '<div class="abs lab" style="left:40px;top:140px;width:500px;text-align:center;font-size:40px;line-height:1.2">¿Algún objetivo determinante procede?</div>' +
        '<div class="abs pill leaf-bg" id="vd-yes" style="left:40px;top:290px;font-size:46px;padding:20px 40px">Sí → FUNDADO</div>' +
        '<div class="abs pill line" style="left:40px;top:400px;font-size:34px;border-color:rgba(232,246,251,.3);opacity:.7">Si no → INFUNDADO</div></div>' +
      '<div class="abs pill aqua-bg" data-frag="2" style="left:1160px;top:850px;font-size:38px">' + I("user-check", 48, "#052b45", 2) + "La persona revisa y aprueba</div>" +
      '<div class="abs" data-frag="2" style="left:1040px;top:846px">' + I("pen-line", 70, "#5ee0f0", 1.7) + "</div>";
    FX.veredicto = {};
  })();

  /* ============ 9 · Dónde corre ============ */
  (function () {
    H.corre =
      eyebrow("08", "Dónde corre") +
      '<div class="abs title" data-anim style="left:96px;top:130px;width:1700px">En su servidor o en la nube. <span class="aqua">Usted elige.</span></div>' +
      '<div class="abs" id="cr-local" style="left:96px;top:380px;width:800px;height:540px;border-radius:40px;border:4px solid rgba(94,224,240,.35);background:rgba(11,79,120,.5);text-align:center" data-anim>' +
        '<div class="abs center" style="left:0;top:40px;width:800px;gap:34px">' + I("server", 190, "#5ee0f0", 1.5) + '<div style="position:relative;width:150px;height:150px" class="center"><span class="lk-open">' + I("lock-open", 140, "#e8f6fb", 1.7) + '</span><span class="lk-closed abs" style="left:0;top:0;opacity:0">' + I("lock", 140, "#3fd17a", 1.7) + "</span></div></div>" +
        '<div class="abs eyebrow" style="left:0;top:290px;width:800px;font-size:44px">Local</div>' +
        '<div class="abs lab" style="left:40px;top:370px;width:720px;font-size:46px;line-height:1.2">Los datos del reclamo no salen de su empresa</div></div>' +
      '<div class="abs" id="cr-cloud" style="left:1024px;top:380px;width:800px;height:540px;border-radius:40px;border:4px solid rgba(232,246,251,.2);background:rgba(11,79,120,.35);text-align:center" data-anim>' +
        '<div class="abs center" style="left:0;top:40px;width:800px">' + I("cloud", 200, "#e8f6fb", 1.4) + "</div>" +
        '<div class="abs eyebrow" style="left:0;top:290px;width:800px;font-size:44px;color:#e8f6fb">Nube</div>' +
        '<div class="abs lab" style="left:40px;top:370px;width:720px;font-size:46px;line-height:1.2">Proveedores externos, con su propia clave</div></div>' +
      '<div class="abs" id="cr-toggle" style="left:810px;top:250px;width:300px;height:110px;border-radius:55px;background:rgba(232,246,251,.25);border:4px solid rgba(232,246,251,.6)" data-anim>' +
        '<div id="cr-knob" class="abs" style="left:10px;top:10px;width:84px;height:84px;border-radius:50%;background:#e8f6fb"></div></div>' +
      '<div class="abs eyebrow" data-anim style="left:560px;top:284px;width:230px;text-align:right;font-size:40px">Local</div>' +
      '<div class="abs eyebrow" data-anim style="left:1130px;top:284px;font-size:40px;color:#e8f6fb">Nube</div>';
    FX.corre = {
      level: function (f, l, prev, imm) {
        var knob = f.querySelector("#cr-knob"), loc = f.querySelector("#cr-local"), cld = f.querySelector("#cr-cloud");
        var open = f.querySelector(".lk-open"), closed = f.querySelector(".lk-closed"), tg = f.querySelector("#cr-toggle");
        var d = imm ? 0 : 0.6;
        gsap.killTweensOf([knob, loc, cld, open, closed, tg]);
        if (l >= 1) {
          gsap.to(knob, { x: 0, duration: d, ease: "power2.inOut" });
          gsap.to(tg, { backgroundColor: "rgba(94,224,240,.55)", borderColor: "#5ee0f0", duration: d });
          gsap.to(loc, { borderColor: "#5ee0f0", boxShadow: "0 0 80px rgba(94,224,240,.45)", duration: d });
          gsap.to(cld, { opacity: 0.35, duration: d });
          gsap.to(open, { opacity: 0, duration: d });
          gsap.to(closed, { opacity: 1, duration: d, delay: imm ? 0 : 0.2 });
        } else {
          gsap.to(knob, { x: 196, duration: d, ease: "power2.inOut" });
          gsap.to(tg, { backgroundColor: "rgba(232,246,251,.25)", borderColor: "rgba(232,246,251,.6)", duration: d });
          gsap.to(loc, { borderColor: "rgba(94,224,240,.35)", boxShadow: "0 0 0 rgba(94,224,240,0)", duration: d });
          gsap.to(cld, { opacity: 1, duration: d });
          gsap.to(open, { opacity: 1, duration: d });
          gsap.to(closed, { opacity: 0, duration: d });
        }
      },
    };
  })();

  /* ============ 10 · Yumi funcionando (cuadros reales de la aplicación, con datos de ejemplo) ============ */
  (function () {
    var LV = [
      { fr: "f01_lista", r: [200, 95, 1180, 720], t: "Elegir el reclamo", s: "Lista de reclamos con inspección realizada", st: "Reclamo" },
      { fr: "f02_datos", r: [330, 95, 910, 380], t: "Datos del reclamo", s: "Motivo, clasificación y fechas, ya cargados", st: "Datos" },
      { fr: "f02_datos", r: [330, 455, 910, 330], t: "Qué hay que probar", s: "Objetivos, con los determinantes marcados", st: "Objetivos" },
      { fr: "c8", r: [1500, 598, 404, 224], t: "Yumi analiza las pruebas", s: "Preprocesa, interpreta y marca Listo", st: "Pruebas" },
      { fr: "f04_modal_tarjeta", r: [500, 185, 910, 670], t: "Cada prueba, explicada", s: "Datos, problemas y resumen editable", st: "Detalle" },
      { fr: "f05_informe", r: [330, 30, 910, 430], t: "El informe se redacta solo", s: "Una sección por cada prueba", st: "Informe" },
      { fr: "f06_conclusion", r: [600, 205, 700, 625], t: "Conclusión con la norma", s: "Fundamentación y problemas determinantes", st: "Conclusión" },
      { fr: "f07_conciliacion", r: [330, 290, 910, 520], t: "Propuesta de conciliación", s: "Lista para aprobar o editar", st: "Conciliación" },
      { fr: "f08_resolucion", r: [330, 430, 910, 590], t: "Resolución y Word", s: "FUNDADO o INFUNDADO, con descarga", st: "Resolución" },
      { fr: "f09_normativa", r: [500, 50, 905, 940], t: "El reglamento, a un clic", s: "Búsqueda en la norma de SUNASS", st: "Normativa" },
      { fr: "f10_inferencia", r: [680, 230, 540, 590], t: "Eligen el modelo", s: "Servidor local o proveedores", st: "Modelo" },
      { fr: "f11_tareas", r: [1500, 330, 404, 700], t: "Todo listo", s: "Ahora, en vivo", st: "Listo" },
    ];
    // estados reales de la corrida: [cuadro, y del elemento activo]
    var PROG = [["c1", 128], ["c2", 380], ["c3", 370], ["c4", 369], ["c5", 380], ["c6", 336], ["c7", 346], ["c8", 698]];
    var FRAMES = ["f01_lista", "f02_datos", "f03_base", "f04_modal_tarjeta", "f05_informe", "f06_conclusion", "f07_conciliacion", "f08_resolucion", "f09_normativa", "f10_inferencia", "f11_tareas", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "c8"];
    var WI = 1440, HI = 788;
    var imgs = "";
    FRAMES.forEach(function (n) {
      imgs += '<img class="dmf" data-f="' + n + '" src="assets/yumi/' + n + '.png" alt="" style="position:absolute;left:0;top:0;width:1904px;height:1041px;opacity:0;display:none">';
    });
    var steps = "";
    LV.forEach(function (v, i) {
      steps += '<div class="dmst" data-i="' + i + '" style="position:absolute;left:1600px;top:' + (214 + i * 60) + 'px;width:300px;height:52px;display:flex;align-items:center;gap:18px;opacity:.45">' +
        '<span class="dot" style="width:22px;height:22px;border-radius:50%;border:4px solid #5ee0f0;background:transparent;flex:none"></span>' +
        '<span style="font-size:32px;font-weight:700;color:#e8f6fb">' + v.st + "</span></div>";
    });
    H.demo =
      '<div class="abs eyebrow" data-anim style="left:96px;top:40px">09 · Yumi funcionando</div>' +
      '<div class="abs title" id="dm-t" data-anim style="left:96px;top:84px;width:1460px;font-size:56px;line-height:1.05">' + LV[0].t + "</div>" +
      '<div class="abs sub" id="dm-s" data-anim style="left:96px;top:150px;width:1460px;font-size:36px">' + LV[0].s + "</div>" +
      '<div class="abs" id="dm-win" data-anim style="left:100px;top:208px;width:' + WI + 'px;height:' + HI + 'px;overflow:hidden;border-radius:24px;background:#eaf6fd;box-shadow:0 40px 90px rgba(0,0,0,.5),0 0 0 3px rgba(94,224,240,.35)">' +
        '<div id="dm-cam" style="position:absolute;left:0;top:0;width:1904px;height:1041px;transform-origin:0 0">' + imgs + "</div></div>" +
      '<div class="abs eyebrow" data-anim style="left:1600px;top:170px;font-size:28px">Recorrido real</div>' +
      steps +
      '<button class="btn-live" id="btn-live" data-frag="11" style="position:absolute;left:150px;top:880px;font-size:40px;padding:22px 36px">En vivo ' + I("external-link", 38, "#052b45", 2.4) + "</button>" +
      '<div class="abs note" data-anim style="left:100px;top:1010px;width:1440px;font-size:26px">Interfaz real de Yumi con datos de ejemplo · nombres y números de cliente reemplazados</div>';

    function camFor(r) {
      var S = Math.min(WI / r[2], HI / r[3]) * 0.96;
      return { x: WI / 2 - S * (r[0] + r[2] / 2), y: HI / 2 - S * (r[1] + r[3] / 2), scale: S };
    }
    function progRect(i) {
      var ya = PROG[i][1];
      return [1400, Math.max(105, ya - 130), 504, 276];
    }
    FX.demo = {
      level: function (f, l, prev, imm) {
        var cam = f.querySelector("#dm-cam");
        var imgsEl = f.querySelectorAll(".dmf");
        var tEl = f.querySelector("#dm-t"), sEl = f.querySelector("#dm-s");
        var v = LV[l];
        if (f.__seq) { f.__seq.kill(); f.__seq = null; }
        gsap.killTweensOf(cam);
        function show(name, d) {
          for (var i = 0; i < imgsEl.length; i++) {
            var im = imgsEl[i];
            gsap.killTweensOf(im);
            if (im.getAttribute("data-f") === name) {
              im.style.display = "block";
              if (d) gsap.to(im, { opacity: 1, duration: d }); else im.style.opacity = "1";
            } else if (im.style.display !== "none") {
              if (d) gsap.to(im, { opacity: 0, duration: d, onComplete: function () { this.targets()[0].style.display = "none"; } });
              else { im.style.opacity = "0"; im.style.display = "none"; }
            }
          }
        }
        function move(r, d, ease) {
          var c = camFor(r);
          gsap.to(cam, { x: c.x, y: c.y, scale: c.scale, duration: d, ease: ease || "power3.inOut" });
        }
        if (l === 3) {
          if (imm) {
            show("c8", 0);
            var cf = camFor(progRect(7));
            gsap.set(cam, { x: cf.x, y: cf.y, scale: cf.scale });
          } else {
            var tl = gsap.timeline();
            PROG.forEach(function (p, i) {
              tl.call(function () { show(p[0], 0.3); move(progRect(i), 0.8, "power2.inOut"); }, null, i * 1.0);
            });
            f.__seq = tl;
          }
        } else {
          show(v.fr, imm ? 0 : 0.55);
          if (imm) {
            var c0 = camFor(v.r);
            gsap.set(cam, { x: c0.x, y: c0.y, scale: c0.scale });
          } else move(v.r, 1.2);
        }
        if (imm) { tEl.textContent = v.t; sEl.textContent = v.s; }
        else {
          gsap.to([tEl, sEl], { opacity: 0, duration: 0.15, onComplete: function () { tEl.textContent = v.t; sEl.textContent = v.s; gsap.to([tEl, sEl], { opacity: 1, duration: 0.3 }); } });
        }
        var sts = f.querySelectorAll(".dmst");
        for (var i = 0; i < sts.length; i++) {
          var on = i <= l, cur = i === l;
          gsap.to(sts[i], { opacity: cur ? 1 : (on ? 0.8 : 0.4), duration: imm ? 0 : 0.3 });
          var dot = sts[i].querySelector(".dot");
          gsap.to(dot, { backgroundColor: on ? "#5ee0f0" : "rgba(0,0,0,0)", scale: cur ? 1.35 : 1, duration: imm ? 0 : 0.3 });
        }
      },
    };
  })();

  /* ============ 11 · Resultados ============ */
  (function () {
    function tile(x, big, small, color) {
      return '<div class="panel abs" data-frag="1" style="left:' + x + 'px;top:650px;width:540px;height:300px;text-align:center;padding-top:30px">' +
        '<div class="stat" style="font-size:' + (big.length > 8 ? 92 : 120) + 'px;color:' + color + ';margin-top:30px">' + big + "</div>" +
        '<div class="lab" style="margin-top:24px;font-size:38px;line-height:1.15;padding:0 24px">' + small + "</div></div>";
    }
    H.resultados =
      eyebrow("10", "Resultados") +
      '<div class="abs title" data-anim style="left:96px;top:130px;width:1700px">66 segundos <span class="aqua">frente a</span> 5 a 11 días</div>' +
      '<div class="abs lab" data-anim style="left:96px;top:330px;width:300px;font-size:44px">Yumi</div>' +
      '<div class="abs" data-anim style="left:420px;top:338px;width:1400px;height:44px;border-radius:22px;background:rgba(232,246,251,.12)"><div id="rs-yumi" class="abs" style="left:0;top:0;width:14px;height:44px;border-radius:22px;background:#5ee0f0;box-shadow:0 0 30px #5ee0f0"></div></div>' +
      '<div class="abs lab aqua" id="rs-yumi-l" data-anim style="left:470px;top:332px;font-size:44px">66 s</div>' +
      '<div class="abs lab" data-anim style="left:96px;top:470px;width:300px;font-size:44px">Manual</div>' +
      '<div class="abs" data-anim style="left:420px;top:478px;width:1400px;height:44px;border-radius:22px;background:rgba(232,246,251,.12)"><div id="rs-man" class="abs" style="left:0;top:0;width:1400px;height:44px;border-radius:22px;background:linear-gradient(90deg,#f5b835,#ff6b6b)"></div></div>' +
      '<div class="abs note" data-anim style="left:420px;top:540px;font-size:30px">Barras fuera de escala: 66 s es una milésima parte</div>' +
      tile(96, "&gt;99,99 %", "menos tiempo de procesamiento", "#5ee0f0") +
      tile(690, "3–5 min", "de revisión de la persona", "#f5b835") +
      tile(1284, "27 450 h", "de ahorro anual proyectado en EMAPA", "#3fd17a") +
      '<div class="abs note" data-frag="1" style="left:96px;top:975px;font-size:28px">20 expedientes de prueba · tiempos manuales estimados y validados con personal de EMAPA San Martín</div>';
    FX.resultados = {
      enter: function (f, tl) {
        tl.fromTo(f.querySelector("#rs-man"), { width: 0 }, { width: 1400, duration: 1.8, ease: "power2.inOut" }, 0.6);
        tl.fromTo(f.querySelector("#rs-yumi"), { opacity: 0.2 }, { opacity: 1, duration: 0.3, yoyo: true, repeat: 7 }, 0.6);
      },
    };
  })();

  /* ============ 12 · Quién lo respalda ============ */
  (function () {
    var nodes = [
      ["trophy", "1.er lugar", "macrorregión Oriente · Datathon SUNASS 2026"],
      ["flag", "Final nacional", "Lima, agosto 2026"],
      ["plug", "En operación", "dentro de SYSCO · EMAPA San Martín"],
    ];
    var h = eyebrow("11", "El respaldo") +
      '<div class="abs title" data-anim style="left:96px;top:130px;width:1700px">Probado en concurso <span class="aqua">y en operación</span></div>' +
      '<div class="abs" data-anim style="left:330px;top:512px;width:1260px;height:8px;border-radius:4px;background:rgba(94,224,240,.3)"></div>';
    for (var i = 0; i < 3; i++) {
      var x = 80 + i * 630;
      h += '<div class="abs hito" ' + (i === 0 ? "data-anim" : 'data-frag="' + i + '"') + ' style="left:' + x + 'px;top:400px;width:500px;text-align:center">' +
        '<div class="disc on" style="width:230px;height:230px;margin:0 auto;background:#0a4468">' + I(nodes[i][0], 120, "#5ee0f0", 1.6) + "</div>" +
        '<div class="lab" style="margin-top:36px;font-size:50px;color:#5ee0f0">' + nodes[i][1] + "</div>" +
        '<div class="lab sm" style="margin-top:12px;font-size:38px;line-height:1.15;font-weight:600">' + nodes[i][2] + "</div></div>";
    }
    H.respaldo = h;
  })();

  /* ============ 13 · La ruta del piloto ============ */
  (function () {
    function step(i, x, hgt, icon, t1, t2) {
      return '<div class="abs panel solid" ' + (i === 0 ? "data-anim" : 'data-frag="' + i + '"') + ' style="left:' + x + 'px;top:' + (940 - hgt) + 'px;width:540px;height:' + hgt + 'px;border-radius:36px 36px 0 0;border-color:#5ee0f0">' +
        '<div class="abs center" style="left:0;top:40px;width:540px">' + I(icon, 110, "#5ee0f0", 1.6) + "</div>" +
        '<div class="abs lab" style="left:24px;top:190px;width:492px;text-align:center;font-size:46px;line-height:1.1">' + t1 + "</div>" +
        (t2 ? '<div class="abs pill amber-bg" style="left:' + 150 + 'px;top:' + (hgt - 110) + 'px;font-size:40px">' + t2 + "</div>" : "") + "</div>";
    }
    H.piloto =
      eyebrow("12", "La ruta") +
      '<div class="abs title" data-anim style="left:96px;top:130px;width:1700px">Un piloto en <span class="aqua">tres peldaños</span></div>' +
      step(0, 96, 440, "git-merge", "En paralelo, sin tocar su proceso", "2 meses") +
      step(1, 690, 560, "plug", "Escribe en su sistema comercial", "") +
      step(2, 1284, 680, "zap", "Reclamos simples en automático", "") +
      '<div class="abs" data-frag="2" style="left:1480px;top:130px">' + I("flag", 110, "#3fd17a", 1.7) + "</div>";
  })();

  /* ============ 14 · Cierre ============ */
  H.cierre =
    '<div class="abs" id="ci-ripples" style="left:960px;top:360px;width:0;height:0">' +
      '<div class="rip abs" style="left:-420px;top:-110px;width:840px;height:220px;border-radius:50%;border:5px solid #5ee0f0;opacity:0"></div>' +
      '<div class="rip abs" style="left:-420px;top:-110px;width:840px;height:220px;border-radius:50%;border:5px solid #5ee0f0;opacity:0"></div></div>' +
    '<div class="abs" data-anim style="left:860px;top:90px;width:200px;height:200px">' + dropSvg(200, "gci") + "</div>" +
    '<div class="abs title" data-anim style="left:160px;top:350px;width:1600px;text-align:center;font-size:104px">Pilotemos con <span class="aqua">20 expedientes</span> de su EPS</div>' +
    '<div class="abs center" data-anim style="left:0;top:690px;width:1920px"><button class="btn-live" id="btn-live2">Abrir Yumi en vivo ' + I("external-link", 54, "#052b45", 2.4) + "</button></div>" +
    '<div class="abs" data-anim style="left:96px;top:850px;width:470px;height:134px;background:#fff;border-radius:28px;display:flex;align-items:center;justify-content:center"><img src="assets/logo-emapa.png" alt="Agua San Martín" style="width:390px;height:auto"></div>' +
    '<div class="abs" data-anim style="left:620px;top:846px;width:900px"><div class="lab" style="font-size:42px;line-height:1.2">Darick Gerald Herrera Castillo</div><div class="lab" style="font-size:42px;line-height:1.2">Jhon Dalton Huamán Quintana</div><div class="note" style="font-size:32px;margin-top:6px">FISI · Universidad Nacional de San Martín</div></div>';
  FX.cierre = {
    enter: function (f, tl) {
      var rips = f.querySelectorAll(".rip");
      for (var i = 0; i < rips.length; i++) {
        tl.fromTo(rips[i], { scale: 0.2, opacity: 0.9 }, { scale: 1.2, opacity: 0, duration: 2.4, ease: "power1.out", repeat: 3 }, 0.4 + i * 1.0);
      }
    },
  };

  /* ============ Ramas ============ */
  (function () {
    function row(t, v, color) {
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:18px 0;border-bottom:2px solid rgba(232,246,251,.14);font-size:40px;font-weight:600"><span>' + t + '</span><span style="color:' + (color || "#e8f6fb") + ';font-weight:800">' + v + "</span></div>";
    }
    H.cifras =
      eyebrow("+", "De dónde salen las cifras") +
      '<div class="abs panel" data-anim style="left:96px;top:190px;width:860px;height:800px;padding:36px 48px">' +
        '<div class="lab" style="font-size:50px;color:#f5b835;margin-bottom:12px">Proceso manual</div>' +
        row("Datos en SYSCO", "1–3 d") + row("Análisis de pruebas", "1–2 d") + row("Norma SUNASS", "0,5–1 d") + row("Informe de atención", "1–2 d") + row("Acta de conciliación", "0,5–1 d") + row("Resolución", "1–2 d") +
        '<div style="display:flex;justify-content:space-between;padding-top:26px;font-size:50px;font-weight:800;color:#f5b835"><span>Total</span><span>5–11 días</span></div></div>' +
      '<div class="abs panel" data-anim style="left:1004px;top:190px;width:820px;height:800px;padding:36px 48px;border-color:#5ee0f0">' +
        '<div class="lab" style="font-size:50px;color:#5ee0f0;margin-bottom:12px">Yumi</div>' +
        row("Objetivos", "4,2 s") + row("Investigación de pruebas", "52,8 s") + row("Conciliación", "4,2 s") + row("Resolución", "4,8 s") +
        '<div style="display:flex;justify-content:space-between;padding-top:26px;font-size:50px;font-weight:800;color:#5ee0f0"><span>Total</span><span>66,0 s</span></div>' +
        '<div class="note" style="margin-top:40px;font-size:32px">20 expedientes de prueba. Más 3–5 min de revisión de la persona.</div></div>';
    function node(x, y, icon, t) {
      return '<div class="abs" data-anim style="left:' + (x - 150) + 'px;top:' + y + 'px;width:300px;text-align:center">' + disc(icon, 170, "#5ee0f0", "", "margin:0 auto") + '<div class="lab sm" style="margin-top:16px;line-height:1.1">' + t + "</div></div>";
    }
    function arr(x, y) { return '<div class="abs" data-anim style="left:' + x + 'px;top:' + y + 'px">' + I("arrow-right", 70, "#5ee0f0", 1.6) + "</div>"; }
    H.arquitectura =
      eyebrow("+", "Arquitectura") +
      '<div class="abs title" data-anim style="left:96px;top:130px;width:1700px;font-size:76px">Por dentro: agentes, normativa y modelos</div>' +
      node(250, 360, "monitor", "Panel web") + arr(410, 410) +
      node(660, 360, "server", "Servicio API") + arr(820, 410) +
      node(1070, 360, "bot", "Agentes") + arr(1230, 410) +
      node(1480, 360, "brain", "Modelo local o nube") +
      node(660, 720, "plug", "Sistema comercial") + node(1070, 720, "database", "Normativa vectorial") +
      '<div class="abs" data-anim style="left:625px;top:640px">' + I("arrow-down", 70, "#5ee0f0", 1.6) + "</div>" +
      '<div class="abs" data-anim style="left:1035px;top:640px">' + I("arrow-down", 70, "#5ee0f0", 1.6) + "</div>";
  })();

  window.YUMI_SCENE_HTML = H;
  window.YUMI_SCENE_FX = FX;
})();
