import os
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
    response = requests.get(url, headers=googlebot_headers)
    response.encoding = response.apparent_encoding
    return response.text


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
    if len(parts) >= 5:
        try:
            return bypass_paywall(path)
        except requests.exceptions.RequestException as e:
            return str(e), 400
        except e:
            raise e
    else:
        return "Invalid URL", 400

port = os.getenv("PORT")
if port is None:
    port = 5000

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    app.run(debug=False)
