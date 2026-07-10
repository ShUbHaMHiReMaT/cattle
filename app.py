import os
from flask import Flask, send_from_directory, request, jsonify
from dotenv import load_dotenv

# Load .env (local dev only - ignored on production servers)
load_dotenv()

app = Flask(__name__, static_folder="assets")

# ---------------------------------------------------------------------------
# Database (Aiven MySQL)
# Set DATABASE_URL in your Render / Railway / Heroku environment variables.
# Format: mysql+pymysql://avnadmin:PASSWORD@HOST:PORT/defaultdb
# ---------------------------------------------------------------------------
_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Lazy engine -- created on first DB request so the app always boots cleanly
_engine = None


def get_engine():
    """Return a SQLAlchemy engine, lazily created on first call."""
    global _engine
    if _engine is not None:
        return _engine
    if not _DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. "
            "Add it in your platform's environment variables dashboard."
        )
    from sqlalchemy import create_engine

    # Keep the URL clean -- strip any existing SSL/charset params we will add
    base_url = _DATABASE_URL.split("?")[0]
    url = base_url + "?charset=utf8mb4"

    # PyMySQL SSL: pass via connect_args, NOT URL query params.
    # An empty dict tells PyMySQL to enable TLS without certificate verification.
    _engine = create_engine(
        url,
        pool_pre_ping=True,      # auto-reconnect on stale connections
        pool_recycle=300,        # recycle connections every 5 min (Aiven idle timeout)
        connect_args={"ssl": {}},  # enable TLS (required by Aiven)
    )
    return _engine


def init_db():
    """Create the contact_submissions table if it does not exist."""
    from sqlalchemy import text
    with get_engine().connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS contact_submissions (
                id         INT AUTO_INCREMENT PRIMARY KEY,
                name       VARCHAR(150)  NOT NULL,
                email      VARCHAR(200)  NOT NULL,
                phone      VARCHAR(20),
                interest   VARCHAR(100),
                message    TEXT          NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """))
        conn.commit()


# Routes -------------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory("assets", filename)


@app.route("/health")
def health():
    return jsonify({
        "status":  "online",
        "project": "AVIRA",
        "message": "Server is running",
        "db_url_set": bool(_DATABASE_URL),
    })


@app.route("/db-status")
def db_status():
    """Live database connectivity check -- visit in browser to diagnose."""
    from sqlalchemy import text
    if not _DATABASE_URL:
        return jsonify({
            "db": "error",
            "reason": "DATABASE_URL environment variable is not set on this server.",
            "fix": "Add DATABASE_URL in your Render > Environment settings."
        }), 500
    try:
        with get_engine().connect() as conn:
            ver = conn.execute(text("SELECT VERSION()")).scalar()
            conn.execute(text("SELECT COUNT(*) FROM contact_submissions"))
        return jsonify({
            "db": "connected",
            "mysql_version": ver,
            "host": _DATABASE_URL.split("@")[-1].split("/")[0],
        })
    except Exception as e:
        return jsonify({"db": "error", "detail": str(e)}), 500


@app.route("/contact", methods=["POST"])
def contact():
    from sqlalchemy import text
    data     = request.get_json(silent=True) or request.form
    name     = (data.get("name",     "") or "").strip()
    email    = (data.get("email",    "") or "").strip()
    phone    = (data.get("phone",    "") or "").strip()
    interest = (data.get("interest", "") or "").strip()
    message  = (data.get("message",  "") or "").strip()

    if not name or not email or not message:
        return jsonify({"error": "name, email, and message are required"}), 400

    try:
        # Ensure table exists (idempotent)
        init_db()
        with get_engine().connect() as conn:
            conn.execute(text("""
                INSERT INTO contact_submissions
                    (name, email, phone, interest, message)
                VALUES
                    (:name, :email, :phone, :interest, :message)
            """), {"name": name, "email": email, "phone": phone,
                   "interest": interest, "message": message})
            conn.commit()
        return jsonify({"success": True, "message": "Submission saved."})
    except RuntimeError as e:
        # DATABASE_URL not configured on this server
        return jsonify({"error": "Server configuration error", "detail": str(e)}), 503
    except Exception as e:
        return jsonify({"error": "Database error", "detail": str(e)}), 500


# Entry point ---------------------------------------------------------------
if __name__ == "__main__":
    if _DATABASE_URL:
        try:
            init_db()
            print("[DB] Connected to Aiven MySQL and table ensured.")
        except Exception as e:
            print(f"[DB] Warning - could not initialise database: {e}")
    else:
        print("[DB] Warning - DATABASE_URL not set, running without database.")
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
