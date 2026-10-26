/* El proceso se sigue en SYSCO. Yumi apoya el análisis y la redacción.
   Cada elemento de STEPS es una pulsación de Siguiente dentro de la demo.
   crop = [x, y, ancho, alto] sobre la captura original, sin modificar el PNG. */
(function () {
  var PHASES = ["1 · Ingreso", "2 · Atención", "3 · Conciliación", "4 · Resolución"];
  var STEPS = [
    {
      phase: 0, title: "1 · Ingreso y seguimiento del reclamo",
      subtitle: "SYSCO reúne los datos del reclamo y permite consultar su estado.",
      left: { image: "sysco/detalle_atencion_1", crop: [110, 145, 1120, 380], label: "SYSCO · Datos del reclamo", caption: "Responsable, domicilio, datos y tipo de reclamo." },
      right: { image: "sysco/lista_atencion", crop: [8, 210, 1334, 330], label: "SYSCO · Seguimiento", caption: "Listado de reclamos, oficina responsable y estado de atención." },
      outcome: "El registro y el seguimiento permanecen en el sistema central.",
      say: "El proceso empieza en SYSCO", pose: "left"
    },
    {
      phase: 1, title: "2 · Atención: inspecciones e investigación",
      subtitle: "El personal realiza las inspecciones y reúne los medios probatorios aplicables.",
      left: { image: "sysco/detalle_atencion_2", crop: [85, 275, 1180, 274], label: "SYSCO · Inspecciones y atención", caption: "Inspecciones interna y externa y campo para el informe de atención." },
      right: { image: "yumi/f02_datos", crop: [330, 108, 905, 626], label: "Yumi · Investigación del reclamo", caption: "Consulta los datos y define qué debe investigar con las pruebas disponibles." },
      outcome: "Con las inspecciones realizadas, Yumi interviene en la investigación.",
      say: "¿Qué provocó el reclamo?", pose: "think"
    },
    {
      phase: 1, title: "2 · Atención: análisis de medios probatorios",
      subtitle: "Yumi analiza los medios aplicables y explica los hallazgos para la atención del reclamo.",
      left: { image: "sysco/detalle_atencion_2", crop: [85, 275, 1180, 274], label: "SYSCO · Atención del reclamo", caption: "Las inspecciones y la investigación forman parte de esta etapa." },
      right: { image: "yumi/f04_modal_tarjeta", crop: [504, 190, 900, 664], label: "Yumi · Análisis de un medio", caption: "Datos obtenidos, problemas encontrados e interpretación editable." },
      outcome: "Los hallazgos del análisis sustentan el informe de atención.",
      say: "Analizo los medios aplicables", pose: "point"
    },
    {
      phase: 1, title: "2 · Atención: informe elaborado por Yumi",
      subtitle: "Yumi genera el informe de atención a partir del análisis de los medios probatorios.",
      left: { image: "sysco/detalle_atencion_2", crop: [85, 275, 1180, 184], label: "SYSCO · Campo del informe", caption: "El personal registra aquí el informe de atención revisado." },
      right: { image: "yumi/f05_informe", crop: [355, 48, 860, 460], label: "Yumi · Informe de atención", caption: "El documento reúne los resultados de la investigación para su revisión." },
      outcome: "El personal revisa el informe preparado por Yumi y lo registra en SYSCO.",
      say: "Preparo el informe de atención", pose: "present"
    },
    {
      phase: 2, title: "3 · Conciliación: seguimiento en SYSCO",
      subtitle: "SYSCO permite identificar los reclamos que pasan a conciliación y consultar su estado.",
      left: { image: "sysco/lista_conciliacion", crop: [8, 183, 1334, 355], label: "SYSCO · Reclamos en conciliación", caption: "La lista muestra las fechas, la oficina responsable y el estado del reclamo." },
      right: { image: "yumi/f07_conciliacion", crop: [350, 375, 867, 174], label: "Yumi · Propuesta de la empresa", caption: "Yumi prepara la propuesta tomando como base la atención del reclamo." },
      outcome: "La propuesta de conciliación parte del informe de atención.",
      say: "Propongo con base en la atención", pose: "present"
    },
    {
      phase: 2, title: "3 · Conciliación: datos y resultado",
      subtitle: "El personal conduce la conciliación y registra sus datos en el sistema central.",
      left: { image: "sysco/detalle_conciliacion_1", crop: [85, 300, 1180, 256], label: "SYSCO · Datos de conciliación", caption: "Fecha, asistencia, subsistencia del reclamo y resultado de la conciliación." },
      right: { image: "yumi/f07_conciliacion", crop: [336, 300, 900, 375], label: "Yumi · Apoyo a la propuesta", caption: "La propuesta se puede revisar y editar antes de registrarla." },
      outcome: "El personal lleva la conciliación. Yumi apoya la elaboración de la propuesta.",
      say: "La propuesta queda para revisión", pose: "idle"
    },
    {
      phase: 2, title: "3 · Conciliación: propuesta de la empresa",
      subtitle: "La propuesta revisada y los acuerdos se registran en los campos de SYSCO.",
      left: { image: "sysco/detalle_conciliacion_2", crop: [150, 50, 1048, 405], label: "SYSCO · Propuesta y acuerdos", caption: "Propuesta de la empresa, respuesta del reclamante y puntos de acuerdo." },
      right: { image: "yumi/f07_conciliacion", crop: [350, 375, 867, 174], label: "Yumi · Propuesta preparada", caption: "La propuesta se fundamenta en el análisis y el informe de atención." },
      outcome: "El personal revisa la propuesta y registra lo acordado en SYSCO.",
      say: "Preparo la propuesta de la empresa", pose: "present"
    },
    {
      phase: 3, title: "4 · Resolución: seguimiento del reclamo",
      subtitle: "El sistema central permite consultar las resoluciones y sus fechas de seguimiento.",
      left: { image: "sysco/lista_resolucion", crop: [18, 209, 1314, 350], label: "SYSCO · Reclamos en resolución", caption: "Estado, fecha de resolución, fecha máxima de notificación y acciones." },
      right: { image: "yumi/f08_resolucion", crop: [350, 430, 866, 590], label: "Yumi · Redacción de la resolución", caption: "La resolución utiliza la atención y el resultado de la conciliación." },
      outcome: "La atención y la conciliación sustentan la resolución que redacta Yumi.",
      say: "Reúno la atención y la conciliación", pose: "think"
    },
    {
      phase: 3, title: "4 · Resolución: antecedentes del reclamo",
      subtitle: "SYSCO conserva los datos y las fechas de atención y conciliación del expediente.",
      left: { image: "sysco/detalle_resolucion_1", crop: [238, 355, 874, 240], label: "SYSCO · Datos para la resolución", caption: "Identificación del reclamo y fechas de atención, conciliación y resolución." },
      right: { image: "yumi/f08_resolucion", crop: [350, 430, 866, 400], label: "Yumi · Fundamentos de la resolución", caption: "Redacta los fundamentos a partir de la atención y la conciliación." },
      outcome: "Yumi prepara la redacción para que el personal la revise y apruebe.",
      say: "Redacto con los antecedentes", pose: "present"
    },
    {
      phase: 3, title: "4 · Resolución: redacción y registro",
      subtitle: "El personal revisa la resolución preparada por Yumi y la registra en SYSCO.",
      left: { image: "sysco/detalle_resolucion_2", crop: [150, 315, 1047, 240], label: "SYSCO · Registro de la resolución", caption: "Texto de la resolución, fechas y opciones para guardar y firmar." },
      right: { image: "yumi/f08_resolucion", crop: [350, 430, 866, 590], label: "Yumi · Resolución preparada", caption: "Documento basado en la atención y conciliación, listo para revisión." },
      outcome: "SYSCO conserva el registro y seguimiento. El personal revisa y aprueba.",
      say: "La resolución queda para aprobación", pose: "cheer"
    }
  ];

  // Cada captura conserva su PNG original y sus etiquetas editables.
  var CAPTURE_LABELS = {
    "yumi/f05_informe": [
      { text: "INFORME N.° 251984-2026", x: 378, y: 59, width: 350, bg: "#f8fdff", color: "#003a5d", size: 14 }
    ],
    "yumi/f07_conciliacion": [
      { text: "reclamo, en base al Informe de Atención N.° 251984-2026.", x: 366, y: 519, width: 840, bg: "#f3f4f6" }
    ],
    "yumi/f08_resolucion": [
      { text: "QUE, SEGÚN INFORME N.° 251984-2026 DE FECHA 18 DE OCTUBRE DEL 2026, INFORMA EN ATENCIÓN AL RECLAMO", x: 366, y: 460, width: 840, bg: "#f3f4f6" },
      { text: "ACUERDO A LO ESTABLECIDO EN EL INFORME DE ATENCIÓN N.° 251984-2026.", x: 366, y: 700, width: 840, bg: "#f3f4f6" },
      { text: "PRESTACIÓN DE SERVICIOS DE SANEAMIENTO RESPECTIVAMENTE; LA EMPRESA PRESTADORA ESTÁ FACULTADA PARA", x: 366, y: 780, width: 840, bg: "#f3f4f6" }
    ]
  };
  function escape(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function capture(pane) {
    var r = pane.crop, scale = Math.min(838 / r[2], 420 / r[3]);
    var x = (838 - r[2] * scale) / 2;
    var y = (420 - r[3] * scale) / 2;
    var result = '<div class="demo-screen"><div style="position:absolute;left:' + x + 'px;top:' + y + 'px;width:' + r[2] + 'px;height:' + r[3] + 'px;overflow:hidden;transform-origin:0 0;transform:scale(' + scale + ')"><div class="demo-capture" style="left:' + (-r[0]) + 'px;top:' + (-r[1]) + 'px">';
    result += '<img src="assets/' + pane.image + '.png" alt="' + escape(pane.label) + '">';
    (CAPTURE_LABELS[pane.image] || []).forEach(function (label) {
      result += '<div style="position:absolute;left:' + label.x + 'px;top:' + label.y + 'px;width:' + label.width + 'px;height:20px;background:' + label.bg + ';color:' + (label.color || "#000") + ';font: ' + (label.size || 13) + 'px/20px Segoe UI,Arial,sans-serif;white-space:nowrap;overflow:hidden">' + escape(label.text) + '</div>';
    });
    return result + '</div></div></div>';
  }
  function paneHTML(pane, side) {
    return '<div class="demo-pane ' + side + (pane.image.indexOf("yumi/") === 0 ? ' source-yumi' : '') + '"><div class="demo-pane-label">' + escape(pane.label) + '</div>' + capture(pane) + '<div class="demo-caption">' + escape(pane.caption) + '</div></div>';
  }
  function html(bot) {
    var first = STEPS[0];
    var h = '<div class="tag abs" data-anim style="left:96px;top:40px">08 · Yumi en el proceso de atención</div>';
    h += '<div id="dm-t" class="title demo-heading" data-anim>' + escape(first.title) + '</div>';
    h += '<div id="dm-s" class="sub demo-subtitle" data-anim>' + escape(first.subtitle) + '</div>';
    h += '<div class="demo-phases" data-anim>';
    PHASES.forEach(function (phase, i) {
      h += '<div class="demo-phase' + (i === 0 ? ' is-current' : '') + '" data-phase="' + i + '">' + phase + '</div>';
    });
    h += '</div>';
    STEPS.forEach(function (step, i) {
      h += '<div class="demo-step" data-demo-step="' + i + '" style="opacity:' + (i === 0 ? 1 : 0) + ';visibility:' + (i === 0 ? 'visible' : 'hidden') + '">' + paneHTML(step.left, "left") + paneHTML(step.right, "right") + '</div>';
    });
    h += bot({ x: 1726, y: 4, w: 148, pose: first.pose, id: "dm-bot", d: 0.4, say: first.say, sayId: "dm-say", bx: -620, by: 34, tail: "rr", to: "100% 50%" });
    h += '<div id="dm-outcome" class="demo-outcome">' + escape(first.outcome) + '</div>';
    h += '<button class="btn-live demo-live" id="btn-live" data-frag="' + (STEPS.length - 1) + '">Abrir Yumi</button>';
    h += '<div class="demo-reference">Capturas de referencia de SYSCO y Yumi: muestran pantallas de distintos expedientes.</div>';
    return h;
  }
  var fx = {
    level: function (f, level, prev, immediate) {
      var step = STEPS[level];
      if (!step) return;
      var panels = f.querySelectorAll("[data-demo-step]");
      for (var i = 0; i < panels.length; i++) {
        gsap.killTweensOf(panels[i]);
        if (+panels[i].getAttribute("data-demo-step") === level) {
          gsap.set(panels[i], { visibility: "visible", opacity: immediate ? 1 : 0 });
          if (!immediate) gsap.to(panels[i], { opacity: 1, duration: 0.45, ease: "power2.out" });
        } else gsap.set(panels[i], { opacity: 0, visibility: "hidden" });
      }
      f.querySelector("#dm-t").textContent = step.title;
      f.querySelector("#dm-s").textContent = step.subtitle;
      f.querySelector("#dm-outcome").textContent = step.outcome;
      f.querySelector("#dm-say").textContent = step.say;
      var phases = f.querySelectorAll("[data-phase]");
      for (var j = 0; j < phases.length; j++) {
        var n = +phases[j].getAttribute("data-phase");
        phases[j].classList.toggle("is-current", n === step.phase);
        phases[j].classList.toggle("is-done", n < step.phase);
      }
      var mascot = f.querySelector("#dm-bot");
      mascot.setAttribute("data-pose", step.pose);
      if (window.YumiBotPose) window.YumiBotPose(mascot, step.pose, immediate ? 0 : 0.45);
    }
  };
  window.YumiDemo = { html: html, fx: fx, steps: STEPS, phases: PHASES };
})();
