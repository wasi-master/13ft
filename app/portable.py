import flask
import requests
from flask import request

app = flask.Flask(__name__)
googlebot_headers = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/W.X.Y.Z Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
}
html = """
<html lang="en">
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="X-UA-Compatible" content="IE=edge">
    <title>13ft Ladder</title>

    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Open+Sans&display=swap" rel="stylesheet">

    <style>
        div.centered {
            position: absolute;
            left: 50%;
            top: 50%;
            -webkit-transform: translate(-50%, -50%);
            transform: translate(-50%, -50%);
        }

        h1{
            font-family: 'Product Sans', 'Open Sans', sans-serif;
            text-rendering: optimizeLegibility;
            margin: 0;
            text-align: center;
        }

        input[type=text] {
            padding: 10px;
            margin-bottom: 10px;
            border: 0;
            box-shadow: 0 0 15px 4px rgba(0,0,0,0.3);
            border-radius: 10px;
            width:100%;
            font-family: 'Product Sans', 'Open Sans', sans-serif;
            font-size: inherit;
            text-rendering: optimizeLegibility;
        }

        input[type="submit"] {
            /* remove default behavior */
            -webkit-appearance:none;
            appearance:none;

            /* usual styles */
            padding:10px;
            border:none;
            background-color:#6a0dad;
            color:#fff;
            font-weight:600;
            border-radius:5px;
            width:100%;
            text-transform: uppercase;
            font-family: 'Product Sans', 'Open Sans', sans-serif;
            font-size: 1rem;
            text-rendering: optimizeLegibility;
        }
        input[type="submit"]:active {
            scale: 1.02;
        }
    </style>
</head>

<body>
    <div class="centered">
        <form action="/article" method="post">
            <h1>
                <label for="link">Enter Website Link</label>
            </h1>
            <br>
            <input
                title="Link of the website you want to remove paywall for"
                type="text"
                name="link"
                required
            >
            <input type="submit" value="submit">
        </form>
    </div>
</body>
</html>
"""

def bypass_paywall(url):
    """
    Bypass paywall for a given url
    """
    response = requests.get(url, headers=googlebot_headers)
    response.encoding = response.apparent_encoding
    return response.text


@app.route("/")
def main_page():
    return html


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
    full_url = request.url
    parts = full_url.split('/',4)
    if len(parts) >= 5:
        actual_url = 'https://' + parts[4].lstrip('/')
        try:
            return bypass_paywall(actual_url)
        except requests.exceptions.RequestException as e:
            return str(e), 400
        except e:
            raise e
    else:
        return "Invalid URL", 400


app.run(host='0.0.0.0', port=5001, debug=False)
