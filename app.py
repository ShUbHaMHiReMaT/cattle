from flask import Flask, send_from_directory
import os

app = Flask(__name__, static_folder="assets")


# Home Page
@app.route("/")
def home():
    return send_from_directory(".", "index.html")


# Serve everything inside assets folder
@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory("assets", filename)


# Health Check
@app.route("/health")
def health():
    return {
        "status": "online",
        "project": "AVIRA",
        "message": "Server Running Successfully"
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=True
    )