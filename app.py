import os
from flask import Flask, send_from_directory, request, jsonify, Response, redirect, url_for
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder="assets")

_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
_ADMIN_SECRET = os.getenv("ADMIN_SECRET", "avira-admin-2025")
_engine = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    if not _DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    from sqlalchemy import create_engine
    base_url = _DATABASE_URL.split("?")[0]
    url = base_url + "?charset=utf8mb4"
    _engine = create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args={"ssl": {}},
    )
    return _engine


def init_db():
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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


@app.route("/assets/<path:filename>")
def assets(filename):
    return send_from_directory("assets", filename)


@app.route("/health")
def health():
    return jsonify({"status": "online", "project": "AVIRA", "db_url_set": bool(_DATABASE_URL)})


@app.route("/db-status")
def db_status():
    from sqlalchemy import text
    if not _DATABASE_URL:
        return jsonify({"db": "error", "reason": "DATABASE_URL not set on this server."}), 500
    try:
        with get_engine().connect() as conn:
            ver = conn.execute(text("SELECT VERSION()")).scalar()
        return jsonify({"db": "connected", "mysql_version": ver,
                        "host": _DATABASE_URL.split("@")[-1].split("/")[0]})
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
        init_db()
        with get_engine().connect() as conn:
            conn.execute(text("""
                INSERT INTO contact_submissions (name, email, phone, interest, message)
                VALUES (:name, :email, :phone, :interest, :message)
            """), {"name": name, "email": email, "phone": phone,
                   "interest": interest, "message": message})
            conn.commit()
        return jsonify({"success": True, "message": "Submission saved."})
    except RuntimeError as e:
        return jsonify({"error": "Server configuration error", "detail": str(e)}), 503
    except Exception as e:
        return jsonify({"error": "Database error", "detail": str(e)}), 500


# ---------------------------------------------------------------------------
# Admin – delete a single submission
# ---------------------------------------------------------------------------
@app.route("/admin/delete/<int:row_id>", methods=["POST"])
def admin_delete(row_id):
    from sqlalchemy import text
    key = request.form.get("key", "")
    if key != _ADMIN_SECRET:
        return Response("401 Unauthorized.", status=401, mimetype="text/plain")
    try:
        with get_engine().connect() as conn:
            conn.execute(text("DELETE FROM contact_submissions WHERE id = :id"), {"id": row_id})
            conn.commit()
    except Exception as e:
        return Response(f"DB error: {e}", status=500, mimetype="text/plain")
    return redirect(f"/admin?key={key}&deleted={row_id}")


# ---------------------------------------------------------------------------
# Admin dashboard – view all submissions
# ---------------------------------------------------------------------------
@app.route("/admin")
def admin():
    from sqlalchemy import text

    key = request.args.get("key", "")
    if key != _ADMIN_SECRET:
        return Response(
            "401 Unauthorized. Append ?key=YOUR_ADMIN_SECRET to the URL.",
            status=401, mimetype="text/plain"
        )

    deleted_id = request.args.get("deleted", "")

    try:
        with get_engine().connect() as conn:
            rows = conn.execute(text(
                "SELECT id, name, email, phone, interest, message, created_at "
                "FROM contact_submissions ORDER BY created_at DESC"
            )).fetchall()
        error_msg = None
    except Exception as e:
        rows = []
        error_msg = str(e)

    # Build rows HTML
    if rows:
        tbody = ""
        for r in rows:
            msg_e = str(r[5]).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            tbody += f"""
            <tr id="row-{r[0]}">
              <td class="id-col">{r[0]}</td>
              <td><strong>{r[1]}</strong></td>
              <td><a href="mailto:{r[2]}">{r[2]}</a></td>
              <td>{r[3] or "-"}</td>
              <td><span class="badge">{r[4] or "-"}</span></td>
              <td class="msg">{msg_e}</td>
              <td class="date">{r[6]}</td>
              <td>
                <form method="POST" action="/admin/delete/{r[0]}"
                      onsubmit="return confirm('Delete submission from {r[1]}?')">
                  <input type="hidden" name="key" value="{key}" />
                  <button type="submit" class="del-btn" title="Delete">
                    &#128465; Delete
                  </button>
                </form>
              </td>
            </tr>"""
        table_html = f"""
        <div class="count">Showing <strong>{len(rows)}</strong> submission(s)</div>
        <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th><th>Name</th><th>Email</th><th>Phone</th>
              <th>Interest</th><th>Message</th><th>Date (UTC)</th><th>Action</th>
            </tr>
          </thead>
          <tbody>{tbody}</tbody>
        </table>
        </div>"""
    elif error_msg:
        table_html = f'<div class="empty error">DB Error: {error_msg}</div>'
    else:
        table_html = '<div class="empty">No submissions yet.</div>'

    toast = ""
    if deleted_id:
        toast = f'<div class="toast" id="toast">Submission #{deleted_id} deleted successfully.</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>AVIRA Admin – Contact Submissions</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet"/>
  <style>
    :root {{
      --primary: #1A5276; --green: #27AE60; --gold: #F39C12; --red: #E74C3C;
      --bg: #F0F4F8; --white: #fff; --text: #2C3E50; --muted: #7F8C8D;
      --border: #D5DCE4; --radius: 12px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); }}
    .header {{
      background: linear-gradient(135deg, var(--primary), #2471A3);
      padding: 24px 40px; display: flex; align-items: center; gap: 16px;
      box-shadow: 0 4px 16px rgba(0,0,0,.15);
    }}
    .header h1 {{ color: #fff; font-size: 1.4rem; font-weight: 700; }}
    .logo {{ width: 40px; height: 40px; border-radius: 10px;
      background: linear-gradient(135deg, var(--green), #52BE80);
      display: flex; align-items: center; justify-content: center;
      font-size: 1.1rem; color: #fff; flex-shrink: 0; }}
    .sub {{ color: rgba(255,255,255,.7); font-size: .85rem; margin-top: 2px; }}
    .refresh {{ margin-left: auto; background: rgba(255,255,255,.15);
      border: 1px solid rgba(255,255,255,.3); color: #fff; padding: 8px 18px;
      border-radius: 8px; font-size: .85rem; font-weight: 600; cursor: pointer;
      text-decoration: none; transition: background .2s; }}
    .refresh:hover {{ background: rgba(255,255,255,.25); }}
    .main {{ padding: 32px 40px; max-width: 1500px; margin: 0 auto; }}
    .count {{ margin-bottom: 16px; font-size: .9rem; color: var(--muted); }}
    .count strong {{ color: var(--text); }}
    .table-wrap {{ overflow-x: auto; border-radius: var(--radius); box-shadow: 0 2px 16px rgba(0,0,0,.08); }}
    table {{ width: 100%; border-collapse: collapse; background: var(--white); font-size: .875rem; }}
    thead tr {{ background: var(--primary); }}
    thead th {{ color: #fff; padding: 14px 16px; text-align: left; font-weight: 600;
      font-size: .78rem; letter-spacing: .06em; text-transform: uppercase; white-space: nowrap; }}
    tbody tr {{ border-bottom: 1px solid var(--border); transition: background .15s; }}
    tbody tr:last-child {{ border-bottom: none; }}
    tbody tr:hover {{ background: #F7FAFF; }}
    td {{ padding: 12px 16px; vertical-align: top; }}
    td a {{ color: var(--primary); }}
    .id-col {{ color: var(--muted); font-size: .8rem; width: 40px; }}
    .badge {{ display: inline-block; padding: 3px 10px; border-radius: 50px;
      background: rgba(26,82,118,.1); color: var(--primary);
      font-size: .75rem; font-weight: 600; white-space: nowrap; }}
    .msg {{ max-width: 280px; color: var(--muted); line-height: 1.5; }}
    .date {{ white-space: nowrap; color: var(--muted); font-size: .8rem; }}
    /* Delete button */
    .del-btn {{
      display: inline-flex; align-items: center; gap: 5px;
      background: rgba(231,76,60,.08); border: 1px solid rgba(231,76,60,.3);
      color: var(--red); padding: 6px 12px; border-radius: 8px;
      font-size: .78rem; font-weight: 600; cursor: pointer;
      transition: all .2s; white-space: nowrap;
    }}
    .del-btn:hover {{ background: var(--red); color: #fff; border-color: var(--red); transform: translateY(-1px); box-shadow: 0 4px 12px rgba(231,76,60,.3); }}
    /* Toast notification */
    .toast {{
      position: fixed; bottom: 28px; right: 28px;
      background: var(--green); color: #fff;
      padding: 14px 22px; border-radius: 12px;
      font-size: .9rem; font-weight: 600;
      box-shadow: 0 8px 24px rgba(39,174,96,.35);
      animation: slideUp .3s ease; z-index: 999;
    }}
    @keyframes slideUp {{ from {{ opacity:0; transform:translateY(16px); }} to {{ opacity:1; transform:translateY(0); }} }}
    .empty {{ background: var(--white); border-radius: var(--radius); padding: 48px;
      text-align: center; color: var(--muted); font-size: 1rem;
      box-shadow: 0 2px 12px rgba(0,0,0,.07); }}
    .empty.error {{ color: var(--red); background: #FEF9F9; }}
    @media(max-width:768px) {{ .main {{ padding: 20px; }} .header {{ padding: 16px 20px; }} }}
  </style>
</head>
<body>
  <div class="header">
    <div class="logo">&#128278;</div>
    <div>
      <h1>AVIRA Admin</h1>
      <div class="sub">Contact Form Submissions</div>
    </div>
    <a class="refresh" href="/admin?key={key}">&#8635; Refresh</a>
  </div>
  <div class="main">
    {table_html}
  </div>
  {toast}
  <script>
    // Auto-hide toast after 3 seconds
    const t = document.getElementById('toast');
    if (t) setTimeout(() => t.style.display = 'none', 3000);
  </script>
</body>
</html>"""
    return html


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
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
