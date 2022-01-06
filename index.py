import flask
import requests

app = flask.Flask(__name__)
googlebot_headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/W.X.Y.Z Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}


def bypass_paywall(url):
    """
    Bypass paywall for a given url
    """
    response = requests.get(url, headers=googlebot_headers)
    return response.text


@app.route("/")
def main_page():
    return flask.send_from_directory(".", "index.html")


@app.route("/article", methods=["POST"])
def show_article():
    link = flask.request.form["link"]
    return bypass_paywall(link)


app.run(debug=True)
