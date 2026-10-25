(function() {
  "use strict";
  const API = "/api";
  let backendOnline = false;
  const newDeviceId = () => {
    try {
      if (window.crypto && crypto.randomUUID) return "wc-" + crypto.randomUUID();
    } catch (e) {
    }
    return "wc-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  };
  let DEVICE_ID = localStorage.getItem("wc_device_id");
  if (!DEVICE_ID || !/^[A-Za-z0-9._-]{8,64}$/.test(DEVICE_ID)) {
    DEVICE_ID = newDeviceId();
    localStorage.setItem("wc_device_id", DEVICE_ID);
  }
  let IS_ADMIN = false;
  const getCsrf = () => {
    try {
      return sessionStorage.getItem("watercast_csrf");
    } catch (e) {
      return null;
    }
  };
  const clearStaffSession = () => {
    try {
      ["watercast_csrf", "watercast_user", "watercast_geo"].forEach((k) => sessionStorage.removeItem(k));
    } catch (_) {
    }
  };
  const GET_TTL = [["/news/alert-coverage", 6e5], ["/news", 12e4], ["/risk/ticker", 6e4], ["/geocode", 6e5], ["/reverse", 6e5], ["/place", 12e4], ["/tips", 3e5], ["/sos/top", 3e4], ["/trust/", 3e4], ["/community", 15e3], ["/sos?", 15e3]];
  const getCache = new Map();
  const cloneData = (d) => {
    try {
      return structuredClone(d);
    } catch (e) {
      return JSON.parse(JSON.stringify(d));
    }
  };
  function ttlFor(path) {
    for (const [p, t] of GET_TTL) if (path.startsWith(p)) return t;
    return 0;
  }
  async function apiFetch(path, opts) {
    opts = opts || {};
    const method = (opts.method || "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") getCache.clear();
    const ttl = method === "GET" && !opts.fresh ? ttlFor(path) : 0;
    if (!ttl) return rawFetch(path, opts, method);
    if (getCache.size > 200) getCache.clear();
    let entry = getCache.get(path);
    if (!entry || (!entry.pending && Date.now() - entry.t > ttl)) {
      entry = { p: rawFetch(path, opts, method), t: 0, pending: true };
      getCache.set(path, entry);
      const e = entry;
      e.p.then(() => {
        e.pending = false;
        e.t = Date.now();
      }, () => {
        if (getCache.get(path) === e) getCache.delete(path);
      });
    }
    return cloneData(await entry.p);
  }
  function prefetch(path) {
    apiFetch(path).catch(() => {});
  }
  async function rawFetch(path, opts, method) {
    const headers = { "Content-Type": "application/json" };
    const csrf = getCsrf();
    if (csrf && method !== "GET" && method !== "HEAD") headers["X-CSRF-Token"] = csrf;
    const r = await fetch(API + path, Object.assign({ credentials: "same-origin" }, opts, { headers }));
    if (!r.ok) {
      let detail = "";
      try {
        detail = (await r.json()).error || "";
      } catch (e) {
      }
      const err = new Error(String(r.status));
      err.status = r.status;
      err.detail = detail;
      throw err;
    }
    return r.json();
  }
  async function verifyAdmin() {
    try {
      const s = await apiFetch("/auth/session");
      IS_ADMIN = !!s.authenticated;
      if (IS_ADMIN) {
        try {
          sessionStorage.setItem("watercast_csrf", s.csrf || "");
          sessionStorage.setItem("watercast_user", s.user.username);
        } catch (_) {
        }
      } else {
        clearStaffSession();
      }
    } catch (e) {
      IS_ADMIN = false;
    }
    if (window.wcSyncLoginBtn) window.wcSyncLoginBtn();
  }
  (function() {
    let menu = null, cur = null, hl = -1, openedAt = 0;
    const items = () => menu ? [...menu.querySelectorAll(".wc-menu-item")] : [];
    function close() {
      if (!menu) return;
      const m = menu;
      menu = null;
      if (cur) cur.classList.remove("open");
      cur = null;
      hl = -1;
      m.classList.remove("open");
      m.classList.add("closing");
      setTimeout(() => m.remove(), 190);
    }
    function pick(sel, v) {
      if (v !== sel.value) {
        sel.value = v;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      close();
    }
    function open(sel) {
      close();
      const r = sel.getBoundingClientRect();
      const m = document.createElement("div");
      m.className = "wc-menu";
      m.innerHTML = [...sel.options].map((o, i) => `<div class="wc-menu-item${o.value === sel.value ? " sel" : ""}" data-v="${esc(o.value)}" style="--i:${i}"><span>${esc(o.text)}</span></div>`).join("");
      document.body.appendChild(m);
      m.style.minWidth = Math.max(r.width, 150) + "px";
      const mw = m.offsetWidth, mh = m.offsetHeight;
      let top = r.bottom + 6;
      if (top + mh > innerHeight - 8) top = Math.max(8, r.top - mh - 6);
      const left = Math.min(Math.max(8, r.right - mw), innerWidth - mw - 8);
      m.style.top = top + "px";
      m.style.left = left + "px";
      m.addEventListener("mousedown", (e) => {
        const it = e.target.closest(".wc-menu-item");
        if (!it) return;
        e.preventDefault();
        pick(sel, it.dataset.v);
      });
      requestAnimationFrame(() => m.classList.add("open"));
      menu = m;
      cur = sel;
      openedAt = performance.now();
      sel.classList.add("open");
      hl = [...sel.options].findIndex((o) => o.value === sel.value);
    }
    document.addEventListener("mousedown", (e) => {
      const s = e.target.closest && e.target.closest("select.admin-select");
      if (s) {
        e.preventDefault();
        if (s.disabled) return;
        menu && cur === s ? close() : open(s);
        return;
      }
      if (menu && !e.target.closest(".wc-menu")) close();
    }, true);
    document.addEventListener("keydown", (e) => {
      const s = e.target.closest && e.target.closest("select.admin-select");
      if (!menu) {
        if (s && ["Enter", " ", "ArrowDown", "ArrowUp"].includes(e.key)) {
          e.preventDefault();
          open(s);
        }
        return;
      }
      const list = items();
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        hl = (hl + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length;
        list.forEach((x, i) => x.classList.toggle("hl", i === hl));
      } else if (e.key === "Enter" && hl >= 0) {
        e.preventDefault();
        pick(cur, list[hl].dataset.v);
      }
    }, true);
    window.addEventListener("scroll", (e) => {
      if (!menu || performance.now() - openedAt < 400) return;
      if (e.target && e.target.closest && e.target.closest(".wc-menu")) return;
      close();
    }, true);
    window.addEventListener("resize", close);
  })();
  let MY_LOC = null;
  const readGeo = () => {
    try {
      return JSON.parse(sessionStorage.getItem("watercast_geo") || "null");
    } catch (e) {
      return null;
    }
  };
  async function resolveMyLocation() {
    MY_LOC = null;
    try {
      const m = JSON.parse(sessionStorage.getItem("watercast_manual_loc") || "null");
      if (m && typeof m.lat === "number") {
        MY_LOC = m;
        return;
      }
    } catch (e) {
    }
    const g = readGeo();
    if (!IS_ADMIN || !g || !g.ok) return;
    if (g.resolved) {
      MY_LOC = g.resolved;
      return;
    }
    try {
      const r = await apiFetch("/reverse?lat=" + g.lat + "&lon=" + g.lon);
      MY_LOC = Object.assign({ lat: g.lat, lon: g.lon, acc: g.acc }, r);
    } catch (e) {
      MY_LOC = { lat: g.lat, lon: g.lon, acc: g.acc, label: null, place: null, nearest: null };
    }
    g.resolved = MY_LOC;
    try {
      sessionStorage.setItem("watercast_geo", JSON.stringify(g));
    } catch (e) {
    }
  }
  let toastTimer = null;
  function toast(msg, isErr) {
    const t = document.getElementById("adminToast");
    if (!t) return;
    t.innerHTML = "";
    const sp = document.createElement("span");
    sp.className = "t-txt";
    sp.textContent = msg;
    t.appendChild(sp);
    t.classList.toggle("err", !!isErr);
    t.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("show"), 2400);
  }
  async function saveWithProgress(label, work, okMsg) {
    const t = document.getElementById("adminToast");
    clearTimeout(toastTimer);
    t.innerHTML = "";
    t.classList.remove("err");
    const sp = document.createElement("span");
    sp.className = "t-txt";
    sp.textContent = label;
    t.appendChild(sp);
    t.classList.add("show");
    const L = WCProg.mount(t, { mode: "append", compact: true, hideLabel: true, theme: "on-orange", min: 450, tail: 220 });
    try {
      await work();
    } catch (e) {
      L.cancel();
      throw e;
    }
    await L.done();
    toast(okMsg);
  }
  function selectHTML(kind, id, options, current, extra) {
    return `<select class="admin-select" data-admin="${kind}" data-id="${id}" ${extra || ""}>` + options.map((o) => `<option value="${o.v}"${o.v === current ? " selected" : ""}>${o.t}</option>`).join("") + "</select>";
  }
  const SOS_OPTS = ["Pending", "In Progress", "Resolved"].map((v) => ({ v, t: v }));
  document.addEventListener("change", async (e) => {
    const el = e.target.closest ? e.target.closest("[data-admin]") : null;
    if (!el || !IS_ADMIN) return;
    const kind = el.dataset.admin, id = el.dataset.id, val = el.value;
    el.disabled = true;
    try {
      if (kind === "sos") {
        await saveWithProgress("Saving request status...", async () => {
          await apiFetch("/sos/" + id, { method: "PATCH", body: JSON.stringify({ status: val }) });
          await Promise.all([loadRecentSOS(lastSOSLocality, true), loadMySOS(true)]);
        }, "Request marked " + val);
      }
    } catch (err) {
      toast(err.status === 401 ? "Session expired - please log in again" : err.detail || "Could not save the change", true);
      el.disabled = false;
    }
  });
  function timeAgo(iso) {
    const diff = (Date.now() - new Date(iso).getTime()) / 1e3;
    if (diff < 60) return Math.round(diff) + " sec ago";
    if (diff < 3600) return Math.round(diff / 60) + " min ago";
    if (diff < 86400) return Math.round(diff / 3600) + " hr ago";
    return Math.round(diff / 86400) + " day(s) ago";
  }
  function severityClass(sev) {
    const s = (sev || "").toLowerCase();
    return ["critical", "warning", "watch", "resolved"].includes(s) ? s : "watch";
  }
  function statusClass(label) {
    const l = (label || "").toLowerCase();
    if (l.includes("confirmed dry")) return "dry";
    if (l.includes("drying")) return "drying";
    return "wet";
  }
  function setStatusDot(online) {
    const dot = document.getElementById("backendStatus");
    if (!dot) return;
    dot.style.background = online ? "#22c55e" : "#f59e0b";
    dot.style.boxShadow = online ? "0 0 6px rgba(34,197,94,.7)" : "0 0 6px rgba(245,158,11,.6)";
    dot.title = online ? "Connected to backend" : "Offline demo mode";
  }
  async function checkHealth() {
    const admin = verifyAdmin();
    try {
      await apiFetch("/health");
      backendOnline = true;
      setStatusDot(true);
      await admin;
      await resolveMyLocation();
      loadAll();
    } catch {
      backendOnline = false;
      setStatusDot(false);
    }
  }
  let newsFilter = null;
  let lastSOSLocality = "";
  let rainData = null, rainFilter = "all";
  const NEWS_TABS = ["alerts", "rainfall", "infrastructure", "community"];
  let infraData = null, infraFilter = "all";
  const NEWS_SIDE_HTML = `
      <div>
        <div class="panel" style="margin-bottom:22px;">
          <div class="panel-title">THIS WEEK'S RISK TICKER</div>
          <div id="riskTickerList"><div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div></div>
        </div>
        <div class="panel">
          <div class="panel-title">MOST-REPORTED THIS WEEK</div>
          <div id="mostReportedList"><div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div></div>
        </div>
      </div>`;
  const safeUrl = (u) => /^https?:\/\//i.test(u || "") ? u : "";
  const errBox = (title, msg, tab) => `<div class="nw-error"><b>${esc(title)}</b>${esc(msg || "")}<div><button class="nw-retry" data-retry="${tab}">Try again</button></div></div>`;
  const GOV_ERR_TITLE = "The NDMA SACHET feed could not be loaded";
  async function loadNewsTab(cat, silent) {
    const container = $id("newsLayout");
    if (!container) return;
    const label = { all: "Loading everything", alerts: "Loading government alerts", rainfall: "Scanning rainfall news", infrastructure: "Analysing water infrastructure", community: "Loading community posts" }[cat];
    const L = !silent ? WCProg.mount(container, { label, mode: "replace" }) : null;
    let data;
    try {
      if (cat === "all") {
        const parts = await Promise.allSettled([apiFetch("/news/alerts"), apiFetch("/news/rainfall"), apiFetch("/news/infrastructure"), apiFetch("/community")]);
        if (parts.every((p) => p.status === "rejected")) throw new Error("offline");
        data = parts;
      } else if (cat === "alerts") data = await apiFetch("/news/alerts");
      else if (cat === "rainfall") data = await apiFetch("/news/rainfall");
      else if (cat === "infrastructure") data = await apiFetch("/news/infrastructure");
      else {
        const [posts, arts] = await Promise.all([apiFetch("/community"), apiFetch("/news?category=community").catch(() => [])]);
        data = { posts, arts };
      }
    } catch (e) {
      if (L) L.cancel();
      if ((newsFilter || "all") !== cat) return;
      container.innerHTML = `<div>${errBox("Could not load this tab", "Make sure the backend is running, then try again.", cat)}</div>${NEWS_SIDE_HTML}`;
      fillNewsSide();
      return;
    }
    if (L) await L.done();
    if ((newsFilter || "all") !== cat) return;
    let left = "";
    if (cat === "all") {
      const bad = (title, tag) => `<div class="nw-section"><div class="nw-head"><span class="tag-label ${tag}">${title}</span></div>${errBox("Could not load this section", "Make sure the backend is running, then try again.", "all")}</div>`;
      const [pa, pr, pi, pc] = data;
      left = pa.status === "fulfilled" ? alertsTabHTML(pa.value) : bad("ALERTS BY GOVERNMENT", "alerts");
      if (pr.status === "fulfilled") {
        rainData = pr.value;
        left += rainTabHTML();
      } else left += bad("RAINFALL WATCH", "rainfall");
      if (pi.status === "fulfilled") {
        infraData = pi.value;
        left += infraTabHTML();
      } else left += bad("WATER INFRASTRUCTURE NEWS", "infrastructure");
      left += pc.status === "fulfilled" ? communityTabHTML({ posts: pc.value, arts: [] }) : bad("COMMUNITY BOARD", "community");
    } else if (cat === "alerts") left = alertsTabHTML(data);
    else if (cat === "rainfall") {
      rainData = data;
      left = rainTabHTML();
    } else if (cat === "infrastructure") {
      infraData = data;
      left = infraTabHTML();
    } else left = communityTabHTML(data);
    container.innerHTML = `<div>${left}</div>${NEWS_SIDE_HTML}`;
    requestAnimationFrame(() => WCProg.reveal(container));
    fillNewsSide();
  }
  let govAlertItems = [];
  function fmtWhen(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleString("en-IN", { day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" });
  }
  function openGovAlert(g) {
    if (!g || document.querySelector(".wc-modal-back")) return;
    const back = document.createElement("div");
    back.className = "wc-modal-back";
    const row = (k, v) => v ? `<div class="ga-row"><span class="ga-k">${esc(k)}</span><span class="ga-v">${esc(v)}</span></div>` : "";
    const areas = g.areas || [];
    const body = g.details && g.details !== g.headline ? g.details : "";
    let i = 0;
    const n = () => `style="--i:${i++}"`;
    back.innerHTML = `<div class="wc-modal ga-modal" role="dialog" aria-modal="true" aria-label="Government alert">
        <div class="ga-top" ${n()}><span class="badge ${esc(g.tier)}">${esc(g.severity)}</span><span class="nw-time">${g.sent ? esc(timeAgo(g.sent)) : ""}</span></div>
        <div class="m-title" ${n()}>${esc(g.title)}</div>
        ${g.headline || g.description ? `<div class="m-sub" ${n()}>${esc(g.headline || g.description)}</div>` : ""}
        ${areas.length ? `<div class="nw-areas ga-areas" ${n()}>${areas.map((a) => `<span class="nw-chip">${esc(a)}</span>`).join("")}</div>` : ""}
        ${body ? `<div class="ga-body" ${n()}>${esc(body)}</div>` : ""}
        ${g.instruction ? `<div class="ga-instr" ${n()}><b>What to do</b>${esc(g.instruction)}</div>` : ""}
        <div class="ga-grid" ${n()}>${row("Issued by", g.issued_by || g.sender)}${row("Sent", fmtWhen(g.sent))}${row("In effect from", fmtWhen(g.effective))}${row("Expires", fmtWhen(g.expires))}${row("Urgency", g.urgency)}${row("Certainty", g.certainty)}</div>
        <div class="ga-news" ${n()}><div class="ga-news-h">NEWS COVERAGE</div><div class="ga-news-list" id="gaNewsList"></div></div>
        <div class="m-actions" ${n()}><button class="m-post" type="button" data-ga-close>Close</button></div>
      </div>`;
    document.body.appendChild(back);
    requestAnimationFrame(() => requestAnimationFrame(() => back.classList.add("open")));
    back.querySelector("[data-ga-close]").addEventListener("click", () => closeComposer(back));
    back.addEventListener("mousedown", (e) => {
      if (e.target === back) closeComposer(back);
    });
    back._esc = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeComposer(back);
      }
    };
    document.addEventListener("keydown", back._esc, true);
    setTimeout(() => back.querySelector("[data-ga-close]").focus(), 400);
    loadAlertCoverage(g, back.querySelector("#gaNewsList"));
  }
  function coveragePath(g) {
    const qs = new URLSearchParams({ event: g.title || "" });
    (g.areas || []).slice(0, 6).forEach((a) => qs.append("area", a));
    return "/news/alert-coverage?" + qs;
  }
  async function loadAlertCoverage(g, list) {
    if (!list) return;
    const L = WCProg.mount(list, { label: "Finding news coverage", mode: "replace", compact: true, min: 600 });
    let d;
    try {
      d = await apiFetch(coveragePath(g));
    } catch (e) {
      d = { ok: false };
    }
    await L.done();
    if (!list.isConnected) return;
    if (!d.ok) {
      list.innerHTML = '<div class="no-conn" style="width:auto;">No Connections</div>';
      return;
    }
    const more = d.query ? `<a class="ga-more" href="https://news.google.com/search?${new URLSearchParams({ q: d.query + " when:3d", hl: "en-IN", gl: "IN", ceid: "IN:en" })}" target="_blank" rel="noopener noreferrer">Search more news &#8599;</a>` : "";
    if (!d.items.length) {
      list.innerHTML = `<div class="no-data" style="width:auto;">No coverage from major news outlets yet</div>${more}`;
      return;
    }
    list.innerHTML = d.items.map((a) => `<a class="ga-art" href="${esc(safeUrl(a.link))}" target="_blank" rel="noopener noreferrer"><span class="ga-art-t">${esc(a.title)}</span><span class="ga-art-s">${esc(a.source)}${a.published ? " · " + esc(timeAgo(a.published)) : ""} &#8599;</span></a>`).join("") + more;
    WCProg.reveal(list);
  }
  function alertsTabHTML(d) {
    const gov = d.gov, hot = d.hot;
    govAlertItems = gov && gov.ok ? gov.items : [];
    const govCards = !gov.ok ? errBox(GOV_ERR_TITLE, gov.error, "alerts") : gov.items.length ? gov.items.map((g, gi) => {
      const areas = g.areas || [];
      return `<div class="nw-card ${esc(g.tier)}${gi >= 8 ? " nw-more" : ""}">
              <div class="nw-card-top"><span class="badge ${esc(g.tier)}">${esc(g.severity)}</span><span class="nw-time">${g.sent ? timeAgo(g.sent) : ""}</span></div>
              <div class="nw-title">${esc(g.title)}</div>
              ${areas.length ? `<div class="nw-areas">${areas.slice(0, 6).map((a) => `<span class="nw-chip">${esc(a)}</span>`).join("")}${areas.length > 6 ? `<span class="nw-chip">+${areas.length - 6} more</span>` : ""}</div>` : ""}
              ${g.description ? `<div class="nw-desc">${esc(g.description)}</div>` : ""}
              <div class="nw-foot"><span>${esc(g.issued_by || g.sender)}</span><button type="button" class="nw-official" data-govalert="${gi}">News coverage &#8599;</button></div>
            </div>`;
    }).join("") : '<div class="nw-empty">No active government alerts right now.</div>';
    const showAllBtn = gov.ok && gov.items.length > 8 ? `<button class="nw-retry" id="govShowAll" type="button" style="margin:2px 0 4px;">Show all ${gov.items.length} alerts</button>` : "";
    const max = hot.areas[0] ? hot.areas[0].count : 1;
    const areaRow = (a, near) => `<div class="area-row${near ? " near" : ""}">
        <div class="area-top"><span class="area-name">${esc(a.name)}</span><span class="area-count">${a.count}<small>ALERTS</small></span></div>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(4, Math.round(a.count / (near ? hot.threshold : max) * 100))}%"></div></div>
        <div class="area-meta">${a.gov} government · ${a.app} WaterCast${a.critical ? " · " + a.critical + " critical" : ""}${a.warning ? " · " + a.warning + " warning" : ""}${a.latest ? " · latest " + timeAgo(a.latest) : ""}</div>
      </div>`;
    const hotHTML = hot.areas.length ? hot.areas.map((a) => areaRow(a, false)).join("") : `<div class="nw-empty">No area has received ${hot.threshold}+ alerts in the last ${hot.days} days.</div>` + (hot.near.length ? `<div class="nw-sub" style="margin:16px 0 10px;">CLOSEST TO THE LIMIT</div>${hot.near.map((a) => areaRow(a, true)).join("")}` : "");
    return `<div class="nw-section">
        <div class="nw-head"><span class="tag-label alerts">ALERTS BY GOVERNMENT</span>
          <span class="nw-sub">${gov.ok ? gov.total + " from NDMA SACHET (official)" : "NDMA SACHET"}</span></div>
        ${gov.ok && gov.insecure_tls ? `<div class="nw-note">This PC could not verify NDMA's security certificate, so these alerts were fetched without that check.</div>` : ""}
        ${govCards}
        ${showAllBtn}
      </div>
      <div class="nw-section">
        <div class="nw-head"><span class="tag-label alerts">AREAS WITH ${hot.threshold}+ ALERTS · LAST ${hot.days} DAYS</span>
          <span class="nw-sub">government + WaterCast alerts combined</span></div>
        ${hotHTML}
      </div>`;
  }
  const RAIN_LABEL = { delayed: "Delayed", unseasonal: "Unseasonal", sudden: "Sudden", excess: "Too much" };
  function rainTabHTML() {
    const d = rainData;
    if (!d.ok) return `<div class="nw-section"><div class="nw-head"><span class="tag-label rainfall">RAINFALL WATCH</span></div>${errBox("Could not load rainfall news", d.error, "rainfall")}</div>`;
    const chips = [["all", "All", d.items.length]].concat(Object.keys(RAIN_LABEL).map((k) => [k, RAIN_LABEL[k], (d.counts || {})[k] || 0]));
    return `<div class="nw-section">
        <div class="nw-head"><span class="tag-label rainfall">RAINFALL WATCH</span>
          <span class="nw-sub">delayed, unseasonal, sudden or too much rain · last 7 days · via Google News</span></div>
        <div class="nw-filters" id="rainFilters">${chips.map((c) => `<span class="nw-filter${rainFilter === c[0] ? " on" : ""}" data-rf="${c[0]}">${c[1]} (${c[2]})</span>`).join("")}</div>
        <div id="rainList">${rainListHTML()}</div>
      </div>`;
  }
  function rainListHTML() {
    const items = rainData.items.filter((i) => rainFilter === "all" || i.tags.includes(rainFilter));
    if (!items.length) return '<div class="nw-empty">No matching rainfall headlines in the last 7 days.</div>';
    return items.map((i) => `<div class="nw-card rainfall">
        <div class="rt-chips">${i.tags.map((t) => `<span class="rt-chip ${t}">${RAIN_LABEL[t]}</span>`).join("")}</div>
        <div class="nw-title"><a href="${esc(safeUrl(i.link))}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a></div>
        <div class="nw-foot"><span>${esc(i.source || "News")}${i.published ? " · " + timeAgo(i.published) : ""}</span><a href="${esc(safeUrl(i.link))}" target="_blank" rel="noopener noreferrer">Read &#8599;</a></div>
      </div>`).join("");
  }
  const INFRA_LABEL = { dams: "Dams & reservoirs", pipelines: "Pipelines & supply", tankers: "Tankers", groundwater: "Groundwater", treatment: "Treatment" };
  function infraTabHTML() {
    const nw = infraData.news;
    let body;
    if (!nw.ok) body = errBox("Could not load infrastructure news", nw.error, "infrastructure");
    else {
      const chips = [["all", "All", nw.items.length]].concat(Object.keys(INFRA_LABEL).map((k) => [k, INFRA_LABEL[k], (nw.counts || {})[k] || 0]));
      body = `<div class="nw-filters" id="infraFilters">${chips.map((c) => `<span class="nw-filter${infraFilter === c[0] ? " on" : ""}" data-if="${c[0]}">${c[1]} (${c[2]})</span>`).join("")}</div>
        <div id="infraList">${infraListHTML()}</div>`;
    }
    return `<div class="nw-section">
        <div class="nw-head"><span class="tag-label infrastructure">WATER INFRASTRUCTURE NEWS</span><span class="nw-sub">dams, pipelines, tankers, groundwater, treatment · last 7 days · via Google News</span></div>
        ${body}
      </div>`;
  }
  function infraListHTML() {
    const items = infraData.news.items.filter((i) => infraFilter === "all" || i.tags.includes(infraFilter));
    if (!items.length) return '<div class="nw-empty">No matching infrastructure headlines in the last 7 days.</div>';
    return items.map((i) => `<div class="nw-card" style="border-left-color:#5a72c9">
        <div class="rt-chips">${i.tags.map((t) => `<span class="rt-chip ${t}">${INFRA_LABEL[t]}</span>`).join("")}</div>
        <div class="nw-title"><a href="${esc(safeUrl(i.link))}" target="_blank" rel="noopener noreferrer">${esc(i.title)}</a></div>
        <div class="nw-foot"><span>${esc(i.source || "News")}${i.published ? " · " + timeAgo(i.published) : ""}</span><a href="${esc(safeUrl(i.link))}" target="_blank" rel="noopener noreferrer">Read &#8599;</a></div>
      </div>`).join("");
  }
  function communityTabHTML(d) {
    const posts = d.posts.length ? d.posts.map((p) => `<div class="post-card">
        <div class="post-avatar">${esc((p.author || "A").trim().charAt(0).toUpperCase() || "A")}</div>
        <div class="post-main">
          <div class="post-top"><span class="post-author">${esc(p.author)}</span>${p.locality ? `<span class="post-loc">${esc(p.locality)}</span>` : ""}<span class="post-time">${timeAgo(p.created_at)}</span></div>
          <div class="post-text">${esc(p.text)}</div>
          ${IS_ADMIN ? `<button class="post-del" data-del="${p.id}">Delete post</button>` : `<button class="post-del" data-report="${p.id}">Report</button>`}
        </div></div>`).join("") : '<div class="nw-empty">No posts yet - press the + button and be the first to share something with your community.</div>';
    const arts = (d.arts || []).map((a) => `<div class="nw-card" style="border-left-color:#c9a83f">
        <div class="nw-title">${esc(a.title)}</div>${a.summary ? `<div class="nw-desc">${esc(a.summary)}</div>` : ""}</div>`).join("");
    return `<div class="nw-section">
        <div class="nw-head"><div><span class="tag-label community">COMMUNITY BOARD</span><span class="nw-sub">Anyone can post - no account needed</span></div>
          <button class="plus-btn" id="communityPlus" type="button" aria-label="Add a community post" title="Add a post">+</button></div>
        ${posts}
      </div>
      ${arts ? `<div class="nw-section"><div class="nw-head"><span class="tag-label community">FROM WATERCAST</span></div>${arts}</div>` : ""}`;
  }
  async function postJSON(path, body) {
    const r = await fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    let data = {};
    try {
      data = await r.json();
    } catch (e) {
    }
    return { ok: r.ok, status: r.status, data };
  }
  function closeComposer(back) {
    if (!back) return;
    back.classList.remove("open");
    setTimeout(() => back.remove(), 380);
    document.removeEventListener("keydown", back._esc, true);
  }
  function openComposer() {
    if (document.querySelector(".wc-modal-back")) return;
    const back = document.createElement("div");
    back.className = "wc-modal-back";
    back.innerHTML = `<div class="wc-modal" role="dialog" aria-modal="true" aria-label="New community post">
        <div class="m-title" style="--i:0">Share with the community</div>
        <div class="m-sub" style="--i:1">Type anything you want other residents to see - water supply, rain, questions, tips.</div>
        <textarea id="cpText" maxlength="600" placeholder="What's happening in your area?" style="--i:2"></textarea>
        <div class="cp-count" id="cpCount" style="--i:2">0 / 600</div>
        <div class="cp-row" style="--i:3"><input id="cpName" maxlength="40" placeholder="Your name (optional)" autocomplete="off"><input id="cpLoc" maxlength="80" placeholder="Locality (optional)" autocomplete="off"></div>
        <div class="m-error" id="cpErr"></div>
        <div class="m-actions" style="--i:4"><button class="m-cancel" id="cpCancel" type="button">Cancel</button><button class="m-post" id="cpPost" type="button">Post</button></div>
      </div>`;
    document.body.appendChild(back);
    requestAnimationFrame(() => requestAnimationFrame(() => back.classList.add("open")));
    const $ = (id) => back.querySelector("#" + id);
    try {
      $("cpName").value = localStorage.getItem("wc_post_name") || "";
    } catch (e) {
    }
    if (MY_LOC && (MY_LOC.place || MY_LOC.label)) $("cpLoc").value = MY_LOC.place || MY_LOC.label;
    setTimeout(() => $("cpText").focus(), 450);
    $("cpText").addEventListener("input", () => {
      $("cpCount").textContent = $("cpText").value.length + " / 600";
      $("cpErr").classList.remove("show");
    });
    $("cpCancel").addEventListener("click", () => closeComposer(back));
    back.addEventListener("mousedown", (e) => {
      if (e.target === back) closeComposer(back);
    });
    back._esc = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeComposer(back);
      }
    };
    document.addEventListener("keydown", back._esc, true);
    const showErr = (msg) => {
      const el = $("cpErr");
      el.textContent = msg;
      el.classList.remove("show");
      void el.offsetWidth;
      el.classList.add("show");
    };
    $("cpPost").addEventListener("click", async () => {
      const text = $("cpText").value.trim();
      if (!text) {
        showErr("Write something before posting.");
        return;
      }
      const btn = $("cpPost");
      btn.disabled = true;
      const L = WCProg.mount(btn.parentNode, { label: "Posting your message", mode: "after", full: true, min: 700 });
      let res;
      try {
        res = await postJSON("/community", { text, author: $("cpName").value, locality: $("cpLoc").value, device_id: DEVICE_ID });
      } catch (e) {
        L.cancel();
        btn.disabled = false;
        showErr("Could not reach the server. Try again.");
        return;
      }
      if (!res.ok) {
        L.cancel();
        btn.disabled = false;
        showErr(res.data.error || "Could not post. Try again.");
        return;
      }
      await L.done();
      try {
        localStorage.setItem("wc_post_name", $("cpName").value.trim());
      } catch (e) {
      }
      closeComposer(back);
      toast("Posted to the community board");
      {
        const cur = newsFilter || "all";
        if (cur === "community" || cur === "all") loadNewsTab(cur, true);
      }
    });
  }
  const prefetchCoverage = (e) => {
    const ga = e.target && e.target.closest ? e.target.closest("[data-govalert]") : null;
    const g = ga ? govAlertItems[parseInt(ga.dataset.govalert, 10)] : null;
    if (g) prefetch(coveragePath(g));
  };
  document.addEventListener("pointerover", prefetchCoverage, { passive: true });
  document.addEventListener("focusin", prefetchCoverage);
  document.addEventListener("click", async (e) => {
    const t = e.target.closest ? e.target : null;
    if (!t) return;
    const plus = t.closest("#communityPlus");
    if (plus) {
      openComposer();
      return;
    }
    const ga = t.closest("[data-govalert]");
    if (ga) {
      openGovAlert(govAlertItems[parseInt(ga.dataset.govalert, 10)]);
      return;
    }
    const sa = t.closest("#govShowAll");
    if (sa) {
      const sec = sa.closest(".nw-section");
      const open = !sec.classList.contains("nw-open");
      sec.classList.toggle("nw-open", open);
      sa.textContent = open ? "Show fewer" : "Show all " + sec.querySelectorAll(".nw-card").length + " alerts";
      if (open) WCProg.reveal(sec);
      return;
    }
    const rf = t.closest("[data-rf]");
    if (rf && rainData) {
      rainFilter = rf.dataset.rf;
      document.querySelectorAll("#rainFilters .nw-filter").forEach((x) => x.classList.toggle("on", x.dataset.rf === rainFilter));
      const list = $id("rainList");
      if (list) {
        list.innerHTML = rainListHTML();
        WCProg.reveal(list);
      }
      return;
    }
    const inf = t.closest("[data-if]");
    if (inf && infraData) {
      infraFilter = inf.dataset.if;
      document.querySelectorAll("#infraFilters .nw-filter").forEach((x) => x.classList.toggle("on", x.dataset.if === infraFilter));
      const list = $id("infraList");
      if (list) {
        list.innerHTML = infraListHTML();
        WCProg.reveal(list);
      }
      return;
    }
    const retry = t.closest("[data-retry]");
    if (retry) {
      _cacheBust();
      loadNewsTab(retry.dataset.retry);
      return;
    }
    const rep = t.closest("[data-report]");
    if (rep) {
      rep.disabled = true;
      const res = await postJSON("/community/" + rep.dataset.report + "/report", { device_id: DEVICE_ID });
      if (res.ok) {
        rep.textContent = res.data.hidden ? "Reported - hidden" : "Reported, thanks";
        toast(res.data.hidden ? "Thanks - the post has been hidden for review" : "Thanks - we will review this post");
      } else if (res.status === 409) {
        rep.textContent = "Already reported";
      } else {
        rep.disabled = false;
        toast(res.data.error || "Could not send the report", true);
      }
      return;
    }
    const del = t.closest("[data-del]");
    if (del && IS_ADMIN) {
      del.disabled = true;
      try {
        await apiFetch("/community/" + del.dataset.del, { method: "DELETE" });
        toast("Post deleted");
        {
          const cur = newsFilter || "all";
          if (cur === "community" || cur === "all") loadNewsTab(cur, true);
        }
      } catch (err) {
        del.disabled = false;
        toast("Could not delete the post", true);
      }
    }
  });
  function _cacheBust() {
  }
  async function loadRiskTicker() {
    const ticker = document.getElementById("riskTickerList");
    if (!ticker) return;
    const L = WCProg.mount(ticker, { label: "Gemini is scoring this week's risk", mode: "replace", compact: true, min: 550 });
    let d;
    try {
      d = await apiFetch("/risk/ticker");
    } catch (e) {
      d = { ok: false };
    }
    await L.done();
    const box = document.getElementById("riskTickerList");
    if (!box) return;
    if (!d.ok) {
      box.innerHTML = '<div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div>';
      return;
    }
    if (!d.items.length) {
      box.innerHTML = '<div class="no-data" style="margin:16px 22px 22px;width:auto;">No risk signals this week</div>';
      return;
    }
    const arrow = { rising: "▲", falling: "▼", steady: "■" };
    box.innerHTML = d.items.map((t) => `
        <div class="bar-row risk-row">
          <div class="bar-top"><span class="who">${esc(t.place)}</span><span class="risk-meta"><span class="risk-trend ${esc(t.trend)}" title="${esc(t.trend)} vs last week">${arrow[t.trend] || ""}</span><span class="badge ${esc(t.level.toLowerCase())}">${t.score}/100</span></span></div>
          <div class="bar-track"><div class="bar-fill risk-${esc(t.level.toLowerCase())}" style="width:${t.score}%"></div></div>
          ${t.reason ? `<div class="risk-reason">${esc(t.reason)}</div>` : ""}
        </div>`).join("") + `<div class="risk-foot">Scored by Gemini${d.scored_at ? " · " + esc(timeAgo(d.scored_at)) : ""}</div>`;
    WCProg.reveal(box);
  }
  async function fillNewsSide() {
    loadRiskTicker();
    const mr = document.getElementById("mostReportedList");
    if (!mr) return;
    try {
      const top = await apiFetch("/sos/top?days=7");
      if (!top.length) {
        mr.innerHTML = '<div class="no-data" style="margin:16px 22px 22px;width:auto;">No help requests this week</div>';
        return;
      }
      const maxR = top[0].count || 1;
      mr.innerHTML = top.slice(0, 3).map((t) => `
        <div class="bar-row">
          <div class="bar-top"><span class="who">${esc(t.locality)}</span><span class="num">${t.count} ${t.count === 1 ? "request" : "requests"}</span></div>
          <div class="bar-track"><div class="bar-fill" style="width:${Math.round(t.count / maxR * 100)}%"></div></div>
        </div>`).join("") + '<div style="height:4px"></div>';
    } catch (e) {
      mr.innerHTML = '<div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div>';
    }
  }
  function wireNewsPills() {
    const row = document.querySelector("#page-1 .pill-row");
    if (!row) return;
    row.querySelectorAll(".pill").forEach((p) => {
      if (!p.dataset.wcWired) {
        p.dataset.wcWired = "1";
        p.addEventListener("click", () => {
          const cat = p.textContent.trim().toLowerCase();
          loadNews(cat === "all" ? null : cat);
        });
      }
    });
  }
  async function loadNews(category, silent) {
    newsFilter = category || null;
    wireNewsPills();
    if (NEWS_TABS.includes(newsFilter)) {
      if (newsFilter === "rainfall" && !silent) rainFilter = "all";
      if (newsFilter === "infrastructure" && !silent) infraFilter = "all";
      return loadNewsTab(newsFilter, silent);
    }
    if (!silent) {
      rainFilter = "all";
      infraFilter = "all";
    }
    return loadNewsTab("all", silent);
  }
  function trustRingHTML(score, text) {
    const circ = 238.76;
    const offset = circ - (score || 0) / 100 * circ;
    return `
        <svg width="88" height="88" viewBox="0 0 88 88">
          <circle cx="44" cy="44" r="38" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="7"/>
          <circle cx="44" cy="44" r="38" fill="none" stroke="#e3925a" stroke-width="7" stroke-linecap="round"
            stroke-dasharray="${circ}" stroke-dashoffset="${offset.toFixed(1)}"
            style="transition:stroke-dashoffset .9s ease"/>
        </svg>
        <div style="text-align:center;"><div class="trust-num">${text}</div><div class="trust-den">/100</div></div>`;
  }
  async function loadTrustScore(silent) {
    const footEl = document.getElementById("trustFoot");
    const L = !silent && footEl ? WCProg.mount(footEl, { label: "Gemini is scoring your reports", mode: "after", compact: true, min: 550 }) : null;
    let ts;
    try {
      ts = await apiFetch("/trust/" + DEVICE_ID);
    } catch (e) {
      if (L) L.cancel();
      ts = { ok: false, reports_filed: null, confirmed_accurate: null };
    }
    if (L) await L.done();
    const ring = document.getElementById("trustRing");
    const foot = document.getElementById("trustFoot");
    const info = foot ? foot.closest(".panel")?.querySelector(".trust-info") : null;
    const tv = info ? info.querySelector(".tv") : null;
    const sub = info ? info.querySelector(".ts") : null;
    const num = (v) => v === null || v === undefined ? "-" : v;
    const scored = ts.ok && ts.score !== null && ts.score !== undefined;
    if (ring) ring.innerHTML = trustRingHTML(scored ? ts.score : 0, scored ? ts.score : "-");
    if (foot) foot.innerHTML = `<span>Reports filed <b>${num(ts.reports_filed)}</b></span><span>Confirmed accurate <b>${num(ts.confirmed_accurate)}</b></span>`;
    if (tv) tv.textContent = !ts.ok ? "No Connections" : scored ? ts.label : "No reports yet";
    if (sub) sub.textContent = !ts.ok ? (ts.error || "") : scored ? [ts.summary, "Scored by Gemini"].filter(Boolean).join(" · ") : "";
    if (info) WCProg.reveal(info);
  }
  function initSOSForm() {
    const btn = document.getElementById("sosSubmitBtn");
    const textarea = document.getElementById("sosDescription");
    const locDisp = document.getElementById("sosLocalityDisplay");
    const locInput = document.getElementById("sosLocalityInput");
    const sug = document.getElementById("sosGeoSuggest");
    const useLoc = document.getElementById("sosUseLocation");
    const photoBox = document.getElementById("sosPhotoBox");
    if (!btn) return;
    if (textarea) {
      textarea.removeAttribute("readonly");
      textarea.value = "";
      textarea.placeholder = "Describe what's happening - no water, contamination, tanker delay, etc.";
    }
    let currentLocality = null;
    let currentCoords = null;
    let hasPhoto = false;
    let exactLabel = null;
    const showLoc = (label) => {
      if (locInput) locInput.value = label || "";
    };
    function applyLoc(l, silent) {
      currentCoords = { lat: l.lat, lon: l.lon };
      const n = l.nearest;
      currentLocality = n && n.distance_km <= 50 ? n.name : l.place || n && n.name || currentLocality;
      exactLabel = l.label || null;
      showLoc(l.label || (n ? n.name + ", " + n.state : "Your current position"));
      if (useLoc) useLoc.textContent = "Location set ✓" + (l.acc ? " · ±" + Math.round(l.acc) + " m" : l.manual ? " (typed)" : "");
    }
    let sItems = [], sSel = -1, sTimer = null, sReq = 0;
    const sOpen = () => {
      sug.classList.remove("closing");
      if (sug.style.display !== "block") {
        sug.style.display = "block";
        void sug.offsetWidth;
      }
      if (!sug.classList.contains("open")) {
        void sug.offsetWidth;
        sug.classList.add("open");
      }
    };
    const sClose = () => {
      sReq++;
      sItems = [];
      sSel = -1;
      if (sug.style.display !== "block" || sug.classList.contains("closing")) return;
      sug.classList.remove("open");
      sug.classList.add("closing");
      setTimeout(() => {
        if (sug.classList.contains("closing")) {
          sug.style.display = "none";
          sug.innerHTML = "";
          sug.classList.remove("closing");
        }
      }, 180);
    };
    const sMsg = (a, b) => {
      sOpen();
      sug.innerHTML = `<div class="geo-item"><div><div class="g-name">${esc(a)}</div><div class="g-ctx">${esc(b)}</div></div></div>`;
    };
    const sPaint = (list) => {
      sItems = list;
      sSel = -1;
      if (!list.length) {
        sMsg("No match found", 'Try adding a district or state, e.g. "Hadapsar, Pune"');
        return;
      }
      sOpen();
      sug.innerHTML = list.map((p, i) => `<div class="geo-item" data-gi="${i}" style="--i:${i}"><div><div class="g-name">${esc(p.name)}</div><div class="g-ctx">${esc(p.context || p.country || "")}</div></div></div>`).join("");
    };
    async function sQuery(q, mode) {
      const my = ++sReq;
      sOpen();
      const L = WCProg.mount(sug, { label: "Searching places", mode: "replace", compact: true, min: 300, tail: 160 });
      let res;
      try {
        res = await apiFetch("/geocode?mode=" + mode + "&q=" + encodeURIComponent(q));
      } catch (e) {
        if (my === sReq) {
          L.cancel();
          sMsg("Could not search", "Check your internet connection and try again.");
        }
        return null;
      }
      if (my !== sReq) {
        L.cancel();
        return null;
      }
      await L.done();
      if (my !== sReq) return null;
      sPaint(res);
      return res;
    }
    function chooseManual(p) {
      sClose();
      const label = p.name + (p.context ? ", " + p.context : "");
      const l = { lat: p.lat, lon: p.lon, acc: null, label, place: p.name, state: p.state || "", country: p.country || "", nearest: null, manual: true };
      applyLoc(l);
      MY_LOC = Object.assign({}, l);
      try {
        sessionStorage.setItem("watercast_manual_loc", JSON.stringify(l));
      } catch (e) {
      }
      addMyLocPill();
    }
    if (locInput && sug) {
      locInput.addEventListener("input", () => {
        currentCoords = null;
        currentLocality = null;
        exactLabel = null;
        if (useLoc) useLoc.textContent = "Use current location";
        clearTimeout(sTimer);
        const q = locInput.value.trim();
        if (q.length < 2) {
          sClose();
          return;
        }
        sTimer = setTimeout(() => sQuery(q, "suggest"), 300);
      });
      locInput.addEventListener("keydown", async (e) => {
        const mark = () => sug.querySelectorAll(".geo-item").forEach((el, i) => el.classList.toggle("sel", i === sSel));
        if (e.key === "ArrowDown" && sItems.length) {
          e.preventDefault();
          sSel = (sSel + 1) % sItems.length;
          mark();
        } else if (e.key === "ArrowUp" && sItems.length) {
          e.preventDefault();
          sSel = (sSel - 1 + sItems.length) % sItems.length;
          mark();
        } else if (e.key === "Escape") {
          sClose();
        } else if (e.key === "Enter") {
          e.preventDefault();
          if (sSel >= 0 && sItems[sSel]) {
            chooseManual(sItems[sSel]);
            return;
          }
          const q = locInput.value.trim();
          if (q.length < 2) return;
          clearTimeout(sTimer);
          const res = await sQuery(q, "search");
          if (res && res.length === 1) chooseManual(res[0]);
        }
      });
      sug.addEventListener("mousedown", (e) => {
        const el = e.target.closest("[data-gi]");
        if (el) {
          e.preventDefault();
          const p = sItems[parseInt(el.dataset.gi, 10)];
          if (p) chooseManual(p);
        }
      });
      locInput.addEventListener("blur", () => setTimeout(sClose, 150));
    }
    if (useLoc) {
      useLoc.style.cursor = "pointer";
      useLoc.addEventListener("click", () => {
        if (!navigator.geolocation) {
          useLoc.textContent = "Location not supported";
          return;
        }
        useLoc.textContent = "Locating…";
        const LL = locDisp ? WCProg.mount(locDisp, { label: "Finding your exact position", mode: "after", compact: true, min: 700 }) : null;
        navigator.geolocation.getCurrentPosition(async (pos) => {
          const { latitude: lat, longitude: lon, accuracy } = pos.coords;
          try {
            const r = await apiFetch(`/reverse?lat=${lat}&lon=${lon}`);
            if (LL) await LL.done();
            applyLoc(Object.assign({ lat, lon, acc: accuracy }, r));
          } catch {
            if (LL) LL.cancel();
            currentCoords = { lat, lon };
            useLoc.textContent = "Could not find locality";
          }
        }, () => {
          if (LL) LL.cancel();
          useLoc.textContent = "Location denied";
        }, { enableHighAccuracy: true, timeout: 15e3, maximumAge: 0 });
      });
      if (MY_LOC) applyLoc(MY_LOC, true);
      else if (IS_ADMIN && readGeo() && !readGeo().ok) useLoc.textContent = "Location denied - click to retry";
    }
    if (photoBox) {
      photoBox.style.cursor = "pointer";
      photoBox.addEventListener("click", () => {
        hasPhoto = !hasPhoto;
        photoBox.style.opacity = hasPhoto ? "1" : "0.7";
        photoBox.style.background = hasPhoto ? "rgba(227,146,90,.18)" : "";
        photoBox.querySelector(".u-title").textContent = hasPhoto ? "Photo attached ✓ (trust +4)" : "Add a geo-tagged photo (optional)";
      });
    }
    btn.addEventListener("click", async () => {
      if (btn.disabled) return;
      const issueEl = document.querySelector('.choice-pill.active[data-group="issue"]');
      const urgencyEl = document.querySelector('.urgency-btn.active[data-group="urgency"]');
      const desc = textarea ? textarea.value.trim() : "";
      const issue = issueEl ? issueEl.textContent.trim() : "No Water Supply";
      const urgency = urgencyEl ? urgencyEl.textContent.trim() : "Warning";
      if (!currentCoords) {
        const old = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = "Type your area or use current location first";
        setTimeout(() => {
          btn.disabled = false;
          btn.innerHTML = old;
        }, 2200);
        return;
      }
      btn.disabled = true;
      btn.textContent = "Sending…";
      const SL = WCProg.mount(btn, { label: "Sending your request", mode: "after", full: true, min: 800 });
      try {
        const result = await apiFetch("/sos", {
          method: "POST",
          body: JSON.stringify({
            device_id: DEVICE_ID,
            locality_name: currentLocality,
            lat: currentCoords.lat,
            lon: currentCoords.lon,
            issue_type: issue,
            urgency,
            description: exactLabel ? [desc, "Exact location: " + exactLabel + " (" + currentCoords.lat.toFixed(5) + ", " + currentCoords.lon.toFixed(5) + ")"].filter(Boolean).join("\n") : desc,
            has_photo: hasPhoto
          })
        });
        await SL.done();
        btn.textContent = "✓ SOS Sent - Ref #" + result.sos.id;
        btn.style.background = "linear-gradient(180deg,#22c55e,#16a34a)";
        await loadTrustScore();
        setTimeout(() => {
          btn.disabled = false;
          btn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg> Send SOS Request';
          btn.style.background = "";
          if (textarea) textarea.value = "";
        }, 4e3);
        loadRecentSOS(currentLocality);
        loadMySOS();
      } catch {
        SL.cancel();
        btn.textContent = "Error - try again";
        btn.style.background = "linear-gradient(180deg,#c33c2e,#a0332a)";
        setTimeout(() => {
          btn.disabled = false;
          btn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M5 12l7-7 7 7"/></svg> Send SOS Request';
          btn.style.background = "";
        }, 3e3);
      }
    });
  }
  const SOS_BADGE = { Pending: "critical", "In Progress": "warning", Resolved: "watch" };
  function sosRowsHTML(items, editable, own) {
    return items.map((r) => {
      const when = r.status === "Resolved" && r.resolved_at ? "resolved " + timeAgo(r.resolved_at) : timeAgo(r.created_at);
      const right = editable && IS_ADMIN ? selectHTML("sos", r.id, SOS_OPTS, r.status) : `<span class="badge ${SOS_BADGE[r.status] || "watch"}">${esc(r.status)}</span>`;
      return `<div class="side-list-row"><div>
          <div class="who">${esc(r.locality_name)} · ${esc(r.issue_type)}</div>
          <div class="what"><span class="ref">#${r.id}</span> · ${esc(r.urgency)} · ${own ? "sent " : ""}${esc(when)}</div>
        </div>${right}</div>`;
    }).join("");
  }
  function sosMessage(title) {
    return `<div class="side-list-row"><div><div class="what" style="margin:0;">${esc(title)}</div></div></div>`;
  }
  let sosSearchTerm = "", sosSearchReq = 0;
  async function loadRecentSOS(_locality, silent) {
    const list = document.getElementById("recentSOSList");
    if (!list) return;
    const term = sosSearchTerm;
    const token = ++sosSearchReq;
    const titleEl = document.getElementById("recentSOSTitle");
    const L = !silent && titleEl ? WCProg.mount(titleEl, { label: term ? "Searching requests" : "Loading requests", mode: "after", compact: true, min: 450 }) : null;
    try {
      const items = await apiFetch("/sos?" + new URLSearchParams(term ? { q: term, limit: 100 } : { days: 5, limit: 100 }), { fresh: true });
      if (L) await L.done();
      if (token !== sosSearchReq) return;
      list.innerHTML = items.length ? sosRowsHTML(items, true, false) : sosMessage(term ? "No matches" : "No requests yet");
    } catch (e) {
      if (L) L.cancel();
      if (token !== sosSearchReq) return;
      list.innerHTML = '<div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div>';
    }
  }
  async function loadMySOS(silent) {
    const list = document.getElementById("mySOSList");
    if (!list) return;
    const titleEl = document.getElementById("mySOSTitle");
    const L = !silent && titleEl ? WCProg.mount(titleEl, { label: "Finding your requests", mode: "after", compact: true, min: 450 }) : null;
    try {
      const items = await apiFetch("/sos/mine?" + new URLSearchParams({ device_id: DEVICE_ID }), { fresh: true });
      if (L) await L.done();
      list.innerHTML = items.length ? sosRowsHTML(items, false, true) : sosMessage("No requests yet");
    } catch (e) {
      if (L) L.cancel();
      list.innerHTML = '<div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div>';
    }
  }
  function initSOSSearch() {
    const input = document.getElementById("sosSearchInput");
    if (!input || input.dataset.wcWired) return;
    input.dataset.wcWired = "1";
    let t = null;
    const run = () => {
      const v = input.value.trim();
      if (v === sosSearchTerm) return;
      sosSearchTerm = v;
      loadRecentSOS(null);
    };
    input.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(run, 300);
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        clearTimeout(t);
        run();
      }
    });
  }
  async function loadLocalities() {
    const pillRow = document.getElementById("localityPillRow");
    if (pillRow) {
      pillRow.querySelectorAll(".pill").forEach((p) => {
        if (!p.dataset.wcWired) {
          p.dataset.wcWired = "1";
          p.addEventListener("click", () => {
            const name = p.textContent.trim();
            searchLocality(name);
            const searchInput = document.getElementById("citySearchInput");
            if (searchInput) searchInput.value = name;
          });
        }
      });
    }
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const $id = (id) => document.getElementById(id);
  let placeReq = 0;
  let lastTop = null;
  let otherList = [];
  let tipsOriginal = null;
  const searchHead = (html) => {
    const h = $id("searchResultHead");
    if (h) h.innerHTML = html;
  };
  const errHead = (title, sub) => `<div><span class="result-name">${esc(title)}</span><span class="result-sub"> - ${esc(sub)}</span></div>`;
  const loadingHead = (txt) => `<div><span class="result-name" style="opacity:.55">${esc(txt)}</span></div>`;
  function haversineKm(lat1, lon1, lat2, lon2) {
    const R = 6371, rad = (x) => x * Math.PI / 180;
    const a = Math.sin(rad(lat2 - lat1) / 2) ** 2 + Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(rad(lon2 - lon1) / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(a));
  }
  const headLoader = (txt) => {
    const h = $id("searchResultHead");
    return h ? WCProg.mount(h, { label: txt, mode: "replace", min: 600 }) : null;
  };
  async function searchLocality(name, silent) {
    const token = ++placeReq;
    hideSuggest();
    setOtherMatches([]);
    const L = silent ? null : headLoader("Looking up " + name);
    await searchAnyPlace(name, token, L);
  }
  async function searchAnyPlace(name, token, L) {
    if (L) L.label('Searching for "' + name + '"');
    else L = headLoader('Searching for "' + name + '"');
    let results;
    try {
      results = await apiFetch("/geocode?mode=search&q=" + encodeURIComponent(name));
    } catch (e) {
      if (L) L.cancel();
      if (token !== placeReq) return;
      searchHead(errHead("Place lookup unavailable", String(e.message) === "502" ? "could not reach the lookup service - check your internet connection" : "try again in a moment"));
      return;
    }
    if (token !== placeReq) {
      if (L) L.cancel();
      return;
    }
    if (!results.length) {
      if (L) L.cancel();
      searchHead(errHead("Not found", 'no place matches "' + name + '" - try adding a district or state, e.g. "Hadapsar, Pune"'));
      return;
    }
    setOtherMatches(results.slice(1));
    await loadPlace(results[0], token, L);
  }
  async function loadPlace(p, token, L) {
    if (p.monitored) return searchLocality(p.name);
    if (token == null) token = ++placeReq;
    lastTop = p;
    if (L) L.label("Fetching live weather for " + p.name);
    else L = headLoader("Fetching live weather for " + p.name);
    let w;
    try {
      w = await apiFetch("/place?" + new URLSearchParams({
        lat: p.lat,
        lon: p.lon,
        name: p.name || "",
        state: p.state || "",
        country: p.country || ""
      }));
    } catch (e) {
      if (L) L.cancel();
      if (token !== placeReq) return;
      searchHead(errHead("Weather unavailable", String(e.message) === "502" ? "could not reach the weather service - check your internet connection" : "try again in a moment"));
      return;
    }
    if (token !== placeReq) {
      if (L) L.cancel();
      return;
    }
    if (L) await L.done();
    if (token !== placeReq) return;
    if (!p.keepPill) document.querySelectorAll("#localityPillRow .pill").forEach((x) => x.classList.remove("active", "orange"));
    renderSearchResult({
      live: true,
      name: p.name,
      context: p.context || p.state || p.country,
      status_label: w.derived.status_label,
      risk_tier: w.derived.risk_tier,
      updated_at: w.updated_at,
      w,
      lat: p.lat,
      lon: p.lon
    });
    renderForecast(w);
    renderLiveStrip(w, { lat: p.lat, lon: p.lon, live: true });
    setTips(w, true, { lat: p.lat, lon: p.lon, name: p.name, state: p.state, country: p.country });
  }
  function renderForecast(w) {
    const grid = document.querySelector("#page-3 .day-grid");
    if (!grid) return;
    grid.innerHTML = w.daily.map((d, i) => {
      const p = d.precip_prob;
      const dot = p == null ? "#84988f" : p >= 50 ? "#3f8fdc" : p >= 25 ? "#e3925a" : "#c9a83f";
      const temps = d.tmax != null && d.tmin != null ? Math.round(d.tmax) + "°/" + Math.round(d.tmin) + "° · " : "";
      return `<div class="day-card${i === 0 ? " active" : ""}" title="${esc(d.condition)}">
        <div class="day-name">${d.weekday}${i === 0 ? " · TODAY" : ""}</div>
        <div class="day-dot" style="background:${dot};"></div>
        <div class="day-pct">${p == null ? "-" : p + "%"}</div>
        <div class="day-note">${temps}${d.precip_mm} mm</div></div>`;
    }).join("");
  }
  function ensureLiveEls() {
    let strip = $id("liveStrip");
    if (!strip) {
      const grid = $id("searchStatGrid");
      if (!grid) return [null, null];
      strip = document.createElement("div");
      strip.id = "liveStrip";
      strip.className = "live-strip";
      const note = document.createElement("div");
      note.id = "liveNote";
      note.className = "live-note";
      grid.parentNode.insertBefore(strip, grid);
      grid.parentNode.insertBefore(note, grid);
    }
    return [strip, $id("liveNote")];
  }
  function renderLiveStrip(w, ctx) {
    const [strip, note] = ensureLiveEls();
    if (!strip) return;
    const c = w.current || {};
    const r = (v) => v == null ? "-" : Math.round(v);
    const chip = (label, val) => `<div class="live-chip"><span class="lc-label">${label}</span><b>${val}</b></div>`;
    strip.innerHTML = `<div class="live-chip main"><span class="lc-temp">${r(c.temp_c)}°C</span><span class="lc-cond">${esc(c.condition || "Current conditions")}</span></div>` + chip("FEELS LIKE", r(c.feels_like_c) + "°C") + chip("HUMIDITY", r(c.humidity) + "%") + chip("WIND", r(c.wind_kmh) + " km/h") + chip("RAIN NOW", (c.precip_mm == null ? 0 : c.precip_mm) + " mm") + (w.elevation_m != null ? chip("ELEVATION", Math.round(w.elevation_m) + " m") : "");
    note.innerHTML = (ctx.live ? "Status and risk for places outside the monitored list are estimated from live weather (days since a 1 mm rain day, 30-day rainfall and the 7-day forecast). " : "") + 'Weather by <a href="https://open-meteo.com/" target="_blank" rel="noopener">Open-Meteo</a> · places © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>. Past rainfall is model-estimated, not a rain-gauge reading. Pinpointed at ' + Number(ctx.lat).toFixed(3) + ", " + Number(ctx.lon).toFixed(3) + ".";
  }
  function tipsBox() {
    const t = [...document.querySelectorAll("#page-3 .panel-title")].find((x) => x.textContent.trim() === "HYPERLOCAL CONSERVATION TIPS");
    return t ? t.nextElementSibling : null;
  }
  let tipsReq = 0;
  async function setTips(w, live, place) {
    const box = tipsBox();
    if (!box) return;
    if (tipsOriginal == null) tipsOriginal = box.innerHTML;
    const req = ++tipsReq;
    if (!live || !place) {
      box.innerHTML = tipsOriginal;
      return;
    }
    const L = WCProg.mount(box, { label: "Gemini is writing tips for " + (place.name || "this place"), mode: "replace", compact: true, min: 650 });
    let d;
    try {
      d = await apiFetch("/tips?" + new URLSearchParams({
        lat: place.lat,
        lon: place.lon,
        name: place.name || "",
        state: place.state || "",
        country: place.country || ""
      }));
    } catch (e) {
      d = { ok: false };
    }
    if (req !== tipsReq) {
      L.cancel();
      return;
    }
    await L.done();
    if (req !== tipsReq) return;
    if (!d.ok || !d.tips || !d.tips.length) {
      box.innerHTML = tipsOriginal;
      return;
    }
    box.innerHTML = d.tips.map((t, i) => `<div class="tip-row"${i === 0 ? ' style="border-top:none; padding-top:0;"' : ""}><span class="tip-num">${i + 1}</span><span class="tip-text">${t.title ? `<b class="tip-title">${esc(t.title)}</b>` : ""}${esc(t.text)}</span></div>`).join("") + '<div class="tip-foot">Written by Gemini from live weather, citizen reports and government alerts</div>';
    WCProg.reveal(box);
  }
  function setOtherMatches(list) {
    otherList = list || [];
    let box = $id("otherMatches");
    if (!box) {
      const head = $id("searchResultHead");
      if (!head) return;
      box = document.createElement("div");
      box.id = "otherMatches";
      box.className = "other-matches";
      head.parentNode.insertBefore(box, head);
      box.addEventListener("click", (e) => {
        const el = e.target.closest("[data-om]");
        if (!el) return;
        const p = otherList[parseInt(el.dataset.om, 10)];
        if (!p) return;
        const rest = otherList.filter((_, j) => j !== parseInt(el.dataset.om, 10));
        if (lastTop) rest.unshift(lastTop);
        const inp = $id("citySearchInput");
        if (inp) inp.value = placeLabel(p);
        const token = ++placeReq;
        setOtherMatches(rest);
        loadPlace(p, token);
      });
    }
    if (!otherList.length) {
      box.classList.remove("show");
      box.innerHTML = "";
      return;
    }
    box.innerHTML = '<span class="om-label" style="--i:0">OTHER MATCHES</span>' + otherList.slice(0, 6).map((p, i) => `<span class="om-pill" style="--i:${i + 1}" data-om="${i}" title="${esc(placeLabel(p))}">${esc(p.name)}${p.context ? " <i>" + esc(p.context.split(",").slice(0, 2).join(",")) + "</i>" : ""}</span>`).join("");
    box.classList.add("show");
  }
  const placeLabel = (p) => p.monitored ? p.name : p.name + (p.context ? ", " + p.context : "");
  let suggestItems = [], suggestSel = -1, suggestTimer = null, suggestReq = 0;
  function openSuggestBox() {
    const b = $id("geoSuggest");
    if (!b) return null;
    b.classList.remove("closing");
    if (b.style.display !== "block") {
      b.style.display = "block";
      void b.offsetWidth;
    }
    if (!b.classList.contains("open")) {
      b.classList.remove("open");
      void b.offsetWidth;
      b.classList.add("open");
    }
    return b;
  }
  function hideSuggest() {
    const b = $id("geoSuggest");
    suggestReq++;
    suggestItems = [];
    suggestSel = -1;
    if (!b || b.style.display !== "block" || b.classList.contains("closing")) return;
    b.classList.remove("open");
    b.classList.add("closing");
    setTimeout(() => {
      if (b.classList.contains("closing")) {
        b.style.display = "none";
        b.innerHTML = "";
        b.classList.remove("closing");
      }
    }, 180);
  }
  function renderSuggest(items) {
    suggestItems = items;
    suggestSel = -1;
    if (!items.length) {
      hideSuggest();
      return;
    }
    const b = openSuggestBox();
    if (!b) return;
    b.innerHTML = items.map((p, i) => `<div class="geo-item" data-gi="${i}" style="--i:${i}">
        <div><div class="g-name">${esc(p.name)}</div><div class="g-ctx">${esc(p.context || p.country || "")}</div></div>
        ${p.monitored ? '<span class="geo-tag">MONITORED</span>' : ""}</div>`).join("");
  }
  function pickSuggestion(i) {
    const p = suggestItems[i];
    if (!p) return;
    const inp = $id("citySearchInput");
    if (inp) inp.value = placeLabel(p);
    hideSuggest();
    setOtherMatches([]);
    const token = ++placeReq;
    loadPlace(p, token);
  }
  function initSuggest() {
    const inp = $id("citySearchInput"), box = $id("geoSuggest");
    if (!inp || !box || inp.dataset.wcSuggest) return;
    inp.dataset.wcSuggest = "1";
    inp.addEventListener("input", () => {
      clearTimeout(suggestTimer);
      const q = inp.value.trim();
      if (q.length < 2) {
        hideSuggest();
        return;
      }
      suggestTimer = setTimeout(async () => {
        const req = ++suggestReq;
        const box2 = openSuggestBox();
        const L = box2 ? WCProg.mount(box2, { label: "Searching places", mode: "replace", compact: true, min: 380, tail: 200 }) : null;
        try {
          const items = await apiFetch("/geocode?mode=suggest&q=" + encodeURIComponent(q));
          if (req !== suggestReq) {
            if (L) L.cancel();
            return;
          }
          if (L) await L.done();
          if (req === suggestReq && document.activeElement === inp) renderSuggest(items);
          else if (req === suggestReq) hideSuggest();
        } catch (e) {
          if (L) L.cancel();
          if (req === suggestReq) hideSuggest();
        }
      }, 280);
    });
    inp.addEventListener("keydown", (e) => {
      if (!suggestItems.length) return;
      const mark = () => box.querySelectorAll(".geo-item").forEach((el, i) => el.classList.toggle("sel", i === suggestSel));
      if (e.key === "ArrowDown") {
        e.preventDefault();
        suggestSel = (suggestSel + 1) % suggestItems.length;
        mark();
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        suggestSel = (suggestSel - 1 + suggestItems.length) % suggestItems.length;
        mark();
      } else if (e.key === "Escape") {
        hideSuggest();
      } else if (e.key === "Enter" && suggestSel >= 0) {
        e.preventDefault();
        e.stopImmediatePropagation();
        pickSuggestion(suggestSel);
      }
    }, true);
    box.addEventListener("mousedown", (e) => {
      const el = e.target.closest("[data-gi]");
      if (el) {
        e.preventDefault();
        pickSuggestion(parseInt(el.dataset.gi, 10));
      }
    });
    inp.addEventListener("blur", () => setTimeout(hideSuggest, 120));
    const grid = document.querySelector("#page-3 .day-grid");
    if (grid) grid.addEventListener("click", (e) => {
      const c = e.target.closest(".day-card");
      if (!c) return;
      grid.querySelectorAll(".day-card").forEach((x) => x.classList.remove("active"));
      c.classList.add("active");
    });
  }
  function renderSearchResult(loc) {
    const live = !!loc.live;
    const head = $id("searchResultHead");
    if (head) {
      head.innerHTML = `
        <div>
          <span class="result-name">${esc(loc.name)}</span>
          <span class="result-sub">${live ? esc(loc.context) + " · live weather" : esc(loc.state)} · updated ${timeAgo(loc.updated_at)}</span>
        </div>
        <div class="result-badges">
          <span class="badge ${statusClass(loc.status_label)}">${esc(loc.status_label)}</span>
          <span class="badge ${loc.risk_tier}">${loc.risk_tier.charAt(0).toUpperCase() + loc.risk_tier.slice(1)}</span>
        </div>`;
    }
    const grid = $id("searchStatGrid");
    if (grid) {
      const cards = grid.querySelectorAll(".metric-card");
      const setCard = (c, label, num, note, color) => {
        if (!c) return;
        c.querySelector(".metric-label").textContent = label;
        c.querySelector(".metric-num").textContent = num;
        const n = c.querySelector(".metric-note");
        n.textContent = note;
        n.style.color = color || "";
      };
      if (live) {
        const w = loc.w, p = w.past;
        setCard(cards[0], "Rain · Past 7 Days", p.rain_7d_mm + " mm", p.rain_30d_mm + " mm in the last 30 days");
        setCard(cards[1], "Days Since Rainfall", p.capped ? p.window_days - 1 + "+" : p.days_since_rain, "A rain day = 1 mm or more");
        setCard(cards[2], "Citizen Reports (7d)", w.citizen_reports || 0, "Last 7 days");
        setCard(cards[3], "Scarcity Score", w.derived.scarcity_score + " / 10", "Based on live weather");
      } else {
        const score = ((100 - loc.reservoir_pct) / 100 * 5 + Math.min(loc.days_since_rainfall, 30) / 30 * 5).toFixed(1);
        setCard(cards[0], "Reservoir Level", loc.reservoir_pct + "%", "Current fill level", "#e8836a");
        setCard(cards[1], "Days Since Rainfall", loc.days_since_rainfall, "Days without rain");
        setCard(cards[2], "Citizen Reports (7d)", loc.citizen_reports_7d || 0, "Last 7 days");
        setCard(cards[3], "Scarcity Score", score + " / 10", "Based on data");
      }
    }
    const nearbyPanel = $id("nearbyPanel");
    if (nearbyPanel) {
      const row = (n, i, len, km) => `
          <div class="nearby-row"${i === len - 1 ? ' style="padding-bottom:20px;"' : ""}>
            <div><span class="nn">${esc(n.name)}</span>${km != null ? `<span class="nd">${km} km</span>` : ""}</div>
            <span class="badge ${statusClass(n.status_label)}">${esc(n.status_label)}</span>
          </div>`;
      if (live) {
        const list = loc.w.nearby || [];
        nearbyPanel.innerHTML = `<div class="panel-title">NEARBY LOCALITIES - NOT ALL THE SAME</div>` + (list.length ? list.map((n, i) => row(n, i, list.length, n.distance_km)).join("") : '<div class="no-conn" style="margin:16px 22px 22px;width:auto;">No Connections</div>');
      } else if (loc.nearby) {
        nearbyPanel.innerHTML = `<div class="panel-title">NEARBY LOCALITIES - NOT ALL THE SAME</div>` + loc.nearby.map((n, i) => row(n, i, loc.nearby.length, Math.round(haversineKm(loc.lat, loc.lon, n.lat, n.lon)))).join("");
      }
    }
  }
  function addMyLocPill() {
    const row = document.querySelector("#localityPillRow .pill-row");
    if (!row || !MY_LOC) return;
    const existing = $id("myLocPill");
    if (existing) {
      existing.title = MY_LOC.label || "Your location";
      return;
    }
    const pill = document.createElement("span");
    pill.className = "pill";
    pill.id = "myLocPill";
    pill.textContent = "My location";
    pill.title = MY_LOC.label || "Your current position";
    row.insertBefore(pill, row.firstChild);
    pill.addEventListener("click", () => {
      row.querySelectorAll(".pill").forEach((x) => x.classList.remove("active", "orange"));
      pill.classList.add("active", "orange");
      const inp = $id("citySearchInput");
      if (inp) inp.value = MY_LOC.label || "My location";
      setOtherMatches([]);
      const token = ++placeReq;
      loadPlace({
        name: MY_LOC.place || MY_LOC.label || "My location",
        context: MY_LOC.label || "",
        state: MY_LOC.state || "",
        country: MY_LOC.country || "",
        lat: MY_LOC.lat,
        lon: MY_LOC.lon,
        keepPill: true
      }, token);
    });
  }
  function initCityUseLocation() {
    const btn = $id("cityUseLocation");
    if (!btn || btn.dataset.wcWired) return;
    btn.dataset.wcWired = "1";
    const txt = btn.querySelector(".ul-txt");
    const setTxt = (t) => {
      if (txt) txt.textContent = t;
      btn.title = t;
    };
    const run = () => {
      if (btn.classList.contains("busy")) return;
      if (!navigator.geolocation) {
        setTxt("Location not supported");
        markLocationState("Location unavailable");
        return;
      }
      btn.classList.add("busy");
      setTxt("Locating…");
      setSearchPlaceholders("Locating…");
      hideSuggest();
      setOtherMatches([]);
      const token = ++placeReq;
      const L = headLoader("Finding your exact position");
      navigator.geolocation.getCurrentPosition(async (pos) => {
        const { latitude: lat, longitude: lon, accuracy } = pos.coords;
        let r = null;
        try {
          if (L) L.label("Finding your locality");
          r = await apiFetch(`/reverse?lat=${lat}&lon=${lon}`);
        } catch (e) {
          r = null;
        }
        btn.classList.remove("busy");
        if (token !== placeReq) {
          if (L) L.cancel();
          return;
        }
        const label = r && r.label ? r.label : "Your current position";
        MY_LOC = Object.assign({ lat, lon, acc: accuracy, label: null, place: null, nearest: null }, r || {}, { lat, lon, acc: accuracy });
        const inp = $id("citySearchInput");
        if (inp) inp.value = label;
        document.querySelectorAll("#localityPillRow .pill").forEach((x) => x.classList.remove("active", "orange"));
        setTxt("Location set ✓" + (accuracy ? " · ±" + Math.round(accuracy) + " m" : ""));
        setSearchPlaceholders("No Connections");
        addMyLocPill();
        loadPlace({
          name: (r && (r.place || r.label)) || "Your current position",
          context: r && r.label ? r.label : lat.toFixed(4) + ", " + lon.toFixed(4),
          state: (r && r.state) || "",
          country: (r && r.country) || "",
          lat,
          lon
        }, token, L);
      }, (err) => {
        btn.classList.remove("busy");
        if (L) L.cancel();
        if (token !== placeReq) return;
        const denied = err && err.code === 1;
        setTxt(denied ? "Location denied - click to retry" : "Could not get location - click to retry");
        markLocationState(denied ? "Location denied" : "Location unavailable");
      }, { enableHighAccuracy: true, timeout: 15e3, maximumAge: 0 });
    };
    btn.addEventListener("click", run);
    btn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        run();
      }
    });
    btn._wcRun = run;
  }
  const PLACEHOLDER_TEXTS = ["No Connections", "Location denied", "Location unavailable", "Locating…"];
  function setSearchPlaceholders(label) {
    const page = $id("page-3");
    if (!page) return;
    page.querySelectorAll(".no-conn, .nc-num").forEach((el) => {
      if (PLACEHOLDER_TEXTS.includes(el.textContent.trim())) el.textContent = label;
    });
  }
  function markLocationState(label) {
    setSearchPlaceholders(label);
    searchHead(`<div class="no-conn" style="justify-content:flex-start;min-height:0;padding:14px 18px;width:auto;">${esc(label)}</div>`);
  }
  function autoLocate() {
    const btn = $id("cityUseLocation");
    if (btn && typeof btn._wcRun === "function") btn._wcRun();
  }
  function initSearchBar() {
    initSuggest();
    initCityUseLocation();
    addMyLocPill();
    const input = document.getElementById("citySearchInput");
    const btn = document.getElementById("citySearchBtn");
    const hdrInp = document.querySelector(".search-box input");
    const doSearch = () => {
      const val = input ? input.value.trim() : "";
      if (val) searchLocality(val);
    };
    if (btn) btn.addEventListener("click", doSearch);
    if (input) input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") doSearch();
    });
    if (hdrInp) {
      hdrInp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const val = hdrInp.value.trim();
          if (!val) return;
          if (window.goTo) window.goTo(3);
          else document.querySelector('[data-goto="3"]')?.click();
          const inp = document.getElementById("citySearchInput");
          if (inp) inp.value = val;
          setTimeout(() => searchLocality(val), 200);
        }
      });
    }
  }
  window.wcVote = async function(localityName, lat, lon) {
    return apiFetch("/vote", {
      method: "POST",
      body: JSON.stringify({ device_id: DEVICE_ID, locality_name: localityName, lat, lon })
    });
  };
  window.WaterCastAPI = { loadNews, loadTrustScore, searchLocality, apiFetch, DEVICE_ID };
  async function loadAll() {
    wireNewsPills();
    let newsLoaded = false;
    document.querySelectorAll('[data-goto="1"]').forEach((el) => el.addEventListener("click", () => {
      if (!newsLoaded) {
        newsLoaded = true;
        loadNews(newsFilter);
      } else fillNewsSide();
    }));
    loadLocalities().catch(() => {});
    initSOSForm();
    initSOSSearch();
    loadRecentSOS(null);
    loadMySOS();
    initSearchBar();
    autoLocate();
    loadTrustScore().catch(() => {});
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", checkHealth);
  } else {
    setTimeout(checkHealth, 100);
  }
})();
