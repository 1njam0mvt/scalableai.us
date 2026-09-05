/**
 * ScalableAI app UI i18n
 * -----------------------------------------------------------------
 * Separate from the "Response language" setting (which controls what
 * language the AI replies in). This module controls the language of
 * the app's own interface text: buttons, labels, menus, etc.
 *
 * URL scheme: /es/, /fr/, /ja/, /de/, /pt/, /ko/, /it/  (English = no prefix)
 * Switching language navigates to the same page under the new prefix
 * so each language is a real, crawlable, bookmarkable URL.
 */
(function () {
    "use strict";

    var SUPPORTED = ["en", "es", "fr", "ja", "de", "pt", "ko", "it"];
    var LABELS = {
        en: "English", es: "Español", fr: "Français", ja: "日本語",
        de: "Deutsch", pt: "Português", ko: "한국어", it: "Italiano"
    };
    var DEFAULT_LANG = "en";
    var DICT_CACHE = {};

    var APP_BASE = "app"; // frontend/index.html is also served under /app

    function currentLangFromPath() {
        var parts = window.location.pathname.split("/").filter(Boolean);
        var seg = parts[0] === APP_BASE ? parts[1] : parts[0];
        return SUPPORTED.indexOf(seg) !== -1 ? seg : DEFAULT_LANG;
    }

    function pathWithoutLangPrefix() {
        var parts = window.location.pathname.split("/").filter(Boolean);
        var usesAppBase = parts[0] === APP_BASE;
        if (usesAppBase) parts.shift();
        if (parts.length && SUPPORTED.indexOf(parts[0]) !== -1) {
            parts.shift();
        }
        var rest = parts.join("/");
        return (usesAppBase ? "/" + APP_BASE : "") + "/" + rest;
    }

    function urlForLang(lang) {
        var base = pathWithoutLangPrefix(); // e.g. "/" or "/app/"
        var usesAppBase = base.indexOf("/" + APP_BASE) === 0;
        var rest = usesAppBase ? base.slice(APP_BASE.length + 1) : base; // strip "/app" prefix, keep trailing path
        if (rest === "") rest = "/";

        var url;
        if (lang === DEFAULT_LANG) {
            url = usesAppBase ? "/" + APP_BASE + rest : rest;
        } else {
            var langSeg = "/" + lang + (rest === "/" ? "/" : rest);
            url = usesAppBase ? "/" + APP_BASE + langSeg : langSeg;
        }
        return url + window.location.search;
    }

    function loadDict(lang) {
        if (DICT_CACHE[lang]) return Promise.resolve(DICT_CACHE[lang]);
        return fetch("/i18n/dicts/" + lang + ".json", { credentials: "same-origin" })
            .then(function (r) {
                if (!r.ok) throw new Error("missing dict for " + lang);
                return r.json();
            })
            .then(function (data) {
                DICT_CACHE[lang] = data;
                return data;
            })
            .catch(function () {
                // Fall back to English if a language file is missing or incomplete.
                if (lang !== DEFAULT_LANG) return loadDict(DEFAULT_LANG);
                return {};
            });
    }

    function applyDict(dict) {
        CURRENT_DICT = dict || {};
        // Text content
        document.querySelectorAll("[data-i18n]").forEach(function (el) {
            var key = el.getAttribute("data-i18n");
            if (dict[key] != null) el.textContent = dict[key];
        });
        // Placeholder attributes
        document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
            var key = el.getAttribute("data-i18n-placeholder");
            if (dict[key] != null) el.setAttribute("placeholder", dict[key]);
        });
        // title attributes
        document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
            var key = el.getAttribute("data-i18n-title");
            if (dict[key] != null) el.setAttribute("title", dict[key]);
        });
        // aria-label attributes
        document.querySelectorAll("[data-i18n-aria]").forEach(function (el) {
            var key = el.getAttribute("data-i18n-aria");
            if (dict[key] != null) el.setAttribute("aria-label", dict[key]);
        });
        // Let script.js know the dictionary is ready, so it can (re-)render
        // any dynamically-generated text (greetings, JS-built menus, etc.)
        // using window.ScalableUIi18n.t(key, fallback).
        document.dispatchEvent(new CustomEvent("scalable-i18n-ready", { detail: { lang: currentLangFromPath() } }));
    }

    function injectHreflang() {
        // Remove any previously injected hreflang tags (safe on re-run)
        document.querySelectorAll('link[data-i18n-hreflang]').forEach(function (el) { el.remove(); });
        var base = "https://scalableai.us";
        var path = pathWithoutLangPrefix();
        var frag = document.createDocumentFragment();
        SUPPORTED.forEach(function (code) {
            var link = document.createElement("link");
            link.setAttribute("rel", "alternate");
            link.setAttribute("hreflang", code);
            link.setAttribute("href", base + (code === DEFAULT_LANG ? path : "/" + code + path));
            link.setAttribute("data-i18n-hreflang", "1");
            frag.appendChild(link);
        });
        var xdefault = document.createElement("link");
        xdefault.setAttribute("rel", "alternate");
        xdefault.setAttribute("hreflang", "x-default");
        xdefault.setAttribute("href", base + path);
        xdefault.setAttribute("data-i18n-hreflang", "1");
        frag.appendChild(xdefault);
        document.head.appendChild(frag);
    }

    function buildSwitcher(current) {
        var existing = document.getElementById("ui-lang-switcher");
        if (existing) existing.remove();

        var wrap = document.createElement("div");
        wrap.id = "ui-lang-switcher";
        wrap.setAttribute("role", "navigation");
        wrap.setAttribute("aria-label", "Site language");

        var button = document.createElement("button");
        button.type = "button";
        button.id = "ui-lang-switcher-btn";
        button.setAttribute("aria-haspopup", "listbox");
        button.setAttribute("aria-expanded", "false");
        button.textContent = LABELS[current] || LABELS[DEFAULT_LANG];

        var menu = document.createElement("ul");
        menu.id = "ui-lang-switcher-menu";
        menu.setAttribute("role", "listbox");
        menu.hidden = true;

        SUPPORTED.forEach(function (code) {
            var li = document.createElement("li");
            var a = document.createElement("a");
            a.href = urlForLang(code);
            a.textContent = LABELS[code];
            a.setAttribute("role", "option");
            a.setAttribute("hreflang", code);
            if (code === current) {
                a.setAttribute("aria-current", "true");
                li.className = "ui-lang-current";
            }
            li.appendChild(a);
            menu.appendChild(li);
        });

        button.addEventListener("click", function () {
            var open = menu.hidden === false;
            menu.hidden = open;
            button.setAttribute("aria-expanded", String(!open));
        });
        document.addEventListener("click", function (e) {
            if (!wrap.contains(e.target)) {
                menu.hidden = true;
                button.setAttribute("aria-expanded", "false");
            }
        });

        wrap.appendChild(button);
        wrap.appendChild(menu);
        var slot = document.getElementById("ui-lang-switcher-slot");
        if (slot) {
            slot.appendChild(wrap);
        } else {
            // Fallback: no dedicated header slot found on this page, float it.
            wrap.classList.add("ui-lang-switcher-floating");
            document.body.appendChild(wrap);
        }
    }

    function init() {
        var lang = currentLangFromPath();
        document.documentElement.setAttribute("lang", lang);
        buildSwitcher(lang);
        injectHreflang();
        loadDict(lang).then(applyDict);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    var CURRENT_DICT = {};

    function t(key, fallback) {
        return (CURRENT_DICT && CURRENT_DICT[key] != null) ? CURRENT_DICT[key] : (fallback != null ? fallback : key);
    }

    window.ScalableUIi18n = {
        SUPPORTED: SUPPORTED,
        currentLangFromPath: currentLangFromPath,
        t: t
    };
})();