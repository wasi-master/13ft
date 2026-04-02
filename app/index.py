import json
import os
import re

import flask
import requests
from flask import request
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

app = flask.Flask(__name__)

_DEFAULT_STRINGS = {
    "heading": "Enter Website Link",
    "label": "Link of the website you want to remove paywall for:",
    "submit": "Submit",
    "toggle_dark_mode": "Toggle Dark Mode",
    "invalid_url": "Invalid URL",
}


def load_strings():
    """Load UI strings from a locale JSON file selected by the LOCALE env var.

    Falls back to built-in English strings when the locale file is missing or
    cannot be parsed.  Only alphanumeric characters, hyphens, and underscores
    are accepted as locale names to prevent path traversal.
    """
    locale = os.environ.get("LOCALE", "en")
    if not re.match(r'^[a-zA-Z0-9_-]+$', locale):
        locale = "en"

    if locale == "en":
        return dict(_DEFAULT_STRINGS)

    locale_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
    locale_file = os.path.join(locale_dir, f"{locale}.json")

    try:
        with open(locale_file, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        return {**_DEFAULT_STRINGS, **loaded}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_DEFAULT_STRINGS)


strings = load_strings()

googlebot_headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.6533.119 Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}

def add_base_tag(html_content, original_url):
    soup = BeautifulSoup(html_content, 'html.parser')
    parsed_url = urlparse(original_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}/"
    
    # Handle paths that are not root, e.g., "https://x.com/some/path/w.html"
    if parsed_url.path and not parsed_url.path.endswith('/'):
        base_url = urljoin(base_url, parsed_url.path.rsplit('/', 1)[0] + '/')
    base_tag = soup.find('base')
    
    print(base_url)
    if not base_tag:
        new_base_tag = soup.new_tag('base', href=base_url)
        if soup.head:
            soup.head.insert(0, new_base_tag)
        else:
            head_tag = soup.new_tag('head')
            head_tag.insert(0, new_base_tag)
            soup.insert(0, head_tag)
    
    return str(soup)

def bypass_paywall(url):
    """
    Bypass paywall for a given url
    """
    if url.startswith("http"):
        response = requests.get(url, headers=googlebot_headers)
        response.encoding = response.apparent_encoding
        return add_base_tag(response.text, response.url)

    try:
        return bypass_paywall("https://" + url)
    except requests.exceptions.RequestException as e:
        return bypass_paywall("http://" + url)


@app.route("/")
def main_page():
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()
    return flask.render_template_string(template, **strings)


@app.route("/article", methods=["POST"])
def show_article():
    link = flask.request.form["link"]
    try:
        return bypass_paywall(link)
    except requests.exceptions.RequestException as e:
        return str(e), 400
    except Exception as exc:
        raise exc


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>", methods=["GET"])
def get_article(path):
    full_url = request.url
    parts = full_url.split("/", 4)
    if len(parts) >= 5:
        actual_url = "https://" + parts[4].lstrip("/")
        try:
            return bypass_paywall(actual_url)
        except requests.exceptions.RequestException as e:
            return str(e), 400
        except Exception as e:
            raise e
    else:
        return strings["invalid_url"], 400


app.run(debug=False)
