"""Flask Media Platform main application.

This file contains fixed configuration, database access, routes, uploads,
search, and startup logic.
"""
import hashlib
import os
import secrets
import shutil
import sqlite3
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

# ----- Fixed application configuration -----
BASE_DIRECTORY = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIRECTORY / "app.db"
UPLOAD_DIRECTORY = BASE_DIRECTORY / "uploads"
CHUNK_DIRECTORY = BASE_DIRECTORY / "upload_chunks"
ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
ALLOWED_VIDEO_EXTENSIONS = {"mp4", "webm", "ogg", "mov", "m4v"}
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
MAX_FILE_SIZE = 8 * 1024 * 1024 * 1024
MAX_REQUEST_SIZE = 20 * 1024 * 1024
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000
DEBUG_ENABLED = False
APPLICATION_SECRET_KEY = "flask-media-platform-fixed-secret-key-2026"

app = Flask(__name__, static_folder=None)
app.config.update(
    SECRET_KEY=APPLICATION_SECRET_KEY,
    MAX_CONTENT_LENGTH=MAX_REQUEST_SIZE,
    UPLOAD_FOLDER=str(UPLOAD_DIRECTORY),
)
UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
CHUNK_DIRECTORY.mkdir(parents=True, exist_ok=True)

# ----- Database access and initialization -----
def get_database():
    if "database" in g:
        return g.database
    database_connection = sqlite3.connect(DATABASE_PATH, timeout=30)
    database_connection.row_factory = sqlite3.Row
    database_connection.execute("PRAGMA foreign_keys = ON")
    g.database = database_connection
    return database_connection

@app.teardown_appcontext
def close_database(_exception=None):
    database_connection = g.pop("database", None)
    if database_connection is not None:
        database_connection.close()

def initialize_database():
    database_connection = get_database()
    database_connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS albums (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            is_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id INTEGER NOT NULL,
            original_name TEXT NOT NULL,
            stored_name TEXT NOT NULL UNIQUE,
            media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
            file_hash TEXT,
            file_size INTEGER,
            uploaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS upload_sessions (
            id TEXT PRIMARY KEY,
            album_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            client_key TEXT NOT NULL,
            original_name TEXT NOT NULL,
            media_type TEXT NOT NULL CHECK(media_type IN ('image', 'video')),
            total_size INTEGER NOT NULL,
            chunk_size INTEGER NOT NULL,
            total_chunks INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (album_id) REFERENCES albums(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_albums_user_id ON albums(user_id);
        CREATE INDEX IF NOT EXISTS idx_albums_visibility ON albums(is_hidden, created_at);
        CREATE INDEX IF NOT EXISTS idx_media_album_id ON media(album_id);
        CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        CREATE INDEX IF NOT EXISTS idx_upload_sessions_lookup
        ON upload_sessions(user_id, album_id, client_key, status);
        """
    )
    # Add newer hash columns when an existing database uses an older schema.
    media_columns = {
        column_record["name"]
        for column_record in database_connection.execute("PRAGMA table_info(media)").fetchall()
    }
    if "file_hash" not in media_columns:
        database_connection.execute("ALTER TABLE media ADD COLUMN file_hash TEXT")
    if "file_size" not in media_columns:
        database_connection.execute("ALTER TABLE media ADD COLUMN file_size INTEGER")
    database_connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_album_hash ON media(album_id, file_size, file_hash)"
    )
    database_connection.commit()

# ----- Request lifecycle and security -----
@app.before_request
def load_current_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
        return
    g.user = get_database().execute(
        "SELECT id, username, display_name, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()

@app.context_processor
def inject_template_values():
    session.setdefault("csrf_token", secrets.token_hex(24))
    return {"csrf_token": session["csrf_token"], "max_file_bytes": MAX_FILE_SIZE}

@app.before_request
def verify_csrf_token():
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    csrf_token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    if not csrf_token or csrf_token != session.get("csrf_token"):
        abort(400, description="CSRF token invalid")

def login_required(view_function):
    @wraps(view_function)
    def protected_view(**view_arguments):
        if g.user is not None:
            return view_function(**view_arguments)
        flash("请先登录。", "warning")
        return redirect(url_for("login", next=request.path))

    return protected_view

def wants_json_response():
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.accept_mimetypes.best == "application/json"
    )

def json_error(message, status_code):
    return jsonify(ok=False, error=message), status_code

# ----- Album and media helper functions -----
def get_album_or_404(album_id):
    album_record = get_database().execute(
        """
        SELECT albums.*, users.username, users.display_name
        FROM albums
        JOIN users ON users.id = albums.user_id
        WHERE albums.id = ?
        """,
        (album_id,),
    ).fetchone()
    if album_record is None:
        abort(404)
    return album_record

def require_album_owner(album_record):
    if g.user is not None and album_record["user_id"] == g.user["id"]:
        return
    abort(403)

def can_view_album(album_record):
    if not album_record["is_hidden"]:
        return True
    return g.user is not None and album_record["user_id"] == g.user["id"]

def normalize_filename(filename):
    clean_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    clean_name = "".join(
        character
        for character in clean_name
        if ord(character) >= 32 and character not in {"/", "\\"}
    )
    if len(clean_name) <= 240:
        return clean_name
    filename_stem, filename_extension = os.path.splitext(clean_name)
    maximum_stem_length = max(1, 240 - len(filename_extension))
    return f"{filename_stem[:maximum_stem_length]}{filename_extension}"

def classify_media(filename):
    if "." not in filename:
        return None
    extension = filename.rsplit(".", 1)[1].lower()
    if extension in ALLOWED_IMAGE_EXTENSIONS:
        return "image"
    if extension in ALLOWED_VIDEO_EXTENSIONS:
        return "video"
    return None

def create_unique_media_name(database_connection, album_id, requested_name):
    existing_names = {
        record["original_name"].casefold()
        for record in database_connection.execute(
            "SELECT original_name FROM media WHERE album_id = ?", (album_id,)
        ).fetchall()
    }
    if requested_name.casefold() not in existing_names:
        return requested_name
    filename_stem, filename_extension = os.path.splitext(requested_name)
    suffix_number = 2
    while True:
        suffix_text = f" ({suffix_number})"
        maximum_stem_length = max(1, 240 - len(filename_extension) - len(suffix_text))
        candidate_name = f"{filename_stem[:maximum_stem_length]}{suffix_text}{filename_extension}"
        if candidate_name.casefold() not in existing_names:
            return candidate_name
        suffix_number += 1

def delete_stored_media(stored_name):
    media_path = UPLOAD_DIRECTORY / stored_name
    if media_path.is_file():
        media_path.unlink()

def calculate_file_hash(file_path):
    hash_calculator = hashlib.sha256()
    with file_path.open("rb") as input_stream:
        while True:
            file_block = input_stream.read(4 * 1024 * 1024)
            if not file_block:
                break
            hash_calculator.update(file_block)
    return hash_calculator.hexdigest()

def scan_album_for_duplicate_media(database_connection, album_id):
    media_records = database_connection.execute(
        "SELECT id, original_name, stored_name FROM media WHERE album_id = ? ORDER BY id",
        (album_id,),
    ).fetchall()
    # The first file with a given size and SHA-256 value is retained.
    retained_files = {}
    hash_updates = []
    duplicate_records = []
    for media_record in media_records:
        media_path = UPLOAD_DIRECTORY / media_record["stored_name"]
        if not media_path.is_file():
            continue
        try:
            file_size = media_path.stat().st_size
            file_hash = calculate_file_hash(media_path)
        except OSError:
            app.logger.exception("Failed to hash media file: %s", media_path)
            continue
        hash_updates.append((file_hash, file_size, media_record["id"]))
        duplicate_key = (file_size, file_hash)
        if duplicate_key in retained_files:
            duplicate_records.append(media_record)
            continue
        retained_files[duplicate_key] = media_record["id"]
    # Update hashes and remove duplicate database rows in one write transaction.
    database_connection.execute("BEGIN IMMEDIATE")
    database_connection.executemany(
        "UPDATE media SET file_hash = ?, file_size = ? WHERE id = ?",
        hash_updates,
    )
    if duplicate_records:
        database_connection.executemany(
            "DELETE FROM media WHERE id = ?",
            [(media_record["id"],) for media_record in duplicate_records],
        )
    database_connection.commit()
    for duplicate_record in duplicate_records:
        try:
            delete_stored_media(duplicate_record["stored_name"])
        except OSError:
            app.logger.exception(
                "Failed to delete duplicate media file: %s",
                duplicate_record["stored_name"],
            )
    return {
        "removed_ids": {media_record["id"] for media_record in duplicate_records},
        "removed_names": [media_record["original_name"] for media_record in duplicate_records],
    }

# ----- Chunked-upload helper functions -----
def get_upload_directory(upload_id):
    return CHUNK_DIRECTORY / upload_id

def get_chunk_path(upload_id, chunk_index):
    return get_upload_directory(upload_id) / f"{chunk_index:08d}.part"

def calculate_expected_chunk_size(upload_session, chunk_index):
    chunk_start = chunk_index * upload_session["chunk_size"]
    return min(upload_session["chunk_size"], upload_session["total_size"] - chunk_start)

def get_received_chunk_indexes(upload_session):
    upload_directory = get_upload_directory(upload_session["id"])
    if not upload_directory.exists():
        return []
    received_indexes = []
    for chunk_index in range(upload_session["total_chunks"]):
        current_chunk_path = get_chunk_path(upload_session["id"], chunk_index)
        expected_size = calculate_expected_chunk_size(upload_session, chunk_index)
        if current_chunk_path.is_file() and current_chunk_path.stat().st_size == expected_size:
            received_indexes.append(chunk_index)
    return received_indexes

def remove_upload_directory(upload_id):
    shutil.rmtree(get_upload_directory(upload_id), ignore_errors=True)

def remove_stale_uploads(database_connection):
    stale_sessions = database_connection.execute(
        "SELECT id FROM upload_sessions WHERE updated_at < datetime('now', '-2 days')"
    ).fetchall()
    if not stale_sessions:
        return
    database_connection.executemany(
        "DELETE FROM upload_sessions WHERE id = ?",
        [(session_record["id"],) for session_record in stale_sessions],
    )
    database_connection.commit()
    for session_record in stale_sessions:
        remove_upload_directory(session_record["id"])

def get_upload_session_or_404(upload_id):
    upload_session = get_database().execute(
        "SELECT * FROM upload_sessions WHERE id = ?", (upload_id,)
    ).fetchone()
    if upload_session is None:
        abort(404)
    if g.user is None or upload_session["user_id"] != g.user["id"]:
        abort(403)
    return upload_session

def validate_chunk_upload_payload(payload):
    original_filename = normalize_filename(str(payload.get("filename", "")))
    media_type = classify_media(original_filename)
    client_key = str(payload.get("client_key", ""))[:512]
    try:
        total_size = int(payload.get("size", 0))
        requested_chunk_size = int(payload.get("chunk_size", DEFAULT_CHUNK_SIZE))
    except (TypeError, ValueError):
        return None, json_error("文件参数无效。", 400)
    if not original_filename or media_type is None:
        return None, json_error("不支持的文件格式。", 415)
    if not client_key:
        return None, json_error("缺少上传标识。", 400)
    if total_size <= 0:
        return None, json_error("文件为空。", 400)
    if total_size > MAX_FILE_SIZE:
        maximum_gigabytes = MAX_FILE_SIZE // (1024**3)
        return None, json_error(f"单个文件不能超过 {maximum_gigabytes} GB。", 413)
    chunk_size = max(1024 * 1024, min(requested_chunk_size, MAX_CHUNK_SIZE))
    return {
        "original_filename": original_filename,
        "media_type": media_type,
        "client_key": client_key,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "total_chunks": (total_size + chunk_size - 1) // chunk_size,
    }, None

def copy_chunk_to_output(upload_id, chunk_index, output_stream):
    chunk_path = get_chunk_path(upload_id, chunk_index)
    with chunk_path.open("rb") as input_stream:
        shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)

def assemble_chunked_file(upload_session, upload_id, assembled_path):
    with assembled_path.open("wb") as output_stream:
        for chunk_index in range(upload_session["total_chunks"]):
            copy_chunk_to_output(upload_id, chunk_index, output_stream)
    if assembled_path.stat().st_size != upload_session["total_size"]:
        raise OSError("assembled file size mismatch")

def save_completed_upload(
    database_connection, upload_session, upload_id, assembled_path, final_path, stored_name
):
    database_connection.execute("BEGIN IMMEDIATE")
    final_filename = create_unique_media_name(
        database_connection, upload_session["album_id"], upload_session["original_name"]
    )
    insertion_result = database_connection.execute(
        """
        INSERT INTO media (album_id, original_name, stored_name, media_type)
        VALUES (?, ?, ?, ?)
        """,
        (
            upload_session["album_id"],
            final_filename,
            stored_name,
            upload_session["media_type"],
        ),
    )
    os.replace(assembled_path, final_path)
    database_connection.execute("DELETE FROM upload_sessions WHERE id = ?", (upload_id,))
    database_connection.commit()
    return insertion_result.lastrowid

def reactivate_upload_session(database_connection, upload_id):
    database_connection.execute(
        """
        UPDATE upload_sessions
        SET status = 'active', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (upload_id,),
    )
    database_connection.commit()

# ----- Public page routes -----
@app.route("/")
def index():
    album_records = get_database().execute(
        """
        SELECT albums.*, users.username, users.display_name,
               (SELECT COUNT(*) FROM media WHERE media.album_id = albums.id) AS media_count,
               (SELECT media.id FROM media WHERE media.album_id = albums.id
                AND media.media_type = 'image' ORDER BY media.id LIMIT 1) AS cover_image_id
        FROM albums
        JOIN users ON users.id = albums.user_id
        WHERE albums.is_hidden = 0
        ORDER BY albums.created_at DESC
        LIMIT 24
        """
    ).fetchall()
    return render_template("index.html", albums=album_records)

# ----- Authentication routes -----
def validate_registration_form(username, display_name, password, confirmed_password):
    if not username or len(username) < 3 or len(username) > 30:
        return "用户名长度必须为 3 到 30 个字符。"
    if not username.replace("_", "").isalnum():
        return "用户名只能包含字母、数字和下划线。"
    if not display_name or len(display_name) > 50:
        return "显示名称不能为空，且不能超过 50 个字符。"
    if not password:
        return "密码不能为空。"
    if password != confirmed_password:
        return "两次输入的密码不一致。"
    return None

@app.route("/register", methods=("GET", "POST"))
def register():
    if g.user is not None:
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("register.html")
    username = request.form.get("username", "").strip()
    display_name = request.form.get("display_name", "").strip()
    password = request.form.get("password", "")
    confirmed_password = request.form.get("confirm_password", "")
    validation_error = validate_registration_form(
        username, display_name, password, confirmed_password
    )
    if validation_error:
        flash(validation_error, "danger")
        return render_template("register.html")
    database_connection = get_database()
    try:
        database_connection.execute(
            "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
            (username, display_name, generate_password_hash(password)),
        )
        database_connection.commit()
    except sqlite3.IntegrityError:
        flash("该用户名已经存在。", "danger")
        return render_template("register.html")
    flash("注册成功，请登录。", "success")
    return redirect(url_for("login"))

@app.route("/login", methods=("GET", "POST"))
def login():
    if g.user is not None:
        return redirect(url_for("dashboard"))
    if request.method == "GET":
        return render_template("login.html")
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    user_record = get_database().execute(
        "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
    ).fetchone()
    if user_record is None or not check_password_hash(user_record["password_hash"], password):
        flash("用户名或密码错误。", "danger")
        return render_template("login.html")
    session.clear()
    session["user_id"] = user_record["id"]
    session["csrf_token"] = secrets.token_hex(24)
    next_url = request.args.get("next")
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return redirect(next_url)
    return redirect(url_for("dashboard"))

@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("你已退出登录。", "info")
    return redirect(url_for("index"))

@app.route("/change-password", methods=("GET", "POST"))
@login_required
def change_password():
    if request.method == "GET":
        return render_template("change_password.html")
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirmed_password = request.form.get("confirm_password", "")
    user_record = get_database().execute(
        "SELECT * FROM users WHERE id = ?", (g.user["id"],)
    ).fetchone()
    if not check_password_hash(user_record["password_hash"], current_password):
        flash("当前密码不正确。", "danger")
        return render_template("change_password.html")
    if not new_password:
        flash("新密码不能为空。", "danger")
        return render_template("change_password.html")
    if new_password != confirmed_password:
        flash("两次输入的新密码不一致。", "danger")
        return render_template("change_password.html")
    database_connection = get_database()
    database_connection.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?",
        (generate_password_hash(new_password), g.user["id"]),
    )
    database_connection.commit()
    flash("密码已修改。", "success")
    return redirect(url_for("dashboard"))

# ----- Album management routes -----
@app.route("/dashboard")
@login_required
def dashboard():
    album_records = get_database().execute(
        """
        SELECT albums.*,
               (SELECT COUNT(*) FROM media WHERE media.album_id = albums.id) AS media_count,
               (SELECT media.id FROM media WHERE media.album_id = albums.id
                AND media.media_type = 'image' ORDER BY media.id LIMIT 1) AS cover_image_id
        FROM albums
        WHERE user_id = ?
        ORDER BY created_at DESC
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("dashboard.html", albums=album_records)

@app.route("/albums/create", methods=("GET", "POST"))
@login_required
def create_album():
    if request.method == "GET":
        return render_template("album_form.html", album=None)
    album_title = request.form.get("title", "").strip()
    is_hidden = int(request.form.get("is_hidden") == "on")
    if not album_title or len(album_title) > 100:
        flash("专辑名称不能为空，且不能超过 100 个字符。", "danger")
        return render_template("album_form.html", album=None)
    database_connection = get_database()
    insertion_result = database_connection.execute(
        "INSERT INTO albums (user_id, title, description, is_hidden) VALUES (?, ?, '', ?)",
        (g.user["id"], album_title, is_hidden),
    )
    database_connection.commit()
    flash("专辑已创建。", "success")
    return redirect(url_for("album_detail", album_id=insertion_result.lastrowid))

@app.route("/albums/<int:album_id>")
def album_detail(album_id):
    album_record = get_album_or_404(album_id)
    if not can_view_album(album_record):
        abort(404)
    media_records = get_database().execute(
        "SELECT * FROM media WHERE album_id = ? ORDER BY uploaded_at DESC, id DESC",
        (album_id,),
    ).fetchall()
    return render_template("album_detail.html", album=album_record, media_items=media_records)

@app.route("/albums/<int:album_id>/edit", methods=("GET", "POST"))
@login_required
def edit_album(album_id):
    album_record = get_album_or_404(album_id)
    require_album_owner(album_record)
    if request.method == "GET":
        return render_template("album_form.html", album=album_record)
    album_title = request.form.get("title", "").strip()
    is_hidden = int(request.form.get("is_hidden") == "on")
    if not album_title or len(album_title) > 100:
        flash("专辑名称不能为空，且不能超过 100 个字符。", "danger")
        return render_template("album_form.html", album=album_record)
    database_connection = get_database()
    database_connection.execute(
        """
        UPDATE albums
        SET title = ?, description = '', is_hidden = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (album_title, is_hidden, album_id),
    )
    database_connection.commit()
    flash("专辑已更新。", "success")
    return redirect(url_for("album_detail", album_id=album_id))

@app.post("/albums/<int:album_id>/visibility")
@login_required
def change_album_visibility(album_id):
    album_record = get_album_or_404(album_id)
    require_album_owner(album_record)
    request_payload = request.get_json(silent=True) or {}
    requested_visibility = request_payload.get("is_hidden")
    if "is_hidden" in request_payload:
        is_hidden = int(bool(requested_visibility))
    else:
        is_hidden = int(not album_record["is_hidden"])
    database_connection = get_database()
    database_connection.execute(
        "UPDATE albums SET is_hidden = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (is_hidden, album_id),
    )
    database_connection.commit()
    return jsonify(
        ok=True,
        album_id=album_id,
        is_hidden=bool(is_hidden),
        label="设为公开" if is_hidden else "设为隐藏",
        status="隐藏" if is_hidden else "公开",
    )

@app.post("/albums/<int:album_id>/delete")
@login_required
def delete_album(album_id):
    album_record = get_album_or_404(album_id)
    require_album_owner(album_record)
    database_connection = get_database()
    media_records = database_connection.execute(
        "SELECT stored_name FROM media WHERE album_id = ?", (album_id,)
    ).fetchall()
    upload_sessions = database_connection.execute(
        "SELECT id FROM upload_sessions WHERE album_id = ?", (album_id,)
    ).fetchall()
    database_connection.execute("DELETE FROM albums WHERE id = ?", (album_id,))
    database_connection.commit()
    for media_record in media_records:
        delete_stored_media(media_record["stored_name"])
    for upload_session in upload_sessions:
        remove_upload_directory(upload_session["id"])
    if wants_json_response():
        return jsonify(ok=True, album_id=album_id)
    flash("专辑及其中的媒体文件已删除。", "success")
    return redirect(url_for("dashboard"))

# ----- Chunked-upload API routes -----
@app.post("/albums/<int:album_id>/uploads/init")
@login_required
def init_chunked_upload(album_id):
    album_record = get_album_or_404(album_id)
    require_album_owner(album_record)
    upload_data, validation_response = validate_chunk_upload_payload(
        request.get_json(silent=True) or {}
    )
    if validation_response:
        return validation_response
    database_connection = get_database()
    remove_stale_uploads(database_connection)
    # Reuse an active session so selecting the same file can resume uploaded chunks.
    upload_session = database_connection.execute(
        """
        SELECT * FROM upload_sessions
        WHERE user_id = ? AND album_id = ? AND client_key = ?
          AND original_name = ? AND total_size = ? AND status = 'active'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (
            g.user["id"],
            album_id,
            upload_data["client_key"],
            upload_data["original_filename"],
            upload_data["total_size"],
        ),
    ).fetchone()
    if upload_session is None:
        upload_id = uuid.uuid4().hex
        database_connection.execute(
            """
            INSERT INTO upload_sessions
                (id, album_id, user_id, client_key, original_name, media_type,
                 total_size, chunk_size, total_chunks)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                upload_id,
                album_id,
                g.user["id"],
                upload_data["client_key"],
                upload_data["original_filename"],
                upload_data["media_type"],
                upload_data["total_size"],
                upload_data["chunk_size"],
                upload_data["total_chunks"],
            ),
        )
        database_connection.commit()
        upload_session = database_connection.execute(
            "SELECT * FROM upload_sessions WHERE id = ?", (upload_id,)
        ).fetchone()
    get_upload_directory(upload_session["id"]).mkdir(parents=True, exist_ok=True)
    received_indexes = get_received_chunk_indexes(upload_session)
    return jsonify(
        ok=True,
        upload_id=upload_session["id"],
        filename=upload_session["original_name"],
        chunk_size=upload_session["chunk_size"],
        total_chunks=upload_session["total_chunks"],
        received_chunks=received_indexes,
        chunk_url=url_for("upload_chunk", upload_id=upload_session["id"]),
        complete_url=url_for("complete_chunked_upload", upload_id=upload_session["id"]),
    )

@app.put("/uploads/<upload_id>/chunk")
@login_required
def upload_chunk(upload_id):
    upload_session = get_upload_session_or_404(upload_id)
    if upload_session["status"] != "active":
        return json_error("上传任务当前不可写入。", 409)
    try:
        chunk_index = int(request.args.get("index", "-1"))
    except ValueError:
        return json_error("分块编号无效。", 400)
    if chunk_index < 0 or chunk_index >= upload_session["total_chunks"]:
        return json_error("分块编号超出范围。", 400)
    expected_size = calculate_expected_chunk_size(upload_session, chunk_index)
    if request.content_length != expected_size:
        return json_error("分块大小不正确。", 400)
    upload_directory = get_upload_directory(upload_id)
    upload_directory.mkdir(parents=True, exist_ok=True)
    destination_path = get_chunk_path(upload_id, chunk_index)
    # A correctly sized chunk is idempotent and does not need to be written again.
    if destination_path.is_file() and destination_path.stat().st_size == expected_size:
        return jsonify(ok=True, index=chunk_index, already_received=True)
    temporary_path = upload_directory / f".{chunk_index:08d}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary_path.open("wb") as output_stream:
            shutil.copyfileobj(request.stream, output_stream, length=1024 * 1024)
        if temporary_path.stat().st_size != expected_size:
            temporary_path.unlink(missing_ok=True)
            return json_error("分块传输不完整。", 400)
        os.replace(temporary_path, destination_path)
        database_connection = get_database()
        database_connection.execute(
            "UPDATE upload_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (upload_id,),
        )
        database_connection.commit()
    except OSError:
        temporary_path.unlink(missing_ok=True)
        app.logger.exception("Failed to store upload chunk")
        return json_error("分块保存失败。", 500)
    return jsonify(ok=True, index=chunk_index)

@app.post("/uploads/<upload_id>/complete")
@login_required
def complete_chunked_upload(upload_id):
    upload_session = get_upload_session_or_404(upload_id)
    if upload_session["status"] != "active":
        return json_error("上传任务正在完成或已失效。", 409)
    received_indexes = get_received_chunk_indexes(upload_session)
    if len(received_indexes) != upload_session["total_chunks"]:
        return jsonify(
            ok=False,
            error="仍有分块未上传。",
            received_chunks=received_indexes,
        ), 409
    database_connection = get_database()
    # Atomically claim the completion step to prevent concurrent file assembly.
    update_result = database_connection.execute(
        """
        UPDATE upload_sessions
        SET status = 'completing', updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status = 'active'
        """,
        (upload_id,),
    )
    database_connection.commit()
    if update_result.rowcount != 1:
        return json_error("上传任务正在由其他请求处理。", 409)
    filename_extension = upload_session["original_name"].rsplit(".", 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{filename_extension}"
    assembled_path = UPLOAD_DIRECTORY / f".{stored_name}.assembling"
    final_path = UPLOAD_DIRECTORY / stored_name
    try:
        assemble_chunked_file(upload_session, upload_id, assembled_path)
        media_id = save_completed_upload(
            database_connection,
            upload_session,
            upload_id,
            assembled_path,
            final_path,
            stored_name,
        )
    except Exception:
        database_connection.rollback()
        assembled_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        reactivate_upload_session(database_connection, upload_id)
        app.logger.exception("Failed to complete chunked upload")
        return json_error("文件合并失败，可点击重试继续。", 500)
    remove_upload_directory(upload_id)
    duplicate_scan = scan_album_for_duplicate_media(
        database_connection, upload_session["album_id"]
    )
    if media_id in duplicate_scan["removed_ids"]:
        return jsonify(
            ok=True,
            uploaded={
                "id": media_id,
                "original_name": upload_session["original_name"],
                "renamed": False,
                "media_type": upload_session["media_type"],
                "duplicate": True,
                "html": "",
            },
        )
    media_record = database_connection.execute(
        "SELECT * FROM media WHERE id = ?", (media_id,)
    ).fetchone()
    if media_record is None:
        return jsonify(
            ok=True,
            uploaded={
                "id": media_id,
                "original_name": upload_session["original_name"],
                "renamed": False,
                "media_type": upload_session["media_type"],
                "duplicate": True,
                "html": "",
            },
        )
    album_record = get_album_or_404(upload_session["album_id"])
    return jsonify(
        ok=True,
        uploaded={
            "id": media_record["id"],
            "original_name": media_record["original_name"],
            "renamed": media_record["original_name"] != upload_session["original_name"],
            "media_type": media_record["media_type"],
            "duplicate": False,
            "html": render_template(
                "_media_card.html", item=media_record, album=album_record
            ),
        },
    )

# ----- Standard multi-file upload route -----
@app.post("/albums/<int:album_id>/upload")
@login_required
def upload_media(album_id):
    album_record = get_album_or_404(album_id)
    require_album_owner(album_record)
    uploaded_files = request.files.getlist("media_files")
    if not uploaded_files or all(not uploaded_file.filename for uploaded_file in uploaded_files):
        if wants_json_response():
            return json_error("没有收到文件。", 400)
        flash("请选择至少一个文件。", "danger")
        return redirect(url_for("album_detail", album_id=album_id))
    database_connection = get_database()
    uploaded_results = []
    rejected_results = []
    for uploaded_file in uploaded_files:
        original_filename = normalize_filename(uploaded_file.filename)
        media_type = classify_media(original_filename)
        if not original_filename or media_type is None:
            rejected_results.append(
                {"name": original_filename or "未命名文件", "reason": "不支持的文件格式"}
            )
            continue
        filename_extension = original_filename.rsplit(".", 1)[1].lower()
        stored_name = f"{uuid.uuid4().hex}.{filename_extension}"
        final_path = UPLOAD_DIRECTORY / stored_name
        try:
            uploaded_file.save(final_path)
            database_connection.execute("BEGIN IMMEDIATE")
            final_filename = create_unique_media_name(
                database_connection, album_id, original_filename
            )
            insertion_result = database_connection.execute(
                """
                INSERT INTO media (album_id, original_name, stored_name, media_type)
                VALUES (?, ?, ?, ?)
                """,
                (album_id, final_filename, stored_name, media_type),
            )
            database_connection.commit()
        except Exception:
            database_connection.rollback()
            delete_stored_media(stored_name)
            app.logger.exception("Failed to save uploaded media")
            rejected_results.append({"name": original_filename, "reason": "服务器保存失败"})
            continue
        media_record = database_connection.execute(
            "SELECT * FROM media WHERE id = ?", (insertion_result.lastrowid,)
        ).fetchone()
        uploaded_results.append(
            {
                "id": media_record["id"],
                "original_name": media_record["original_name"],
                "renamed": media_record["original_name"] != original_filename,
                "media_type": media_record["media_type"],
                "duplicate": False,
                "html": render_template(
                    "_media_card.html", item=media_record, album=album_record
                ),
            }
        )
    duplicate_scan = scan_album_for_duplicate_media(database_connection, album_id)
    removed_ids = duplicate_scan["removed_ids"]
    duplicate_results = [
        uploaded_result for uploaded_result in uploaded_results
        if uploaded_result["id"] in removed_ids
    ]
    uploaded_results = [
        uploaded_result for uploaded_result in uploaded_results
        if uploaded_result["id"] not in removed_ids
    ]
    for duplicate_result in duplicate_results:
        duplicate_result["duplicate"] = True
        duplicate_result["html"] = ""
    if wants_json_response():
        has_processed_files = bool(uploaded_results or duplicate_results)
        status_code = 200 if has_processed_files else 415
        return jsonify(
            ok=has_processed_files,
            uploaded=uploaded_results,
            duplicates=duplicate_results,
            rejected=rejected_results,
        ), status_code
    if uploaded_results:
        flash(f"成功上传 {len(uploaded_results)} 个文件。", "success")
    if duplicate_results:
        flash(f"检测并删除了 {len(duplicate_results)} 个重复文件。", "warning")
    if rejected_results:
        flash(f"有 {len(rejected_results)} 个文件未上传。", "warning")
    return redirect(url_for("album_detail", album_id=album_id))

# ----- Media access and deletion routes -----
@app.route("/media/<int:media_id>/file")
def media_file(media_id):
    media_record = get_database().execute(
        """
        SELECT media.*, albums.user_id, albums.is_hidden
        FROM media
        JOIN albums ON albums.id = media.album_id
        WHERE media.id = ?
        """,
        (media_id,),
    ).fetchone()
    if media_record is None:
        abort(404)
    is_private = media_record["is_hidden"] and (
        g.user is None or g.user["id"] != media_record["user_id"]
    )
    if is_private:
        abort(404)
    media_path = UPLOAD_DIRECTORY / media_record["stored_name"]
    if not media_path.exists():
        abort(404)
    return send_file(media_path, download_name=media_record["original_name"])

@app.post("/media/<int:media_id>/delete")
@login_required
def delete_media(media_id):
    media_record = get_database().execute(
        """
        SELECT media.*, albums.user_id
        FROM media
        JOIN albums ON albums.id = media.album_id
        WHERE media.id = ?
        """,
        (media_id,),
    ).fetchone()
    if media_record is None:
        abort(404)
    if media_record["user_id"] != g.user["id"]:
        abort(403)
    database_connection = get_database()
    database_connection.execute("DELETE FROM media WHERE id = ?", (media_id,))
    database_connection.commit()
    delete_stored_media(media_record["stored_name"])
    if wants_json_response():
        return jsonify(ok=True, media_id=media_id)
    flash("媒体文件已删除。", "success")
    return redirect(url_for("album_detail", album_id=media_record["album_id"]))

# ----- User profile and live-search routes -----
@app.route("/users/<username>")
def user_profile(username):
    user_record = get_database().execute(
        """
        SELECT id, username, display_name, created_at
        FROM users
        WHERE username = ? COLLATE NOCASE
        """,
        (username,),
    ).fetchone()
    if user_record is None:
        abort(404)
    is_owner = g.user is not None and g.user["id"] == user_record["id"]
    visibility_clause = "" if is_owner else "AND is_hidden = 0"
    album_records = get_database().execute(
        f"""
        SELECT albums.*,
               (SELECT COUNT(*) FROM media WHERE media.album_id = albums.id) AS media_count,
               (SELECT media.id FROM media WHERE media.album_id = albums.id
                AND media.media_type = 'image' ORDER BY media.id LIMIT 1) AS cover_image_id
        FROM albums
        WHERE user_id = ? {visibility_clause}
        ORDER BY created_at DESC
        """,
        (user_record["id"],),
    ).fetchall()
    return render_template(
        "user_profile.html",
        profile_user=user_record,
        albums=album_records,
        is_owner=is_owner,
    )

def normalize_search_text(text):
    return " ".join((text or "").casefold().split())

def longest_common_subsequence_length(search_text, candidate_text):
    normalized_search = normalize_search_text(search_text)
    normalized_candidate = normalize_search_text(candidate_text)
    if not normalized_search or not normalized_candidate:
        return 0
    # Use a two-row dynamic-programming table to keep memory usage linear.
    previous_row = [0] * (len(normalized_candidate) + 1)
    for search_character in normalized_search:
        current_row = [0]
        for candidate_index, candidate_character in enumerate(normalized_candidate, start=1):
            if search_character == candidate_character:
                current_row.append(previous_row[candidate_index - 1] + 1)
                continue
            current_row.append(max(current_row[-1], previous_row[candidate_index]))
        previous_row = current_row
    return previous_row[-1]

def build_search_results(search_query):
    database_connection = get_database()
    user_records = database_connection.execute(
        """
        SELECT users.id, users.username, users.display_name, users.created_at,
               (SELECT COUNT(*) FROM albums
                WHERE albums.user_id = users.id AND albums.is_hidden = 0) AS public_album_count
        FROM users
        """
    ).fetchall()
    album_records = database_connection.execute(
        """
        SELECT albums.id, albums.title, albums.created_at,
               users.username, users.display_name,
               (SELECT COUNT(*) FROM media WHERE media.album_id = albums.id) AS media_count
        FROM albums
        JOIN users ON users.id = albums.user_id
        WHERE albums.is_hidden = 0
        """
    ).fetchall()
    search_results = []
    for user_record in user_records:
        username_score = longest_common_subsequence_length(search_query, user_record["username"])
        display_name_score = longest_common_subsequence_length(
            search_query, user_record["display_name"]
        )
        match_score = max(username_score, display_name_score)
        if match_score == 0:
            continue
        search_results.append(
            {
                "result_type": "user",
                "primary_text": user_record["display_name"],
                "secondary_text": f"@{user_record['username']}",
                "badge_text": f"用户 · {user_record['public_album_count']}",
                "url": url_for("user_profile", username=user_record["username"]),
                "lcs_score": match_score,
                "sort_text": normalize_search_text(user_record["display_name"]),
            }
        )
    for album_record in album_records:
        match_score = longest_common_subsequence_length(search_query, album_record["title"])
        if match_score == 0:
            continue
        search_results.append(
            {
                "result_type": "album",
                "primary_text": album_record["title"],
                "secondary_text": (
                    f"{album_record['display_name']} @{album_record['username']}"
                ),
                "badge_text": f"专辑 · {album_record['media_count']}",
                "url": url_for("album_detail", album_id=album_record["id"]),
                "lcs_score": match_score,
                "sort_text": normalize_search_text(album_record["title"]),
            }
        )
    # Higher LCS scores appear first; text and type provide deterministic tie-breaking.
    search_results.sort(
        key=lambda result: (
            -result["lcs_score"],
            result["sort_text"],
            result["result_type"],
        )
    )
    return search_results[:50]

@app.route("/search")
def search():
    search_query = request.args.get("q", "").strip()[:120]
    search_results = build_search_results(search_query) if search_query else []
    if request.args.get("format") == "json" or wants_json_response():
        return jsonify(ok=True, query=search_query, results=search_results)
    return render_template("search.html", query=search_query, results=search_results)

# ----- HTTP error handlers -----
def render_error_response(code, message):
    if wants_json_response():
        return jsonify(ok=False, error=message), code
    return render_template("error.html", code=code, message=message), code

@app.errorhandler(413)
def file_too_large(_error):
    return render_error_response(413, "上传分块超过服务器允许的请求大小。")

@app.errorhandler(400)
def bad_request(_error):
    return render_error_response(400, "请求无效或安全令牌已失效，请刷新页面后重试。")

@app.errorhandler(403)
def forbidden(_error):
    return render_error_response(403, "你没有权限执行此操作。")

@app.errorhandler(404)
def not_found(_error):
    return render_error_response(404, "页面或内容不存在。")

# ----- Database initialization and application startup -----
with app.app_context():
    initialize_database()

def run_application():
    app.run(host=SERVER_HOST, port=SERVER_PORT, debug=DEBUG_ENABLED)

if __name__ == "__main__":
    run_application()
