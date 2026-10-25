const form = document.getElementById("loginForm");
const userEl = document.getElementById("username");
const passEl = document.getElementById("password");
const errBox = document.getElementById("errorBox");
const errText = document.getElementById("errorText");
const submitBtn = form.querySelector("button[type=submit]");
function showError(msg) {
  errText.textContent = msg;
  errBox.classList.remove("show");
  void errBox.offsetWidth;
  errBox.classList.add("show");
}
document.getElementById("eyeBtn").addEventListener("click", () => {
  passEl.type = passEl.type === "password" ? "text" : "password";
});
[userEl, passEl].forEach((el) => el.addEventListener("input", () => errBox.classList.remove("show")));
function getLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) {
      resolve({ ok: false, reason: "unsupported" });
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ ok: true, lat: pos.coords.latitude, lon: pos.coords.longitude, acc: pos.coords.accuracy, ts: Date.now() }),
      (err) => resolve({ ok: false, reason: err.code === 1 ? "denied" : err.code === 3 ? "timeout" : "unavailable" }),
      { enableHighAccuracy: true, timeout: 15e3, maximumAge: 0 }
    );
  });
}
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const u = userEl.value.trim();
  const p = passEl.value;
  if (!u || !p) {
    showError("Please enter both username and password.");
    return;
  }
  submitBtn.disabled = true;
  try {
    const r = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: u, password: p })
    });
    let data = {};
    try {
      data = await r.json();
    } catch (_) {
    }
    if (!r.ok) {
      showError(r.status === 429 ? "Too many attempts. Please wait a few minutes and try again." : data.error || "Invalid username or password.");
      passEl.value = "";
      passEl.focus();
      return;
    }
    try {
      sessionStorage.setItem("watercast_user", data.user.username);
      sessionStorage.setItem("watercast_csrf", data.csrf);
      sessionStorage.removeItem("watercast_geo");
      sessionStorage.removeItem("watercast_manual_loc");
    } catch (_) {
    }
    document.getElementById("whoName").textContent = data.user.username;
    document.getElementById("loginView").style.display = "none";
    document.getElementById("grantedView").classList.add("show");
    const geoEl = document.getElementById("geoStatus");
    const say = (txt, warn) => {
      geoEl.classList.toggle("warn", !!warn);
      geoEl.textContent = txt;
      geoEl.classList.remove("t-in");
      void geoEl.offsetWidth;
      geoEl.classList.add("t-in");
    };
    say("Please choose Allow in the browser prompt to use your exact location.");
    const geo = await getLocation();
    try {
      sessionStorage.setItem("watercast_geo", JSON.stringify(geo));
    } catch (_) {
    }
    if (geo.ok) {
      say("Location set - accuracy about " + Math.round(geo.acc) + " m.");
    } else {
      say(geo.reason === "denied" ? "Location not shared. To use your exact location, allow it for this site (lock icon in the address bar) and log in again." : geo.reason === "unsupported" ? "This browser cannot share a location." : "Could not get a location fix - you can type your area on the Request Help page instead.", true);
    }
    setTimeout(() => {
      window.location.href = "/";
    }, geo.ok ? 1100 : 2600);
  } catch (_) {
    showError("Cannot reach the server. Check your connection and try again.");
  } finally {
    submitBtn.disabled = false;
  }
});
