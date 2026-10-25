(function() {
  var sleep = function(ms) {
    return new Promise(function(r) {
      setTimeout(r, ms);
    });
  };
  function make(o) {
    o = o || {};
    var el = document.createElement("div");
    el.className = "wc-prog" + (o.compact ? " compact" : "") + (o.center ? " center" : "") + (o.full ? " full" : "") + (o.hideLabel ? " nolabel" : "") + (o.theme ? " " + o.theme : "");
    el.setAttribute("role", "progressbar");
    el.setAttribute("aria-valuemin", "0");
    el.setAttribute("aria-valuemax", "100");
    el.setAttribute("aria-valuenow", "0");
    el.innerHTML = '<div class="wc-prog-top"><span class="wc-prog-label"></span><span class="wc-prog-pct">0%</span></div><div class="wc-prog-track"><div class="wc-prog-fill"></div></div>';
    el.querySelector(".wc-prog-label").textContent = o.label || "Loading";
    return el;
  }
  function mount(host, o) {
    o = o || {};
    var mode = o.mode || "replace";
    var el = make(o), wrap = el, prev = null;
    if (mode === "replace") {
      prev = host.innerHTML;
      wrap = document.createElement("div");
      wrap.className = "wc-load-block" + (o.compact ? " compact-block" : "");
      wrap.appendChild(el);
      host.innerHTML = "";
      host.appendChild(wrap);
    } else if (mode === "after") {
      host.insertAdjacentElement("afterend", el);
    } else {
      host.appendChild(el);
    }
    var fill = el.querySelector(".wc-prog-fill"), pctEl = el.querySelector(".wc-prog-pct"), labelEl = el.querySelector(".wc-prog-label");
    var p = 0, alive = true, timer = null, t0 = performance.now();
    var minMs = o.min == null ? 650 : o.min, tail = o.tail == null ? 320 : o.tail;
    function set(v) {
      p = v;
      fill.style.width = v + "%";
      pctEl.textContent = v + "%";
      el.setAttribute("aria-valuenow", String(v));
    }
    function tick() {
      if (!alive) return;
      var cap = 90 + Math.random() * 6;
      var step = 2 + Math.random() * 15;
      var np = Math.min(cap, p + step * (1 - p / 108));
      if (np > p) set(Math.round(np));
      timer = setTimeout(tick, 100 + Math.random() * 280);
    }
    timer = setTimeout(tick, 90);
    function gone() {
      return !wrap.parentNode;
    }
    var ctl = {
      el,
      label: function(t) {
        labelEl.textContent = t;
        labelEl.style.animation = "none";
        void labelEl.offsetWidth;
        labelEl.style.animation = "";
      },
      set,
      done: function() {
        var wait = minMs - (performance.now() - t0);
        return sleep(Math.max(0, wait)).then(function() {
          alive = false;
          clearTimeout(timer);
          set(100);
          return sleep(tail);
        }).then(function() {
          wrap.classList.add("wc-out");
          return sleep(220);
        }).then(function() {
          if (mode !== "replace" && wrap.parentNode) wrap.parentNode.removeChild(wrap);
        });
      },
      restore: function() {
        alive = false;
        clearTimeout(timer);
        if (mode === "replace" && prev != null && host.contains(wrap)) host.innerHTML = prev;
        else if (!gone() && mode !== "replace") wrap.parentNode.removeChild(wrap);
      },
      cancel: function() {
        ctl.restore();
      }
    };
    return ctl;
  }
  function reveal(host) {
    if (!host) return;
    host.classList.remove("wc-reveal");
    void host.offsetWidth;
    host.classList.add("wc-reveal");
    setTimeout(function() {
      host.classList.remove("wc-reveal");
    }, 1e3);
  }
  window.WCProg = { make, mount, reveal, sleep };
})();
