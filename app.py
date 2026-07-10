import os
from flask import Flask, send_from_directory, request, jsonify
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

# Load .env
load_dotenv()

app = Flask(__name__, static_folder="assets")

# Database (Aiven MySQL)
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Copy .env.example to .env and fill in your Aiven password."
    )

# Append charset if not already present
if "charset" not in DATABASE_URL:
    DATABASE_URL += "?charset=utf8mb4"

# Aiven MySQL requires SSL; PyMySQL accepts ssl dict with empty value to
# enable TLS without needing the CA certificate bundle downloaded locally.
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,    # auto-reconnect on stale connections
    pool_recycle=300,      # recycle connections every 5 min
    connect_args={
        "ssl": {},         # empty dict = enable SSL, no cert verification
    },
)

# Create contact_submissions table if it doesn't exist
def init_db():
    with engine.connect() as conn:
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

try:
    init_db()
    print("[DB] Connected to Aiven MySQL and table ensured.")
except Exception as e:
    print(f"[DB] Warning – could not initialise database: {e}")


# ── Routes ────────────────────────────────────────────────────────────────────

# Home Page
@app.route("/")
def home():
    return send_from_directory(".", "index.html")


# Serve everything inside assets/ folder
@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory("assets", filename)


# Health Check
@app.route("/health")
def health():
    return jsonify({
        "status":  "online",
        "project": "AVIRA",
        "message": "Server Running Successfully"
    })


# Database Status Check
@app.route("/db-status")
def db_status():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return jsonify({"db": "connected", "host": os.getenv("DB_HOST", "unknown")})
    except OperationalError as e:
        return jsonify({"db": "error", "detail": str(e)}), 500


# Contact Form Submission – saves to MySQL
@app.route("/contact", methods=["POST"])
def contact():
    data = request.get_json(silent=True) or request.form
    name     = (data.get("name",     "") or "").strip()
    email    = (data.get("email",    "") or "").strip()
    phone    = (data.get("phone",    "") or "").strip()
    interest = (data.get("interest", "") or "").strip()
    message  = (data.get("message",  "") or "").strip()

    if not name or not email or not message:
        return jsonify({"error": "name, email, and message are required"}), 400

    try:
        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO contact_submissions
                    (name, email, phone, interest, message)
                VALUES
                    (:name, :email, :phone, :interest, :message)
            """), {"name": name, "email": email, "phone": phone,
                   "interest": interest, "message": message})
            conn.commit()
        return jsonify({"success": True, "message": "Submission saved."})
    except Exception as e:
        return jsonify({"error": "Database error", "detail": str(e)}), 500


# ── Entry Point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)