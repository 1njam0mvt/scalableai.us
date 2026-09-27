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

    // Apply immediately to avoid a flash of the wrong theme.
    if (document.body) {
        applyTheme(getSaved());
    }

    // If this script runs after the DOM is already parsed (e.g. placed at
    // the end of <body>), DOMContentLoaded may already have fired, so check
    // readyState instead of relying solely on the event.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
