from __future__ import annotations

import os
import sqlite3
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import uuid
from pathlib import Path

import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from datetime import datetime, timedelta




def allowed_file(filename: str) -> bool:
    
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
DATABASE = DATA_DIR / "notes.db"
#  Настройки загрузки файлов 
UPLOAD_FOLDER = BASE_DIR / "uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'docx', 'xlsx', 'xls'}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 МБ

UPLOAD_FOLDER.mkdir(exist_ok=True)

def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

ROLES = {
    "superadmin": "Суперадминистратор",
    "org_admin": "Администратор организации",
    "teacher": "Преподаватель",
    "student": "Ученик/студент",
    "parent": "Родитель",
}

NOTE_TEMPLATE_ROLES = {
    "all": "Для всех",
    "superadmin": "Суперадминистратор",
    "org_admin": "Администратор организации",
    "teacher": "Преподаватель",
    "student": "Ученик/студент",
    "parent": "Родитель",
}

ACCESS_LEVELS = {
    "view": "Просмотр",
    "comment": "Комментирование",
    "edit": "Редактирование",
    "owner": "Полные права",
}
# Настройки для отправки почты 
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = "edunotes747@gmail.com"
MAIL_PASSWORD = "qnqbpzoxtbtobwxo"   
MAIL_DEFAULT_SENDER = MAIL_USERNAME

def send_mail(to: str, subject: str, html_body: str, text_body: str = None):
    """Отправляет письмо через SMTP. Если почта не настроена — логирует."""
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        
        print(f"📧 [EMAIL] To: {to}\nSubject: {subject}\nBody: {html_body}\n")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = MAIL_DEFAULT_SENDER
    msg["To"] = to

    
    if text_body is None:
        text_body = re.sub(r'<[^>]+>', '', html_body)

    part1 = MIMEText(text_body, "plain")
    part2 = MIMEText(html_body, "html")
    msg.attach(part1)
    msg.attach(part2)

    try:
        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT) as server:
            if MAIL_USE_TLS:
                server.starttls()
            if MAIL_USERNAME and MAIL_PASSWORD:
                server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_DEFAULT_SENDER, [to], msg.as_string())
    except Exception as e:
        print(f"❌ Ошибка отправки письма на {to}: {e}")

def find_mentioned_users(text: str) -> list:
    """
    Ищет в тексте упоминания @Имя Фамилия и возвращает список пользователей (объекты Row).
    """
    
    pattern = r'@([А-Яа-яЁёA-Za-z\s\-\.]+)'
    mentions = re.findall(pattern, text)
    users = []
    for name in mentions:
        name_clean = name.strip()
        if not name_clean:
            continue
        
        user = query_one("SELECT id, email, name FROM users WHERE name = ?", (name_clean,))
        if user:
            users.append(user)
        
    return users

def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["DATABASE"] = DATABASE

    @app.before_request
    def load_current_user() -> None:
        user_id = session.get("user_id")
        g.user = None
        if user_id:
            g.user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))

    @app.context_processor
    def inject_globals() -> dict:
        return {
        "ROLES": ROLES,
        "ACCESS_LEVELS": ACCESS_LEVELS,
        "NOTE_TEMPLATE_ROLES": NOTE_TEMPLATE_ROLES,
        "can_delete_user": can_delete_user,   
    }

    return app


app = create_app()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_: Exception | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_all(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> sqlite3.Cursor:
    db = get_db()
    cursor = db.execute(sql, params)
    db.commit()
    return cursor


def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for("login"))
        return view(**kwargs)

    return wrapped_view


def can_manage_users() -> bool:
    return g.user["role"] in {"superadmin", "org_admin"}

def can_delete_user(target_role: str) -> bool:
    """Проверяет, может ли текущий пользователь удалить пользователя с target_role"""
    if g.user["role"] == "superadmin":
        return True
    
    if g.user["role"] == "org_admin":
        
        ranks = {"org_admin": 4, "teacher": 3, "student": 2, "parent": 2}
        current_rank = ranks.get(g.user["role"], 0)
        target_rank = ranks.get(target_role, 0)
        return current_rank > target_rank
    
    return False

def can_manage_workspace(workspace_id: int) -> bool:
    """Проверяет, может ли текущий пользователь управлять пространством."""
    ws = query_one("SELECT owner_id FROM workspaces WHERE id = ?", (workspace_id,))
    if not ws:
        return False
    if g.user["role"] in {"superadmin", "org_admin"}:
        return True
    return ws["owner_id"] == g.user["id"]

def can_manage_folder(folder_id: int) -> bool:
    """Проверяет, может ли текущий пользователь управлять папкой."""
    folder = query_one("SELECT workspace_id FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        return False
    return can_manage_workspace(folder["workspace_id"])

def note_access(note_id: int) -> str | None:
    if g.user["role"] in {"superadmin", "org_admin"}:
        return "owner"

    direct = query_one(
        "SELECT access_level FROM note_access WHERE note_id = ? AND user_id = ?",
        (note_id, g.user["id"]),
    )
    if direct:
        return direct["access_level"]

    note = query_one("SELECT author_id FROM notes WHERE id = ?", (note_id,))
    if note and note["author_id"] == g.user["id"]:
        return "owner"
    return None


def access_rank(level: str | None) -> int:
    ranks = {"view": 1, "comment": 2, "edit": 3, "owner": 4}
    return ranks.get(level or "", 0)


def require_note_access(note_id: int, minimum: str = "view") -> str:
    level = note_access(note_id)
    if access_rank(level) < access_rank(minimum):
        abort(403)
    return level or ""


def split_tags(tags: str) -> list[str]:
    return sorted({tag.strip().lower() for tag in tags.split(",") if tag.strip()})


def save_note_tags(note_id: int, tags: str) -> None:
    db = get_db()
    db.execute("DELETE FROM note_tags WHERE note_id = ?", (note_id,))
    for tag_name in split_tags(tags):
        tag = db.execute("SELECT id FROM tags WHERE name = ?", (tag_name,)).fetchone()
        if tag is None:
            tag_id = db.execute("INSERT INTO tags (name) VALUES (?)", (tag_name,)).lastrowid
        else:
            tag_id = tag["id"]
        db.execute("INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)", (note_id, tag_id))
    db.commit()


def add_version(note_id: int, title: str, content: str) -> None:
    execute(
        """
        INSERT INTO note_versions (note_id, title, content, author_id)
        VALUES (?, ?, ?, ?)
        """,
        (note_id, title, content, g.user["id"]),
    )
def process_attachments(note_id: int) -> int:
    """Обрабатывает загрузку файлов из формы и привязывает к заметке.
       Возвращает количество загруженных файлов.
    """
    count = 0
    files = request.files.getlist('files')
    for file in files:
        if not file or not file.filename:
            continue
        
        if not allowed_file(file.filename):
            flash(f"Тип файла {file.filename} не поддерживается.", "error")
            continue
        
        # Проверка размера
        file.seek(0, 2)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > MAX_FILE_SIZE:
            flash(f"Файл {file.filename} слишком большой (макс. 10 МБ).", "error")
            continue
        
        try:
            ext = file.filename.rsplit('.', 1)[1].lower()
            unique_name = f"{uuid.uuid4()}.{ext}"
            file_path = UPLOAD_FOLDER / unique_name
            file.save(file_path)
            actual_size = file_path.stat().st_size
            
            execute(
                """
                INSERT INTO note_attachments 
                (note_id, filename, original_name, file_size, mime_type, uploaded_by)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (note_id, unique_name, file.filename, actual_size, 
                 file.content_type or 'application/octet-stream', g.user["id"])
            )
            count += 1
        except Exception as e:
            print(f"❌ Ошибка загрузки {file.filename}: {e}")
            flash(f"Не удалось загрузить файл {file.filename}", "error")
    
    return count

def ensure_schema_extensions() -> None:
    execute(
        """
        CREATE TABLE IF NOT EXISTS note_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'all',
            description TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            workspace_kind TEXT NOT NULL DEFAULT 'group',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    existing = query_one("SELECT COUNT(*) AS count FROM note_templates")
    if existing and existing["count"]:
        return

    templates = [
        (
            "План урока",
            "teacher",
            "Шаблон для подготовки занятия.",
            "План урока: {topic}",
            "Тема: {topic}\nЦель: \nМатериалы: \nХод урока:\n1.\n2.\n3.\nДомашнее задание:\n",
            "урок,план",
            "group",
        ),
        (
            "Домашнее задание",
            "teacher",
            "Шаблон для выдачи домашнего задания.",
            "Домашнее задание по {subject}",
            "Что сделать:\n1.\n2.\n3.\nКритерии проверки:\n",
            "домашнее-задание",
            "group",
        ),
        (
            "Конспект занятия",
            "student",
            "Шаблон для личных заметок ученика.",
            "Конспект по теме {topic}",
            "Ключевые тезисы:\n- \n- \n\nВопросы, которые нужно уточнить:\n- \n",
            "конспект,учёба",
            "personal",
        ),
        (
            "Наблюдение за учеником",
            "parent",
            "Краткая форма для родителя о прогрессе ребенка.",
            "Наблюдение за прогрессом {child_name}",
            "Что получилось хорошо:\n\nЧто стоит подтянуть:\n\nКомментарии:\n",
            "родитель,наблюдение",
            "personal",
        ),
        (
            "Уведомление группы",
            "org_admin",
            "Быстрое сообщение для класса или группы.",
            "Сообщение для группы: {topic}",
            "Текст сообщения:\n\nДействия для участников:\n",
            "объявление,группа",
            "group",
        ),
    ]
    for template in templates:
        execute(
            """
            INSERT INTO note_templates (name, role, description, title, content, tags, workspace_kind)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            template,
        )


def ensure_demo_content() -> None:
    users = [
        (1, "Главный администратор", "admin@example.com", "superadmin"),
        (5, "Ольга Смирнова", "olga.teacher@example.com", "teacher"),
        (6, "Денис Кузнецов", "denis.student@example.com", "student"),
        (7, "Екатерина Кузнецова", "ekaterina.parent@example.com", "parent"),
    ]
    for user_id, name, email, role in users:
        if query_one("SELECT 1 FROM users WHERE email = ?", (email,)) is None:
            execute(
                "INSERT INTO users (id, name, email, password_hash, role) VALUES (?, ?, ?, ?, ?)",
                (user_id, name, email, generate_password_hash("password"), role),
            )

    if query_one("SELECT 1 FROM users WHERE id = 7") is not None:
        execute("UPDATE users SET child_user_id = 6 WHERE id = 7")

    workspaces = [
        (4, "Личное пространство Ольги", "personal", 5),
        (5, "Группа 9-Б", "group", 5),
    ]
    for workspace_id, name, kind, owner_id in workspaces:
        if query_one("SELECT 1 FROM workspaces WHERE id = ?", (workspace_id,)) is None:
            execute(
                "INSERT INTO workspaces (id, name, kind, owner_id) VALUES (?, ?, ?, ?)",
                (workspace_id, name, kind, owner_id),
            )

    folders = [
        (4, 5, None, "Подготовка к урокам"),
        (5, 5, None, "Оценки и контрольные"),
        (6, 4, None, "Личное"),
    ]
    for folder_id, workspace_id, parent_id, name in folders:
        if query_one("SELECT 1 FROM folders WHERE id = ?", (folder_id,)) is None:
            execute(
                "INSERT INTO folders (id, workspace_id, parent_id, name) VALUES (?, ?, ?, ?)",
                (folder_id, workspace_id, parent_id, name),
            )

    def get_tag_id(tag_name: str) -> int:
        tag = query_one("SELECT id FROM tags WHERE name = ?", (tag_name,))
        if tag is None:
            return execute("INSERT INTO tags (name) VALUES (?)", (tag_name,)).lastrowid
        return tag["id"]

    extra_tags = ["геометрия", "литература", "контрольная", "родителям", "биология", "проект"]
    for name in extra_tags:
        get_tag_id(name)

    notes = [
        (
            3,
            5,
            4,
            5,
            "План урока: геометрия и углы",
            "Разобрать виды углов, чертежи и практические задания.\n\nМатериалы:\n- линейка\n- транспортир\n- раздаточный лист",
            "2026-05-28",
            0,
        ),
        (
            4,
            5,
            5,
            5,
            "Контрольная работа по геометрии",
            "Проверка знаний по треугольникам, углам и площадям фигур.\n\nВремя: 40 минут.\n\nФорма: индивидуально.",
            "2026-05-29",
            0,
        ),
        (
            5,
            4,
            6,
            6,
            "Конспект по литературе",
            "Тема: образ героя в рассказе.\n\nОсновные тезисы:\n- \n- \n\nЧто нужно повторить:\n- термины\n- примеры из текста",
            "2026-05-27",
            0,
        ),
        (
            6,
            4,
            6,
            7,
            "Наблюдение родителя по учебе",
            "Ребенок стал увереннее отвечать у доски, но нужно подтянуть домашние задания по точным наукам.",
            None,
            0,
        ),
        (
            7,
            5,
            4,
            5,
            "План проекта по биологии",
            "Тема проекта: экосистема школьного двора.\n\nЭтапы:\n1. Наблюдение\n2. Фотофиксация\n3. Мини-отчет\n4. Презентация",
            "2026-05-30",
            0,
        ),
        (
            8,
            5,
            5,
            5,
            "Архив: черновик контрольной",
            "Черновой вариант контрольной работы, оставлен в архиве для истории изменений.",
            "2026-05-20",
            1,
        ),
    ]
    for note_id, workspace_id, folder_id, author_id, title, content, lesson_date, is_archived in notes:
        execute(
            """
            INSERT INTO notes (id, workspace_id, folder_id, author_id, title, content, lesson_date, is_archived)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                workspace_id = excluded.workspace_id,
                folder_id = excluded.folder_id,
                author_id = excluded.author_id,
                title = excluded.title,
                content = excluded.content,
                lesson_date = excluded.lesson_date,
                is_archived = excluded.is_archived,
                updated_at = CURRENT_TIMESTAMP
            """,
            (note_id, workspace_id, folder_id, author_id, title, content, lesson_date, is_archived),
        )
        if query_one(
            "SELECT 1 FROM note_versions WHERE note_id = ? AND title = ? AND content = ?",
            (note_id, title, content),
        ) is None:
            execute(
                """
                INSERT INTO note_versions (note_id, title, content, author_id)
                VALUES (?, ?, ?, ?)
                """,
                (note_id, title, content, author_id),
            )

    tag_map = {
        3: ["геометрия", "проект"],
        4: ["геометрия", "контрольная"],
        5: ["литература"],
        6: ["родителям"],
        7: ["биология", "проект"],
        8: ["контрольная"],
    }
    for note_id, tag_names in tag_map.items():
        for tag_name in tag_names:
            tag_id = get_tag_id(tag_name)
            if query_one(
                "SELECT 1 FROM note_tags WHERE note_id = ? AND tag_id = ?",
                (note_id, tag_id),
            ) is None:
                execute("INSERT INTO note_tags (note_id, tag_id) VALUES (?, ?)", (note_id, tag_id))

    access_rows = [
        (3, 6, "comment"),
        (3, 7, "view"),
        (4, 6, "view"),
        (5, 5, "edit"),
        (6, 6, "owner"),
        (6, 7, "view"),
        (7, 6, "comment"),
    ]
    for note_id, user_id, access_level in access_rows:
        if query_one(
            "SELECT 1 FROM note_access WHERE note_id = ? AND user_id = ?",
            (note_id, user_id),
        ) is None:
            execute(
                "INSERT INTO note_access (note_id, user_id, access_level) VALUES (?, ?, ?)",
                (note_id, user_id, access_level),
            )

    comments = [
        (3, 6, "Можно добавить примеры с чертежами?"),
        (4, 6, "Нужен ли калькулятор на контрольной?"),
        (5, 7, "Спасибо, конспект помог повторить тему."),
        (7, 6, "@Ольга Смирнова, можно ли перенести сдачу проекта на день позже?"),
    ]
    for note_id, author_id, body in comments:
        if query_one(
            "SELECT 1 FROM comments WHERE note_id = ? AND author_id = ? AND body = ?",
            (note_id, author_id, body),
        ) is None:
            execute(
                "INSERT INTO comments (note_id, author_id, body) VALUES (?, ?, ?)",
                (note_id, author_id, body),
            )

    template_updates = [
        ("Памятка для родителей", "parent", "Короткая домашняя сводка для семьи.", "Памятка по {subject}", "Что получилось:\n\nЧто стоит повторить:\n\nСообщение родителям:\n", "родителям,памятка", "personal"),
        ("Проверочная работа", "teacher", "Быстрый шаблон для контрольных и мини-проверок.", "Проверочная работа: {topic}", "Цель проверки:\n\nЗадания:\n1.\n2.\n3.\n\nКритерии:\n", "контрольная,проверка", "group"),
        ("Личный план ученика", "student", "Шаблон для целей на неделю.", "Личный план на неделю", "Цели:\n- \n- \n\nЧто мешает:\n\nЧто поможет:\n", "план,личное", "personal"),
    ]
    for name, role, description, title, content, tags, workspace_kind in template_updates:
        if query_one("SELECT 1 FROM note_templates WHERE name = ?", (name,)) is None:
            execute(
                """
                INSERT INTO note_templates (name, role, description, title, content, tags, workspace_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, role, description, title, content, tags, workspace_kind),
            )


def init_db() -> None:
    schema = (BASE_DIR / "schema.sql").read_text(encoding="utf-8")
    with app.app_context():
        db = get_db()
        db.executescript(schema)
        db.commit()
        ensure_schema_extensions()
        ensure_demo_content()


with app.app_context():
    if DATABASE.exists():
        ensure_schema_extensions()
        ensure_demo_content()


@app.cli.command("init-db")
def init_db_command() -> None:
    init_db()
    print("База данных создана и заполнена стартовыми данными.")


@app.route("/")
def index():
    if g.user:
        return redirect(url_for("notes"))
    return redirect(url_for("login"))


@app.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = query_one("SELECT * FROM users WHERE email = ?", (email,))
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Вход выполнен.", "success")
            return redirect(url_for("notes"))
        flash("Неверная почта или пароль.", "error")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "success")
    return redirect(url_for("login"))


@app.route("/notes")
@login_required
def notes():
    q = request.args.get("q", "").strip()
    tag = request.args.get("tag", "").strip().lower()
    archived = request.args.get("archived") == "1"
    workspace_id = request.args.get("workspace_id", type=int)
    folder_id = request.args.get("folder_id", type=int)

    filters = ["n.is_archived = ?"]
    params: list = [1 if archived else 0]

    if q:
        filters.append("(n.title LIKE ? OR n.content LIKE ? OR u.name LIKE ?)")
        like = f"%{q}%"
        params.extend([like, like, like])
    if tag:
        filters.append("n.id IN (SELECT note_id FROM note_tags nt JOIN tags t ON t.id = nt.tag_id WHERE t.name = ?)")
        params.append(tag)

    # === НОВОЕ: фильтр по пространству ===
    if workspace_id:
        filters.append("n.workspace_id = ?")
        params.append(workspace_id)

    # === НОВОЕ: фильтр по папке ===
    if folder_id:
        filters.append("n.folder_id = ?")
        params.append(folder_id)
    elif folder_id == 0:  # специальное значение для «Без папки»
        filters.append("n.folder_id IS NULL")

    if g.user["role"] not in {"superadmin", "org_admin"}:
        filters.append(
            """
            (n.author_id = ? OR n.id IN (
                SELECT note_id FROM note_access WHERE user_id = ?
            ))
            """
        )
        params.extend([g.user["id"], g.user["id"]])

    items = query_all(
        f"""
        SELECT n.*, u.name AS author_name, w.name AS workspace_name, f.name AS folder_name,
               GROUP_CONCAT(t.name, ', ') AS tag_names
        FROM notes n
        JOIN users u ON u.id = n.author_id
        JOIN workspaces w ON w.id = n.workspace_id
        LEFT JOIN folders f ON f.id = n.folder_id
        LEFT JOIN note_tags nt ON nt.note_id = n.id
        LEFT JOIN tags t ON t.id = nt.tag_id
        WHERE {' AND '.join(filters)}
        GROUP BY n.id
        ORDER BY n.updated_at DESC
        """,
        tuple(params),
    )

    # === Получаем списки для фильтров ===
    all_tags = query_all("SELECT name FROM tags ORDER BY name")
    
    # Все пространства (для выпадающего списка)
    if g.user["role"] in {"superadmin", "org_admin"}:
        workspaces = query_all("SELECT * FROM workspaces ORDER BY name")
    else:
        workspaces = query_all(
            """
            SELECT * FROM workspaces 
            WHERE kind = 'group' OR (kind = 'personal' AND owner_id = ?)
            ORDER BY name
            """,
            (g.user["id"],)
        )

    # Папки для выбранного пространства (или все, если не выбрано)
    if workspace_id:
        folders = query_all(
            "SELECT * FROM folders WHERE workspace_id = ? ORDER BY name",
            (workspace_id,)
        )
    else:
        # Если пространство не выбрано, показываем все папки, к которым есть доступ
        if g.user["role"] in {"superadmin", "org_admin"}:
            folders = query_all("SELECT * FROM folders ORDER BY name")
        else:
            folders = query_all(
                """
                SELECT f.* FROM folders f
                JOIN workspaces w ON w.id = f.workspace_id
                WHERE w.kind = 'group' OR (w.kind = 'personal' AND w.owner_id = ?)
                ORDER BY f.name
                """,
                (g.user["id"],)
            )

    return render_template(
        "notes.html",
        notes=items,
        q=q,
        tag=tag,
        archived=archived,
        tags=all_tags,
        workspaces=workspaces,
        folders=folders,
        selected_workspace_id=workspace_id,
        selected_folder_id=folder_id,
    )


@app.route("/dashboard")
@login_required
def dashboard():
        # Считаем статистику с учётом прав 
    if g.user["role"] in {"superadmin", "org_admin"}:
        # Админы видят всё
        stats = {
            "notes": query_one("SELECT COUNT(*) AS count FROM notes")["count"],
            "archived": query_one("SELECT COUNT(*) AS count FROM notes WHERE is_archived = 1")["count"],
            "comments": query_one("SELECT COUNT(*) AS count FROM comments")["count"],
            "templates": query_one("SELECT COUNT(*) AS count FROM note_templates")["count"],
        }
    else:
        # Обычные пользователи — только свои и те, где есть доступ
        stats = {
            "notes": query_one("""
                SELECT COUNT(DISTINCT n.id) AS count 
                FROM notes n
                LEFT JOIN note_access na ON na.note_id = n.id AND na.user_id = ?
                WHERE n.author_id = ? OR na.user_id = ?
            """, (g.user["id"], g.user["id"], g.user["id"]))["count"],
            "archived": query_one("""
                SELECT COUNT(DISTINCT n.id) AS count 
                FROM notes n
                LEFT JOIN note_access na ON na.note_id = n.id AND na.user_id = ?
                WHERE (n.author_id = ? OR na.user_id = ?) AND n.is_archived = 1
            """, (g.user["id"], g.user["id"], g.user["id"]))["count"],
            "comments": query_one("""
                SELECT COUNT(c.id) AS count 
                FROM comments c
                JOIN notes n ON n.id = c.note_id
                LEFT JOIN note_access na ON na.note_id = n.id AND na.user_id = ?
                WHERE n.author_id = ? OR na.user_id = ?
            """, (g.user["id"], g.user["id"], g.user["id"]))["count"],
            "templates": query_one("SELECT COUNT(*) AS count FROM note_templates")["count"],  # шаблоны можно оставить общие
        }
    recent_notes = query_all(
        """
        SELECT n.id, n.title, n.updated_at, u.name AS author_name, n.is_archived
        FROM notes n
        JOIN users u ON u.id = n.author_id
        ORDER BY n.updated_at DESC
        LIMIT 5
        """
    )
    recent_comments = query_all(
        """
        SELECT c.created_at, c.body, u.name AS author_name, n.id AS note_id, n.title AS note_title
        FROM comments c
        JOIN users u ON u.id = c.author_id
        JOIN notes n ON n.id = c.note_id
        ORDER BY c.created_at DESC
        LIMIT 5
        """
    )
    upcoming_lessons = query_all(
        """
        SELECT id, title, lesson_date, lesson_time, updated_at
        FROM notes
        WHERE lesson_date IS NOT NULL AND is_archived = 0
        ORDER BY lesson_date ASC, updated_at DESC
        LIMIT 6
        """
    )
    return render_template(
        "dashboard.html",
        stats=stats,
        recent_notes=recent_notes,
        recent_comments=recent_comments,
        upcoming_lessons=upcoming_lessons,
    )


@app.route("/templates")
@login_required
def note_templates():
    role = request.args.get("role", "all")
    filters = []
    params: list = []
    if role != "all":
        filters.append("role = ?")
        params.append(role)
    templates = query_all(
        f"""
        SELECT *
        FROM note_templates
        {("WHERE " + " AND ".join(filters)) if filters else ""}
        ORDER BY created_at DESC
        """,
        tuple(params),
    )
    return render_template("templates.html", templates=templates, current_role=role)


@app.route("/templates/<int:template_id>")
@login_required
def note_template_detail(template_id: int):
    template = query_one("SELECT * FROM note_templates WHERE id = ?", (template_id,))
    if template is None:
        abort(404)
    return render_template("template_detail.html", template=template)


@app.route("/templates/new", methods=("GET", "POST"))
@login_required
def note_template_new():
    if request.method == "POST":
        name = request.form["name"].strip()
        title = request.form["title"].strip()
        content = request.form["content"].strip()
        if not name or not title:
            flash("У шаблона должны быть название и заголовок.", "error")
        else:
            execute(
                """
                INSERT INTO note_templates (name, role, description, title, content, tags, workspace_kind)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    request.form["role"],
                    request.form.get("description", "").strip(),
                    title,
                    content,
                    request.form.get("tags", "").strip(),
                    request.form["workspace_kind"],
                ),
            )
            flash("Шаблон создан.", "success")
            return redirect(url_for("note_templates"))

    return render_template("template_form.html")


@app.route("/schedule")
@login_required
def schedule():
    sql = """
        SELECT n.id, n.title, n.lesson_date, n.lesson_time, n.is_archived, n.updated_at,
               u.name AS author_name, w.name AS workspace_name
        FROM notes n
        JOIN users u ON u.id = n.author_id
        JOIN workspaces w ON w.id = n.workspace_id
        WHERE n.lesson_date IS NOT NULL
          AND n.is_archived = 0 
    """
    params = []
    
    if g.user["role"] not in {"superadmin", "org_admin"}:
        sql += """
            AND (n.author_id = ? OR n.id IN (
                SELECT note_id FROM note_access WHERE user_id = ?
            ))
        """
        params.extend([g.user["id"], g.user["id"]])
    
    sql += " ORDER BY n.lesson_date ASC, n.lesson_time ASC, n.updated_at DESC"
    
    lessons = query_all(sql, tuple(params))

    # === НОВОЕ: определяем текущее время по МСК ===
    # Получаем текущее время UTC и прибавляем 3 часа (MSK = UTC+3)
    # Для более точного определения можно использовать библиотеку pytz, но для учебного проекта это приемлемо.
    now_utc = datetime.utcnow()
    msk_now = now_utc + timedelta(hours=3)

    # === Обрабатываем каждую заметку, вычисляем, прошло ли время ===
    lessons_with_status = []
    for lesson in lessons:
        # По умолчанию считаем, что время ещё не прошло
        is_past = False
        
        if lesson["lesson_date"]:
            try:
                # Преобразуем строку даты 'YYYY-MM-DD' в объект date
                lesson_date = datetime.strptime(lesson["lesson_date"], "%Y-%m-%d").date()
                # Если время указано, используем его, иначе считаем время 00:00
                if lesson["lesson_time"]:
                    lesson_time = datetime.strptime(lesson["lesson_time"], "%H:%M").time()
                else:
                    lesson_time = datetime.strptime("00:00", "%H:%M").time()
                
                # Собираем datetime
                lesson_datetime = datetime.combine(lesson_date, lesson_time)
                
                # Сравниваем с текущим моментом по МСК
                if lesson_datetime < msk_now:
                    is_past = True
            except (ValueError, TypeError):
                # Если дата или время невалидны, считаем, что время не прошло
                pass
        
        # Добавляем флаг к данным заметки (превращаем Row в dict для удобства)
        lesson_dict = dict(lesson)
        lesson_dict["is_past"] = is_past
        lessons_with_status.append(lesson_dict)

    return render_template("schedule.html", lessons=lessons_with_status)


@app.route("/schedule/new", methods=("GET", "POST"))
@login_required
def schedule_new():
    if request.method == "POST":
        lesson_date = request.form["lesson_date"]
        title = request.form["title"].strip()
        subject = request.form.get("subject", "").strip()
        lesson_time = request.form.get("lesson_time", "").strip()
        classroom = request.form.get("classroom", "").strip()
        teacher_note = request.form.get("teacher_note", "").strip()
        homework = request.form.get("homework", "").strip()

        if not title or not lesson_date:
            flash("Для расписания нужны название и дата.", "error")
        else:
            content = "\n".join(
                line for line in [
                    f"Предмет: {subject}" if subject else "",
                    f"Время: {lesson_time}" if lesson_time else "",
                    f"Аудитория: {classroom}" if classroom else "",
                    "",
                    "План занятия:",
                    teacher_note,
                    "",
                    "Домашнее задание:",
                    homework,
                ] if line is not None
            ).strip()
            cursor = execute(
                """
                INSERT INTO notes (title, content, author_id, workspace_id, folder_id, lesson_date, lesson_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    content,
                    g.user["id"],
                    request.form["workspace_id"],
                    request.form.get("folder_id") or None,
                    lesson_date,
                    lesson_time,
                ),
            )
            note_id = cursor.lastrowid
            save_note_tags(note_id, request.form.get("tags", "расписание"))
            add_version(note_id, title, content)
            flash("Запись расписания создана.", "success")
            return redirect(url_for("schedule"))

    return render_template("schedule_form.html", **form_options())


@app.route("/workspaces", methods=("GET", "POST"))
@login_required
def workspaces():
    if request.method == "POST":
        name = request.form["name"].strip()
        kind = request.form["kind"]
        if not name:
            flash("У пространства должно быть название.", "error")
        else:
            execute(
                "INSERT INTO workspaces (name, kind, owner_id) VALUES (?, ?, ?)",
                (name, kind, g.user["id"]),
            )
            flash("Пространство создано.", "success")
            return redirect(url_for("workspaces"))

    # ИСПРАВЛЕНИЕ: показываем только доступные пространства 
    if g.user["role"] in {"superadmin", "org_admin"}:
        items = query_all(
            """
            SELECT w.*, u.name AS owner_name, COUNT(n.id) AS notes_count
            FROM workspaces w
            LEFT JOIN users u ON u.id = w.owner_id
            LEFT JOIN notes n ON n.workspace_id = w.id
            GROUP BY w.id
            ORDER BY w.kind, w.name
            """
        )
    else:
        items = query_all(
            """
            SELECT w.*, u.name AS owner_name, COUNT(n.id) AS notes_count
            FROM workspaces w
            LEFT JOIN users u ON u.id = w.owner_id
            LEFT JOIN notes n ON n.workspace_id = w.id
            WHERE w.kind = 'group' 
               OR (w.kind = 'personal' AND w.owner_id = ?)
            GROUP BY w.id
            ORDER BY w.kind, w.name
            """,
            (g.user["id"],)
        )

    return render_template("workspaces.html", workspaces=items)

@app.route("/workspaces/<int:workspace_id>/edit", methods=("GET", "POST"))
@login_required
def workspace_edit(workspace_id: int):
    if not can_manage_workspace(workspace_id):
        abort(403)
    workspace = query_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
    if not workspace:
        abort(404)

    # Список пользователей для выдачи доступа
    users = query_all("SELECT id, name, email FROM users WHERE id != ? ORDER BY name", (g.user["id"],))

    if request.method == "POST":
        new_name = request.form["name"].strip()
        if not new_name:
            flash("Название не может быть пустым.", "error")
        else:
            execute("UPDATE workspaces SET name = ? WHERE id = ?", (new_name, workspace_id))
            flash("Пространство обновлено.", "success")
            return redirect(url_for("workspaces"))

    return render_template("workspace_edit.html", workspace=workspace, users=users)


@app.route("/workspaces/<int:workspace_id>/delete", methods=("POST",))
@login_required
def workspace_delete(workspace_id: int):
    if not can_manage_workspace(workspace_id):
        abort(403)
    execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
    flash("Пространство удалено вместе со всеми папками и заметками.", "success")
    return redirect(url_for("workspaces"))


@app.route("/workspaces/<int:workspace_id>/share", methods=("POST",))
@login_required
def workspace_share(workspace_id: int):
    if not can_manage_workspace(workspace_id):
        abort(403)
    user_id = request.form["user_id"]
    access_level = request.form["access_level"]
    
    # Получаем все заметки в этом пространстве
    notes = query_all("SELECT id FROM notes WHERE workspace_id = ?", (workspace_id,))
    for note in notes:
        execute(
            """
            INSERT INTO note_access (note_id, user_id, access_level)
            VALUES (?, ?, ?)
            ON CONFLICT(note_id, user_id) DO UPDATE SET access_level = excluded.access_level
            """,
            (note["id"], user_id, access_level),
        )
    flash(f"Доступ уровня '{ACCESS_LEVELS[access_level]}' выдан на все заметки пространства.", "success")
    return redirect(url_for("workspaces"))

@app.route("/folders", methods=("GET", "POST"))
@login_required
def folders():
    if request.method == "POST":
        name = request.form["name"].strip()
        workspace_id = request.form["workspace_id"]
        parent_id = request.form.get("parent_id") or None
        if not name:
            flash("У папки должно быть название.", "error")
        else:
            # Проверка прав
            if g.user["role"] not in {"superadmin", "org_admin"}:
                ws = query_one("SELECT kind, owner_id FROM workspaces WHERE id = ?", (workspace_id,))
                if ws and ws["kind"] == "personal" and ws["owner_id"] != g.user["id"]:
                    flash("У вас нет прав создавать папки в чужом личном пространстве.", "error")
                    return redirect(url_for("folders"))

            execute(
                "INSERT INTO folders (workspace_id, parent_id, name) VALUES (?, ?, ?)",
                (workspace_id, parent_id, name),
            )
            flash("Папка создана.", "success")
            return redirect(url_for("folders"))

    #  ИСПРАВЛЕНИЕ: показываем только доступные папки 
    if g.user["role"] in {"superadmin", "org_admin"}:
        items = query_all(
            """
            SELECT f.*, w.name AS workspace_name, p.name AS parent_name, COUNT(n.id) AS notes_count
            FROM folders f
            JOIN workspaces w ON w.id = f.workspace_id
            LEFT JOIN folders p ON p.id = f.parent_id
            LEFT JOIN notes n ON n.folder_id = f.id
            GROUP BY f.id
            ORDER BY w.name, f.name
            """
        )
        all_workspaces = query_all("SELECT * FROM workspaces ORDER BY name")
        all_folders = query_all("SELECT * FROM folders ORDER BY name")
    else:
        items = query_all(
            """
            SELECT f.*, w.name AS workspace_name, p.name AS parent_name, COUNT(n.id) AS notes_count
            FROM folders f
            JOIN workspaces w ON w.id = f.workspace_id
            LEFT JOIN folders p ON p.id = f.parent_id
            LEFT JOIN notes n ON n.folder_id = f.id
            WHERE w.kind = 'group' 
               OR (w.kind = 'personal' AND w.owner_id = ?)
            GROUP BY f.id
            ORDER BY w.name, f.name
            """,
            (g.user["id"],)
        )
        all_workspaces = query_all(
            """
            SELECT * FROM workspaces 
            WHERE kind = 'group' OR (kind = 'personal' AND owner_id = ?)
            ORDER BY name
            """,
            (g.user["id"],)
        )
        all_folders = query_all(
            """
            SELECT f.* FROM folders f
            JOIN workspaces w ON w.id = f.workspace_id
            WHERE w.kind = 'group' OR (w.kind = 'personal' AND w.owner_id = ?)
            ORDER BY f.name
            """,
            (g.user["id"],)
        )

    return render_template(
        "folders.html",
        folders=items,
        workspaces=all_workspaces,
        folder_options=all_folders,
    )

@app.route("/folders/<int:folder_id>/edit", methods=("GET", "POST"))
@login_required
def folder_edit(folder_id: int):
    if not can_manage_folder(folder_id):
        abort(403)
    folder = query_one("SELECT * FROM folders WHERE id = ?", (folder_id,))
    if not folder:
        abort(404)

    # Список пользователей для выдачи доступа
    users = query_all("SELECT id, name, email FROM users WHERE id != ? ORDER BY name", (g.user["id"],))

    if request.method == "POST":
        new_name = request.form["name"].strip()
        if not new_name:
            flash("Название не может быть пустым.", "error")
        else:
            execute("UPDATE folders SET name = ? WHERE id = ?", (new_name, folder_id))
            flash("Папка обновлена.", "success")
            return redirect(url_for("folders"))

    return render_template("folder_edit.html", folder=folder, users=users)


@app.route("/folders/<int:folder_id>/delete", methods=("POST",))
@login_required
def folder_delete(folder_id: int):
    if not can_manage_folder(folder_id):
        abort(403)
    execute("DELETE FROM folders WHERE id = ?", (folder_id,))
    flash("Папка удалена вместе со всеми заметками.", "success")
    return redirect(url_for("folders"))


@app.route("/folders/<int:folder_id>/share", methods=("POST",))
@login_required
def folder_share(folder_id: int):
    if not can_manage_folder(folder_id):
        abort(403)
    user_id = request.form["user_id"]
    access_level = request.form["access_level"]
    
    # Получаем все заметки в этой папке
    notes = query_all("SELECT id FROM notes WHERE folder_id = ?", (folder_id,))
    for note in notes:
        execute(
            """
            INSERT INTO note_access (note_id, user_id, access_level)
            VALUES (?, ?, ?)
            ON CONFLICT(note_id, user_id) DO UPDATE SET access_level = excluded.access_level
            """,
            (note["id"], user_id, access_level),
        )
    flash(f"Доступ уровня '{ACCESS_LEVELS[access_level]}' выдан на все заметки в папке.", "success")
    return redirect(url_for("folders"))


@app.route("/notes/new", methods=("GET", "POST"))
@login_required
def note_new():
    template_id = request.args.get("template_id", type=int)
    note_template = None
    initial = {
        "title": "",
        "content": "",
        "tags": "",
        "workspace_id": "",
        "folder_id": "",
        "lesson_date": "",
    }
    if template_id:
        note_template = query_one("SELECT * FROM note_templates WHERE id = ?", (template_id,))
        if note_template:
            initial["title"] = note_template["title"]
            initial["content"] = note_template["content"]
            initial["tags"] = note_template["tags"]
            if note_template["workspace_kind"] == "personal":
                workspace = query_one(
                    "SELECT id FROM workspaces WHERE owner_id = ? AND kind = 'personal' ORDER BY id LIMIT 1",
                    (g.user["id"],),
                )
            else:
                workspace = query_one(
                    "SELECT id FROM workspaces WHERE kind = 'group' ORDER BY id LIMIT 1"
                )
            if workspace:
                initial["workspace_id"] = workspace["id"]

    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"].strip()
        
        if not title:
            flash("У заметки должен быть заголовок.", "error")
        else:
            cursor = execute(
                """
                INSERT INTO notes (title, content, author_id, workspace_id, folder_id, lesson_date, lesson_time)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    title,
                    content,
                    g.user["id"],
                    request.form["workspace_id"],
                    request.form.get("folder_id") or None,
                    request.form.get("lesson_date") or None,
                    request.form.get("lesson_time") or None,
                ),
            )
            note_id = cursor.lastrowid

            save_note_tags(note_id, request.form.get("tags", ""))
            add_version(note_id, title, content)
            uploaded = process_attachments(note_id)
            if uploaded:
                flash(f"Заметка создана, загружено файлов: {uploaded}.", "success")
            else:
                flash("Заметка создана без файлов.", "success")
            

    return render_template(
        "note_form.html",
        note=None,
        tag_names=initial["tags"],
        note_template=note_template,
        initial=initial,
        **form_options(),
    )


@app.route("/notes/<int:note_id>")
@login_required
def note_detail(note_id: int):
    level = require_note_access(note_id)
    note = query_one(
        """
        SELECT n.*, u.name AS author_name, w.name AS workspace_name, f.name AS folder_name,
               GROUP_CONCAT(t.name, ', ') AS tag_names
        FROM notes n
        JOIN users u ON u.id = n.author_id
        JOIN workspaces w ON w.id = n.workspace_id
        LEFT JOIN folders f ON f.id = n.folder_id
        LEFT JOIN note_tags nt ON nt.note_id = n.id
        LEFT JOIN tags t ON t.id = nt.tag_id
        WHERE n.id = ?
        GROUP BY n.id
        """,
        (note_id,),
    )
    if note is None:
        abort(404)

    # ===== НОВОЕ: пагинация комментариев =====
    page = request.args.get('page', 1, type=int)
    per_page = 8
    if page < 1:
        page = 1

    total_comments = query_one(
        "SELECT COUNT(*) AS count FROM comments WHERE note_id = ?", 
        (note_id,)
    )["count"]
    total_pages = (total_comments + per_page - 1) // per_page
    if page > total_pages and total_pages > 0:
        page = total_pages

    offset = (page - 1) * per_page
    comments = query_all(
        """
        SELECT c.*, u.name AS author_name
        FROM comments c JOIN users u ON u.id = c.author_id
        WHERE c.note_id = ?
        ORDER BY c.created_at DESC
        LIMIT ? OFFSET ?
        """,
        (note_id, per_page, offset),
    )
    # ========================================

    versions = query_all(
        """
        SELECT v.*, u.name AS author_name
        FROM note_versions v JOIN users u ON u.id = v.author_id
        WHERE v.note_id = ?
        ORDER BY v.created_at DESC
        """,
        (note_id,),
    )

    shares = query_all(
        """
        SELECT na.*, u.name, u.email
        FROM note_access na JOIN users u ON u.id = na.user_id
        WHERE na.note_id = ?
        ORDER BY u.name
        """,
        (note_id,),
    )

    attachments = query_all(
        """
        SELECT * FROM note_attachments 
        WHERE note_id = ? 
        ORDER BY uploaded_at DESC
        """,
        (note_id,)
    )

    users = query_all("SELECT id, name, email FROM users WHERE id != ? ORDER BY name", (g.user["id"],))

    return render_template(
        "note_detail.html",
        note=note,
        comments=comments,
        versions=versions,
        shares=shares,
        attachments=attachments,
        users=users,
        level=level,
        page=page,
        total_pages=total_pages,
        total_comments=total_comments,
    )


@app.route("/notes/<int:note_id>/print")
@login_required
def note_print(note_id: int):
    require_note_access(note_id)
    note = query_one(
        """
        SELECT n.*, u.name AS author_name, w.name AS workspace_name, f.name AS folder_name,
               GROUP_CONCAT(t.name, ', ') AS tag_names
        FROM notes n
        JOIN users u ON u.id = n.author_id
        JOIN workspaces w ON w.id = n.workspace_id
        LEFT JOIN folders f ON f.id = n.folder_id
        LEFT JOIN note_tags nt ON nt.note_id = n.id
        LEFT JOIN tags t ON t.id = nt.tag_id
        WHERE n.id = ?
        GROUP BY n.id
        """,
        (note_id,),
    )
    if note is None:
        abort(404)
    return render_template("print_note.html", note=note)


@app.route("/notes/<int:note_id>/edit", methods=("GET", "POST"))
@login_required
def note_edit(note_id: int):
    require_note_access(note_id, "edit")
    note = query_one("SELECT * FROM notes WHERE id = ?", (note_id,))
    if note is None:
        abort(404)

    if request.method == "POST":
        title = request.form["title"].strip()
        content = request.form["content"].strip()
        
        if not title:
            flash("У заметки должен быть заголовок.", "error")
        else:
            execute(
    """
                UPDATE notes
                SET title = ?, content = ?, workspace_id = ?, folder_id = ?, lesson_date = ?, lesson_time = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    title,
                    content,
                    request.form["workspace_id"],
                    request.form.get("folder_id") or None,
                    request.form.get("lesson_date") or None,
                    request.form.get("lesson_time") or None,   
                    note_id,
                ),
            )
            save_note_tags(note_id, request.form.get("tags", ""))
            add_version(note_id, title, content)

            uploaded = process_attachments(note_id)
            if uploaded:
                flash(f"Заметка обновлена, добавлено файлов: {uploaded}.", "success")
            else:
                flash("Заметка обновлена.", "success")

            

    # GET-запрос
    tag_names = ", ".join(row["name"] for row in query_all(
        "SELECT t.name FROM tags t JOIN note_tags nt ON nt.tag_id = t.id WHERE nt.note_id = ? ORDER BY t.name",
        (note_id,),
    ))
    return render_template(
        "note_form.html",
        note=note,
        tag_names=tag_names,
        initial=None,
        note_template=None,
        **form_options(),
    )

@app.post("/notes/<int:note_id>/archive")
@login_required
def note_archive(note_id: int):
    require_note_access(note_id, "edit")
    note = query_one("SELECT is_archived FROM notes WHERE id = ?", (note_id,))
    execute("UPDATE notes SET is_archived = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (0 if note["is_archived"] else 1, note_id))
    flash("Статус архива изменен.", "success")
    return redirect(url_for("note_detail", note_id=note_id))


@app.post("/notes/<int:note_id>/delete")
@login_required
def note_delete(note_id: int):
    require_note_access(note_id, "owner")
    
    # 1. Сначала получаем список файлов, которые принадлежат заметке 
    attachments = query_all("SELECT filename FROM note_attachments WHERE note_id = ?", (note_id,))
    
    # 2. Удаляем файлы с диска 
    for att in attachments:
        file_path = UPLOAD_FOLDER / att["filename"]
        if file_path.exists():
            try:
                file_path.unlink()  # удаляем физический файл
            except Exception as e:
                print(f"Не удалось удалить файл {file_path}: {e}")
    
    # 3. Удаляем заметку (каскадно удалятся записи о файлах из БД) 
    execute("DELETE FROM notes WHERE id = ?", (note_id,))
    
    flash("Заметка и все её файлы удалены.", "success")
    return redirect(url_for("notes"))


@app.post("/notes/<int:note_id>/comments")
@login_required
def comment_add(note_id: int):
    require_note_access(note_id, "comment")
    body = request.form["body"].strip()
    if not body:
        flash("Комментарий не может быть пустым.", "error")
        return redirect(url_for("note_detail", note_id=note_id))

    # 1. Сохраняем комментарий
    execute(
        "INSERT INTO comments (note_id, author_id, body) VALUES (?, ?, ?)",
        (note_id, g.user["id"], body),
    )
    flash("Комментарий добавлен.", "success")

    # 2. Обработка упоминаний
    mentioned_users = find_mentioned_users(body)
    if mentioned_users:
        # Получаем информацию о заметке
        note = query_one("SELECT title FROM notes WHERE id = ?", (note_id,))
        if note:
            note_title = note["title"]
            author_name = g.user["name"]
            note_url = url_for("note_detail", note_id=note_id, _external=True)

            for user in mentioned_users:
                # Не отправляем уведомление автору комментария, если он упомянул себя
                if user["id"] == g.user["id"]:
                    continue

                subject = f"Вас упомянули в заметке «{note_title}»"
                html_body = f"""
                <p>Здравствуйте, {user['name']}!</p>
                <p>Пользователь <strong>{author_name}</strong> упомянул вас в комментарии к заметке 
                <a href="{note_url}">«{note_title}»</a>.</p>
                <p><strong>Комментарий:</strong></p>
                <blockquote>{body}</blockquote>
                <p>Перейти к заметке: <a href="{note_url}">{note_url}</a></p>
                """
                text_body = f"""
                Здравствуйте, {user['name']}!
                Пользователь {author_name} упомянул вас в комментарии к заметке «{note_title}».
                Комментарий:
                {body}
                Перейти к заметке: {note_url}
                """
                send_mail(
                    to=user["email"],
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body
                )
        # Если заметка не найдена (маловероятно) — просто игнорируем.

    return redirect(url_for("note_detail", note_id=note_id))


@app.post("/notes/<int:note_id>/share")
@login_required
def share_note(note_id: int):
    require_note_access(note_id, "owner")
    user_id = request.form["user_id"]
    access_level = request.form["access_level"]
    execute(
        """
        INSERT INTO note_access (note_id, user_id, access_level)
        VALUES (?, ?, ?)
        ON CONFLICT(note_id, user_id) DO UPDATE SET access_level = excluded.access_level
        """,
        (note_id, user_id, access_level),
    )
    flash("Доступ обновлен.", "success")
    return redirect(url_for("note_detail", note_id=note_id))


@app.post("/notes/<int:note_id>/restore/<int:version_id>")
@login_required
def restore_version(note_id: int, version_id: int):
    require_note_access(note_id, "edit")
    version = query_one("SELECT * FROM note_versions WHERE id = ? AND note_id = ?", (version_id, note_id))
    if version is None:
        abort(404)
    execute(
        "UPDATE notes SET title = ?, content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (version["title"], version["content"], note_id),
    )
    add_version(note_id, version["title"], version["content"])
    flash("Версия восстановлена.", "success")
    return redirect(url_for("note_detail", note_id=note_id))


@app.route("/admin/users", methods=("GET", "POST"))
@login_required
def users_admin():
    if not can_manage_users():
        abort(403)

    #  УДАЛЕНИЕ ПОЛЬЗОВАТЕЛЯ 
    if request.method == "POST" and request.form.get("action") == "delete":
        user_id = request.form.get("user_id", type=int)
        if user_id:
            target = query_one("SELECT id, role FROM users WHERE id = ?", (user_id,))
            if target:
                if user_id == g.user["id"]:
                    flash("Нельзя удалить самого себя.", "error")
                elif can_delete_user(target["role"]):
                    execute("DELETE FROM users WHERE id = ?", (user_id,))
                    flash("Пользователь успешно удалён.", "success")
                else:
                    flash("Недостаточно прав для удаления этого пользователя.", "error")
            else:
                flash("Пользователь не найден.", "error")
        return redirect(url_for("users_admin"))

    # СОЗДАНИЕ ПОЛЬЗОВАТЕЛЯ 
    if request.method == "POST" and request.form.get("action") != "delete":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        role = request.form["role"]
        child_user_id = request.form.get("child_user_id") or None  # новое поле

        # Валидация: если роль parent, child_user_id обязателен
        if role == "parent" and not child_user_id:
            flash("Для родителя необходимо указать ребёнка (студента).", "error")
            return redirect(url_for("users_admin"))

        execute(
            """
            INSERT INTO users (name, email, password_hash, role, child_user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, email, generate_password_hash(password), role, child_user_id),
        )
        flash("Пользователь создан.", "success")
        return redirect(url_for("users_admin"))

    #  ПОЛУЧАЕМ СПИСКИ ДЛЯ ОТОБРАЖЕНИЯ 
    users = query_all("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC")
    students = query_all("SELECT id, name, email FROM users WHERE role = 'student' ORDER BY name")
    return render_template("users.html", users=users, students=students)

def form_options() -> dict:
    if g.user["role"] in {"superadmin", "org_admin"}:
        workspaces = query_all("SELECT * FROM workspaces ORDER BY name")
        folders = query_all("SELECT * FROM folders ORDER BY name")
    else:
        workspaces = query_all(
            """
            SELECT * FROM workspaces 
            WHERE kind = 'group' OR (kind = 'personal' AND owner_id = ?)
            ORDER BY name
            """,
            (g.user["id"],)
        )
        folders = query_all(
            """
            SELECT f.* FROM folders f
            JOIN workspaces w ON w.id = f.workspace_id
            WHERE w.kind = 'group' OR (w.kind = 'personal' AND w.owner_id = ?)
            ORDER BY f.name
            """,
            (g.user["id"],)
        )

    return {
        "workspaces": workspaces,
        "folders": folders,
    }
@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    # 1. Находим, к какой заметке прикреплён файл
    attachment = query_one("SELECT note_id FROM note_attachments WHERE filename = ?", (filename,))
    if not attachment:
        abort(404)  # файла нет в базе
    
    # 2. Проверяем права доступа к этой заметке (минимум просмотр)
    require_note_access(attachment["note_id"], "view")
    
    # 3. Отдаём файл
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.post("/attachments/<int:attachment_id>/delete")
@login_required
def delete_attachment(attachment_id: int):
    attachment = query_one(
        "SELECT * FROM note_attachments WHERE id = ?", 
        (attachment_id,)
    )
    if not attachment:
        abort(404)

    # Проверяем права: только владелец заметки или owner
    note_id = attachment["note_id"]
    level = note_access(note_id)
    if access_rank(level) < access_rank("owner"):
        abort(403)

    # Удаляем файл с диска
    file_path = UPLOAD_FOLDER / attachment["filename"]
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception as e:
            print(f"Не удалось удалить файл с диска: {e}")

    # Удаляем запись из базы
    execute("DELETE FROM note_attachments WHERE id = ?", (attachment_id,))

    flash("Файл удалён.", "success")
    return redirect(url_for("note_detail", note_id=note_id))
if __name__ == "__main__":
    if not DATABASE.exists():
        init_db()
    app.run(debug=True)
