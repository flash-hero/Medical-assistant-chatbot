/* Applies the saved colour theme before first paint (no flash). Loaded with the per-request CSP nonce. */
(function () {
  try {
    var saved = window.localStorage.getItem("ausculta-theme");
    if (saved === "light" || saved === "dark") document.documentElement.setAttribute("data-theme", saved);
  } catch {
    /* Storage blocked (private mode, policy): the system preference applies. */
  }
})();
