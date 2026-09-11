import os
import io
import base64
import csv

import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, login_required,
    logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from pdf2image import convert_from_bytes
import pytesseract

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-this-secret-key")
def _normalize_db_url(url):
    if not url:
        return "sqlite:///app.db"
    # Some providers use postgres:// which SQLAlchemy no longer accepts
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # channel_binding isn't always supported by the bundled psycopg2 libpq;
    # sslmode=require is enough for a secure connection to Neon.
    url = url.replace("&channel_binding=require", "").replace("?channel_binding=require", "?")
    return url


app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(os.environ.get("DATABASE_URL"))
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB max upload

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class WordEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    word = db.Column(db.String(255), nullable=False)
    meaning = db.Column(db.Text)          # Arabic translation
    synonym = db.Column(db.Text)          # synonym(s), comma separated
    language = db.Column(db.String(20))   # detected source language of the word


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ---------------------------------------------------------------------------
# Helpers: OCR, translation, synonyms
# ---------------------------------------------------------------------------
def ocr_pdf_bytes(pdf_bytes, lang="ara+eng"):
    """Convert PDF bytes to images (in-memory, no manual pdftoppm step needed)
    and run Tesseract OCR on every page. Returns list of page texts."""
    images = convert_from_bytes(pdf_bytes, dpi=300)
    pages_text = []
    for img in images:
        text = pytesseract.image_to_string(img, lang=lang)
        pages_text.append(text.strip())
    return pages_text


def detect_language(word):
    """Very simple heuristic: Arabic unicode range vs. anything else -> English."""
    for ch in word:
        if "\u0600" <= ch <= "\u06FF":
            return "ar"
    return "en"


def translate_to_arabic(word, source_lang="en"):
    """Free translation via MyMemory API (no key required, rate-limited)."""
    if source_lang == "ar":
        return word  # already Arabic
    try:
        resp = requests.get(
            "https://api.mymemory.translated.net/get",
            params={"q": word, "langpair": f"{source_lang}|ar"},
            timeout=10,
        )
        data = resp.json()
        return data["responseData"]["translatedText"]
    except Exception:
        return ""


def get_synonyms(word, source_lang="en"):
    """Free synonyms via Datamuse API (English only)."""
    if source_lang != "en":
        return ""
    try:
        resp = requests.get(
            "https://api.datamuse.com/words",
            params={"rel_syn": word, "max": 5},
            timeout=10,
        )
        data = resp.json()
        return ", ".join(item["word"] for item in data)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("من فضلك ادخل اسم مستخدم وباسورد")
            return redirect(url_for("register"))
        if User.query.filter_by(username=username).first():
            flash("اسم المستخدم مستخدم قبل كده")
            return redirect(url_for("register"))
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        flash("تم التسجيل بنجاح، سجل دخولك الآن")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))
        flash("بيانات الدخول غلط")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------
@app.route("/")
@login_required
def index():
    entries = WordEntry.query.filter_by(user_id=current_user.id).order_by(WordEntry.id.desc()).all()
    return render_template("index.html", entries=entries)


# ---------------------------------------------------------------------------
# PDF OCR endpoint
# Accepts EITHER a multipart file upload (field name "file")
# OR a JSON body: {"pdf_base64": "..."}
# Returns: {"pages": ["text of page 1", "text of page 2", ...]}
# ---------------------------------------------------------------------------
@app.route("/api/ocr", methods=["POST"])
@login_required
def api_ocr():
    pdf_bytes = None

    if "file" in request.files:
        pdf_bytes = request.files["file"].read()
    else:
        data = request.get_json(silent=True) or {}
        b64 = data.get("pdf_base64")
        if b64:
            try:
                pdf_bytes = base64.b64decode(b64)
            except Exception:
                return jsonify({"error": "base64 غير صالح"}), 400

    if not pdf_bytes:
        return jsonify({"error": "لم يتم استلام ملف PDF (file أو pdf_base64)"}), 400

    lang = request.args.get("lang", "ara+eng")
    try:
        pages = ocr_pdf_bytes(pdf_bytes, lang=lang)
    except Exception as e:
        return jsonify({"error": f"فشل تحليل الملف: {e}"}), 500

    return jsonify({"pages": pages, "page_count": len(pages)})


# ---------------------------------------------------------------------------
# Dataset endpoints: word -> meaning / synonym / language
# ---------------------------------------------------------------------------
@app.route("/api/words", methods=["POST"])
@login_required
def add_word():
    data = request.get_json(silent=True) or request.form
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "الكلمة مطلوبة"}), 400

    lang = detect_language(word)
    meaning = translate_to_arabic(word, source_lang=lang)
    synonym = get_synonyms(word, source_lang=lang)

    entry = WordEntry(
        user_id=current_user.id,
        word=word,
        meaning=meaning,
        synonym=synonym,
        language=lang,
    )
    db.session.add(entry)
    db.session.commit()

    return jsonify({
        "id": entry.id,
        "word": entry.word,
        "meaning": entry.meaning,
        "synonym": entry.synonym,
        "language": entry.language,
    })


@app.route("/api/words", methods=["GET"])
@login_required
def list_words():
    entries = WordEntry.query.filter_by(user_id=current_user.id).order_by(WordEntry.id.desc()).all()
    return jsonify([{
        "id": e.id, "word": e.word, "meaning": e.meaning,
        "synonym": e.synonym, "language": e.language,
    } for e in entries])


@app.route("/api/words/<int:word_id>", methods=["DELETE"])
@login_required
def delete_word(word_id):
    entry = WordEntry.query.filter_by(id=word_id, user_id=current_user.id).first()
    if not entry:
        return jsonify({"error": "غير موجود"}), 404
    db.session.delete(entry)
    db.session.commit()
    return jsonify({"deleted": word_id})


@app.route("/api/words/export")
@login_required
def export_words():
    entries = WordEntry.query.filter_by(user_id=current_user.id).order_by(WordEntry.id.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Word", "Meaning", "Synonym", "Language"])
    for e in entries:
        writer.writerow([e.word, e.meaning, e.synonym, e.language])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=dataset.csv"},
    )


# ---------------------------------------------------------------------------
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
