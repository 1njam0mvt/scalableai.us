const API = (typeof window !== 'undefined' && window.location.origin)
    ? window.location.origin
    : 'http://localhost:8000';

let sessionId = null;
let currentMode = 'scalable';
let isStreaming = false;
let isListening = false;
let camStream = null;
let autoListenMode = false;
const SPEECH_ERROR_MAX_RETRIES = 3;
let speechErrorRetryCount = 0;
const SPEECH_SEND_DELAY_MS = 500;
const SPEECH_RESTART_DELAY_MS = 700;
let speechSendTimeout = null;
let pendingSendTranscript = null;
let safariVoiceHintShown = false;
let orb = null;
let recognition = null;
let ttsPlayer = null;
let pendingModePrefix = null;
let userClosedActivity = false;
const AUTH_TOKEN_KEY = 'scalable_auth_token';
const GUEST_TOKEN_KEY = 'scalable_guest_token';
const THEME_KEY = 'scalable_theme';

function getAuthToken() {
    try { return localStorage.getItem(AUTH_TOKEN_KEY); } catch (e) { return null; }
}

function setAuthToken(token) {
    try {
        if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
        else localStorage.removeItem(AUTH_TOKEN_KEY);
    } catch (e) { }
}

function getGuestToken() {
    try { return localStorage.getItem(GUEST_TOKEN_KEY); } catch (e) { return null; }
}

function setGuestToken(token) {
    try {
        if (token) localStorage.setItem(GUEST_TOKEN_KEY, token);
        else localStorage.removeItem(GUEST_TOKEN_KEY);
    } catch (e) { }
}

// Effective token for API calls: a real signed-in session always wins;
// otherwise fall back to the guest preview token, if one was issued.
function getEffectiveToken() {
    return getAuthToken() || getGuestToken();
}

function getStoredTheme() {
    try { return localStorage.getItem(THEME_KEY); } catch (e) { return null; }
}

let themeTransitionTimer = null;

function applyTheme(theme, animate = false) {
    const isLight = theme === 'light';
    const root = document.documentElement;
    if (animate) {
        root.classList.add('theme-transitioning');
        if (themeTransitionTimer) clearTimeout(themeTransitionTimer);
        themeTransitionTimer = setTimeout(() => {
            root.classList.remove('theme-transitioning');
        }, 520);
    }
    root.setAttribute('data-theme', isLight ? 'light' : 'dark');
    const icon = document.getElementById('theme-icon');
    if (icon) {
        // Sun icon when light theme is active, moon icon when dark.
        icon.innerHTML = isLight
            ? '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>'
            : '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>';
    }
}

function setTheme(theme) {
    try { localStorage.setItem(THEME_KEY, theme); } catch (e) { }
    applyTheme(theme, true);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    setTheme(current === 'light' ? 'dark' : 'light');
}

// Apply saved (or system) theme immediately, before first paint of dynamic content.
applyTheme(getStoredTheme() || (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'));

async function authFetch(url, options) {
    options = options || {};
    const headers = Object.assign({}, options.headers || {});
    const usingGuestToken = !getAuthToken() && !!getGuestToken();
    const token = getEffectiveToken();
    if (token) headers['Authorization'] = 'Bearer ' + token;
    const res = await fetch(url, Object.assign({}, options, { headers }));
    if (res.status === 401 && !usingGuestToken && typeof window.scalableShowAuthGate === 'function') {
        // A guest session legitimately gets 401 from endpoints that require a
        // real account (chat history, projects, settings, ...) - that's
        // expected and shouldn't force a guest back to the sign-in screen.
        // Only a real, previously-authenticated session expiring does that.
        setAuthToken(null);
        window.scalableShowAuthGate('Your session expired. Please sign in again.');
    } else if (res.status === 403 && usingGuestToken && typeof window.scalableShowAuthGate === 'function') {
        setGuestToken(null);
        window.scalableShowAuthGate("You've used your free preview messages. Sign in to keep chatting.");
    }
    return res;
}
window.authFetch = authFetch;

const RECENT_CHATS_KEY = 'scalable_recent_chats';
const MAX_RECENT_CHATS = 30;
const SETTINGS_KEY = 'scalable_settings';
const PERSONALIZATION_KEY = 'scalable_personalization';
const LANGUAGE_KEY = 'scalable_language';
const TTS_VOICE_KEY = 'scalable_tts_voice';
const DEFAULT_SETTINGS = { autoOpenActivity: true, autoOpenSearchResults: true, thinkingSounds: true, voiceInterrupt: true };
const PRE_STARTER_FILES = ['starter_1', 'starter_2', 'starter_3', 'starter_4', 'starter_5', 'starter_6', 'starter_7', 'starter_8', 'starter_9', 'starter_10'];
let PRE_STARTER_CACHE = {};
let settings = { ...DEFAULT_SETTINGS };

function getPersonalizationPayload() {
    try {
        const raw = localStorage.getItem(PERSONALIZATION_KEY);
        const langRaw = localStorage.getItem(LANGUAGE_KEY);
        const voiceRaw = localStorage.getItem(TTS_VOICE_KEY);
        const language = langRaw ? langRaw.trim() : '';
        const voice = voiceRaw ? voiceRaw.trim() : '';
        if (!raw && !language && !voice) return null;
        const p = raw ? JSON.parse(raw) : {};
        const nickname = (p.nickname || '').trim();
        const length = (p.length || '').trim();
        const customInstructions = (p.customInstructions || '').trim();
        if (!nickname && !length && !customInstructions && !language && !voice) return null;
        return {
            nickname: nickname || null,
            length: length || null,
            custom_instructions: customInstructions || null,
            language: language || null,
            voice: voice || null,
        };
    } catch (e) {
        return null;
    }
}
window.getPersonalizationPayload = getPersonalizationPayload;
const $ = id => document.getElementById(id);
const chatMessages = $('chat-messages');
const messageInput = $('message-input');
const sendBtn = $('send-btn');
const micBtn = $('mic-btn');
const ttsBtn = $('tts-btn');
const newChatBtn = $('new-chat-btn');
const charCount = $('char-count');
const welcomeTitle = $('welcome-title');
const modeSlider = $('mode-slider');
const btnScalable = $('btn-scalable');
const statusDot = document.querySelector('.status-dot');
const statusText = document.querySelector('.status-text');
const orbContainer = $('orb-container');
const themeToggleBtn = $('theme-toggle-badge');
const searchResultsToggle = $('search-results-toggle');
const searchResultsWidget = $('search-results-widget');
const searchResultsClose = $('search-results-close');
const searchResultsQuery = $('search-results-query');
const searchResultsAnswer = $('search-results-answer');
const searchResultsList = $('search-results-list');
const activityPanel = $('activity-panel');
const activityToggle = $('activity-toggle');
const activityClose = $('activity-close');
const activityList = $('activity-list');
const panelOverlay = $('panel-overlay');
const speechWidget = $('speech-widget');
const speechWidgetText = $('speech-widget-text');
const settingsBtn = $('settings-btn');
const camBtn = $('cam-btn');
const camPanel = $('cam-panel');
const camVideo = $('cam-video');
const camCanvas = $('cam-canvas');
const camVisionModeInput = $('cam-vision-mode');
const camMinimize = $('cam-minimize');
const camClose = $('cam-close');
const camPanelHeader = $('cam-panel-header');
const camPanelResize = $('cam-panel-resize');
const settingsPanel = $('settings-panel');
const settingsClose = $('settings-close');
const toggleAutoActivity = $('toggle-auto-activity');
const toggleAutoSearch = $('toggle-auto-search');
const toggleThinkingSounds = $('toggle-thinking-sounds');
const toggleVoiceInterrupt = $('toggle-voice-interrupt');
const toastContainer = $('toast-container');
const pendingModeChip = $('pending-mode-chip');
const pendingModeLabel = $('pending-mode-label');
const pendingModeClear = $('pending-mode-clear');
const fileInputEl = $('file-input');
const sidebarHistory = $('sidebar-history');

class PreStarterPlayer {
    constructor() {
        this.audio = document.createElement('audio');
        this.audio.preload = 'auto';
    }
    play(onComplete) {
        const loaded = PRE_STARTER_FILES.filter(f => PRE_STARTER_CACHE[f]);
        if (loaded.length === 0) {
            if (onComplete) onComplete();
            return;
        }
        const file = loaded[Math.floor(Math.random() * loaded.length)];
        const base64 = PRE_STARTER_CACHE[file];
        if (!base64) {
            if (onComplete) onComplete();
            return;
        }
        this.audio.src = 'data:audio/mp3;base64,' + base64;
        this.audio.currentTime = 0;
        let fired = false;
        const done = () => {
            if (fired) return;
            fired = true;
            this.audio.onended = null;
            this.audio.onerror = null;
            if (onComplete) onComplete();
        };
        this.audio.onended = done;
        this.audio.onerror = done;
        const p = this.audio.play();
        if (p) p.catch(done);
    }
}

let preStarterPlayer = null;

class TTSPlayer {
    constructor() {
        this.queue = [];
        this.playing = false;
        this.enabled = true;
        this.stopped = false;
        this.audio = document.createElement('audio');
        this.audio.preload = 'auto';
    }
    unlock() {
        const silentWav = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA';
        this.audio.src = silentWav;
        const p = this.audio.play();
        if (p) p.catch(() => { });
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const g = ctx.createGain();
            g.gain.value = 0;
            const o = ctx.createOscillator();
            o.connect(g);
            g.connect(ctx.destination);
            o.start(0);
            o.stop(ctx.currentTime + 0.001);
            setTimeout(() => ctx.close(), 200);
        } catch (_) { }
    }
    enqueue(base64Audio) {
        if (!this.enabled || this.stopped) return;
        this.queue.push(base64Audio);
        if (!this.playing) this._playLoop();
    }
    stop() {
        this.stopped = true;
        this.audio.pause();
        this.audio.removeAttribute('src');
        this.audio.load();
        this.queue = [];
        this.playing = false;
        if (ttsBtn) ttsBtn.classList.remove('tts-speaking');
        if (orbContainer) orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (typeof this.onPlaybackComplete === 'function') this.onPlaybackComplete();
    }
    reset() {
        this.stop();
        this.stopped = false;
        this._loopId = (this._loopId || 0) + 1;
    }
    async _playLoop() {
        if (this.playing) return;
        this.playing = true;
        this._loopId = (this._loopId || 0) + 1;
        const myId = this._loopId;
        if (ttsBtn) ttsBtn.classList.add('tts-speaking');
        if (orbContainer) orbContainer.classList.add('speaking');
        if (orb) orb.setActive(true);
        while (this.queue.length > 0) {
            if (this.stopped || myId !== this._loopId) break;
            const b64 = this.queue.shift();
            try {
                await this._playB64(b64);
            } catch (e) {
                console.warn('TTS segment error:', e);
            }
        }
        if (myId !== this._loopId) {
            this.playing = false;
            return;
        }
        this.playing = false;
        if (ttsBtn) ttsBtn.classList.remove('tts-speaking');
        if (orbContainer) orbContainer.classList.remove('speaking');
        if (orb) orb.setActive(false);
        if (typeof this.onPlaybackComplete === 'function') this.onPlaybackComplete();
    }
    _playB64(b64) {
        return new Promise(resolve => {
            this.audio.src = 'data:audio/mp3;base64,' + b64;
            const done = () => { resolve(); };
            this.audio.onended = done;
            this.audio.onerror = done;
            const p = this.audio.play();
            if (p) p.catch(done);
        });
    }
}

function init() {
    if (!chatMessages || !messageInput) {
        console.error('[SCALABLE] Required DOM elements (chat-messages, message-input) not found.');
        return;
    }
    loadSettings();
    ttsPlayer = new TTSPlayer();
    ttsPlayer.onPlaybackComplete = maybeRestartListening;
    if (ttsBtn) ttsBtn.classList.add('tts-active');
    setGreeting();
    initOrb();
    initSpeech();
    preloadStarterAudio();
    preStarterPlayer = new PreStarterPlayer();
    checkHealth();
    bindEvents();
    setMode(currentMode);
    autoResizeInput();
    renderRecentChats();
    syncRecentChatsFromServer();
}

async function syncRecentChatsFromServer() {
    try {
        const res = await authFetch(`${API}/chat/sessions`);
        if (!res || !res.ok) return;
        const serverSessions = await res.json();
        if (!Array.isArray(serverSessions)) return;

        const local = loadRecentChats();
        const localById = new Map(local.map(c => [c.id, c]));

        serverSessions.forEach(s => {
            const existing = localById.get(s.session_id);
            localById.set(s.session_id, {
                id: s.session_id,
                title: (existing && existing.renamed) ? existing.title : (s.title || (existing && existing.title) || 'New chat'),
                renamed: existing ? !!existing.renamed : false,
                pinned: existing ? !!existing.pinned : false,
                starred: existing ? !!existing.starred : false,
                unread: existing ? !!existing.unread : false,
                ts: s.updated_at ? s.updated_at * 1000 : (existing ? existing.ts : Date.now()),
            });
        });

        const merged = Array.from(localById.values()).sort((a, b) => b.ts - a.ts);
        saveRecentChats(merged);
        renderRecentChats();
    } catch (e) {
        // Best effort - if this fails, the locally-known list (if any) still shows.
    }
}

async function preloadStarterAudio() {
    const base = (typeof window !== 'undefined' && window.location.origin) ? window.location.origin : '';
    for (const file of PRE_STARTER_FILES) {
        try {
            const r = await fetch(`${base}/app/audio/${file}.mp3`);
            if (!r.ok) continue;
            const blob = await r.blob();
            const base64 = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onloadend = () => resolve((reader.result || '').split(',')[1] || '');
                reader.onerror = reject;
                reader.readAsDataURL(blob);
            });
            if (base64) PRE_STARTER_CACHE[file] = base64;
        } catch (_) { }
    }
}

function loadSettings() {
    try {
        const s = localStorage.getItem(SETTINGS_KEY);
        if (s) {
            const parsed = JSON.parse(s);
            settings = { ...DEFAULT_SETTINGS, ...parsed };
        }
        if (toggleAutoActivity) toggleAutoActivity.checked = settings.autoOpenActivity;
        if (toggleAutoSearch) toggleAutoSearch.checked = settings.autoOpenSearchResults;
        if (toggleThinkingSounds) toggleThinkingSounds.checked = settings.thinkingSounds;
        if (toggleVoiceInterrupt) toggleVoiceInterrupt.checked = settings.voiceInterrupt;
    } catch (_) { }
}

function saveSettings() {
    try {
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (_) { }
}


function setGreeting() {
    const T = (window.ScalableUIi18n && window.ScalableUIi18n.t) ? window.ScalableUIi18n.t : (k, f) => f;
    const h = new Date().getHours();
    let g = T('welcome.evening', 'Good evening.');
    if (h < 12) g = T('welcome.morning', 'Good morning.');
    else if (h < 17) g = T('welcome.afternoon', 'Good afternoon.');
    else if (h >= 22) g = T('welcome.late_night', 'Burning the midnight oil?');
    if (welcomeTitle) welcomeTitle.textContent = g;
}
document.addEventListener('scalable-i18n-ready', setGreeting);

function initOrb() {
    if (typeof OrbRenderer === 'undefined') return;
    try {
        orb = new OrbRenderer(orbContainer, {
            hue: 0,
            hoverIntensity: 0.3,
            backgroundColor: [0.02, 0.02, 0.06]
        });
    } catch (e) { console.warn('Orb init failed:', e); }
}

function isSafariOrIOS() {
    if (typeof navigator === 'undefined') return false;
    const ua = navigator.userAgent || '';
    return /iPad|iPhone|iPod/.test(ua) ||
        (navigator.vendor && navigator.vendor.indexOf('Apple') > -1) ||
        (/Safari/.test(ua) && !/Chrome|Chromium|CriOS/.test(ua));
}

function initSpeech() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { micBtn.title = 'Speech not supported in this browser'; return; }
    recognition = new SR();
    const safariMode = isSafariOrIOS();
    recognition.continuous = false;
    recognition.interimResults = !safariMode;
    recognition.maxAlternatives = 1;
    recognition.lang = 'en-US';
    recognition.onresult = e => {
        if (!e.results || e.results.length === 0) return;
        const last = e.results[e.results.length - 1];
        const transcript = (last && last[0]) ? last[0].transcript.trim() : '';
        const isFinal = last && last.isFinal;
        if (speechWidgetText) speechWidgetText.textContent = transcript;
        if (speechWidget) speechWidget.classList.add('visible');
        if (settings.voiceInterrupt && ttsPlayer && ttsPlayer.playing && transcript.length > 0) {
            ttsPlayer.stop();
            ttsPlayer.stopped = false;
        }
        if (isFinal && transcript) {
            pendingSendTranscript = transcript;
            clearTimeout(speechSendTimeout);
            speechSendTimeout = setTimeout(() => {
                if (pendingSendTranscript) {
                    sendMessage(pendingSendTranscript);
                    pendingSendTranscript = null;
                }
                speechSendTimeout = null;
                stopListening();
            }, SPEECH_SEND_DELAY_MS);
        } else if (!isFinal) {
            pendingSendTranscript = null;
            clearTimeout(speechSendTimeout);
            speechSendTimeout = null;
        }
    };

    recognition.onstart = () => { speechErrorRetryCount = 0; };
    recognition.onerror = e => {
        stopListening();
        const msg = (e && e.error) ? String(e.error) : '';
        const isPermissionDenied = /denied|not-allowed|permission/i.test(msg);
        if (isPermissionDenied && micBtn) {
            micBtn.title = 'Microphone access denied. Allow in browser settings.';
            speechErrorRetryCount = SPEECH_ERROR_MAX_RETRIES;
        }
        if (autoListenMode && !isStreaming && speechErrorRetryCount < SPEECH_ERROR_MAX_RETRIES) {
            speechErrorRetryCount++;
            setTimeout(() => maybeRestartListening(), SPEECH_RESTART_DELAY_MS);
        } else if (speechErrorRetryCount >= SPEECH_ERROR_MAX_RETRIES && micBtn) {
            micBtn.title = 'Voice input — click to try again';
        }
    };

    recognition.onend = () => {
        if (pendingSendTranscript) {
            clearTimeout(speechSendTimeout);
            speechSendTimeout = null;
            sendMessage(pendingSendTranscript);
            pendingSendTranscript = null;
        } else {
            clearTimeout(speechSendTimeout);
            speechSendTimeout = null;
        }
        if (isListening) stopListening();
        maybeRestartListening();
    };
}

function startListening() {
    if (!recognition || isStreaming || isListening) return;
    if (isSafariOrIOS() && !safariVoiceHintShown) {
        showToast('Voice works best in Chrome. Safari has limited support.');
        safariVoiceHintShown = true;
    }
    isListening = true;
    pendingSendTranscript = null;
    clearTimeout(speechSendTimeout);
    speechSendTimeout = null;
    if (micBtn) micBtn.classList.add('listening');
    if (speechWidget) speechWidget.classList.add('visible');
    if (speechWidgetText) speechWidgetText.textContent = '';
    try {
        recognition.start();
    } catch (err) {
        isListening = false;
        if (micBtn) micBtn.classList.remove('listening');
        if (speechWidget) speechWidget.classList.remove('visible');
        if (isSafariOrIOS()) showToast('Tap the mic to continue voice input.');
    }
}

function stopListening() {
    clearTimeout(speechSendTimeout);
    speechSendTimeout = null;
    pendingSendTranscript = null;
    isListening = false;
    if (micBtn) micBtn.classList.remove('listening');
    if (speechWidget) speechWidget.classList.remove('visible');
    if (speechWidgetText) speechWidgetText.textContent = '';
    try { recognition.stop(); } catch (_) { }
}

function maybeRestartListening() {
    if (!autoListenMode || !recognition) return;
    if (isStreaming) return;

    const ttsActive = ttsPlayer && (ttsPlayer.playing || ttsPlayer.queue.length > 0);
    if (ttsActive && !settings.voiceInterrupt) return;

    const delay = ttsActive ? 150 : SPEECH_RESTART_DELAY_MS;
    setTimeout(() => {
        if (autoListenMode && !isStreaming && !isListening && recognition) {
            startListening();
        }
    }, delay);
}

const CAM_BYPASS_TOKEN = 'TTCAMTOKENTT';
const CAMERA_QUERY_PATTERNS = [
    /what\s+(can|do)\s+you\s+see/i,
    /can\s+you\s+see/i,
    /describe\s+(what\s+you\s+see|this|the\s+image)/i,
    /what('s|s)\sss+in\sss+(this\sss+)?(picture|image)/i,
    /what\s+do\s+i\s+look\s+like/i,
    /what\s+(am\s+i\s+)?holding/i,
    /show\s+me\s+what\s+you\s+see/i,
];
function isCameraQuery(text) {
    if (!text || typeof text !== 'string') return false;
    const t = text.trim().toLowerCase();
    return CAMERA_QUERY_PATTERNS.some(r => r.test(t)) ||
        (t.includes('see') && (t.includes('what') || t.includes('describe')));
}

function startCamera() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showToast('Camera not supported in this browser.');
        return Promise.reject(new Error('Camera not supported'));
    }
    if (camStream) return Promise.resolve();
    return navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user' }, audio: false })
        .then(stream => {
            camStream = stream;
            if (camVideo) camVideo.srcObject = stream;
            if (camPanel) { camPanel.classList.add('visible'); camPanel.setAttribute('aria-hidden', 'false'); }
            if (camBtn) {
                camBtn.classList.add('cam-active');
                camBtn.title = 'Camera on — click to turn off';
                const icon = camBtn.querySelector('.cam-icon');
                const iconActive = camBtn.querySelector('.cam-icon-active');
                if (icon) icon.style.display = 'none';
                if (iconActive) iconActive.style.display = '';
            }
        })
        .catch(err => {
            showToast('Camera access denied. ' + (err.message || ''));
            throw err;
        });
}

function stopCamera() {
    if (camStream) {
        camStream.getTracks().forEach(t => t.stop());
        camStream = null;
    }
    if (camVideo) camVideo.srcObject = null;
    if (camPanel) { camPanel.classList.remove('visible'); camPanel.setAttribute('aria-hidden', 'true'); }
    if (camVisionModeInput) camVisionModeInput.checked = false;
    if (camBtn) {
        camBtn.classList.remove('cam-active');
        camBtn.title = 'Camera — capture and send for vision';
        const icon = camBtn.querySelector('.cam-icon');
        const iconActive = camBtn.querySelector('.cam-icon-active');
        if (icon) icon.style.display = '';
        if (iconActive) iconActive.style.display = 'none';
    }
}

function initCameraPanel() {
    if (!camPanel) return;
    let dragStart = { x: 0, y: 0, left: 0, top: 0 };
    let resizeStart = { x: 0, y: 0, w: 0, h: 0 };
    if (camClose) camClose.addEventListener('click', () => stopCamera());
    if (camMinimize) camMinimize.addEventListener('click', () => {
        camPanel.classList.toggle('minimized');
    });
    if (camPanelHeader) {
        camPanelHeader.addEventListener('mousedown', (e) => {
            if (e.target.closest('.cam-panel-btn, .cam-panel-vision-mode')) return;
            e.preventDefault();
            const r = camPanel.getBoundingClientRect();
            dragStart = { x: e.clientX, y: e.clientY, left: r.left, top: r.top };
            const onMove = (ev) => {
                const dx = ev.clientX - dragStart.x;
                const dy = ev.clientY - dragStart.y;
                camPanel.style.left = (dragStart.left + dx) + 'px';
                camPanel.style.top = (dragStart.top + dy) + 'px';
                camPanel.style.right = 'auto';
                camPanel.style.bottom = 'auto';
            };
            const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
    if (camPanelResize) {
        camPanelResize.addEventListener('mousedown', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const r = camPanel.getBoundingClientRect();
            resizeStart = { x: e.clientX, y: e.clientY, w: r.width, h: r.height };
            const onMove = (ev) => {
                const dw = ev.clientX - resizeStart.x;
                const dh = ev.clientY - resizeStart.y;
                const nw = Math.max(200, Math.min(window.innerWidth, resizeStart.w + dw));
                const nh = Math.max(150, Math.min(window.innerHeight * 0.7, resizeStart.h + dh));
                camPanel.style.width = nw + 'px';
                camPanel.style.height = nh + 'px';
            };
            const onUp = () => { document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp); };
            document.addEventListener('mousemove', onMove);
            document.addEventListener('mouseup', onUp);
        });
    }
    camPanel.addEventListener('dblclick', (e) => {
        if (e.target.closest('.cam-panel-header') && !e.target.closest('.cam-panel-btn, .cam-panel-vision-mode')) {
            camPanel.classList.toggle('minimized');
        }
    });
    camPanel.querySelector('.cam-panel-body')?.addEventListener('click', (e) => {
        if (camPanel.classList.contains('minimized')) camPanel.classList.remove('minimized');
    });
}

function handleActions(actions, contentEl) {
    if (!actions) return;
    if (!contentEl) return;
    const safeOpen = url => {
        if (url && (url.startsWith('http://') || url.startsWith('https://'))) {
            try {
                const w = window.open(url, '_blank', 'noopener');
                if (!w) showToast('Pop-up blocked. Please allow pop-ups or copy the URL.');
            } catch (_) {
                showToast('Could not open link. Please try again.');
            }
        }
    };
    (actions.wopens || []).forEach(safeOpen);
    (actions.plays || []).forEach(safeOpen);
    (actions.googlesearches || []).forEach(safeOpen);
    (actions.youtubesearches || []).forEach(safeOpen);
    if (actions.images && actions.images.length > 0) {
        const wrap = document.createElement('div');
        wrap.className = 'msg-actions-images';
        actions.images.forEach(url => {
            const img = document.createElement('img');
            img.alt = 'Generated image';
            img.className = 'msg-action-image';
            img.loading = 'lazy';
            wrap.appendChild(img);

            // /tasks/{id}/image is auth-protected — a plain <img src> request
            // can't carry the bearer token, so fetch it as a blob instead.
            const fetchFn = (typeof authFetch === 'function') ? authFetch : fetch;
            fetchFn(url)
                .then(res => res.blob())
                .then(blob => { img.src = URL.createObjectURL(blob); })
                .catch(() => {
                    img.style.display = 'none';
                    const fallback = document.createElement('div');
                    fallback.className = 'msg-action-image-fallback';
                    fallback.textContent = 'Image failed to load.';
                    wrap.appendChild(fallback);
                });
        });
        contentEl.appendChild(wrap);
    }
    if (actions.contents && actions.contents.length > 0) {
        const wrap = document.createElement('div');
        wrap.className = 'msg-actions-contents';
        actions.contents.forEach(t => {
            const p = document.createElement('div');
            p.className = 'msg-action-content';
            p.textContent = t;
            wrap.appendChild(p);
        });
        contentEl.appendChild(wrap);
    }
    if (actions.cam) {
        if (actions.cam.action === 'open') {
            startCamera();
        } else if (actions.cam.action === 'close') {
            stopCamera();
        } else if (actions.cam.action === 'open_and_capture') {
            const resendMsg = actions.cam.resend_message || 'What do you see?';
            (async () => {
                try {
                    await startCamera();
                    await new Promise((resolve) => {
                        if (!camVideo) { resolve(); return; }
                        if (camVideo.readyState >= 2 && camVideo.videoWidth > 0) {
                            setTimeout(resolve, 500);
                            return;
                        }
                        const onReady = () => {
                            camVideo.removeEventListener('loadeddata', onReady);
                            clearTimeout(t);
                            setTimeout(resolve, 600);
                        };
                        const t = setTimeout(() => {
                            camVideo.removeEventListener('loadeddata', onReady);
                            resolve();
                        }, 4000);
                        camVideo.addEventListener('loadeddata', onReady);
                    });
                    const frame = await captureFrameAsBase64Safe();
                    if (frame) {
                        sendMessageWithImage(resendMsg, frame);
                    } else {
                        showToast('Could not capture camera frame. Please try again.');
                    }
                } catch (err) {
                    showToast('Camera access denied.');
                }
            })();
        }
    }
    if (actions.reminder) {
        scheduleReminder(actions.reminder);
    }
}

// Reminders are delivered entirely client-side (no backend job runner):
// a JS timer fires after `delay_seconds` and shows a browser Notification
// if permission was granted, falling back to an in-app toast otherwise.
// This only works while the tab stays open - it won't survive the tab
// being closed or the computer sleeping.
function scheduleReminder(reminder) {
    if (!reminder || !reminder.message || !reminder.delay_seconds) return;

    const deliver = () => {
        const title = 'Scalable reminder';
        const body = reminder.message;

        if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
            try {
                new Notification(title, { body, icon: '/app/favicon.ico' });
            } catch (_) {
                showToast(`⏰ Reminder: ${body}`);
            }
        } else {
            showToast(`⏰ Reminder: ${body}`);
        }

        // Also play a short beep so it's noticeable even if the tab is backgrounded.
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.frequency.value = 880;
            gain.gain.setValueAtTime(0.15, ctx.currentTime);
            osc.start();
            osc.stop(ctx.currentTime + 0.3);
        } catch (_) { /* audio not available - notification/toast still fired */ }
    };

    if (typeof Notification !== 'undefined' && Notification.permission === 'default') {
        Notification.requestPermission();
    }

    showToast(`Reminder set: "${reminder.message}" in ${reminder.label}`);
    setTimeout(deliver, reminder.delay_seconds * 1000);
}

function handleBackgroundTasks(tasks, contentEl) {
    if (!tasks || !tasks.length || !contentEl) return;
    tasks.forEach(task => {
        const card = document.createElement('div');
        card.className = 'bg-task-card';
        card.dataset.taskId = task.task_id;
        const label = task.type === 'generate image' ? 'Image Generation' : task.type === 'content' ? 'Content Writing' : task.type;
        const promptText = task.label ? `"${task.label}"` : '';
        card.innerHTML =
            '<div class="bg-task-header">' +
            '<div class="bg-task-spinner"></div>' +
            '<span class="bg-task-label">' + label + '</span>' +
            '<span class="bg-task-status">Working...</span>' +
            '</div>' +
            (promptText ? '<div class="bg-task-prompt">' + promptText + '</div>' : '');
        contentEl.appendChild(card);
        scrollToBottom();
        pollBackgroundTask(task.task_id, card);
    });
}

function pollBackgroundTask(taskId, cardEl) {
    let pollCount = 0;
    const maxPolls = 120;
    const interval = setInterval(() => {
        pollCount++;
        if (pollCount > maxPolls) {
            clearInterval(interval);
            updateTaskCard(cardEl, 'failed', 'Timed out');
            return;
        }
        authFetch(`${API}/tasks/${encodeURIComponent(taskId)}`)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(data => {
                if (data.status === 'completed') {
                    clearInterval(interval);
                    updateTaskCard(cardEl, 'completed', data);
                } else if (data.status === 'failed') {
                    clearInterval(interval);
                    updateTaskCard(cardEl, 'failed', data.error || 'Task failed');
                }
            })
            .catch(() => { });
    }, 1500);
}

function updateTaskCard(cardEl, status, data) {
    if (!cardEl) return;
    const spinner = cardEl.querySelector('.bg-task-spinner');
    const statusEl = cardEl.querySelector('.bg-task-status');
    if (status === 'completed') {
        if (spinner) spinner.className = 'bg-task-done-icon';
        if (statusEl) statusEl.textContent = 'Ready!';
        cardEl.classList.add('bg-task-done');
        const viewBtn = document.createElement('button');
        viewBtn.className = 'bg-task-view-btn';
        viewBtn.textContent = 'Open in new tab';
        viewBtn.addEventListener('click', () => {
            const taskId = cardEl.dataset.taskId;
            window.open(`${window.location.origin}/app/viewer.html?task_id=${taskId}`, '_blank');
        });
        cardEl.appendChild(viewBtn);
        try {
            const taskId = cardEl.dataset.taskId;
            const w = window.open(`${window.location.origin}/app/viewer.html?task_id=${taskId}`, '_blank');
            if (!w) {
                showToast('Result ready! Click "Open in new tab" to view.');
            }
        } catch (_) { }
    } else if (status === 'failed') {
        if (spinner) spinner.className = 'bg-task-fail-icon';
        if (statusEl) statusEl.textContent = typeof data === 'string' ? data : 'Failed';
        cardEl.classList.add('bg-task-failed');
    }
    scrollToBottom();
}

function captureFrameAsBase64() {
    if (!camVideo || !camStream || camVideo.readyState < 2) return null;
    if (!camCanvas) return null;
    const w = camVideo.videoWidth;
    const h = camVideo.videoHeight;
    if (!w || !h || w < 64 || h < 64) return null;
    camCanvas.width = w;
    camCanvas.height = h;
    const ctx = camCanvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(camVideo, 0, 0, w, h);
    try {
        return camCanvas.toDataURL('image/jpeg', 0.85).split(',')[1];
    } catch (_) {
        return null;
    }
}

async function captureFrameAsBase64Safe() {
    if (!camVideo || !camStream || !camCanvas) return null;
    return new Promise((resolve) => {
        const doCapture = () => {
            const w = camVideo.videoWidth;
            const h = camVideo.videoHeight;
            if (!w || !h || w < 64 || h < 64) {
                resolve(null);
                return;
            }
            camCanvas.width = w;
            camCanvas.height = h;
            const ctx = camCanvas.getContext('2d');
            if (!ctx) { resolve(null); return; }
            ctx.drawImage(camVideo, 0, 0, w, h);
            try {
                const b64 = camCanvas.toDataURL('image/jpeg', 0.9).split(',')[1];
                resolve(b64);
            } catch (_) {
                resolve(null);
            }
        };
        if (camVideo.readyState < 2) {
            const onReady = () => { camVideo.removeEventListener('loadeddata', onReady); doCapture(); };
            camVideo.addEventListener('loadeddata', onReady);
            setTimeout(() => { camVideo.removeEventListener('loadeddata', onReady); doCapture(); }, 3000);
            return;
        }
        const w = camVideo.videoWidth;
        const h = camVideo.videoHeight;
        if (w && h && w >= 64 && h >= 64) {
            if (typeof camVideo.requestVideoFrameCallback === 'function') {
                camVideo.requestVideoFrameCallback(() => { doCapture(); });
            } else {
                setTimeout(doCapture, 150);
            }
        } else {
            setTimeout(() => {
                const w2 = camVideo.videoWidth || 0;
                const h2 = camVideo.videoHeight || 0;
                if (w2 && h2 && w2 >= 64 && h2 >= 64) doCapture();
                else resolve(null);
            }, 300);
        }
    });
}

async function sendMessageWithImage(text, imgBase64) {
    if (!text || !imgBase64 || isStreaming) return;
    userClosedActivity = false;
    const messageToSend = text + ' ' + CAM_BYPASS_TOKEN;
    addMessage('user', text);
    addTypingIndicator();
    isStreaming = true;
    if (sendBtn) sendBtn.disabled = true;
    if (messageInput) messageInput.disabled = true;
    if (orbContainer) orbContainer.classList.add('active');
    if (ttsPlayer) { ttsPlayer.reset(); ttsPlayer.unlock(); }
    let timeoutId = null;
    const controller = new AbortController();
    try {
        timeoutId = setTimeout(() => controller.abort(), 300000);
        const res = await authFetch(`${API}/chat/scalable/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: messageToSend,
                session_id: sessionId,
                tts: !!(ttsPlayer && ttsPlayer.enabled),
                imgbase64: imgBase64,
                personalization: getPersonalizationPayload(),
            }),
            signal: controller.signal,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        removeTypingIndicator();
        const contentEl = addMessage('assistant', '');
        contentEl.innerHTML = '<span class="msg-stream-text">...</span>';
        scrollToBottom();
        if (!res.body) throw new Error('No response body');
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';
        let fullResponse = '';
        let cursorEl = null;
        let streamDone = false;
        while (!streamDone) {
            const { done, value } = await reader.read();
            if (done) break;
            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split('\n\n');
            sseBuffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.session_id) {
                        sessionId = data.session_id;
                        upsertRecentChat(sessionId, text);
                    }
                    if (data.activity) {
                        appendActivity(data.activity);
                        if (activityToggle) activityToggle.style.display = '';
                        if (activityPanel && settings.autoOpenActivity && !userClosedActivity) { activityPanel.classList.add('open'); updatePanelOverlay(); }
                    }
                    if (data.actions) handleActions(data.actions, contentEl);
                    if (data.background_tasks) handleBackgroundTasks(data.background_tasks, contentEl);
                    if ('chunk' in data) {
                        const chunkText = data.chunk || '';
                        fullResponse += chunkText;
                        const textSpan = contentEl.querySelector('.msg-stream-text');
                        if (textSpan) {
                            textSpan.textContent = fullResponse;
                            textSpan.classList.remove('stream-placeholder');
                        }
                        if (!cursorEl) {
                            cursorEl = document.createElement('span');
                            cursorEl.className = 'stream-cursor';
                            cursorEl.textContent = '|';
                            contentEl.appendChild(cursorEl);
                        }
                        scrollToBottom();
                    }
                    if (data.audio && ttsPlayer) ttsPlayer.enqueue(data.audio);
                    if (data.error) throw new Error(data.error);
                    if (data.done) { streamDone = true; break; }
                } catch (parseErr) {
                    if (parseErr.message && !parseErr.message.includes('JSON')) throw parseErr;
                }
            }
            if (streamDone) break;
        }
        if (cursorEl) cursorEl.remove();
        const textSpan = contentEl.querySelector('.msg-stream-text');
        if (textSpan && !fullResponse) textSpan.textContent = '(No response)';
    } catch (err) {
        clearTimeout(timeoutId);
        removeTypingIndicator();
        addMessage('assistant', 'Something went wrong analyzing the image. Please try again.');
    } finally {
        clearTimeout(timeoutId);
        isStreaming = false;
        if (sendBtn) sendBtn.disabled = false;
        if (messageInput) messageInput.disabled = false;
        if (orbContainer) orbContainer.classList.remove('active');
    }
}

async function checkHealth() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 5000);
        const r = await fetch(`${API}/health`, { signal: controller.signal });
        clearTimeout(timeoutId);
        const d = await r.json().catch(() => null);
        const ok = d && (d.status === 'healthy' || d.status === 'degraded');
        if (statusDot) statusDot.classList.toggle('offline', !ok);
        if (statusText) statusText.textContent = ok ? 'Online' : 'Offline';
    } catch (e) {
        if (statusDot) statusDot.classList.add('offline');
        if (statusText) statusText.textContent = 'Offline';
        if (typeof console !== 'undefined' && console.warn) console.warn('[Health] Check failed:', e);
    }
}

function showToast(msg, durationMs = 5000) {
    if (!toastContainer || !msg) return;
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = msg;
    toastContainer.appendChild(el);
    el.offsetHeight;
    el.classList.add('toast-visible');
    const t = setTimeout(() => {
        el.classList.remove('toast-visible');
        setTimeout(() => el.remove(), 300);
    }, durationMs);
    el.addEventListener('click', () => { clearTimeout(t); el.classList.remove('toast-visible'); setTimeout(() => el.remove(), 300); });
}

function bindEvents() {
    if (sendBtn) sendBtn.addEventListener('click', () => { if (!isStreaming) sendMessage(); });
    if (messageInput) messageInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); if (!isStreaming) sendMessage(); }
    });
    if (messageInput) messageInput.addEventListener('input', () => {
        autoResizeInput();
        const len = messageInput.value.length;
        if (charCount) charCount.textContent = len > 100 ? `${len.toLocaleString()} / 32,000` : '';
    });
    if (camBtn) camBtn.addEventListener('click', () => {
        if (camStream) stopCamera();
        else startCamera();
    });
    initCameraPanel();
    if (micBtn) micBtn.addEventListener('click', () => {
        if (isListening) {
            autoListenMode = false;
            stopListening();
            if (micBtn) micBtn.classList.remove('auto-listen');
        } else {
            autoListenMode = true;
            speechErrorRetryCount = 0;
            if (micBtn) {
                micBtn.classList.add('auto-listen');
                micBtn.title = 'Voice input — click to stop auto-listen';
            }
            startListening();
        }
    });
    if (ttsBtn) ttsBtn.addEventListener('click', () => {
        if (ttsPlayer) ttsPlayer.enabled = !ttsPlayer.enabled;
        ttsBtn.classList.toggle('tts-active', ttsPlayer && ttsPlayer.enabled);
        if (ttsPlayer && !ttsPlayer.enabled) ttsPlayer.stop();
    });
    if (newChatBtn) newChatBtn.addEventListener('click', newChat);
    if (btnScalable) btnScalable.addEventListener('click', () => setMode('scalable'));
    document.querySelectorAll('.chip').forEach(c => {
        c.addEventListener('click', () => { if (!isStreaming) sendMessage(c.dataset.msg); });
    });
    initQuickActionsRow();
    if (themeToggleBtn) {
        themeToggleBtn.addEventListener('click', toggleTheme);
    }
    if (searchResultsToggle) {
        searchResultsToggle.addEventListener('click', () => {
            if (searchResultsWidget) { searchResultsWidget.classList.toggle('open'); updatePanelOverlay(); }
        });
    }
    if (searchResultsClose && searchResultsWidget) {
        searchResultsClose.addEventListener('click', () => { searchResultsWidget.classList.remove('open'); updatePanelOverlay(); });
    }
    const clipboardCopyBtn = $('clipboard-copy-btn');
    if (clipboardCopyBtn) {
        clipboardCopyBtn.addEventListener('click', async () => {
            const replies = chatMessages.querySelectorAll('.message.assistant .msg-content');
            if (!replies.length) { showToast('No reply to copy yet.'); return; }
            const lastReply = replies[replies.length - 1].textContent.trim();
            if (!lastReply) { showToast('No reply to copy yet.'); return; }
            try {
                await navigator.clipboard.writeText(lastReply);
                clipboardCopyBtn.classList.add('active-state');
                showToast('Copied last reply to clipboard.');
                setTimeout(() => clipboardCopyBtn.classList.remove('active-state'), 1200);
            } catch (err) {
                showToast('Could not copy — clipboard access denied.');
            }
        });
    }
    if (activityToggle) {
        activityToggle.addEventListener('click', () => {
            if (activityPanel) {
                const nowOpen = activityPanel.classList.toggle('open');
                userClosedActivity = !nowOpen;
                updatePanelOverlay();
            }
        });
    }
    if (activityClose && activityPanel) {
        activityClose.addEventListener('click', () => {
            activityPanel.classList.remove('open');
            userClosedActivity = true;
            updatePanelOverlay();
        });
    }
    if (settingsBtn && settingsPanel) {
        settingsBtn.addEventListener('click', () => {
            settingsPanel.classList.toggle('open');
            updatePanelOverlay();
        });
    }
    if (settingsClose && settingsPanel) {
        settingsClose.addEventListener('click', () => {
            settingsPanel.classList.remove('open');
            updatePanelOverlay();
        });
    }
    if (toggleAutoActivity) {
        toggleAutoActivity.addEventListener('change', () => {
            settings.autoOpenActivity = toggleAutoActivity.checked;
            saveSettings();
        });
    }
    if (toggleAutoSearch) {
        toggleAutoSearch.addEventListener('change', () => {
            settings.autoOpenSearchResults = toggleAutoSearch.checked;
            saveSettings();
        });
    }
    if (toggleThinkingSounds) {
        toggleThinkingSounds.addEventListener('change', () => {
            settings.thinkingSounds = toggleThinkingSounds.checked;
            saveSettings();
        });
    }
    if (toggleVoiceInterrupt) {
        toggleVoiceInterrupt.addEventListener('change', () => {
            settings.voiceInterrupt = toggleVoiceInterrupt.checked;
            saveSettings();
        });
    }
    if (pendingModeClear) {
        pendingModeClear.addEventListener('click', () => clearPendingMode());
    }
}

function autoResizeInput() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
}

function updatePanelOverlay() {
    if (!panelOverlay) return;
    const anyOpen = (activityPanel && activityPanel.classList.contains('open')) ||
        (searchResultsWidget && searchResultsWidget.classList.contains('open')) ||
        (settingsPanel && settingsPanel.classList.contains('open'));
    panelOverlay.classList.toggle('visible', !!anyOpen);
}
window.updatePanelOverlay = updatePanelOverlay;

function setMode(mode) {
    currentMode = mode || 'scalable';
    if (btnScalable) btnScalable.classList.add('active');
    if (modeSlider) modeSlider.classList.remove('center', 'right');
    if (activityToggle) activityToggle.style.display = '';
}

// ---- Pending mode chip: Create image / Web search / Deep research ----
function armPendingMode(label, prefix) {
    pendingModePrefix = prefix;
    if (pendingModeLabel) pendingModeLabel.textContent = label;
    if (pendingModeChip) pendingModeChip.style.display = 'flex';
    const wrap = messageInput ? messageInput.closest('.textarea-wrap') : null;
    if (wrap) wrap.classList.add('has-pending-mode');
    if (messageInput) messageInput.focus();
}

function clearPendingMode() {
    pendingModePrefix = null;
    if (pendingModeChip) pendingModeChip.style.display = 'none';
    const wrap = messageInput ? messageInput.closest('.textarea-wrap') : null;
    if (wrap) wrap.classList.remove('has-pending-mode');
    document.querySelectorAll('#explore-menu .explore-menu-item.active').forEach(i => i.classList.remove('active'));
}
window.armPendingMode = armPendingMode;
window.scalableSendMessage = function (text) { return sendMessage(text); };

// ---- Add photos & files: read the picked file(s) and send through the vision pathway ----
function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
            const result = reader.result || '';
            const commaIdx = result.indexOf(',');
            resolve(commaIdx >= 0 ? result.slice(commaIdx + 1) : result);
        };
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

async function handleFilesSelected(fileList) {
    const files = Array.from(fileList || []);
    if (!files.length || isStreaming) return;

    const imageFile = files.find(f => f.type && f.type.startsWith('image/'));
    const textFile = files.find(f => /\.(txt|md)$/i.test(f.name || ''));
    const unsupportedFile = files.find(f => /\.(pdf|docx?|doc)$/i.test(f.name || ''));

    if (imageFile) {
        if (files.length > 1) {
            showToast('Only the first image will be analyzed for now.');
        }
        try {
            const base64 = await fileToBase64(imageFile);
            const label = (messageInput && messageInput.value.trim()) || 'What do you see in this image?';
            messageInput.value = '';
            autoResizeInput();
            await sendMessageWithImage(label, base64);
        } catch (e) {
            showToast('Could not read that image file.');
        }
        return;
    }

    if (textFile) {
        try {
            const text = await textFile.text();
            const trimmed = text.length > 20000 ? text.slice(0, 20000) + '\n\n[...truncated]' : text;
            const currentInput = (messageInput && messageInput.value.trim()) || '';
            const combined = `Here is the content of "${textFile.name}":\n\n${trimmed}` +
                (currentInput ? `\n\n${currentInput}` : '');
            if (messageInput) {
                messageInput.value = combined;
                autoResizeInput();
                messageInput.focus();
            }
            showToast(`Added "${textFile.name}" to your message.`);
        } catch (e) {
            showToast('Could not read that text file.');
        }
        return;
    }

    if (unsupportedFile) {
        const T = (window.ScalableUIi18n && window.ScalableUIi18n.t) ? window.ScalableUIi18n.t : (k, f) => f;
        showToast(T('chat.pdf_docx_unsupported', "PDF and Word documents aren't supported here yet — add them as Context inside a Project instead."));
        return;
    }

    const T = (window.ScalableUIi18n && window.ScalableUIi18n.t) ? window.ScalableUIi18n.t : (k, f) => f;
    showToast(T('chat.filetype_unsupported', "That file type isn't supported here yet."));
}
window.handleFilesSelected = handleFilesSelected;

// ---- Recent chats: persist lightweight session metadata in localStorage ----
// (Projects moved to a backend-connected implementation - see the Projects
// section renderer and projectsApi.* functions further down this file.)

function loadRecentChats() {
    // Recent-chat titles are meaningful personal data (even without message
    // content) and must never surface for a guest, even if this browser was
    // previously used by a real logged-in account. Only a real session sees
    // the cached list; a guest always starts from empty.
    if (!getAuthToken()) return [];
    try {
        const raw = localStorage.getItem(RECENT_CHATS_KEY);
        return raw ? JSON.parse(raw) : [];
    } catch (_) {
        return [];
    }
}
window.loadRecentChats = loadRecentChats;

function saveRecentChats(list) {
    // Mirror the guest guard in loadRecentChats: never persist chat titles
    // to this device-wide key on behalf of a guest session.
    if (!getAuthToken()) return;
    try {
        localStorage.setItem(RECENT_CHATS_KEY, JSON.stringify(list.slice(0, MAX_RECENT_CHATS)));
    } catch (_) { }
}

function upsertRecentChat(id, title) {
    if (!id || !title) return;
    let list = loadRecentChats();
    const existing = list.find(c => c.id === id);
    list = list.filter(c => c.id !== id);
    list.unshift({
        id,
        title: (existing && existing.renamed) ? existing.title : title.slice(0, 60),
        renamed: existing ? !!existing.renamed : false,
        pinned: existing ? !!existing.pinned : false,
        starred: existing ? !!existing.starred : false,
        unread: existing ? !!existing.unread : false,
        ts: Date.now()
    });
    saveRecentChats(list);
    renderRecentChats();
}

function deleteRecentChat(id) {
    const list = loadRecentChats().filter(c => c.id !== id);
    saveRecentChats(list);
    renderRecentChats();
}

// ---- Delete confirmation modal ----
let pendingDeleteId = null;
let deleteInFlight = false;
const deleteConfirmOverlay = document.getElementById('delete-confirm-overlay');
const deleteConfirmBox = document.getElementById('delete-confirm-box');
const deleteConfirmCancelBtn = document.getElementById('delete-confirm-cancel');
const deleteConfirmOkBtn = document.getElementById('delete-confirm-ok');
let deleteModalPrevFocus = null;

function requestDeleteChat(id) {
    if (!deleteConfirmOverlay || !id) {
        // Fallback: modal markup missing for some reason, don't silently no-op the delete.
        deleteRecentChat(id);
        return;
    }
    pendingDeleteId = id;
    deleteInFlight = false;
    if (deleteConfirmOkBtn) deleteConfirmOkBtn.disabled = false;
    deleteModalPrevFocus = document.activeElement;
    deleteConfirmOverlay.style.display = 'flex';
    requestAnimationFrame(() => deleteConfirmOverlay.classList.add('open'));
    if (deleteConfirmBox) deleteConfirmBox.focus();
}

function closeDeleteConfirm() {
    if (!deleteConfirmOverlay) return;
    deleteConfirmOverlay.classList.remove('open');
    setTimeout(() => {
        if (!deleteConfirmOverlay.classList.contains('open')) deleteConfirmOverlay.style.display = 'none';
    }, 200);
    pendingDeleteId = null;
    deleteInFlight = false;
    if (deleteModalPrevFocus && typeof deleteModalPrevFocus.focus === 'function') {
        deleteModalPrevFocus.focus();
    }
}

if (deleteConfirmCancelBtn) {
    deleteConfirmCancelBtn.addEventListener('click', () => closeDeleteConfirm());
}
if (deleteConfirmOkBtn) {
    deleteConfirmOkBtn.addEventListener('click', () => {
        if (deleteInFlight || !pendingDeleteId) return;
        deleteInFlight = true; // guard against double-clicks/double-deletion
        deleteConfirmOkBtn.disabled = true;
        const idToDelete = pendingDeleteId;
        deleteRecentChat(idToDelete);
        closeDeleteConfirm();
    });
}
if (deleteConfirmOverlay) {
    deleteConfirmOverlay.addEventListener('click', (e) => {
        if (e.target === deleteConfirmOverlay) closeDeleteConfirm();
    });
}
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && deleteConfirmOverlay && deleteConfirmOverlay.classList.contains('open')) {
        closeDeleteConfirm();
    }
});

function togglePinChat(id) {
    const list = loadRecentChats();
    const chat = list.find(c => c.id === id);
    if (!chat) return;
    chat.pinned = !chat.pinned;
    saveRecentChats(list);
    renderRecentChats();
}

function toggleStarChat(id) {
    const list = loadRecentChats();
    const chat = list.find(c => c.id === id);
    if (!chat) return;
    chat.starred = !chat.starred;
    saveRecentChats(list);
    renderRecentChats();
}

function toggleUnreadChat(id) {
    const list = loadRecentChats();
    const chat = list.find(c => c.id === id);
    if (!chat) return;
    chat.unread = !chat.unread;
    saveRecentChats(list);
    renderRecentChats();
}

function renameChat(id, newTitle) {
    const title = (newTitle || '').trim();
    if (!title) return;
    const list = loadRecentChats();
    const chat = list.find(c => c.id === id);
    if (!chat) return;
    chat.title = title.slice(0, 60);
    chat.renamed = true;
    saveRecentChats(list);
    renderRecentChats();
}

function renderRecentChats() {
    if (!sidebarHistory) return;
    document.querySelectorAll('body > .sidebar-history-dropdown').forEach(d => d.remove());
    let list = loadRecentChats();

    if (!list.length) {
        sidebarHistory.innerHTML = '<div class="sidebar-empty" id="sidebar-empty">No conversations yet</div>';
        return;
    }
    const pinned = list.filter(c => c.pinned);
    const unpinned = list.filter(c => !c.pinned);
    sidebarHistory.innerHTML = '';

    function buildItem(chat) {
        const item = document.createElement('div');
        item.className = 'sidebar-history-item' + (chat.id === sessionId ? ' active' : '');
        item.dataset.sessionId = chat.id;

        const titleSpan = document.createElement('span');
        titleSpan.className = 'sidebar-history-item-title';
        titleSpan.textContent = chat.title;

        const renameInput = document.createElement('input');
        renameInput.className = 'sidebar-history-item-rename-input';
        renameInput.type = 'text';
        renameInput.value = chat.title;
        renameInput.style.display = 'none';
        renameInput.maxLength = 60;

        function commitRename() {
            renameInput.style.display = 'none';
            titleSpan.style.display = '';
            const val = renameInput.value.trim();
            if (val && val !== chat.title) renameChat(chat.id, val);
        }
        renameInput.addEventListener('click', e => e.stopPropagation());
        renameInput.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); commitRename(); }
            if (e.key === 'Escape') { renameInput.value = chat.title; commitRename(); }
        });
        renameInput.addEventListener('blur', commitRename);

        const menuWrap = document.createElement('div');
        menuWrap.className = 'sidebar-history-item-menu-wrap';

        const moreBtn = document.createElement('button');
        moreBtn.className = 'sidebar-history-item-more';
        moreBtn.title = 'More';
        moreBtn.setAttribute('aria-label', 'Conversation options');
        moreBtn.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>';

        const dropdown = document.createElement('div');
        dropdown.className = 'sidebar-history-dropdown';
        dropdown.setAttribute('role', 'menu');

        const pinItem = document.createElement('button');
        pinItem.className = 'sidebar-history-dropdown-item';
        pinItem.setAttribute('role', 'menuitem');
        pinItem.innerHTML = chat.pinned
            ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14l-1.5-1.5A3 3 0 0 1 17 13.4V7a5 5 0 0 0-10 0v6.4a3 3 0 0 1-.5 2.1L5 17z"/><line x1="2" y1="2" x2="22" y2="22"/></svg><span>Unpin</span>'
            : '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="17" x2="12" y2="22"/><path d="M5 17h14l-1.5-1.5A3 3 0 0 1 17 13.4V7a5 5 0 0 0-10 0v6.4a3 3 0 0 1-.5 2.1L5 17z"/></svg><span>Pin</span>';
        pinItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open');
            menuWrap.classList.remove('force-visible');
            togglePinChat(chat.id);
        });

        const starItem = document.createElement('button');
        starItem.className = 'sidebar-history-dropdown-item' + (chat.starred ? ' starred' : '');
        starItem.setAttribute('role', 'menuitem');
        starItem.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="' + (chat.starred ? 'currentColor' : 'none') + '" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg><span>' + (chat.starred ? 'Unstar' : 'Star') + '</span><span class="shortcut-hint">P</span>';
        starItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open');
            menuWrap.classList.remove('force-visible');
            toggleStarChat(chat.id);
        });

        const unreadItem = document.createElement('button');
        unreadItem.className = 'sidebar-history-dropdown-item';
        unreadItem.setAttribute('role', 'menuitem');
        unreadItem.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 2l-5 5-5-5"/><path d="M2 12c2-4 6-6 10-6s8 2 10 6c-2 4-6 6-10 6s-8-2-10-6z"/><line x1="2" y1="2" x2="22" y2="22"/></svg><span>' + (chat.unread ? 'Mark as read' : 'Mark as unread') + '</span><span class="shortcut-hint">U</span>';
        unreadItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open');
            menuWrap.classList.remove('force-visible');
            toggleUnreadChat(chat.id);
        });

        const renameItem = document.createElement('button');
        renameItem.className = 'sidebar-history-dropdown-item';
        renameItem.setAttribute('role', 'menuitem');
        renameItem.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.12 2.12 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg><span>Rename</span><span class="shortcut-hint">R</span>';
        renameItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open');
            menuWrap.classList.remove('force-visible');
            titleSpan.style.display = 'none';
            renameInput.style.display = '';
            renameInput.value = chat.title;
            renameInput.focus();
            renameInput.select();
        });

        const dropdownDivider = document.createElement('div');
        dropdownDivider.className = 'sidebar-history-dropdown-divider';

        const delItem = document.createElement('button');
        delItem.className = 'sidebar-history-dropdown-item delete';
        delItem.setAttribute('role', 'menuitem');
        delItem.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg><span>Delete</span><span class="shortcut-hint">D</span>';
        delItem.addEventListener('click', (e) => {
            e.stopPropagation();
            dropdown.classList.remove('open');
            menuWrap.classList.remove('force-visible');
            requestDeleteChat(chat.id);
        });

        dropdown.appendChild(pinItem);
        dropdown.appendChild(starItem);
        dropdown.appendChild(unreadItem);
        dropdown.appendChild(renameItem);
        dropdown.appendChild(dropdownDivider);
        dropdown.appendChild(delItem);
        document.body.appendChild(dropdown);

        moreBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const alreadyOpen = dropdown.classList.contains('open');
            document.querySelectorAll('.sidebar-history-dropdown.open').forEach(d => d.classList.remove('open'));
            document.querySelectorAll('.sidebar-history-item-menu-wrap.force-visible').forEach(w => w.classList.remove('force-visible'));
            if (alreadyOpen) return;
            const rowRect = item.getBoundingClientRect();
            const sidebarEl = document.getElementById('sidebar');
            const sidebarRect = sidebarEl ? sidebarEl.getBoundingClientRect() : null;
            const margin = 8;
            const menuWidth = 190;
            const menuHeight = 250; // approx height of the 6-item dropdown + divider
            // Vertically align with the clicked row, clamped to stay on-screen.
            let top = rowRect.top;
            top = Math.min(top, window.innerHeight - menuHeight - 8);
            top = Math.max(8, top);
            // Flyout to the right of the sidebar itself, not the row or button.
            const left = sidebarRect ? (sidebarRect.right + margin) : (rowRect.right + margin);
            dropdown.style.width = menuWidth + 'px';
            dropdown.style.top = top + 'px';
            dropdown.style.left = left + 'px';
            dropdown.classList.add('open');
            menuWrap.classList.add('force-visible');
        });

        menuWrap.appendChild(moreBtn);
        item.appendChild(titleSpan);
        item.appendChild(renameInput);
        item.appendChild(menuWrap);
        item.addEventListener('click', () => loadChatSession(chat.id));
        return item;
    }

    if (pinned.length) {
        const label = document.createElement('div');
        label.className = 'sidebar-section-sublabel';
        label.textContent = 'PINNED';
        sidebarHistory.appendChild(label);
        pinned.forEach(chat => sidebarHistory.appendChild(buildItem(chat)));
    }
    if (unpinned.length) {
        if (pinned.length) {
            const label = document.createElement('div');
            label.className = 'sidebar-section-sublabel';
            label.textContent = 'RECENT';
            sidebarHistory.appendChild(label);
        }
        unpinned.forEach(chat => sidebarHistory.appendChild(buildItem(chat)));
    }
    const clearBtn = document.getElementById('sidebar-filter-clear');
    if (clearBtn) clearBtn.addEventListener('click', clearProjectFilter);
}
window.renderRecentChats = renderRecentChats;

// ---- Recent section header: chevron collapse, Organize menu, pencil (new chat) ----
(function initRecentHeader() {
    const header = document.getElementById('sidebar-recent-header');
    const toggleBtn = document.getElementById('sidebar-recent-toggle');
    const historyEl = document.getElementById('sidebar-history');
    const organizeBtn = document.getElementById('sidebar-organize-btn');
    const organizeMenu = document.getElementById('sidebar-organize-menu');
    const oneListItem = document.getElementById('organize-one-list');
    const byProjectItem = document.getElementById('organize-by-project');
    const editBtn = document.getElementById('sidebar-recent-edit-btn');
    if (!header || !toggleBtn || !historyEl) return;

    toggleBtn.addEventListener('click', () => {
        const collapsed = header.classList.toggle('collapsed');
        historyEl.style.display = collapsed ? 'none' : '';
        toggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    });

    if (organizeBtn && organizeMenu) {
        organizeBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const willOpen = !organizeMenu.classList.contains('open');
            document.querySelectorAll('.sidebar-history-dropdown.open').forEach(d => d.classList.remove('open'));
            organizeMenu.classList.toggle('open', willOpen);
            organizeBtn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
            const actions = header.querySelector('.sidebar-recent-actions');
            if (actions) actions.classList.toggle('force-visible', willOpen);
        });
        organizeMenu.addEventListener('click', (e) => e.stopPropagation());
    }

    if (oneListItem && byProjectItem) {
        oneListItem.addEventListener('click', () => {
            oneListItem.classList.add('active');
            oneListItem.setAttribute('aria-checked', 'true');
            byProjectItem.classList.remove('active');
            byProjectItem.setAttribute('aria-checked', 'false');
            if (organizeMenu) organizeMenu.classList.remove('open');
        });
        byProjectItem.addEventListener('click', () => {
            // Projects isn't built yet — reflect that honestly instead of pretending to switch.
            showToast("Organizing by project isn't available yet.");
        });
    }

    if (editBtn) {
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            newChat();
        });
    }
})();

document.addEventListener('click', () => {
    document.querySelectorAll('.sidebar-history-dropdown.open').forEach(d => d.classList.remove('open'));
    document.querySelectorAll('.sidebar-history-item-menu-wrap.force-visible').forEach(w => w.classList.remove('force-visible'));
    const organizeMenuEl = document.getElementById('sidebar-organize-menu');
    if (organizeMenuEl) organizeMenuEl.classList.remove('open');
    const organizeBtnEl = document.getElementById('sidebar-organize-btn');
    if (organizeBtnEl) organizeBtnEl.setAttribute('aria-expanded', 'false');
    document.querySelectorAll('.sidebar-recent-actions.force-visible').forEach(a => a.classList.remove('force-visible'));
});

async function loadChatSession(id) {
    if (isStreaming || !id || id === sessionId) return;
    try {
        const res = await authFetch(`${API}/chat/history/${encodeURIComponent(id)}`);
        if (!res.ok) {
            showToast('That conversation could not be loaded.');
            deleteRecentChat(id);
            return;
        }
        const data = await res.json();
        const messages = data.messages || [];
        if (ttsPlayer) ttsPlayer.stop();
        if (camStream) stopCamera();
        clearPendingMode();
        sessionId = id;
        if (chatMessages) chatMessages.innerHTML = '';
        if (!messages.length) {
            chatMessages.appendChild(createWelcome());
            setQuickActionsVisible(false);
        } else {
            messages.forEach(m => addMessage(m.role === 'assistant' ? 'assistant' : 'user', m.content));
        }
        scrollToBottom();
        if (searchResultsWidget) searchResultsWidget.classList.remove('open');
        if (activityPanel) activityPanel.classList.remove('open');
        renderRecentChats();
    } catch (e) {
        showToast('Could not load that conversation.');
    }
}

function newChat() {
    if (ttsPlayer) ttsPlayer.stop();
    if (camStream) stopCamera();
    const chatsNavItem = document.querySelector('.sidebar-nav-item[data-nav="chats"]');
    if (chatsNavItem && !chatsNavItem.classList.contains('active')) chatsNavItem.click();
    sessionId = null;
    clearPendingMode();
    if (chatMessages) chatMessages.innerHTML = '';
    chatMessages.appendChild(createWelcome());
    setQuickActionsVisible(false);
    messageInput.value = '';
    autoResizeInput();
    setGreeting();
    if (searchResultsWidget) searchResultsWidget.classList.remove('open');
    if (searchResultsToggle) searchResultsToggle.style.display = 'none';
    if (activityPanel) activityPanel.classList.remove('open');
    if (settingsPanel) settingsPanel.classList.remove('open');
    if (activityToggle) activityToggle.style.display = 'none';
    if (activityList) {
        activityList.innerHTML = '<div class="activity-empty" id="activity-empty">Send a message to see the flow here.</div>';
    }
    updatePanelOverlay();
    renderRecentChats();
}

function createWelcome() {
    const T = (window.ScalableUIi18n && window.ScalableUIi18n.t) ? window.ScalableUIi18n.t : (k, f) => f;
    const h = new Date().getHours();
    let g = T('welcome.evening', 'Good evening.');
    if (h < 12) g = T('welcome.morning', 'Good morning.');
    else if (h < 17) g = T('welcome.afternoon', 'Good afternoon.');
    else if (h >= 22) g = T('welcome.late_night', 'Burning the midnight oil?');
    const div = document.createElement('div');
    div.className = 'welcome-screen';
    div.id = 'welcome-screen';
    div.innerHTML = `
        <div class="welcome-icon">
            <img class="welcome-icon-logo" src="/scalable-logo.png" alt="Scalable">
        </div>
        <h2 class="welcome-title">${g}</h2>
        <p class="welcome-sub">${T('welcome.sub', 'How may I assist you today?')}</p>
        <div class="welcome-chips">
            <button class="chip" data-msg="What can you do?">${T('welcome.chip_capabilities', 'What can you do?')}</button>
            <button class="chip" data-msg="Open YouTube for me">${T('welcome.chip_youtube', 'Open YouTube')}</button>
            <button class="chip" data-msg="Tell me a fun fact">${T('welcome.chip_fun_fact', 'Fun fact')}</button>
            <button class="chip" data-msg="Play some music">${T('welcome.chip_music', 'Play music')}</button>
        </div>`;
    div.querySelectorAll('.chip').forEach(c => {
        c.addEventListener('click', () => { if (!isStreaming) sendMessage(c.dataset.msg); });
    });
    return div;
}

function isUrlLike(str) {
    if (!str || typeof str !== 'string') return false;
    const s = str.trim();
    return s.length > 40 && (/^https?:\/\//i.test(s));
}

function friendlyUrlLabel(url) {
    if (!url || typeof url !== 'string') return 'View source';
    try {
        const u = new URL(url.startsWith('http') ? url : 'https://' + url);
        const host = u.hostname.replace(/^www\./, '');
        const path = u.pathname !== '/' ? u.pathname.slice(0, 20) + (u.pathname.length > 20 ? '…' : '') : '';
        return path ? host + path : host;
    } catch (_) {
        return url.length > 40 ? url.slice(0, 37) + '…' : url;
    }
}

function truncateSnippet(text, maxLen) {
    if (!text || typeof text !== 'string') return '';
    const t = text.trim();
    if (t.length <= maxLen) return t;
    return t.slice(0, maxLen).trim() + '…';
}

function renderSearchResults(payload) {
    if (!payload) return;
    if (searchResultsQuery) searchResultsQuery.textContent = (payload.query || '').trim() || 'Search';
    if (searchResultsAnswer) searchResultsAnswer.textContent = (payload.answer || '').trim() || '';
    if (!searchResultsList) return;
    searchResultsList.innerHTML = '';
    const results = payload.results || [];
    const maxContentLen = 220;
    for (const r of results) {
        let title = (r.title || '').trim();
        let content = (r.content || '').trim();
        const url = (r.url || '').trim();
        if (isUrlLike(title)) title = friendlyUrlLabel(url) || 'Source';
        if (!title) title = friendlyUrlLabel(url) || 'Source';
        if (isUrlLike(content)) content = '';
        content = truncateSnippet(content, maxContentLen);
        const score = r.score != null ? Math.round((r.score || 0) * 100) : null;
        const card = document.createElement('div');
        card.className = 'search-result-card';
        const urlDisplay = url ? escapeHtml(friendlyUrlLabel(url)) : '';
        const hrefSafe = safeUrlForHref(url);
        const urlMarkup = urlDisplay
            ? (hrefSafe ? `<a href="${hrefSafe}" target="_blank" rel="noopener" class="card-url" title="${escapeAttr(url)}">${urlDisplay}</a>` : `<span class="card-url">${urlDisplay}</span>`)
            : '';
        card.innerHTML = `
            <div class="card-title">${escapeHtml(title)}</div>
            ${content ? `<div class="card-content">${escapeHtml(content)}</div>` : ''}
            ${urlMarkup}
            ${score != null ? `<div class="card-score">Relevance: ${escapeHtml(String(score))}%</div>` : ''}`;
        searchResultsList.appendChild(card);
    }
}

function safeUrlForHref(url) {
    if (!url || typeof url !== 'string') return '';
    const u = url.trim();
    if (u.startsWith('https://') || u.startsWith('http://')) return escapeAttr(u);
    return '';
}

function escapeAttr(str) {
    if (typeof str !== 'string') return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

const ACTIVITY_STEPS = {
    query_detected: { step: 1, label: 'Query detected' },
    decision: { step: 2, label: 'Primary Brain' },
    intent_classified: { step: 3, label: 'Task Brain' },
    routing: { step: 4, label: 'Route selected' },
    tasks_executing: { step: 0, label: 'Executing tasks' },
    tasks_completed: { step: 0, label: 'Tasks completed' },
    actions_emitted: { step: 0, label: 'Actions sent' },
    vision_analyzing: { step: 0, label: 'Analyzing image' },
    streaming_started: { step: 5, label: 'Streaming response' },
    extracting_query: { step: 0, label: 'Extracting query' },
    searching_web: { step: 0, label: 'Searching web' },
    search_completed: { step: 0, label: 'Search completed' },
    context_retrieved: { step: 0, label: 'Context retrieved' },
    background_dispatched: { step: 0, label: 'Background tasks' },
    first_chunk: { step: 6, label: 'Core responded' },
};

function appendActivity(activity) {
    if (!activityList || !activity) return;
    const item = document.createElement('div');
    item.className = 'activity-item';
    item.setAttribute('data-event', activity.event || '');
    const stepInfo = ACTIVITY_STEPS[activity.event] || { step: 0, label: activity.event || 'Activity', icon: 'dot' };
    let detail = '';
    const addRouteClass = (route) => {
        if (route === 'general') item.classList.add('route-general');
        else if (route === 'realtime') item.classList.add('route-realtime');
        else if (route === 'vision' || route === 'camera') item.classList.add('route-vision');
        else if (route === 'task') item.classList.add('route-task');
        else if (route === 'mixed') item.classList.add('route-task');
        else if (route === 'chat') item.classList.add('route-chat');
    };
    if (activity.event === 'query_detected') {
        detail = activity.message || '';
    } else if (activity.event === 'decision') {
        const ms = activity.elapsed_ms;
        const timing = ms != null ? ` (${ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(2) + ' s'})` : '';
        const cat = (activity.query_type || '?').charAt(0).toUpperCase() + (activity.query_type || '').slice(1);
        detail = `${cat} — ${activity.reasoning || ''}${timing}`;
        addRouteClass(activity.query_type);
    } else if (activity.event === 'intent_classified') {
        detail = (activity.intent || '?').charAt(0).toUpperCase() + (activity.intent || '').slice(1);
        item.classList.add('activity-sub', 'route-task');
    } else if (activity.event === 'routing') {
        detail = `→ ${(activity.route || '?').charAt(0).toUpperCase() + (activity.route || '').slice(1)}`;
        addRouteClass(activity.route);
    } else if (activity.event === 'tasks_executing') {
        detail = activity.message || 'Running tasks...';
        item.classList.add('activity-sub', 'route-task');
    } else if (activity.event === 'tasks_completed') {
        detail = activity.message || 'Completed';
        item.classList.add('activity-sub', 'route-task');
    } else if (activity.event === 'actions_emitted') {
        detail = activity.message || 'Actions sent';
        item.classList.add('activity-sub');
    } else if (activity.event === 'vision_analyzing') {
        detail = activity.message || 'Analyzing image...';
        item.classList.add('activity-sub', 'route-vision');
    } else if (activity.event === 'streaming_started') {
        detail = `Generating via ${(activity.route || '?').charAt(0).toUpperCase() + (activity.route || '').slice(1)}`;
        addRouteClass(activity.route);
    } else if (activity.event === 'first_chunk') {
        const ms = activity.elapsed_ms;
        detail = ms != null ? `Core responded in ${ms < 1000 ? ms + ' ms' : (ms / 1000).toFixed(2) + ' s'}` : 'Response started';
        addRouteClass(activity.route);
    } else if (activity.event === 'extracting_query') {
        detail = activity.message || 'Parsing your question for search...';
        item.classList.add('activity-sub');
    } else if (activity.event === 'searching_web') {
        detail = activity.message || (activity.query ? `Query: "${activity.query}"` : 'Scanning Pulse...');
        item.classList.add('activity-sub', 'route-realtime');
    } else if (activity.event === 'search_completed') {
        detail = activity.message || 'Search completed';
        item.classList.add('activity-sub', 'route-realtime');
    } else if (activity.event === 'context_retrieved') {
        detail = activity.message || 'Knowledge base ready';
        item.classList.add('activity-sub', 'route-general');
    } else {
        detail = activity.message || (typeof activity === 'object' ? JSON.stringify(activity) : String(activity));
    }
    const stepNum = stepInfo.step ? `<span class="activity-step">${stepInfo.step}</span>` : '';
    item.innerHTML = `
        <div class="activity-event">${stepNum}${escapeHtml(stepInfo.label)}</div>
        <div class="activity-detail">${escapeHtml(detail || '')}</div>`;
    const emptyEl = activityList.querySelector('.activity-empty');
    if (emptyEl) emptyEl.style.display = 'none';
    activityList.appendChild(item);
    activityList.scrollTop = activityList.scrollHeight;
}

function escapeHtml(str) {
    if (typeof str !== 'string') return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function hideWelcome() {
    const w = document.getElementById('welcome-screen');
    if (w) w.remove();
    setQuickActionsVisible(true);
}

function setQuickActionsVisible(visible) {
    const container = document.getElementById('quick-actions-row');
    if (!container) return;
    container.style.display = visible ? '' : 'none';
}

const AVATAR_ICON_USER = '<svg class="msg-avatar-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
const AVATAR_ICON_ASSISTANT = '<img class="msg-avatar-logo" src="scalable-logo.png" alt="Scalable">';

const QUICK_ACTIONS = [
    { icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>', label: 'Open Website', msg: 'Open a website for me' },
    { icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>', label: 'Play Music', msg: 'Play some music for me' },
    { icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>', label: 'Generate Image', msg: 'Generate an image for me' },
    { icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>', label: 'Answer Questions', msg: 'What can you help me with?' },
    { icon: '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>', label: 'Analyze Camera', msg: null, action: 'camera' }
];

function buildQuickActionsRow() {
    const row = document.createElement('div');
    QUICK_ACTIONS.forEach(a => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'quick-action-btn';
        btn.innerHTML = `${a.icon}<span>${a.label}</span>`;
        btn.addEventListener('click', () => {
            if (isStreaming) return;
            if (a.action === 'camera') {
                if (camStream) stopCamera(); else startCamera();
                return;
            }
            sendMessage(a.msg);
        });
        row.appendChild(btn);
    });
    return row.childNodes ? Array.from(row.childNodes) : [];
}

function initQuickActionsRow() {
    const container = document.getElementById('quick-actions-row');
    if (!container) return;
    if (!container.childElementCount) {
        buildQuickActionsRow().forEach(btn => container.appendChild(btn));
    }
    const hasWelcome = !!document.getElementById('welcome-screen');
    setQuickActionsVisible(!hasWelcome);
}

function addMessage(role, text) {
    hideWelcome();
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.innerHTML = role === 'assistant' ? AVATAR_ICON_ASSISTANT : AVATAR_ICON_USER;
    const body = document.createElement('div');
    body.className = 'msg-body';
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = role === 'assistant' ? 'Scalable' : 'You';
    const content = document.createElement('div');
    content.className = 'msg-content';
    content.textContent = text;
    body.appendChild(label);
    body.appendChild(content);
    msg.appendChild(avatar);
    msg.appendChild(body);
    chatMessages.appendChild(msg);
    scrollToBottom();
    return content;
}

function addTypingIndicator() {
    hideWelcome();
    const msg = document.createElement('div');
    msg.className = 'message assistant';
    msg.id = 'typing-msg';
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar';
    avatar.innerHTML = AVATAR_ICON_ASSISTANT;
    const body = document.createElement('div');
    body.className = 'msg-body';
    const label = document.createElement('div');
    label.className = 'msg-label';
    label.textContent = 'Scalable';
    const content = document.createElement('div');
    content.className = 'msg-content';
    content.innerHTML = '<span class="msg-stream-text">...</span>';
    body.appendChild(label);
    body.appendChild(content);
    msg.appendChild(avatar);
    msg.appendChild(body);
    chatMessages.appendChild(msg);
    scrollToBottom();
    return content;
}

function removeTypingIndicator() {
    const t = document.getElementById('typing-msg');
    if (t) t.remove();
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatMessages.scrollTop = chatMessages.scrollHeight;
    });
}

async function sendMessage(textOverride) {
    let text = (textOverride || messageInput.value).trim();
    if (!text) { clearPendingMode(); }
    const titleText = text;
    if (text && pendingModePrefix) {
        text = pendingModePrefix + text;
        clearPendingMode();
    }
    userClosedActivity = false;
    const visionModeOn = camVisionModeInput && camVisionModeInput.checked;
    const wantsCamera = visionModeOn || isCameraQuery(text) || (camStream && text);
    if (wantsCamera && !text) text = 'What do you see?';
    if (!text || isStreaming) return;
    if (isListening) {
        pendingSendTranscript = null;
        clearTimeout(speechSendTimeout);
        speechSendTimeout = null;
        stopListening();
    }
    if ((isCameraQuery(text) || visionModeOn) && !camStream) {
        try {
            await startCamera();
            await new Promise((resolve) => {
                if (!camVideo) { resolve(); return; }
                if (camVideo.readyState >= 2 && camVideo.videoWidth > 0) { resolve(); return; }
                const onReady = () => { camVideo.removeEventListener('loadeddata', onReady); clearTimeout(t); resolve(); };
                const t = setTimeout(() => { camVideo.removeEventListener('loadeddata', onReady); resolve(); }, 3000);
                camVideo.addEventListener('loadeddata', onReady);
            });
        } catch (_) {
        }
    }
    let imgBase64 = null;
    if (camStream && wantsCamera) {
        imgBase64 = await captureFrameAsBase64Safe();
        if (!imgBase64) showToast('Camera frame not ready. Please try again.');
    }
    messageInput.value = '';
    autoResizeInput();
    charCount.textContent = '';
    addMessage('user', text);
    addTypingIndicator();
    isStreaming = true;
    if (sendBtn) sendBtn.disabled = true;
    if (messageInput) messageInput.disabled = true;
    if (orbContainer) orbContainer.classList.add('active');
    if (ttsPlayer) { ttsPlayer.reset(); ttsPlayer.unlock(); }
    const messageToSend = imgBase64 ? (text + ' ' + CAM_BYPASS_TOKEN) : text;
    const endpoint = '/chat/scalable/stream';
    if (activityList) {
        activityList.innerHTML = '<div class="activity-empty" id="activity-empty">Processing...</div>';
        if (activityToggle) activityToggle.style.display = '';
        if (activityPanel && settings.autoOpenActivity && !userClosedActivity) { activityPanel.classList.add('open'); updatePanelOverlay(); }
    }
    let firstChunkReceived = false;
    let timeoutId = null;
    const controller = new AbortController();
    try {
        if (ttsPlayer?.enabled && settings.thinkingSounds && preStarterPlayer) {
            preStarterPlayer.play(() => { });
        }
        timeoutId = setTimeout(() => controller.abort(), 300000);
        const res = await authFetch(`${API}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: messageToSend,
                session_id: sessionId,
                tts: !!(ttsPlayer && ttsPlayer.enabled),
                imgbase64: imgBase64 || null,
                personalization: getPersonalizationPayload(),
            }),
            signal: controller.signal,
        });
        if (!res.ok) {
            let errMsg = `HTTP ${res.status}`;
            try {
                const err = await res.json();
                errMsg = err.detail || (Array.isArray(err.detail) ? err.detail.map(d => d.msg || d.loc?.join('.')).join('; ') : err.message) || errMsg;
            } catch (_) { }
            throw new Error(errMsg);
        }
        removeTypingIndicator();
        const contentEl = addMessage('assistant', '');
        contentEl.innerHTML = '<span class="msg-stream-text">...</span>';
        scrollToBottom();
        if (!res.body) throw new Error('No response body');
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let sseBuffer = '';
        let fullResponse = '';
        let cursorEl = null;
        let streamDone = false;
        while (!streamDone) {
            const { done, value } = await reader.read();
            if (done) break;
            sseBuffer += decoder.decode(value, { stream: true });
            const lines = sseBuffer.split('\n\n');
            sseBuffer = lines.pop();
            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.session_id) {
                        sessionId = data.session_id;
                        upsertRecentChat(sessionId, titleText);
                    }
                    if (data.activity) {
                        appendActivity(data.activity);
                        if (activityToggle) activityToggle.style.display = '';
                        if (activityPanel && settings.autoOpenActivity && !userClosedActivity) { activityPanel.classList.add('open'); updatePanelOverlay(); }
                    }
                    if (data.search_results) {
                        renderSearchResults(data.search_results);
                        if (searchResultsToggle) searchResultsToggle.style.display = '';
                        if (searchResultsWidget && settings.autoOpenSearchResults) { searchResultsWidget.classList.add('open'); updatePanelOverlay(); }
                    }
                    if (data.actions) {
                        handleActions(data.actions, contentEl);
                    }
                    if (data.background_tasks) {
                        handleBackgroundTasks(data.background_tasks, contentEl);
                    }
                    if ('chunk' in data) {
                        const chunkText = data.chunk || '';
                        if (chunkText && !firstChunkReceived) {
                            firstChunkReceived = true;
                            if (ttsPlayer) ttsPlayer.reset();
                        }
                        fullResponse += chunkText;
                        const textSpan = contentEl.querySelector('.msg-stream-text');
                        if (textSpan) {
                            textSpan.textContent = fullResponse;
                            textSpan.classList.remove('stream-placeholder');
                        }
                        if (!cursorEl) {
                            cursorEl = document.createElement('span');
                            cursorEl.className = 'stream-cursor';
                            cursorEl.textContent = '|';
                            contentEl.appendChild(cursorEl);
                        }
                        scrollToBottom();
                    }
                    if (data.audio && ttsPlayer) {
                        ttsPlayer.enqueue(data.audio);
                    }
                    if (data.error) throw new Error(data.error);
                    if (data.done) { streamDone = true; break; }
                } catch (parseErr) {
                    if (parseErr.message && !parseErr.message.includes('JSON'))
                        throw parseErr;
                }
            }
            if (streamDone) break;
        }
        if (cursorEl) cursorEl.remove();
        const textSpan = contentEl.querySelector('.msg-stream-text');
        if (textSpan && !fullResponse) textSpan.textContent = '(No response)';
    } catch (err) {
        clearTimeout(timeoutId);
        removeTypingIndicator();
        let msg = 'Something went wrong. Please try again.';
        if (err.name === 'AbortError') {
            msg = 'Request timed out. Please try again.';
        } else if (err.message && err.message.includes('503')) {
            msg = 'Service temporarily unavailable. Please try again in a moment.';
        } else if (err.message && err.message.includes('429')) {
            msg = 'Rate limit reached. Please wait a moment before trying again.';
        } else if (err.message && err.message.length > 0) {
            msg = err.message.length > 100 ? err.message.slice(0, 97) + '...' : err.message;
        }
        addMessage('assistant', msg);
        showToast(msg, 6000);
    } finally {
        clearTimeout(timeoutId);
        isStreaming = false;
        if (sendBtn) sendBtn.disabled = false;
        if (messageInput) messageInput.disabled = false;
        if (orbContainer) orbContainer.classList.remove('active');
        maybeRestartListening();
    }
}

// ---- Auth gate: login/signup screen that controls whether the app initializes ----
const AUTH_USER_KEY = 'scalable_auth_user';

function getAuthUser() {
    try {
        const raw = localStorage.getItem(AUTH_USER_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
}
window.getAuthUser = getAuthUser;

function setAuthUser(user) {
    try {
        if (user) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
        else localStorage.removeItem(AUTH_USER_KEY);
    } catch (e) { }
}

function applyAuthUserToUI(user) {
    if (!user) return;
    const emailSpots = [document.getElementById('account-flyout-email')];
    emailSpots.forEach(function (el) { if (el) el.textContent = user.email || user.username; });

    const usernameEl = document.getElementById('account-flyout-username');
    if (usernameEl) usernameEl.textContent = user.username || '';

    const avatarEl = document.getElementById('account-flyout-avatar');
    if (avatarEl) {
        const source = user.display_name || user.username || '?';
        avatarEl.textContent = source.charAt(0).toUpperCase() || '?';
    }
}
window.applyAuthUserToUI = applyAuthUserToUI;

function scalableInitAuthGate() {
    const gate = document.getElementById('auth-gate');
    const appShell = document.getElementById('app-shell');
    const loadingEl = document.getElementById('auth-loading');
    const usernameInput = document.getElementById('auth-username-input');
    const usernameLabel = document.getElementById('auth-username-label');
    const emailField = document.getElementById('auth-email-field');
    const emailInput = document.getElementById('auth-email-input');
    const displayNameField = document.getElementById('auth-displayname-field');
    const displayNameInput = document.getElementById('auth-displayname-input');
    const passwordInput = document.getElementById('auth-password-input');
    const errorEl = document.getElementById('auth-gate-error');
    const submitBtn = document.getElementById('auth-gate-submit');
    const switchBtn = document.getElementById('auth-gate-switch-btn');
    const switchText = document.getElementById('auth-gate-switch-text');
    const modeSub = document.getElementById('auth-gate-mode-sub');

    if (!gate || !appShell) return;

    let mode = 'login'; // or 'signup'
    let appStarted = false;
    let wantsExplicitAuth = false;

    try {
        const urlParams = new URLSearchParams(window.location.search);
        const urlMode = urlParams.get('mode');
        if (urlMode === 'signup') { mode = 'signup'; wantsExplicitAuth = true; }
        else if (urlMode === 'login') { mode = 'login'; wantsExplicitAuth = true; }

        const oauthError = urlParams.get('oauth_error');
        if (oauthError) {
            wantsExplicitAuth = true;
            const messages = {
                invalid_request: 'That sign-in link expired or was already used — please try again.',
                exchange_failed: 'Could not complete sign-in with that provider. Please try again.',
                account_error: 'Something went wrong creating your account. Please try again.'
            };
            setTimeout(function () { showError(messages[oauthError] || 'Sign-in failed. Please try again.'); }, 0);
            history.replaceState(null, '', window.location.pathname + window.location.search.replace(/[?&]oauth_error=[^&]*/, '').replace(/^&/, '?'));
        }
    } catch (e) { }

    // OAuth login hands the session token back via a URL fragment
    // (#oauth_token=...) rather than a query param or cookie, so it never
    // ends up logged server-side or sent in a Referer header. Pick it up
    // once, store it like any other session token, then scrub the URL.
    try {
        if (window.location.hash.indexOf('oauth_token=') !== -1) {
            const hashParams = new URLSearchParams(window.location.hash.slice(1));
            const oauthToken = hashParams.get('oauth_token');
            if (oauthToken) {
                setAuthToken(oauthToken);
                wantsExplicitAuth = true;
                history.replaceState(null, '', window.location.pathname + window.location.search);
            }
        }
    } catch (e) { }

    // Show only the "Continue with X" buttons for providers the backend
    // actually has credentials configured for — never show a button that
    // would just 404.
    (function setUpOAuthButtons() {
        const oauthWrap = document.getElementById('auth-gate-oauth');
        const buttons = {
            google: document.getElementById('auth-oauth-google'),
            apple: document.getElementById('auth-oauth-apple'),
            github: document.getElementById('auth-oauth-github')
        };
        Object.keys(buttons).forEach(function (provider) {
            const btn = buttons[provider];
            if (btn) btn.addEventListener('click', function () {
                window.location.href = `${API}/auth/oauth/${provider}/start`;
            });
        });
        fetch(`${API}/auth/oauth/providers`).then(function (r) { return r.ok ? r.json() : { providers: [] }; })
            .then(function (data) {
                const available = data.providers || [];
                if (!available.length) return;
                available.forEach(function (provider) {
                    if (buttons[provider]) buttons[provider].style.display = '';
                });
                if (oauthWrap) oauthWrap.style.display = '';
            })
            .catch(function () { /* leave OAuth section hidden on failure */ });
    })();

    function showError(msg) {
        if (!errorEl) return;
        errorEl.textContent = msg;
        errorEl.style.display = msg ? 'block' : 'none';
    }

    function setMode(newMode) {
        mode = newMode;
        showError('');
        if (mode === 'signup') {
            if (submitBtn) submitBtn.textContent = 'Sign up';
            if (modeSub) modeSub.textContent = 'Create your account';
            if (usernameLabel) usernameLabel.textContent = 'Username';
            if (emailField) emailField.style.display = '';
            if (displayNameField) displayNameField.style.display = '';
            if (switchText) switchText.textContent = 'Already have an account?';
            if (switchBtn) switchBtn.textContent = 'Sign in';
            if (passwordInput) passwordInput.setAttribute('autocomplete', 'new-password');
        } else {
            if (submitBtn) submitBtn.textContent = 'Sign in';
            if (modeSub) modeSub.textContent = 'Sign in to continue';
            if (usernameLabel) usernameLabel.textContent = 'Username or email';
            if (emailField) emailField.style.display = 'none';
            if (displayNameField) displayNameField.style.display = 'none';
            if (switchText) switchText.textContent = "Don't have an account?";
            if (switchBtn) switchBtn.textContent = 'Sign up';
            if (passwordInput) passwordInput.setAttribute('autocomplete', 'current-password');
        }
    }

    function hideLoading() {
        if (!loadingEl) return;
        loadingEl.classList.add('fade-out');
        setTimeout(function () { loadingEl.style.display = 'none'; }, 260);
    }

    function showGate(message) {
        appStarted = false;
        hideLoading();
        gate.style.display = 'flex';
        appShell.style.display = 'none';
        setAuthToken(null);
        setAuthUser(null);
        updateGuestAuthUI(true);
        if (message) showError(message);
        if (usernameInput) usernameInput.focus();
    }

    function hideGate() {
        hideLoading();
        gate.style.display = 'none';
        appShell.style.display = '';
        updateGuestAuthUI(!getAuthToken());
        if (!appStarted) {
            appStarted = true;
            init();
        }
    }

    async function trySubmit() {
        const username = (usernameInput && usernameInput.value.trim()) || '';
        const password = (passwordInput && passwordInput.value) || '';
        const email = (emailInput && emailInput.value.trim()) || '';
        const displayName = (displayNameInput && displayNameInput.value.trim()) || '';

        if (!username || !password) {
            showError('Please fill in both fields.');
            return;
        }
        if (mode === 'signup' && !email) {
            showError('Please enter your email.');
            return;
        }

        if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = mode === 'signup' ? 'Signing up...' : 'Signing in...'; }
        showError('');

        try {
            const path = mode === 'signup' ? '/auth/signup' : '/auth/login';
            const body = mode === 'signup'
                ? { username, email, password, display_name: displayName || null }
                : { username, password };

            const res = await fetch(`${API}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok) {
                showError(data.detail || 'Something went wrong.');
                return;
            }

            setAuthToken(data.token);
            setGuestToken(null);
            const userForUI = { username: data.username, email: data.email, display_name: data.display_name, created_at: data.created_at };
            setAuthUser(userForUI);
            applyAuthUserToUI(userForUI);
            updateGuestAuthUI(false);
            hideGate();
        } catch (e) {
            showError('Could not reach the server. Is it running?');
        } finally {
            if (submitBtn) { submitBtn.disabled = false; setMode(mode); }
        }
    }

    if (submitBtn) submitBtn.addEventListener('click', trySubmit);
    [usernameInput, emailInput, passwordInput, displayNameInput].forEach(function (el) {
        if (!el) return;
        el.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); trySubmit(); }
        });
    });
    if (switchBtn) {
        switchBtn.addEventListener('click', function () {
            setMode(mode === 'signup' ? 'login' : 'signup');
        });
    }

    window.scalableShowAuthGate = showGate;
    window.scalableSignOut = async function () {
        try {
            await fetch(`${API}/auth/logout`, {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + (getAuthToken() || '') },
            });
        } catch (e) { /* best effort */ }
        // Clear local session state, then leave the app shell entirely and
        // land back on the site root (login/landing page) instead of
        // staying stuck on /app/?mode=login.
        try {
            setAuthToken(null);
            setAuthUser(null);
            setGuestToken(null);
        } catch (e) { /* best effort */ }
        window.location.href = '/';
    };

    function updateGuestAuthUI(isGuest) {
        const el = document.getElementById('header-guest-auth');
        if (el) el.style.display = isGuest ? 'flex' : 'none';
        const disclosure = document.getElementById('guest-disclosure-line');
        if (disclosure) disclosure.style.display = isGuest ? 'block' : 'none';
        document.body.classList.toggle('guest-mode', !!isGuest);
    }

    async function startGuestSession() {
        // Reuses any guest token already issued this browser session so a
        // page refresh doesn't grant a fresh set of free messages - the
        // server-side cap in require_auth_or_guest is keyed by this same id.
        const existingGuest = getGuestToken();
        if (existingGuest) {
            hideLoading();
            hideGate();
            updateGuestAuthUI(true);
            return;
        }
        try {
            const res = await fetch(`${API}/auth/guest`, { method: 'POST' });
            if (!res.ok) throw new Error('guest token request failed');
            const data = await res.json();
            setGuestToken(data.token);
            hideLoading();
            hideGate();
            updateGuestAuthUI(true);
        } catch (e) {
            // If even guest access can't be issued (server down, etc.), fall
            // back to the real sign-in screen rather than leaving a blank page.
            setMode('login');
            showGate('Could not start a preview session. Please sign in.');
        }
    }

    // Verify any existing token before deciding whether to show the gate or the app.
    const existingToken = getAuthToken(); if (!existingToken) {
        if (wantsExplicitAuth) {
            setMode(mode);
            showGate('');
        } else {
            startGuestSession();
        }
        return;
    }

    fetch(`${API}/auth/me`, { headers: { 'Authorization': 'Bearer ' + existingToken } })
        .then(function (res) {
            if (res.status === 401 || res.status === 403) {
                setAuthToken(null);
                const err = new Error('invalid session');
                err.authRejected = true;
                throw err;
            }
            if (!res.ok) {
                const err = new Error('auth check failed: ' + res.status);
                err.authRejected = false;
                throw err;
            }
            return res.json();
        })
        .then(function (profile) {
            setAuthUser(profile);
            applyAuthUserToUI(profile);
            updateGuestAuthUI(false);
            hideGate();
        })
        .catch(function (err) {
            // Only a genuine auth rejection (401/403) should log the user out.
            // A network error, timeout, or server 5xx (e.g. the backend still
            // starting up on reload) does NOT mean the session is invalid -
            // wiping the token here was throwing valid sessions back to login
            // any time this request merely failed to complete.
            if (err && err.authRejected === false) {
                hideLoading();
                gate.style.display = 'flex';
                appShell.style.display = 'none';
                setMode('login');
                showError('Could not reach the server. Please check your connection and try again.');
                if (usernameInput) usernameInput.focus();
                return;
            }
            setMode('login');
            showGate('');
        });
}

document.addEventListener('DOMContentLoaded', scalableInitAuthGate);