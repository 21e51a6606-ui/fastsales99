/* Shared front-end helpers for FastSales admin portal */
(function () {
  window.FS = {
    toast(msg, ms = 2600) {
      let t = document.getElementById("toast");
      if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.appendChild(t); }
      t.textContent = msg; t.classList.add("show");
      clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms);
    },
    async post(url, data, method = "POST") {
      const r = await fetch(url, { method, headers: { "Content-Type": "application/json", "X-Requested-With": "fetch" }, body: data ? JSON.stringify(data) : undefined });
      let j = {};
      try { j = await r.json(); } catch (e) { }
      if (!r.ok) throw new Error(j.error || ("Request failed (" + r.status + ")"));
      return j;
    },
    async get(url) { const r = await fetch(url, { headers: { "X-Requested-With": "fetch" } }); return r.json(); },
    openModal(id) { const m = document.getElementById(id); if (m) { m.classList.add("open"); const f = m.querySelector("input,select,textarea"); if (f) setTimeout(() => f.focus(), 50); } },
    closeModal(id) { const m = document.getElementById(id); if (m) m.classList.remove("open"); },
    inr(v, compact) {
      v = Number(v || 0);
      if (compact) { if (Math.abs(v) >= 1e7) return "₹" + (v / 1e7).toFixed(1) + "Cr"; if (Math.abs(v) >= 1e5) return "₹" + (v / 1e5).toFixed(1) + "L"; if (Math.abs(v) >= 1e3) return "₹" + (v / 1e3).toFixed(1) + "K"; }
      return "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
    },
    fmtDate(iso) { if (!iso) return "-"; const d = new Date(iso); return d.toLocaleString("en-US", { month: "numeric", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" }); },
    confirm(msg) { return window.confirm(msg); },
    chartColors: ["#5b4fe8", "#10b981", "#f59e0b", "#ef4444", "#3b82f6", "#a855f7", "#14b8a6", "#f97316"],
    esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); },
  };

  document.addEventListener("DOMContentLoaded", () => {
    if (window.lucide) lucide.createIcons();
    // close modals
    document.querySelectorAll(".modal-backdrop").forEach(b => {
      b.addEventListener("click", e => { if (e.target === b) b.classList.remove("open"); });
    });
    document.addEventListener("keydown", e => { if (e.key === "Escape") document.querySelectorAll(".modal-backdrop.open").forEach(m => m.classList.remove("open")); });
    // dropdown
    const um = document.getElementById("userMenu");
    if (um) {
      um.addEventListener("click", e => { e.stopPropagation(); um.querySelector(".dropdown").classList.toggle("open"); });
      document.addEventListener("click", () => um.querySelector(".dropdown").classList.remove("open"));
    }
    // theme toggle
    const tt = document.getElementById("themeToggle");
    if (tt) tt.addEventListener("click", async () => {
      const dark = document.documentElement.getAttribute("data-theme") !== "dark";
      document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
      try { localStorage.setItem("fs-theme", dark ? "dark" : "light"); } catch (e) { }
      try { await FS.post("/settings/theme", { dark }); } catch (e) { }
      if (window.lucide) lucide.createIcons();
    });
    // flash auto-dismiss
    setTimeout(() => document.querySelectorAll(".flash-stack .alert").forEach(a => a.style.display = "none"), 5000);
    // global search
    const gs = document.getElementById("globalSearch");
    if (gs) gs.addEventListener("keydown", e => { if (e.key === "Enter" && gs.value.trim()) location.href = "/search?q=" + encodeURIComponent(gs.value.trim()); });
    document.addEventListener("keydown", e => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); if (gs) gs.focus(); } });
    // refresh button
    const rb = document.getElementById("refreshBtn");
    if (rb) rb.addEventListener("click", () => location.reload());
    // confirm forms
    document.querySelectorAll("form[data-confirm]").forEach(f => f.addEventListener("submit", e => { if (!confirm(f.dataset.confirm)) e.preventDefault(); }));
    // show/hide password
    document.querySelectorAll(".eye").forEach(b => b.addEventListener("click", () => {
      const i = b.parentElement.querySelector("input"); i.type = i.type === "password" ? "text" : "password";
    }));
  });
})();
