"""
13ft Ladder - Article Fetcher Service
A production-ready paywall bypass service with proper error handling,
thread-safety, and caching.
"""

import json
import os
import logging
import re
import time
import threading
import uuid
from contextlib import ExitStack
from urllib.parse import urlparse, urljoin, urlunparse, quote, unquote

import flask
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter, Retry

# =============================================================================
# CONFIGURATION & LOGGING
# =============================================================================

app = flask.Flask(__name__)

# Production logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

# =============================================================================
# LOCALIZATION
# =============================================================================

_DEFAULT_STRINGS = {
    "heading": "Enter Website Link",
    "label": "Link of the website you want to remove paywall for:",
    "submit": "Submit",
    "toggle_dark_mode": "Toggle Dark Mode",
    "status_heading": "Fetching Article",
    "error_title": "Something went wrong",
    "retry_button": "Try Another URL",
    "elapsed_template": "{seconds}s elapsed",
    "connection_lost_error": "Connection to server lost. The page may be taking too long to load.",
    "step_connect": "Connecting to website...",
    "step_fetch": "Downloading page content...",
    "step_detect": "Checking for anti-bot challenges...",
    "step_fallback_freedium": "Trying Freedium (Medium bypass)...",
    "step_fallback_org": "Trying archive.org snapshot...",
    "step_fallback_ph": "Trying archive.today / archive.ph snapshot...",
    "step_process": "Processing article...",
    "step_cleanup": "Cleaning up & preparing view...",
    "step_done": "Done!",
    "invalid_url": "Invalid URL",
    "medium_challenge_error": (
        "Medium served an anti-bot challenge and Freedium / archive.org / "
        "archive.today all came back empty. The article may be too new to "
        "have been archived yet."
    ),
    "challenge_error": (
        "The site served an anti-bot challenge (Cloudflare or similar) "
        "and no usable snapshot was found on archive.org or archive.today. "
        "This site is actively blocking automated requests."
    ),
    "timeout_error": "The website took too long to respond (30s timeout). Try again later.",
    "connection_error": "Could not connect to the website. Check the URL and try again.",
    "request_error": "Failed to fetch the page.",
    "unexpected_error": "Unexpected error while fetching the page.",
}


def get_locale():
    locale = os.environ.get("LOCALE", "en")
    if not re.match(r"^[a-zA-Z0-9_-]+$", locale):
        locale = "en"
    return locale


class ThreadLocalStrings:
    """Thread-local cache for locale strings to avoid repeated lookups."""

    def __init__(self):
        self._cache = threading.local()
        self._lock = threading.Lock()

    def get(self):
        if not hasattr(self._cache, 'strings') or self._cache.strings is None:
            with self._lock:
                if not hasattr(self._cache, 'strings') or self._cache.strings is None:
                    self._cache.strings = _load_strings_for_locale(get_locale())
        return self._cache.strings

    def invalidate(self):
        """Clear cache on locale change."""
        if hasattr(self._cache, 'strings'):
            del self._cache.strings


_locale_strings = ThreadLocalStrings()


def _load_strings_for_locale(locale):
    """Load strings from locale file or use defaults."""
    strings = dict(_DEFAULT_STRINGS)
    locale_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
    locale_file = os.path.join(locale_dir, f"{locale}.json")

    if locale != "en":
        try:
            with open(locale_file, "r", encoding="utf-8") as file:
                strings.update(json.load(file))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            locale = "en"

    strings["lang"] = locale
    return strings


def load_strings():
    return _locale_strings.get()


googlebot_headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.119 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}

# =============================================================================
# THREAD-SAFE STATE & LOCKS
# =============================================================================

jobs = {}
jobs_lock = threading.Lock()

page_cache = {}
page_cache_lock = threading.Lock()
PAGE_CACHE_TTL = 300  # 5 minutes


class UserFacingError(Exception):
    def __init__(self, user_message):
        super().__init__(user_message)
        self.user_message = user_message


html = """
<!DOCTYPE html>
<html lang="{{ lang }}">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>13ft Ladder</title>
    <link rel="icon" href="/favicon.ico" type="image/png">
    <link href="https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600&display=swap" rel="stylesheet" async>
    <style>
        * { box-sizing: border-box; }
        body {
            font-family: 'Open Sans', sans-serif;
            background-color: #FFF;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 90vh;
            transition: background-color 0.3s, color 0.3s;
        }

        h1 {
            font-size: 1.5rem;
            margin-bottom: 20px;
            text-align: center;
            color: #333;
        }

        label {
            display: block;
            margin-bottom: 10px;
            font-weight: bold;
        }

        input[type=text] {
            padding: 10px;
            margin-bottom: 10px;
            border: 1px solid #ccc;
            border-radius: 5px;
            width: 100%;
            font-size: 1rem;
        }

        input[type="submit"] {
            padding: 16px;
            background-color: #a327f0;
            color: #fff;
            border: none;
            border-radius: 5px;
            width: 100%;
            text-transform: uppercase;
            font-size: 1rem;
            font-weight: 600;
            cursor: pointer;
            transition: background-color 0.3s ease;
        }

        input[type="submit"]:hover {
            background-color: #821fc0;
        }

        .dark-mode-toggle {
            position: absolute;
            top: 10px;
            right: 10px;
        }

        .dark-mode-toggle input {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0, 0, 0, 0);
            white-space: nowrap;
            border: 0;
        }

        .dark-mode-toggle label {
            cursor: pointer;
            width: 54px;
            height: 28px;
            background: #cbd5e1;
            display: block;
            border-radius: 100px;
            position: relative;
            transition: background-color 0.3s, border-color 0.3s;
            border: 1px solid #b8c2cc;
        }

        .dark-mode-toggle label:hover {
            background: #b8c2cc;
            border-color: #a1b0be;
        }

        .dark-mode-toggle input:focus-visible + label {
            outline: 2px solid #a327f0;
            outline-offset: 3px;
        }

        body.dark-mode .dark-mode-toggle input:focus-visible + label {
            outline-color: #7359f8;
        }

        .dark-mode-toggle .thumb {
            position: absolute;
            top: 2px;
            left: 2px;
            width: 22px;
            height: 22px;
            background: #fff;
            border-radius: 50%;
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), background-color 0.3s, box-shadow 0.3s;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.15);
        }

        .dark-mode-toggle input:checked+label {
            background: #312e81;
            border-color: #4338ca;
        }

        .dark-mode-toggle input:checked+label:hover {
            background: #2e2a78;
            border-color: #3b379d;
        }

        .dark-mode-toggle input:checked+label .thumb {
            transform: translateX(26px);
            background: #1e1b4b;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4), 0 0 8px rgba(99, 102, 241, 0.4);
        }

        .dark-mode-toggle .icon {
            position: absolute;
            width: 14px;
            height: 14px;
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s ease;
        }

        .dark-mode-toggle .icon.sun {
            color: #ea580c;
            opacity: 1;
            transform: scale(1) rotate(0deg);
        }

        .dark-mode-toggle .icon.moon {
            color: #4f46e5;
            opacity: 0;
            transform: scale(0) rotate(-90deg);
        }

        .dark-mode-toggle input:checked+label .icon.sun {
            opacity: 0;
            transform: scale(0) rotate(90deg);
        }

        .dark-mode-toggle input:checked+label .icon.moon {
            color: #c7d2fe;
            opacity: 1;
            transform: scale(1) rotate(0deg);
        }

        @media only screen and (max-width: 600px) {
            form, .status-container { padding: 10px; }
            h1 { font-size: 1.2rem; }
        }

        body.dark-mode { background-color: #191a21; color: #FFF; }
        body.dark-mode h1 { color: #FFF; }
        body.dark-mode input[type=text] { background-color: #555; border: 1px solid #777; color: #FFF; }
        body.dark-mode input[type="submit"] { background-color: #7359f8; }
        body.dark-mode input[type="submit"]:hover { background-color: #5c47c6; }
        body.dark-mode .status-container { background: #23243a; }
        body.dark-mode .step { color: #aaa; }
        body.dark-mode .step.active { color: #fff; }
        body.dark-mode .step.done { color: #7359f8; }
        body.dark-mode .error-box { background: #3a1c1c; border-color: #ff6b6b; color: #ffaaaa; }

        .status-container {
            max-width: 480px;
            width: 100%;
            padding: 30px;
            text-align: center;
        }

        .status-container h1 { margin-bottom: 30px; }

        .url-display {
            font-size: 0.85rem;
            color: #888;
            margin-bottom: 24px;
            word-break: break-all;
        }

        .progress-bar-track {
            width: 100%;
            height: 6px;
            background: #e0e0e0;
            border-radius: 3px;
            overflow: hidden;
            margin-bottom: 28px;
        }

        body.dark-mode .progress-bar-track { background: #444; }

        .progress-bar-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #a327f0, #7359f8);
            border-radius: 3px;
            transition: width 0.5s ease;
        }

        .steps { text-align: left; margin-bottom: 24px; }

        .step {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 0;
            color: #bbb;
            font-size: 0.95rem;
            transition: color 0.3s;
        }

        .step.active { color: #333; font-weight: 600; }
        .step.done { color: #a327f0; }

        .step-icon {
            width: 24px;
            height: 24px;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .spinner {
            width: 18px;
            height: 18px;
            border: 2px solid #e0e0e0;
            border-top-color: #a327f0;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }

        body.dark-mode .spinner { border-color: #444; border-top-color: #7359f8; }

        @keyframes spin { to { transform: rotate(360deg); } }

        .checkmark { color: #a327f0; font-weight: bold; font-size: 1.1rem; }

        .elapsed {
            font-size: 0.85rem;
            color: #999;
            margin-top: 4px;
        }

        .error-box {
            background: #fff0f0;
            border: 1px solid #ffcccc;
            border-radius: 8px;
            padding: 16px;
            margin-top: 16px;
            color: #cc3333;
            font-size: 0.9rem;
            text-align: left;
        }

        .error-box strong { display: block; margin-bottom: 6px; }

        .retry-btn {
            display: inline-block;
            margin-top: 16px;
            padding: 10px 24px;
            background: #a327f0;
            color: #fff;
            border: none;
            border-radius: 5px;
            font-size: 0.95rem;
            font-weight: 600;
            cursor: pointer;
            text-decoration: none;
        }

        .retry-btn:hover { background: #821fc0; }
    </style>
</head>

<body>
    <div class="dark-mode-toggle">
        <input type="checkbox" id="dark-mode-toggle">
        <label for="dark-mode-toggle" title="{{ toggle_dark_mode }}">
            <span class="thumb">
                <svg class="icon sun" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <circle cx="12" cy="12" r="5"></circle>
                    <line x1="12" y1="1" x2="12" y2="3"></line>
                    <line x1="12" y1="21" x2="12" y2="23"></line>
                    <line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line>
                    <line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line>
                    <line x1="1" y1="12" x2="3" y2="12"></line>
                    <line x1="21" y1="12" x2="23" y2="12"></line>
                    <line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line>
                    <line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>
                </svg>
                <svg class="icon moon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
                </svg>
            </span>
        </label>
    </div>

    <div id="form-view">
        <form id="url-form">
            <h1>{{ heading }}</h1>
            <label for="link">{{ label }}</label>
            <input type="text" id="link" name="link" required autofocus>
            <input type="submit" value="{{ submit }}">
        </form>
    </div>

    <div id="status-view" style="display:none;">
        <div class="status-container">
            <h1>{{ status_heading }}</h1>
            <div class="url-display" id="status-url"></div>
            <div class="progress-bar-track">
                <div class="progress-bar-fill" id="progress-fill"></div>
            </div>
            <div class="steps" id="steps-list"></div>
            <div class="elapsed" id="elapsed-time"></div>
            <div id="error-area"></div>
        </div>
    </div>

    <script>
        const toggleSwitch = document.getElementById('dark-mode-toggle');
        const currentTheme = localStorage.getItem('theme') || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

        if (currentTheme === "dark") {
            document.body.classList.add("dark-mode");
            toggleSwitch.checked = true;
        }

        toggleSwitch.addEventListener('change', function () {
            if (this.checked) {
                document.body.classList.add("dark-mode");
                localStorage.setItem('theme', 'dark');
            } else {
                document.body.classList.remove("dark-mode");
                localStorage.setItem('theme', 'light');
            }
        });

        const UI_STRINGS = {{ ui_strings | tojson }};
        const STEPS = {{ steps | tojson }};

        function renderSteps(activeIdx) {
            const container = document.getElementById('steps-list');
            container.innerHTML = '';
            STEPS.forEach((step, i) => {
                const div = document.createElement('div');
                div.className = 'step' + (i < activeIdx ? ' done' : i === activeIdx ? ' active' : '');
                const icon = document.createElement('div');
                icon.className = 'step-icon';
                if (i < activeIdx) {
                    icon.innerHTML = '<span class="checkmark">&#10003;</span>';
                } else if (i === activeIdx) {
                    icon.innerHTML = '<div class="spinner"></div>';
                } else {
                    icon.innerHTML = '<span style="color:#ddd;">&#9675;</span>';
                }
                const text = document.createElement('span');
                text.textContent = step.label;
                div.appendChild(icon);
                div.appendChild(text);
                container.appendChild(div);
            });
        }

        function showStatus(url) {
            document.getElementById('form-view').style.display = 'none';
            document.getElementById('status-view').style.display = 'flex';
            document.getElementById('status-url').textContent = url;
            document.getElementById('error-area').innerHTML = '';
            renderSteps(0);
            document.getElementById('progress-fill').style.width = '0%';
        }

        function showError(message) {
            const area = document.getElementById('error-area');
            area.innerHTML = '';
            const box = document.createElement('div');
            box.className = 'error-box';
            const strong = document.createElement('strong');
            strong.textContent = UI_STRINGS.error_title;
            box.appendChild(strong);
            box.appendChild(document.createTextNode(message));
            area.appendChild(box);
            const retry = document.createElement('a');
            retry.href = '/';
            retry.className = 'retry-btn';
            retry.textContent = UI_STRINGS.retry_button;
            area.appendChild(retry);
        }

        document.getElementById('url-form').addEventListener('submit', function(e) {
            e.preventDefault();
            const link = document.getElementById('link').value.trim();
            if (!link) return;
            showStatus(link);

            const startTime = Date.now();
            const elapsedEl = document.getElementById('elapsed-time');
            const progressEl = document.getElementById('progress-fill');

            const timer = setInterval(() => {
                const sec = ((Date.now() - startTime) / 1000).toFixed(0);
                elapsedEl.textContent = UI_STRINGS.elapsed_template.replace('{seconds}', sec);
            }, 500);

            const evtSource = new EventSource('/status?url=' + encodeURIComponent(link));

            evtSource.addEventListener('step', function(e) {
                const data = JSON.parse(e.data);
                const idx = STEPS.findIndex(s => s.id === data.step);
                if (idx >= 0) {
                    renderSteps(idx);
                    const pct = Math.min(((idx + 1) / STEPS.length) * 100, 95);
                    progressEl.style.width = pct + '%';
                }
                if (data.redirect) {
                    evtSource.close();
                    clearInterval(timer);
                    renderSteps(STEPS.length);
                    progressEl.style.width = '100%';
                    setTimeout(() => {
                        window.location.href = data.redirect;
                    }, 400);
                }
            });

            evtSource.addEventListener('error_msg', function(e) {
                evtSource.close();
                clearInterval(timer);
                const data = JSON.parse(e.data);
                showError(data.message);
            });

            evtSource.onerror = function() {
                evtSource.close();
                clearInterval(timer);
                showError(UI_STRINGS.connection_lost_error);
            };
        });

        window.addEventListener('pageshow', function(event) {
            if (event.persisted) {
                document.getElementById('form-view').style.display = '';
                document.getElementById('status-view').style.display = 'none';
                document.getElementById('link').value = '';
            }
        });
    </script>
</body>

</html>
"""


def build_steps(strings):
    return [
        {"id": "connect", "label": strings["step_connect"]},
        {"id": "fetch", "label": strings["step_fetch"]},
        {"id": "detect", "label": strings["step_detect"]},
        {"id": "fallback_freedium", "label": strings["step_fallback_freedium"]},
        {"id": "fallback_org", "label": strings["step_fallback_org"]},
        {"id": "fallback_ph", "label": strings["step_fallback_ph"]},
        {"id": "process", "label": strings["step_process"]},
        {"id": "cleanup", "label": strings["step_cleanup"]},
        {"id": "done", "label": strings["step_done"]},
    ]


def render_main_page():
    strings = load_strings()
    ui_strings = {
        "error_title": strings["error_title"],
        "retry_button": strings["retry_button"],
        "elapsed_template": strings["elapsed_template"],
        "connection_lost_error": strings["connection_lost_error"],
    }
    return flask.render_template_string(
        html,
        steps=build_steps(strings),
        ui_strings=ui_strings,
        **strings,
    )


# =============================================================================
# HTML PROCESSING
# =============================================================================

def normalize_base_url(url):
    """Return a base URL for resolving relative links."""
    try:
        parsed = urlparse(url)
        # Normalize to https://domain/ or https://domain/path/
        base = f"{parsed.scheme or 'https'}://{parsed.netloc}/"
        if parsed.path and not parsed.path.endswith("/"):
            base = urljoin(base, parsed.path.rsplit("/", 1)[0] + "/")
        return base
    except Exception:
        return "https://" + url


def make_absolute(soup, base_url):
    """Resolve all relative URLs in an HTML document."""
    for tag in soup.find_all(href=True):
        href = tag.get("href", "")
        if href and not href.startswith(("http://", "https://", "#", "mailto:")):
            tag["href"] = urljoin(base_url, href)
    for tag in soup.find_all(src=True):
        src = tag.get("src", "")
        if src and not src.startswith(("http://", "https://", "#")):
            tag["src"] = urljoin(base_url, src)
    return soup


def proxify_links(soup, base_url):
    """Rewrite <a href> links so they route back through this proxy
    (/https://target/path) instead of sending the browser to the origin site.
    Assets (src, stylesheets) stay absolute/direct via the <base> tag."""
    skip = ("#", "mailto:", "tel:", "javascript:", "data:", "sms:")
    for tag in soup.find_all("a", href=True):
        href = (tag.get("href") or "").strip()
        if not href or href.lower().startswith(skip):
            continue
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme in ("http", "https"):
            tag["href"] = "/" + absolute
    return soup


def process_html_document(html_content, original_url):
    """
    Parses HTML, injects the <base> tag to fix relative links, and applies
    site-specific modifications (like stripping paywall JS) where needed.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    base_url = normalize_base_url(original_url)

    # Handle <base> tag
    base_tag = soup.find("base")
    if base_tag:
        base_tag["href"] = base_url
    else:
        new_base_tag = soup.new_tag("base", href=base_url)
        if soup.head:
            soup.head.insert(0, new_base_tag)
        else:
            head_tag = soup.new_tag("head")
            head_tag.insert(0, new_base_tag)
            soup.insert(0, head_tag)

    proxify_links(soup, base_url)

    domain = urlparse(original_url).netloc.lower()

    # Strip anti-hotlinking and frame-busting scripts
    for script in soup.find_all("script", src=False):
        content = script.get_text()
        if "location.hostname" in content and ("location.href" in content or "location.replace" in content):
            script.decompose()
        elif "top.location" in content or "window.top" in content:
            script.decompose()

    # Seattle Times specific fixes
    if "seattletimes.com" in domain:
        for script in soup.find_all("script", src=True):
            if "st-user-messaging" in script["src"] or "st-advertising" in script["src"]:
                script.decompose()
        if soup.body:
            current_style = soup.body.get("style", "")
            soup.body["style"] = f"{current_style}; overflow: auto !important; position: static !important;"

    # Remove favicons from source and add our own
    for link_tag in soup.find_all("link", rel=lambda r: r and any(
            v.lower() in ("icon", "shortcut icon", "apple-touch-icon",
                          "apple-touch-icon-precomposed", "mask-icon")
            for v in (r if isinstance(r, list) else [r])
    )):
        link_tag.decompose()

    favicon_tag = soup.new_tag("link", rel="icon", href="/favicon.ico", type="image/png")
    if soup.head:
        soup.head.append(favicon_tag)

    return str(soup)


# =============================================================================
# CHALLENGE DETECTION
# =============================================================================

CHALLENGE_SIGNATURES = [
    "just a moment",
    "checking your browser",
    "cloudflare",
    "cf-challenge",
    "ddos protection",
    "attention required",
    "enable javascript and cookies to continue",
    "please verify you are a human",
    "_incapsula_resource",
    "incapsula incident",
    "request unsuccessful",
    "datadome",
    "enable js and disable any ad blocker",
]


def is_challenge_page(html_text):
    if not html_text:
        return False
    lower = html_text[:8000].lower()
    hits = sum(1 for sig in CHALLENGE_SIGNATURES if sig in lower)
    if hits >= 1 and len(html_text) < 20000:
        return True
    return hits >= 2


# =============================================================================
# REQUEST SESSION (with retry logic)
# =============================================================================

session = requests.Session()

def create_adapter():
    retry = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    return adapter

session.mount("https://", create_adapter())
session.mount("http://", create_adapter())


# =============================================================================
# FETCH FUNCTIONS
# =============================================================================

FREEDIUM_MIRRORS = ["freedium-mirror.cfd", "freedium.cfd"]
ARCHIVE_PH_MIRRORS = ["archive.ph", "archive.today", "archive.is", "archive.li"]


def is_medium_url(url):
    try:
        host = (urlparse(url).hostname or "").lower()
        return host == "medium.com" or host.endswith(".medium.com")
    except Exception:
        return False


def fetch_via_freedium(url, job_id=None):
    """Freedium is a Medium-specific paywall bypass service."""
    logger.info(f"Trying Freedium for: {url}")
    set_step(job_id, 'fallback_freedium')
    clean_url = url.split('?')[0]
    for mirror in FREEDIUM_MIRRORS:
        try:
            freedium_url = f"https://{mirror}/{clean_url}"
            resp = session.get(
                freedium_url,
                headers=googlebot_headers,
                timeout=30,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                continue
            resp.encoding = resp.apparent_encoding
            text = resp.text
            if is_challenge_page(text):
                continue
            if 'main-content' not in text or len(text) < 2000:
                continue
            return text, resp.url
        except Exception:
            continue
    return None, None


def set_step(job_id, step):
    with jobs_lock:
        if job_id and job_id in jobs:
            jobs[job_id]['step'] = step


REAL_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_via_archive_org(url, job_id=None):
    set_step(job_id, 'fallback_org')
    wayback_api = "https://archive.org/wayback/available"
    try:
        meta = session.get(wayback_api, params={"url": url}, timeout=15).json()
        snapshot = meta.get("archived_snapshots", {}).get("closest", {})
        if not snapshot.get("available"):
            return None, None
        archived_url = snapshot["url"]
        if archived_url.startswith("http://"):
            archived_url = "https://" + archived_url[len("http://"):]
        if "/web/" in archived_url and "id_/" not in archived_url:
            archived_url = archived_url.replace(
                archived_url.split("/web/")[1].split("/")[0],
                archived_url.split("/web/")[1].split("/")[0] + "id_",
                1,
            )
        resp = session.get(archived_url, headers=googlebot_headers, timeout=30)
        resp.encoding = resp.apparent_encoding
        return resp.text, resp.url
    except Exception:
        return None, None


def fetch_via_archive_ph(url, job_id=None):
    """Try archive.today / archive.ph / archive.is — all mirrors of the same service."""
    set_step(job_id, 'fallback_ph')
    for mirror in ARCHIVE_PH_MIRRORS:
        try:
            newest_url = f"https://{mirror}/newest/{quote(url, safe=':/')}"
            resp = session.get(
                newest_url,
                headers=REAL_BROWSER_HEADERS,
                timeout=20,
                allow_redirects=True,
            )
            if resp.status_code != 200:
                continue

            final = resp.url
            if not re.search(r"https?://archive\.(ph|today|is|li)/[A-Za-z0-9]{4,}", final):
                continue
            if re.search(r"archive\.(ph|today|is|li)/newest/", final):
                continue

            text = resp.text
            if is_challenge_page(text):
                continue

            lower_head = text[:5000].lower()
            if "no results" in lower_head or "0 captures" in lower_head:
                continue

            return text, final
        except Exception:
            continue
    return None, None


def bypass_paywall(url, strings, job_id=None):
    set_step(job_id, 'connect')

    if not url.startswith("http"):
        url = "https://" + url

    medium = is_medium_url(url)
    html_text = ""
    final_url = url

    if medium:
        freedium_html, freedium_final = fetch_via_freedium(url, job_id)
        if freedium_html:
            set_step(job_id, 'process')
            result = process_html_document(freedium_html, freedium_final)
            set_step(job_id, 'cleanup')
            return result
    else:
        set_step(job_id, 'fetch')
        response = session.get(url, headers=googlebot_headers, timeout=30)
        response.encoding = response.apparent_encoding
        html_text = response.text
        final_url = response.url

    set_step(job_id, 'detect')
    if not html_text or is_challenge_page(html_text):
        recovered = False

        archived_html, archived_url = fetch_via_archive_org(url, job_id)
        if archived_html and not is_challenge_page(archived_html):
            html_text = archived_html
            final_url = archived_url
            recovered = True

        if not recovered:
            archived_html, archived_url = fetch_via_archive_ph(url, job_id)
            if archived_html and not is_challenge_page(archived_html):
                html_text = archived_html
                final_url = archived_url
                recovered = True

        if not recovered:
            if medium:
                msg = strings["medium_challenge_error"]
            else:
                msg = strings["challenge_error"]
            raise UserFacingError(msg)

    set_step(job_id, 'process')
    result = process_html_document(html_text, final_url)

    set_step(job_id, 'cleanup')
    return result


def normalize_cache_url(url):
    if "://" in url:
        return "https://" + url.split("://", 1)[1]
    return "https://" + url


def clean_page_cache():
    now = time.time()
    expired = [k for k, v in page_cache.items() if now - v['timestamp'] > PAGE_CACHE_TTL]
    for k in expired:
        del page_cache[k]


def fetch_worker(job_id, url, strings):
    try:
        result = bypass_paywall(url, strings, job_id)
        cache_key = normalize_cache_url(url)
        with page_cache_lock:
            clean_page_cache()
            page_cache[cache_key] = {'html': result, 'timestamp': time.time()}
        with jobs_lock:
            jobs[job_id]['result'] = cache_key
            jobs[job_id]['step'] = 'done'
    except requests.exceptions.Timeout:
        with jobs_lock:
            jobs[job_id]['error'] = strings["timeout_error"]
            jobs[job_id]['step'] = 'error'
    except requests.exceptions.ConnectionError:
        with jobs_lock:
            jobs[job_id]['error'] = strings["connection_error"]
            jobs[job_id]['step'] = 'error'
    except requests.exceptions.RequestException as e:
        with jobs_lock:
            jobs[job_id]['error'] = strings["request_error"]
            jobs[job_id]['step'] = 'error'
    except UserFacingError as error:
        with jobs_lock:
            jobs[job_id]['error'] = error.user_message
            jobs[job_id]['step'] = 'error'
    except Exception:
        logger.exception("Unexpected error fetching %s", url)
        with jobs_lock:
            jobs[job_id]['error'] = strings["unexpected_error"]
            jobs[job_id]['step'] = 'error'


@app.route("/favicon.ico")
def favicon():
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logo.png")
    if os.path.exists(logo_path):
        with open(logo_path, "rb") as f:
            data = f.read()
        return flask.Response(data, mimetype="image/png",
                              headers={"Cache-Control": "public, max-age=86400"})
    return "", 404


@app.route("/")
def main_page():
    return render_main_page()


@app.route("/status")
def status_stream():
    raw_url = flask.request.args.get("url", "")
    url = unquote(raw_url)

    if not url:
        return "Missing URL", 400

    strings = load_strings()
    job_id = str(uuid.uuid4())
    with jobs_lock:
        jobs[job_id] = {'step': 'queued', 'result': None, 'error': None}

    thread = threading.Thread(target=fetch_worker, args=(job_id, url, strings))
    thread.daemon = True
    thread.start()

    def generate():
        last_step = None
        try:
            while True:
                with jobs_lock:
                    job = dict(jobs[job_id]) if job_id in jobs else None
                if not job:
                    break

                current = job['step']
                if current != last_step:
                    last_step = current
                    if current == 'done':
                        yield f"event: step\ndata: {json.dumps({'step': 'done', 'redirect': '/' + job['result']})}\n\n"
                        break
                    elif current == 'error':
                        yield f"event: error_msg\ndata: {json.dumps({'message': job['error']})}\n\n"
                        break
                    else:
                        yield f"event: step\ndata: {json.dumps({'step': current})}\n\n"

                time.sleep(0.2)
        finally:
            with jobs_lock:
                jobs.pop(job_id, None)

    return flask.Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.route("/article", methods=["POST"])
def show_article():
    link = flask.request.form["link"]
    strings = load_strings()
    try:
        return bypass_paywall(link, strings)
    except requests.exceptions.Timeout:
        return strings["timeout_error"], 400
    except requests.exceptions.ConnectionError:
        return strings["connection_error"], 400
    except requests.exceptions.RequestException:
        return strings["request_error"], 400
    except UserFacingError as error:
        return error.user_message, 400
    except Exception:
        logger.exception("Unexpected error fetching page")
        return strings["unexpected_error"], 500


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>", methods=["GET"])
def get_article(path):
    strings = load_strings()
    full_url = flask.request.url
    parts = full_url.split("/", 4)
    if len(parts) >= 5:
        actual_url = "https://" + parts[4].lstrip("/")

        with page_cache_lock:
            cached = page_cache.get(actual_url)
        if cached:
            return cached['html']

        try:
            return bypass_paywall(actual_url, strings)
        except requests.exceptions.Timeout:
            return strings["timeout_error"], 400
        except requests.exceptions.ConnectionError:
            return strings["connection_error"], 400
        except requests.exceptions.RequestException:
            return strings["request_error"], 400
        except UserFacingError as error:
            return error.user_message, 400
        except Exception:
            return strings["unexpected_error"], 500
    else:
        return strings["invalid_url"], 400


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=os.getenv("PORT") or 5000, debug=False)
