(function () {
    var STORAGE_KEY = 'scalable_theme';

    function applyTheme(theme) {
        var isLight = theme === 'light';
        document.body.classList.toggle('light-theme', isLight);

        var toggle = document.querySelector('.theme-toggle');
        if (!toggle) return;
        var moon = toggle.querySelector('.icon-moon');
        var sun = toggle.querySelector('.icon-sun');
        if (moon && sun) {
            moon.style.display = isLight ? 'none' : '';
            sun.style.display = isLight ? '' : 'none';
        }
        toggle.setAttribute('aria-label', isLight ? 'Switch to dark theme' : 'Switch to light theme');
    }

    function getSaved() {
        var saved = null;
        try { saved = localStorage.getItem(STORAGE_KEY); } catch (error) { }
        return saved === 'light' ? 'light' : 'dark';
    }

    function init() {
        applyTheme(getSaved());

        var toggle = document.querySelector('.theme-toggle');
        if (!toggle) return;

        toggle.addEventListener('click', function () {
            var nowLight = !document.body.classList.contains('light-theme');
            applyTheme(nowLight ? 'light' : 'dark');
            try { localStorage.setItem(STORAGE_KEY, nowLight ? 'light' : 'dark'); } catch (error) { }
        });
    }

    // Apply theme immediately (avoids a flash of the wrong theme).
    if (document.body) {
        applyTheme(getSaved());
    }

    // Attach the click handler once the DOM is ready. If this script is
    // loaded at the end of <body> (as intended), the DOM is already parsed
    // and DOMContentLoaded may have already fired, so check readyState
    // instead of only listening for the event.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
