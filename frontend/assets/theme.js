// Light/dark theme for every page. Load in <head> before tw-config.js so the saved theme applies
// before first paint. Each color token is a CSS variable holding "R G B", which lets Tailwind keep
// opacity modifiers (bg-primary-container/15) working in both themes.
(function () {
  const KEY = "career-advisor-theme";

  const DARK = {
    "background": "#0f131d", "on-background": "#dfe2f1",
    "surface": "#0f131d", "surface-dim": "#0f131d", "surface-bright": "#353944", "surface-tint": "#ffba38",
    "surface-container-lowest": "#0a0e18", "surface-container-low": "#171b26", "surface-container": "#1c1f2a",
    "surface-container-high": "#262a35", "surface-container-highest": "#313540", "surface-variant": "#313540",
    "on-surface": "#dfe2f1", "on-surface-variant": "#d6c4ac",
    "inverse-surface": "#dfe2f1", "inverse-on-surface": "#2c303b", "inverse-primary": "#7e5700",
    "outline": "#9e8e78", "outline-variant": "#514532",
    "primary": "#ffd79b", "on-primary": "#432c00", "primary-container": "#ffb300", "on-primary-container": "#6b4900",
    "primary-fixed": "#ffdeac", "primary-fixed-dim": "#ffba38", "on-primary-fixed": "#281900", "on-primary-fixed-variant": "#604100",
    "secondary": "#ffb95f", "on-secondary": "#472a00", "secondary-container": "#ee9800", "on-secondary-container": "#5b3800",
    "secondary-fixed": "#ffddb8", "secondary-fixed-dim": "#ffb95f", "on-secondary-fixed": "#2a1700", "on-secondary-fixed-variant": "#653e00",
    "tertiary": "#eddf7b", "on-tertiary": "#363100", "tertiary-container": "#d0c363", "on-tertiary-container": "#585000",
    "tertiary-fixed": "#f2e580", "tertiary-fixed-dim": "#d5c867", "on-tertiary-fixed": "#201c00", "on-tertiary-fixed-variant": "#4f4800",
    "error": "#ffb4ab", "on-error": "#690005", "error-container": "#93000a", "on-error-container": "#ffdad6",
    "emerald-400": "#34d399", "emerald-500": "#10b981",
    "shadow": "#000000",
  };

  // Warm off-white surfaces; gold stays the accent, but gold *text* is darkened to stay readable on white.
  const LIGHT = {
    "background": "#fbfaf7", "on-background": "#1c1b19",
    "surface": "#fbfaf7", "surface-dim": "#ece9e2", "surface-bright": "#ffffff", "surface-tint": "#8a5d00",
    "surface-container-lowest": "#ffffff", "surface-container-low": "#f6f4ef", "surface-container": "#efece6",
    "surface-container-high": "#e8e5de", "surface-container-highest": "#dfdcd4", "surface-variant": "#ebe4d6",
    "on-surface": "#1c1b19", "on-surface-variant": "#51483b",
    "inverse-surface": "#2f3033", "inverse-on-surface": "#f2f0ec", "inverse-primary": "#ffb300",
    "outline": "#817667", "outline-variant": "#d3c8b6",
    "primary": "#8a5d00", "on-primary": "#281900", "primary-container": "#ffb300", "on-primary-container": "#3d2800",
    "primary-fixed": "#ffdeac", "primary-fixed-dim": "#ffba38", "on-primary-fixed": "#281900", "on-primary-fixed-variant": "#604100",
    "secondary": "#9a5a00", "on-secondary": "#ffffff", "secondary-container": "#ffb95f", "on-secondary-container": "#3d2400",
    "secondary-fixed": "#ffddb8", "secondary-fixed-dim": "#ffb95f", "on-secondary-fixed": "#2a1700", "on-secondary-fixed-variant": "#653e00",
    "tertiary": "#6b6000", "on-tertiary": "#ffffff", "tertiary-container": "#efe38a", "on-tertiary-container": "#4a4300",
    "tertiary-fixed": "#f2e580", "tertiary-fixed-dim": "#d5c867", "on-tertiary-fixed": "#201c00", "on-tertiary-fixed-variant": "#4f4800",
    "error": "#b3261e", "on-error": "#ffffff", "error-container": "#ffdad6", "on-error-container": "#410002",
    "emerald-400": "#047857", "emerald-500": "#059669",
    "shadow": "#8a8171",
  };

  const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(" ");
  const vars = (palette) => Object.entries(palette).map(([k, v]) => `--c-${k}: ${rgb(v)};`).join(" ");

  const style = document.createElement("style");
  style.textContent = `:root, :root.dark { ${vars(DARK)} color-scheme: dark; }
:root.light { ${vars(LIGHT)} color-scheme: light; }
/* Gold on white fails contrast; gold used as text falls back to the darker primary in light mode. */
:root.light .text-primary-container { color: rgb(var(--c-primary)); }`;
  document.head.appendChild(style);

  function read() { try { return localStorage.getItem(KEY); } catch { return null; } }
  function get() { return document.documentElement.classList.contains("light") ? "light" : "dark"; }
  function set(theme) {
    const root = document.documentElement;
    root.classList.toggle("light", theme === "light");
    root.classList.toggle("dark", theme !== "light");
    try { localStorage.setItem(KEY, theme); } catch {}
    document.querySelectorAll("[data-theme-icon]").forEach((el) => { el.textContent = theme === "light" ? "dark_mode" : "light_mode"; });
  }
  function toggle() { set(get() === "light" ? "dark" : "light"); }

  // Dark is the default look; a saved choice wins.
  const saved = read();
  document.documentElement.classList.toggle("light", saved === "light");
  document.documentElement.classList.toggle("dark", saved !== "light");

  // Tailwind color tokens that point at the variables above.
  const tokens = {};
  for (const k of Object.keys(DARK)) if (!k.startsWith("emerald-") && k !== "shadow") tokens[k] = `rgb(var(--c-${k}) / <alpha-value>)`;
  tokens.emerald = { 400: "rgb(var(--c-emerald-400) / <alpha-value>)", 500: "rgb(var(--c-emerald-500) / <alpha-value>)" };
  tokens.shadow = "rgb(var(--c-shadow) / <alpha-value>)";

  // Sun/moon button markup for the portal headers; Theme.bind() wires it up after mounting.
  const buttonHtml = (cls) => `<button type="button" data-theme-toggle class="${cls}" title="Switch light / dark theme" aria-label="Switch light / dark theme"><span class="material-symbols-outlined text-[20px]" data-theme-icon>${get() === "light" ? "dark_mode" : "light_mode"}</span></button>`;
  function bind(root = document) {
    root.querySelectorAll("[data-theme-toggle]").forEach((b) => b.addEventListener("click", toggle));
  }

  window.Theme = { get, set, toggle, tokens, buttonHtml, bind };
})();
