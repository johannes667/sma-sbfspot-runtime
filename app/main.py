from flask import Flask, jsonify

from config import VERSION, WEB_PORT
from storage import history, read_state

app = Flask(__name__, static_folder="/web/static", static_url_path="")


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/live")
@app.route("/api/state")
def api_state():
    state = read_state()
    state.setdefault("version", VERSION)
    return jsonify(state)


@app.route("/api/history")
def api_history():
    return jsonify(history())


@app.route("/api/status")
def api_status():
    s = read_state()
    return jsonify({
        "status": s.get("status"),
        "timestamp": s.get("timestamp"),
        "version": s.get("version", VERSION),
        "last_error": s.get("last_error", ""),
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=WEB_PORT)
