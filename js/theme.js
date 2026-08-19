// theme.js — theme toggle, persisted to localStorage.
(function () {
  const STORAGE_KEY = 'lc_bankvalue_theme';
  const THEMES = ['terminal', 'editorial'];
  const DEFAULT_THEME = 'terminal';

  function getStoredTheme() {
    try {
      const t = localStorage.getItem(STORAGE_KEY);
      return THEMES.includes(t) ? t : null;
    } catch (_) {
      return null;
    }
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('[data-theme-btn]').forEach((btn) => {
      btn.classList.toggle('active', btn.getAttribute('data-theme-btn') === theme);
    });
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch (_) {}
  }

  function initTheme() {
    applyTheme(getStoredTheme() || DEFAULT_THEME);
    document.querySelectorAll('[data-theme-btn]').forEach((btn) => {
      btn.addEventListener('click', () => applyTheme(btn.getAttribute('data-theme-btn')));
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }
})();
