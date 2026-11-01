/* Símbolo original de Yumi, tomado de assets/yumi-icon.svg.
   Conserva la API de la mascota y los tamaños usados por las escenas.
   Las cintas, sus colores y sus huecos corresponden al SVG de origen. */
(function (root) {
  var ART = "<defs>\n    <linearGradient id=\"yumi-orbit-back\" x1=\"12\" y1=\"50\" x2=\"48\" y2=\"7\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#0039df\"/>\n      <stop offset=\"0.55\" stop-color=\"#0056f1\"/>\n      <stop offset=\"1\" stop-color=\"#0739c9\"/>\n    </linearGradient>\n    <linearGradient id=\"yumi-orbit-base\" x1=\"19\" y1=\"55\" x2=\"58\" y2=\"37\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#0086ec\"/>\n      <stop offset=\"0.55\" stop-color=\"#14b9d0\"/>\n      <stop offset=\"1\" stop-color=\"#20cbb7\"/>\n    </linearGradient>\n    <linearGradient id=\"yumi-orbit-top\" x1=\"14\" y1=\"11\" x2=\"43\" y2=\"19\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#079fb6\"/>\n      <stop offset=\"0.6\" stop-color=\"#00859e\"/>\n      <stop offset=\"1\" stop-color=\"#22c6d6\"/>\n    </linearGradient>\n    <linearGradient id=\"yumi-orbit-front\" x1=\"17\" y1=\"20\" x2=\"30\" y2=\"50\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#61eee1\"/>\n      <stop offset=\"0.35\" stop-color=\"#00c5ed\"/>\n      <stop offset=\"0.72\" stop-color=\"#0072f3\"/>\n      <stop offset=\"1\" stop-color=\"#0040e4\"/>\n    </linearGradient>\n    <linearGradient id=\"yumi-orbit-rise\" x1=\"53\" y1=\"9\" x2=\"33\" y2=\"45\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#438fff\"/>\n      <stop offset=\"0.45\" stop-color=\"#0068f6\"/>\n      <stop offset=\"1\" stop-color=\"#0030cc\"/>\n    </linearGradient>\n  </defs>\n\n  <!-- Cintas vectoriales entrelazadas; los huecos conservan transparencia. -->\n  <path d=\"M14 29C5 40 3 50 10 55c6 5 17 2 29-7C52 38 59 24 58 13 57 5 50 3 43 6L31 12c9-3 17-4 19 0 4 7-2 19-12 30-9 10-18 14-23 11-5-3-3-13 3-21Z\" fill=\"url(#yumi-orbit-back)\"/>\n  <path d=\"M55 28c8 12 5 23-6 29-9 5-23 4-32-1 10 2 22-2 30-10 6-6 9-12 8-18Z\" fill=\"url(#yumi-orbit-base)\"/>\n  <path d=\"M14 11c8-5 21 0 32 8-13-6-22-4-29 2-4-2-6-6-3-10Z\" fill=\"url(#yumi-orbit-top)\"/>\n  <path d=\"M14 11c-5 9 5 14 13 20 8 6 10 12 5 20-5 8-16 9-23 4 7 3 15 3 18-2 3-5-3-10-10-16C7 28 7 17 14 11Z\" fill=\"url(#yumi-orbit-front)\"/>\n  <path d=\"M52 5c9 4 2 15-8 25-7 7-9 8-9 16 0 3-1 6-3 8 13-9 23-22 26-33 2-8 0-14-6-16Z\" fill=\"url(#yumi-orbit-rise)\"/>\n  <path d=\"M52 5c4 5 1 11-4 17 7-6 9-13 4-17Z\" fill=\"#90c7ff\" opacity=\"0.55\"/>";
  var POSES = {
    idle:    { tilt: 0,  x: 0,   scale: 1,    dots: false },
    wave:    { tilt: 4,  x: 0,   scale: 1,    dots: false },
    point:   { tilt: -3, x: 8,   scale: 1,    dots: false },
    think:   { tilt: -7, x: 0,   scale: 0.97, dots: true },
    cheer:   { tilt: 0,  x: 0,   scale: 1.06, dots: false },
    present: { tilt: 0,  x: 0,   scale: 1.03, dots: false },
    left:    { tilt: 3,  x: -8,  scale: 1,    dots: false }
  };
  var serial = 0;
  function svg(o) {
    o = o || {};
    var id = (o.id || "yumi") + "-" + serial++;
    var P = POSES[o.pose] || POSES.idle;
    var W = o.width || 400, H = o.height || Math.round(W * 470 / 400);
    var compact = o.crop === "head", cy = compact ? 200 : 235;
    var art = ART.replace(/id="([^"]+)"/g, 'id="' + id + '-$1"')
      .replace(/url\(#([^)]+)\)/g, 'url(#' + id + '-$1)');
    var s = '<svg xmlns="http://www.w3.org/2000/svg" class="yumi-bot ' + (o.cls || "") + '" width="' + W + '" height="' + H + '" viewBox="0 0 400 ' + (compact ? 400 : 470) + '" aria-hidden="true">';
    if (!compact) {
      s += '<ellipse class="bot-shadow" cx="200" cy="452" rx="78" ry="11" fill="#0086ec" opacity=".22"/>';
    }
    s += '<g class="yumi-voice"><g class="yumi-gesture"><g class="yumi-symbol" data-origin="200 ' + cy + '" transform="translate(' + P.x + ' 0) rotate(' + P.tilt + ' 200 ' + cy + ')">';
    s += '<svg x="40" y="' + (compact ? 40 : 75) + '" width="320" height="320" viewBox="0 0 64 64">' + art + '</svg>';
    s += '</g></g></g>';
    if (!compact) {
      s += '<g class="bot-dots" opacity="' + (P.dots ? 1 : 0) + '"><circle cx="334" cy="70" r="6" fill="#14b9d0"/><circle cx="354" cy="48" r="9" fill="#14b9d0"/><circle cx="382" cy="24" r="12" fill="#14b9d0"/></g>';
    }
    return s + '</svg>';
  }
  var api = { svg: svg, POSES: POSES, VIEW: [400, 470] };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.YumiRobot = api;
})(typeof window !== "undefined" ? window : this);
