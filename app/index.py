import flask
import requests
from flask import request

app = flask.Flask(__name__)
googlebot_headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/W.X.Y.Z Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}


def bypass_paywall(url):
    """
    Bypass paywall for a given url
    """
    if url.startswith("http"):
        response = requests.get(url, headers=googlebot_headers)
        response.encoding = response.apparent_encoding
        return response.text
    
    try:
        return bypass_paywall("https://" + url)
    except requests.exceptions.RequestException as e:
        return bypass_paywall("http://" + url)

@app.route("/")
def main_page():
    return flask.send_from_directory(".", "index.html")


@app.route("/article", methods=["POST"])
def show_article():
    link = flask.request.form["link"]
    try:
        return bypass_paywall(link)
    except requests.exceptions.RequestException as e:
        return str(e), 400
    except e:
        raise e

@app.route("/", defaults={"path": ""})
@app.route('/<path:path>', methods=["GET"])
def get_article(path):
    print(path)
    full_url = request.url
    parts = full_url.split('/',4)
    if len(parts) >= 5:
        actual_url = 'https://' + parts[4].lstrip('/')
        print(actual_url)
        try:
            return bypass_paywall(actual_url)
        except requests.exceptions.RequestException as e:
            return str(e), 400
        except e:
            raise e
    else:
        return "Invalid URL", 400

app.run(debug=False)
