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

    var saved = null;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch (error) { }
    applyTheme(saved === 'light' ? 'light' : 'dark');

    document.addEventListener('DOMContentLoaded', function () {
        var toggle = document.querySelector('.theme-toggle');
        if (!toggle) return;

        applyTheme(saved === 'light' ? 'light' : 'dark');

        toggle.addEventListener('click', function () {
            var nowLight = !document.body.classList.contains('light-theme');
            applyTheme(nowLight ? 'light' : 'dark');
            try { localStorage.setItem(STORAGE_KEY, nowLight ? 'light' : 'dark'); } catch (error) { }
        });
    });
}());
