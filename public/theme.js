/*
 * Shared theme toggle for terms.html, privacy.html, faq.html,
 * features.html, contact.html.
 *
 * Matches the main app's own theme system (frontend/script.js
 * THEME_KEY/applyTheme/toggleTheme) so switching themes on these public
 * pages behaves identically to switching them inside the app - same
 * localStorage key, same single-icon-swap approach, same transition.
 *
 * Two entry points, both required:
 *   1. The inline blocking <script> in each page's <head> (before any
 *      CSS) sets data-theme on <html> synchronously so the correct theme
 *      is applied before first paint. Kept inline per page rather than
 *      linked here, since an external <script src> would itself cost a
 *      network round trip and reintroduce the flash it's meant to prevent.
 *   2. This file wires up the toggle button's click handler and icon.
 *      Safe to load normally/deferred since the theme itself is already
 *      correct by the time this runs.
 */
(function () {
    var THEME_KEY = 'scalable_theme';

    var ICON_MOON = '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
    var ICON_SUN = '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>';

    function getStoredTheme() {
        try {
            return localStorage.getItem(THEME_KEY);
        } catch (e) {
            // localStorage can throw in some browsers' private-browsing
            // modes - fall through to the system preference instead of
            // letting that exception break page load.
            return null;
        }
    }

    function setStoredTheme(theme) {
        try {
            localStorage.setItem(THEME_KEY, theme);
        } catch (e) {
            // Preference just won't persist this session; not fatal.
        }
    }

    var transitionTimer = null;

    function applyTheme(theme, animate) {
        var isLight = theme === 'light';
        var root = document.documentElement;

        if (animate) {
            root.classList.add('theme-transitioning');
            if (transitionTimer) clearTimeout(transitionTimer);
            transitionTimer = setTimeout(function () {
                root.classList.remove('theme-transitioning');
            }, 520);
        }

        root.setAttribute('data-theme', isLight ? 'light' : 'dark');

        var icon = document.querySelector('.theme-toggle svg');
        if (icon) icon.innerHTML = isLight ? ICON_SUN : ICON_MOON;

        var toggle = document.querySelector('.theme-toggle');
        if (toggle) {
            toggle.setAttribute('aria-pressed', isLight ? 'true' : 'false');
            toggle.setAttribute('aria-label', isLight ? 'Switch to dark theme' : 'Switch to light theme');
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var toggle = document.querySelector('.theme-toggle');
        if (!toggle) return;

        // Sync the button's icon/aria state with whatever the inline
        // blocking script in <head> already applied before this ran.
        applyTheme(document.documentElement.getAttribute('data-theme') || 'dark', false);

        toggle.addEventListener('click', function () {
            var current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
            var next = current === 'light' ? 'dark' : 'light';
            applyTheme(next, true);
            setStoredTheme(next);
        });
    });
})();
