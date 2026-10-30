from __future__ import annotations

import streamlit as st


COMPONENT_RECOVERY_SCRIPT = r"""
<script>
(() => {
  if (window.__hkLowVolRecoveryInstalled) return;
  window.__hkLowVolRecoveryInstalled = true;
  const recoveryKey = "hk-low-vol-component-recovery";
  const moduleError = /(Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module)/i;
  const recover = (reason) => {
    const message = String(reason?.message || reason || "");
    if (!moduleError.test(message)) return;
    const now = Date.now();
    const previous = Number(sessionStorage.getItem(recoveryKey) || 0);
    if (now - previous < 45000) return;
    sessionStorage.setItem(recoveryKey, String(now));
    const url = new URL(window.location.href);
    url.searchParams.set("reload", String(now));
    window.location.replace(url.toString());
  };
  window.addEventListener("unhandledrejection", (event) => recover(event.reason));
  window.addEventListener("error", (event) => recover(event.error || event.message), true);
})();
</script>
"""


def render_html(body: str, *, target=None) -> None:
    """Render trusted app-owned HTML without routing it through Markdown."""
    destination = st if target is None else target
    html = getattr(destination, "html", None)
    if callable(html):
        html(body)
        return
    destination.markdown(body, unsafe_allow_html=True)


def install_component_recovery() -> None:
    """Reload once with a cache-busting URL when stale JS chunks are detected."""
    html = getattr(st, "html", None)
    if callable(html):
        html(COMPONENT_RECOVERY_SCRIPT, unsafe_allow_javascript=True)
