(function() {
  var d = document.documentElement;
  try {
    var v = document.createElement("video");
    if (!v.canPlayType || !(v.canPlayType("video/mp4") || v.canPlayType("video/webm")) || !Element.prototype.animate) return;
  } catch (e) {
    return;
  }
  d.classList.add("has-intro");
  window.__introGuard = setTimeout(function() {
    d.classList.remove("has-intro");
    d.classList.add("intro-done");
    var el = document.getElementById("intro");
    if (el) el.remove();
  }, 9e3);
})();
