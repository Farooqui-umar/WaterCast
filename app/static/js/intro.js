(function() {
  "use strict";
  var root = document.documentElement;
  var intro = document.getElementById("intro");
  if (!intro || !root.classList.contains("has-intro")) return;
  var video = document.getElementById("introVideo");
  var scrim = intro.querySelector(".intro-scrim");
  var reduce = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  var DOCK_LOGO = [0.0729, 0.2338, 0.381, 0.2853];
  var DOCK_MAP = [0.47, 0.1047, 0.79, 0.489];
  var SNAP_LOGO = { r: [0, 0, 0.46, 1], f: { l: 0, r: 0.08, t: 0, b: 0 } };
  var SNAP_MAP = { r: [0.38, 0, 1, 1], f: { l: 0.08, r: 0, t: 0, b: 0 } };
  var FALLBACK_AR = 2100 / 1728;
  var EASE_GLIDE = "cubic-bezier(.19,1,.22,1)";
  var EASE_SOFT = "cubic-bezier(.4,0,.2,1)";
  var T = { glide: 1100, snapDelay: 60, snapFade: 520, liveFade: 460, scrimDelay: 40, scrim: 440, bloom: 950 };
  var EASE_LIGHT = "cubic-bezier(.33,0,.4,1)";
  var started = false, finished = false, objectUrl = null, fontsOk = false;
  var anims = [], snaps = [];
  var $ = function(s) {
    return document.querySelector(s);
  };
  var $$ = function(s) {
    return Array.prototype.slice.call(document.querySelectorAll(s));
  };
  var header = $(".site-header");
  var title = $("#page-0 .hero-title");
  var tag = $("#page-0 .hero-tag");
  var desc = $("#page-0 .hero-desc");
  var mapEl = $("#page-0 .map-stage");
  var legend = $("#page-0 .legend");
  var rule = $("#page-0 .rule");
  var stats = $$("#page-0 .stat");
  var cards = $$("#page-0 .feature-card");
  function wait(ms) {
    return new Promise(function(r) {
      setTimeout(r, ms);
    });
  }
  function makeVideoUrl() {
    return "/static/media/intro.mp4";
  }
  function fitted() {
    var r = intro.getBoundingClientRect();
    var ar = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : FALLBACK_AR;
    var w = r.width, h = r.width / ar;
    if (h > r.height) {
      h = r.height;
      w = h * ar;
    }
    return { x: r.left + (r.width - w) / 2, y: r.top + (r.height - h) / 2, w, h };
  }
  function box(fit, n) {
    return { x: fit.x + n[0] * fit.w, y: fit.y + n[1] * fit.h, w: (n[2] - n[0]) * fit.w, h: (n[3] - n[1]) * fit.h };
  }
  function liveTitleRect() {
    var rg = document.createRange();
    rg.selectNodeContents(title);
    return rg.getBoundingClientRect();
  }
  function liveMapRect() {
    var g = mapEl.querySelector("img") || mapEl.querySelector("svg > g[filter]:not([opacity])") || mapEl.querySelector("svg") || mapEl;
    return g.getBoundingClientRect();
  }
  function snapshot(def, fit) {
    var vw = video.videoWidth, vh = video.videoHeight;
    var r = def.r, f = def.f;
    var sx = r[0] * vw, sy = r[1] * vh, sw = (r[2] - r[0]) * vw, sh = (r[3] - r[1]) * vh;
    var c = document.createElement("canvas");
    c.width = Math.max(1, Math.round(sw));
    c.height = Math.max(1, Math.round(sh));
    var ctx = c.getContext("2d");
    ctx.drawImage(video, sx, sy, sw, sh, 0, 0, c.width, c.height);
    var rw = r[2] - r[0], rh = r[3] - r[1];
    function ramp(x0, y0, x1, y1, a, b) {
      var g = ctx.createLinearGradient(x0, y0, x1, y1);
      g.addColorStop(0, "rgba(0,0,0," + (a > 0 ? 0 : 1) + ")");
      g.addColorStop(Math.max(a, 1e-4), "rgba(0,0,0,1)");
      g.addColorStop(1 - Math.max(b, 1e-4), "rgba(0,0,0,1)");
      g.addColorStop(1, "rgba(0,0,0," + (b > 0 ? 0 : 1) + ")");
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, c.width, c.height);
    }
    ctx.globalCompositeOperation = "destination-in";
    ramp(0, 0, c.width, 0, f.l / rw, f.r / rw);
    ramp(0, 0, 0, c.height, f.t / rh, f.b / rh);
    var rect = box(fit, r);
    c.className = "intro-snap";
    c.style.left = rect.x + "px";
    c.style.top = rect.y + "px";
    c.style.width = rect.w + "px";
    c.style.height = rect.h + "px";
    return { canvas: c, left: rect.x, top: rect.y };
  }
  function looksPainted(snap, dock, fit, minLevel) {
    try {
      var c = snap.canvas, ctx = c.getContext("2d");
      var k = c.width / parseFloat(c.style.width);
      var y = Math.round((dock.y + dock.h / 2 - snap.top) * k);
      var x = Math.round((dock.x - snap.left) * k), w = Math.max(1, Math.round(dock.w * k));
      var d = ctx.getImageData(Math.max(0, x), Math.max(0, Math.min(c.height - 1, y)), Math.min(w, c.width - Math.max(0, x)), 1).data;
      var m = 0;
      for (var i = 0; i < d.length; i += 4) m = Math.max(m, d[i], d[i + 1], d[i + 2]);
      return m >= minLevel;
    } catch (e) {
      return false;
    }
  }
  function pair(el, live, dock, snap, mode) {
    var er = el.getBoundingClientRect();
    var lcx = live.left + live.width / 2, lcy = live.top + live.height / 2;
    var dcx = dock.x + dock.w / 2, dcy = dock.y + dock.h / 2;
    var sx = dock.w / live.width, sy = dock.h / live.height;
    var s = mode === "w" ? sx : Math.sqrt(sx * sy);
    if (!(s > 0.15 && s < 6) || !isFinite(lcx + lcy + dcx + dcy)) return null;
    var dx = lcx - dcx, dy = lcy - dcy;
    return {
      liveOrigin: lcx - er.left + "px " + (lcy - er.top) + "px",
      liveFrom: "translate(" + -dx + "px," + -dy + "px) scale(" + s + ")",
      snapOrigin: dcx - snap.left + "px " + (dcy - snap.top) + "px",
      snapTo: "translate(" + dx + "px," + dy + "px) scale(" + 1 / s + ")"
    };
  }
  function A(el, kf, o) {
    var a = el.animate(kf, Object.assign({ fill: "both" }, o));
    anims.push(a);
    return a;
  }
  function run(lift) {
    var move = !reduce;
    var fit = fitted();
    var pT = null, pM = null, sL = null, sM = null;
    if (lift && move && video.videoWidth) {
      var tRect = liveTitleRect(), mRect = liveMapRect();
      var dL = box(fit, DOCK_LOGO), dM = box(fit, DOCK_MAP);
      sL = snapshot(SNAP_LOGO, fit);
      sM = snapshot(SNAP_MAP, fit);
      if (looksPainted(sL, dL, fit, 200) && looksPainted(sM, dM, fit, 60)) {
        pT = pair(title, tRect, dL, sL, "w");
        pM = pair(mapEl, mRect, dM, sM, "avg");
      }
      if (!pT || !pM) {
        sL = sM = pT = pM = null;
      }
    }
    var lifted = !!(pT && pM);
    if (lifted) {
      document.body.appendChild(sL.canvas);
      document.body.appendChild(sM.canvas);
      snaps.push(sL.canvas, sM.canvas);
      video.style.visibility = "hidden";
      [[sL, pT], [sM, pM]].forEach(function(x) {
        x[0].canvas.style.transformOrigin = x[1].snapOrigin;
        A(x[0].canvas, [{ transform: "none" }, { transform: x[1].snapTo }], { duration: T.glide, easing: EASE_GLIDE });
        A(x[0].canvas, [{ opacity: 1 }, { opacity: 0 }], { delay: T.snapDelay, duration: T.snapFade, easing: "ease-in-out" });
      });
      title.style.transformOrigin = pT.liveOrigin;
      A(title, [{ transform: pT.liveFrom }, { transform: "none" }], { duration: T.glide, easing: EASE_GLIDE });
      A(title, [{ opacity: 0 }, { opacity: 1 }], { duration: T.liveFade, easing: "ease-out" });
      mapEl.style.transformOrigin = pM.liveOrigin;
      A(mapEl, [{ transform: pM.liveFrom }, { transform: "none" }], { duration: T.glide, easing: EASE_GLIDE });
      A(mapEl, [{ opacity: 0 }, { opacity: 1 }], { duration: T.liveFade, easing: "ease-out" });
      A(scrim, [{ opacity: 0.996 }, { opacity: 0 }], { delay: T.scrimDelay, duration: T.scrim, easing: EASE_LIGHT });
    } else {
      var quick = !move ? 500 : 750;
      A(intro, [{ opacity: 1 }, { opacity: 0 }], { duration: quick, easing: EASE_SOFT });
      A(title, [{ opacity: 0 }, { opacity: 1 }], { delay: 60, duration: 600, easing: "ease-out" });
      A(mapEl, [{ opacity: 0 }, { opacity: 1 }], { delay: 60, duration: 600, easing: "ease-out" });
    }
    if (move) {
      A(title, [
        { textShadow: "0 0 14px rgba(84,120,255,.95), 0 0 38px rgba(52,84,255,.80), 0 0 84px rgba(36,60,255,.60)" },
        { textShadow: "0 0 0 rgba(84,120,255,0), 0 0 0 rgba(52,84,255,0), 0 0 0 rgba(36,60,255,0)" }
      ], { delay: 40, duration: T.bloom, easing: "ease-out" });
    }
    function rise(el, delay, dur, dy) {
      if (!el) return;
      A(
        el,
        [{ opacity: 0, transform: move ? "translateY(" + dy + "px)" : "none" }, { opacity: 1, transform: "none" }],
        { delay, duration: dur, easing: EASE_GLIDE }
      );
    }
    if (!lifted) {
      var base = 150;
      rise(header, base + 240, 800, -14);
      rise(tag, base + 260, 800, 16);
      rise(desc, base + 340, 800, 16);
      rise(legend, base + 500, 800, 12);
      if (rule) A(rule, [{ opacity: 0 }, { opacity: 1 }], { delay: base + 480, duration: 700, easing: "ease-out" });
      stats.forEach(function(el, i) {
        rise(el, base + 460 + i * 80, 800, 16);
      });
      cards.forEach(function(el, i) {
        rise(el, base + 560 + i * 100, 900, 30);
      });
    }
    root.classList.add("intro-live");
    intro.style.pointerEvents = "none";
    Promise.all(anims.map(function(a) {
      return a.finished.catch(function() {
      });
    })).then(cleanup);
    setTimeout(cleanup, 3e3);
  }
  function cleanup() {
    if (finished) return;
    finished = true;
    clearTimeout(window.__introGuard);
    root.classList.remove("has-intro", "intro-live");
    root.classList.add("intro-done");
    anims.forEach(function(a) {
      try {
        a.cancel();
      } catch (e) {
      }
    });
    [title, mapEl].forEach(function(el) {
      if (el) el.style.transformOrigin = "";
    });
    snaps.forEach(function(c) {
      c.remove();
    });
    intro.remove();
    try {
      video.removeAttribute("src");
      video.load();
    } catch (e) {
    }
    objectUrl = null;
    window.removeEventListener("pointerdown", onSkip, true);
    window.removeEventListener("keydown", onSkip, true);
  }
  function handoff(lift) {
    if (started) return;
    started = true;
    clearTimeout(startGuard);
    clearTimeout(window.__introGuard);
    if (!lift) {
      try {
        video.pause();
      } catch (e) {
      }
    }
    function go() {
      try {
        run(lift);
      } catch (err) {
        try {
          console.warn("WaterCast intro: falling back to a simple reveal", err);
        } catch (e) {
        }
        anims.forEach(function(a) {
          try {
            a.cancel();
          } catch (e) {
          }
        });
        anims = [];
        snaps.forEach(function(c) {
          c.remove();
        });
        snaps = [];
        root.classList.add("intro-live");
        cleanup();
      }
    }
    if (fontsOk || !document.fonts || !document.fonts.ready) go();
    else Promise.race([document.fonts.ready, wait(150)]).then(go);
  }
  function onSkip(e) {
    if (started) return;
    if (e.type === "keydown" && /^(Tab|Shift|Control|Alt|Meta|CapsLock)$/.test(e.key)) return;
    handoff(false);
  }
  window.addEventListener("pointerdown", onSkip, true);
  window.addEventListener("keydown", onSkip, true);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(function() {
    fontsOk = true;
  }, function() {
    fontsOk = true;
  });
  var startGuard = setTimeout(function() {
    handoff(false);
  }, 4500);
  try {
    objectUrl = makeVideoUrl();
  } catch (e) {
    handoff(false);
    return;
  }
  video.muted = true;
  video.defaultMuted = true;
  video.playsInline = true;
  video.addEventListener("playing", function() {
    clearTimeout(startGuard);
  }, { once: true });
  video.addEventListener("ended", function() {
    handoff(true);
  });
  video.addEventListener("error", function() {
    handoff(false);
  });
  video.src = objectUrl;
  var p = video.play();
  if (p && p.catch) p.catch(function() {
    handoff(false);
  });
})();
