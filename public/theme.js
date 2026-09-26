/*
 * Shared theme toggle for terms.html, privacy.html, faq.html,
 * features.html, contact.html.
 *
 * Two entry points, both required:
 *   1. theme-init.js (inline, in <head>, before any CSS) - sets
 *      data-theme on <html> synchronously so the correct theme is applied
 *      before first paint. This file is tiny on purpose: an external
 *      <script src> would itself cost a network round trip and reintroduce
 *      the same flash it's meant to prevent, so it's inlined per page
 *      rather than linked.
 *   2. theme.js (this file, external, loaded normally) - wires up the
 *      toggle button's click handler. Safe to load late/deferred since
 *      the theme itself is already correct by the time this runs.
 */
(function () {
    var STORAGE_KEY = 'theme-preference';

    function getStoredTheme() {
        try {
            return localStorage.getItem(STORAGE_KEY);
        } catch (e) {
            // localStorage can throw in some browsers' private-browsing
            // modes - fall through to the system preference instead of
            // letting that exception break page load.
            return null;
        }
    }

    function setStoredTheme(theme) {
        try {
            localStorage.setItem(STORAGE_KEY, theme);
        } catch (e) {
            // Preference just won't persist this session; not fatal.
        }
    }

    function applyTheme(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        var toggle = document.querySelector('.theme-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', theme === 'light' ? 'true' : 'false');
            toggle.setAttribute(
                'aria-label',
                theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'
            );
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var toggle = document.querySelector('.theme-toggle');
        if (!toggle) return;

        // Sync the button's aria state with whatever theme-init.js already
        // applied before this ran.
        applyTheme(document.documentElement.getAttribute('data-theme') || 'dark');

        toggle.addEventListener('click', function () {
            var current = document.documentElement.getAttribute('data-theme') || 'dark';
            var next = current === 'light' ? 'dark' : 'light';
            applyTheme(next);
            setStoredTheme(next);
        });
    });
})();