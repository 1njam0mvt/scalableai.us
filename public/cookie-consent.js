(function () {
    var STORAGE_KEY = 'scalable_cookie_consent';
    var banner = document.createElement('aside');
    banner.className = 'cookie-banner';
    banner.setAttribute('aria-label', 'Cookie preferences');
    banner.innerHTML = '<div class="cookie-banner-copy"><strong>We value your privacy</strong><p>We use essential browser storage to keep Scalable working. Optional cookies may be used for analytics or advertising only with your permission. <a href="/privacy.html#learn-more">Read our Privacy Policy</a>.</p></div><div class="cookie-banner-actions"><button type="button" class="cookie-manage">Manage cookies</button><button type="button" class="cookie-reject">Reject non-essential</button><button type="button" class="cookie-accept">Accept all</button></div>';
    document.body.appendChild(banner);

    function setConsent(value) {
        try { localStorage.setItem(STORAGE_KEY, value); } catch (error) { }
        banner.hidden = true;
    }

    function showBanner() {
        banner.hidden = false;
    }

    banner.querySelector('.cookie-accept').addEventListener('click', function () {
        setConsent('accepted');
    });
    banner.querySelector('.cookie-reject').addEventListener('click', function () {
        setConsent('rejected');
    });
    banner.querySelector('.cookie-manage').addEventListener('click', showBanner);

    var savedConsent = null;
    try { savedConsent = localStorage.getItem(STORAGE_KEY); } catch (error) { }
    banner.hidden = savedConsent === 'accepted' || savedConsent === 'rejected';

    window.scalableManageCookies = showBanner;
}());
