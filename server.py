from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import secrets
import string
import os

app = Flask(__name__)

# Database (SQLite)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///keys.db'  # railway persistent storage recommended
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# -------------------- DATABASE MODEL --------------------
class Key(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    duration_type = db.Column(db.String(20), default="6h")  # 6h / 1m / 3m / lifetime
    expires_at = db.Column(db.DateTime, nullable=True)      # None = lifetime
    hwid = db.Column(db.String(200), nullable=True)         # stored on first validation


# -------------------- HELPERS --------------------
def generate_key(length=30):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


@app.before_first_request
def create_tables():
    db.create_all()


# -------------------- ROUTES --------------------

@app.route("/")
def home():
    return jsonify({"message": "Key server running ✓"})


# -------- CREATE KEY --------
# example:
# /add_key?duration=6h
# /add_key?duration=1m
# /add_key?duration=3m
# /add_key?duration=lifetime
@app.route("/add_key", methods=["GET", "POST"])
def add_key():
    duration = request.args.get("duration", "6h")
    
    # If POST JSON contains key use it, otherwise generate one
    if request.method == "POST":
        key_value = request.json.get("key")
    else:
        key_value = None

    if not key_value:
        key_value = generate_key()

    # make sure key is unique
    while Key.query.filter_by(key=key_value).first():
        key_value = generate_key()

    # durations
    if duration == "6h":
        expires_at = datetime.utcnow() + timedelta(hours=6)
    elif duration == "1m":
        expires_at = datetime.utcnow() + timedelta(days=30)
    elif duration == "3m":
        expires_at = datetime.utcnow() + timedelta(days=90)
    elif duration == "lifetime":
        expires_at = None
    else:
        return jsonify({"ok": False, "error": "Invalid duration type"}), 400

    new_key = Key(key=key_value, duration_type=duration, expires_at=expires_at)
    db.session.add(new_key)
    db.session.commit()

    return jsonify({
        "ok": True,
        "key": key_value,
        "type": duration,
        "expires_at": expires_at.isoformat() if expires_at else "never"
    })


# -------- CHECK KEY + HWID BINDING --------
@app.route("/check_key")
def check_key():
    key_value = request.args.get("key")
    hwid = request.args.get("hwid")

    if not key_value:
        return jsonify({"ok": False, "error": "Key missing"})

    key_entry = Key.query.filter_by(key=key_value).first()
    if not key_entry:
        return jsonify({"ok": False, "error": "Invalid key"})

    # expiration
    if key_entry.expires_at and datetime.utcnow() > key_entry.expires_at:
        db.session.delete(key_entry)
        db.session.commit()
        return jsonify({"ok": False, "expired": True})

    # HWID binding
    if key_entry.hwid is None:
        if not hwid:
            return jsonify({"ok": False, "error": "HWID required for first activation"})
        key_entry.hwid = hwid
        db.session.commit()
        return jsonify({"ok": True, "status": "HWID linked", "type": key_entry.duration_type})

    if hwid != key_entry.hwid:
        return jsonify({"ok": False, "error": "HWID mismatch"})

    return jsonify({"ok": True, "status": "valid", "type": key_entry.duration_type})


# -------------------- RUN SERVER --------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Running server on port {port}")
    app.run(host="0.0.0.0", port=port, debug=True)
