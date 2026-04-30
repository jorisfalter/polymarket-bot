/**
 * Shared theme + navigation helpers for all dashboard pages.
 * - Persists day/night preference in localStorage
 * - Renders a consistent navigation bar
 */

(function () {
    const STORAGE_KEY = 'polymarket_theme';

    function getCurrentTheme() {
        return localStorage.getItem(STORAGE_KEY) || 'dark';
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        localStorage.setItem(STORAGE_KEY, theme);
        const btn = document.getElementById('theme-toggle');
        if (btn) btn.textContent = theme === 'dark' ? '☀️ Light' : '🌙 Dark';
    }

    window.toggleTheme = function () {
        const next = getCurrentTheme() === 'dark' ? 'light' : 'dark';
        applyTheme(next);
    };

    // Apply theme as early as possible to avoid flash
    document.addEventListener('DOMContentLoaded', () => {
        applyTheme(getCurrentTheme());
    });
    // Also apply immediately for the documentElement
    applyTheme(getCurrentTheme());
})();
