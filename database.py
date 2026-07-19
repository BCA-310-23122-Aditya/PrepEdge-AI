"""
database.py — InterviewAI database layer (MySQL / PyMySQL)
──────────────────────────────────────────────────────────
• Pure MySQL — zero SQLite dependency
• PyMySQL with DictCursor throughout
• Single get_conn() entry point returning MySQLWrapper
• init_db() is idempotent (CREATE TABLE IF NOT EXISTS)
• All parameterised queries use %s placeholders
• COLLATE NOCASE removed from DDL (MySQL uses utf8mb4_unicode_ci for case-insensitive collation)
• is_blocked column present in users table (required by verify_user / is_user_blocked)
"""

import pymysql
import json
import hashlib
import os
import secrets
import string
from pymysql.cursors import DictCursor
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

# ══════════════════════════════════════════════════════════════
#  MYSQL CONFIGURATION
#  Set these in your .env file or as environment variables.
# ══════════════════════════════════════════════════════════════
MYSQL_HOST     = os.environ.get('MYSQL_HOST',     '127.0.0.1')
MYSQL_PORT     = int(os.environ.get('MYSQL_PORT', 3306))
MYSQL_USER     = os.environ.get('MYSQL_USER',     'root')
MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
MYSQL_DB       = os.environ.get('MYSQL_DB',       'interviewai')


# ══════════════════════════════════════════════════════════════
#  CONNECTION WRAPPER
#  Provides a minimal sqlite3-compatible API on top of PyMySQL
#  so callers can use .execute(), .fetchone(), .fetchall(),
#  .lastrowid, .commit(), and .close() without changes.
# ══════════════════════════════════════════════════════════════
class MySQLWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, query: str, params=()):
        """
        Run one parameterised statement.
        Converts SQLite '?' placeholders to MySQL '%s'.
        Strips any residual 'COLLATE NOCASE' from ad-hoc queries.
        Returns the PyMySQL cursor so callers can use .fetchone(),
        .fetchall(), and .lastrowid directly.
        """
        q = query.replace('?', '%s')
        q = q.replace(' COLLATE NOCASE', '').replace(' COLLATE nocase', '')
        cur = self.conn.cursor()
        cur.execute(q, params)
        return cur

    def executescript(self, script: str):
        """
        Execute multiple semicolon-separated DDL statements.
        Used exclusively by init_db() for table creation.
        Each statement is executed in its own cursor so MySQL
        does not complain about multi-statement calls.
        """
        cur = self.conn.cursor()
        for stmt in script.split(';'):
            stmt = stmt.strip()
            if stmt:
                cur.execute(stmt)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()


# ══════════════════════════════════════════════════════════════
#  CONNECTION FACTORY
# ══════════════════════════════════════════════════════════════
def get_conn() -> MySQLWrapper:
    """
    Open a fresh PyMySQL connection to MYSQL_DB.
    Creates the database if it does not already exist.
    Always uses DictCursor so rows are returned as dicts.
    Raises RuntimeError with a human-readable message on failure.
    """
    # Ensure the database itself exists (connect without selecting a DB)
    try:
        bootstrap = pymysql.connect(
            host=MYSQL_HOST, port=MYSQL_PORT,
            user=MYSQL_USER, password=MYSQL_PASSWORD,
            connect_timeout=10,
        )
        with bootstrap.cursor() as cur:
            cur.execute(
                f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
        bootstrap.commit()
        bootstrap.close()
    except pymysql.err.OperationalError as exc:
        raise RuntimeError(
            f"Cannot connect to MySQL at {MYSQL_HOST}:{MYSQL_PORT}. "
            f"Check MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD. "
            f"Original error: {exc}"
        ) from exc

    conn = pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DB,
        charset='utf8mb4',
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
    )
    return MySQLWrapper(conn)


# ══════════════════════════════════════════════════════════════
#  SCHEMA INITIALISATION
#  Safe to run on every startup — all statements use
#  CREATE TABLE IF NOT EXISTS / ALTER TABLE IF NOT EXISTS.
# ══════════════════════════════════════════════════════════════
def init_db():
    """Create all required tables and the default admin account."""
    conn = get_conn()
    try:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id              INT          PRIMARY KEY AUTO_INCREMENT,
                username        VARCHAR(150) NOT NULL UNIQUE,
                email           VARCHAR(255) NOT NULL UNIQUE,
                password_hash   VARCHAR(255) NOT NULL,
                created_at      VARCHAR(50)  NOT NULL,
                last_login_at   VARCHAR(50),
                last_logout_at  VARCHAR(50),
                last_jobtitle   VARCHAR(255),
                is_blocked      TINYINT      NOT NULL DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS admins (
                id              INT          PRIMARY KEY AUTO_INCREMENT,
                username        VARCHAR(150) NOT NULL UNIQUE,
                email           VARCHAR(255) NOT NULL UNIQUE,
                password_hash   VARCHAR(255) NOT NULL,
                created_at      VARCHAR(50)  NOT NULL,
                last_login_at   VARCHAR(50),
                last_logout_at  VARCHAR(50)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id             INT          PRIMARY KEY AUTO_INCREMENT,
                user_id        INT,
                job_title      VARCHAR(255) NOT NULL,
                experience     VARCHAR(50)  NOT NULL,
                questions_json LONGTEXT     NOT NULL,
                ratings_json   LONGTEXT     DEFAULT '{}',
                created_at     VARCHAR(50)  NOT NULL,
                CONSTRAINT fk_sessions_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS question_scores (
                id             INT          PRIMARY KEY AUTO_INCREMENT,
                session_id     INT          NOT NULL,
                question_index INT          NOT NULL,
                question_text  TEXT,
                score_label    VARCHAR(50),
                score_pct      INT,
                answered_at    VARCHAR(50)  NOT NULL,
                CONSTRAINT fk_qscores_session
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id         INT          PRIMARY KEY AUTO_INCREMENT,
                user_id    INT,
                admin_id   INT,
                token      VARCHAR(255) NOT NULL UNIQUE,
                otp        VARCHAR(50)  NOT NULL,
                expires_at VARCHAR(50)  NOT NULL,
                used       TINYINT      NOT NULL DEFAULT 0,
                created_at VARCHAR(50)  NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS user_activity_log (
                id          INT          PRIMARY KEY AUTO_INCREMENT,
                user_id     INT,
                admin_id    INT,
                is_admin    TINYINT      NOT NULL DEFAULT 0,
                action      VARCHAR(255),
                ip_address  VARCHAR(100),
                created_at  VARCHAR(50)  NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS resumes (
                id            INT          PRIMARY KEY AUTO_INCREMENT,
                user_id       INT          NOT NULL,
                filename      VARCHAR(255) NOT NULL,
                file_size     INT          DEFAULT 0,
                detected_role VARCHAR(255) DEFAULT '',
                ats_score     INT          DEFAULT 0,
                ats_report    LONGTEXT     DEFAULT '{}',
                resume_text   LONGTEXT     DEFAULT '',
                created_at    VARCHAR(50)  NOT NULL,
                CONSTRAINT fk_resumes_user
                    FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS account_deletions (
                id         INT          PRIMARY KEY AUTO_INCREMENT,
                user_id    INT          NOT NULL,
                username   VARCHAR(150) NOT NULL,
                email      VARCHAR(255),
                reasons    TEXT,
                comment    TEXT,
                deleted_at VARCHAR(50)  NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contact_requests (
                id           INT          PRIMARY KEY AUTO_INCREMENT,
                username     TEXT,
                email        TEXT,
                subject      VARCHAR(255),
                message      TEXT,
                request_type VARCHAR(100),
                status       VARCHAR(50)  DEFAULT 'pending',
                created_at   VARCHAR(50)  NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notifications (
                id                 INT          PRIMARY KEY AUTO_INCREMENT,
                type               VARCHAR(50),
                title              VARCHAR(255),
                message            TEXT,
                related_user       VARCHAR(150),
                related_request_id INT,
                is_read            TINYINT      DEFAULT 0,
                created_at         VARCHAR(50)  NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS registration_otps (
                id         INT          PRIMARY KEY AUTO_INCREMENT,
                username   VARCHAR(150) NOT NULL,
                email      VARCHAR(255) NOT NULL,
                otp        VARCHAR(50)  NOT NULL,
                expires_at VARCHAR(50)  NOT NULL,
                verified   TINYINT      NOT NULL DEFAULT 0,
                created_at VARCHAR(50)  NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        conn.commit()

        # Idempotent column additions — safe to run even if columns already exist
        _add_column_if_missing(conn, 'users',   'is_blocked',    'TINYINT NOT NULL DEFAULT 0')
        _add_column_if_missing(conn, 'users',   'last_jobtitle', 'VARCHAR(255)')
        _add_column_if_missing(conn, 'users',   'avatar_url',    'VARCHAR(255) DEFAULT NULL')
        _add_column_if_missing(conn, 'admins',  'last_login_at', 'VARCHAR(50)')
        _add_column_if_missing(conn, 'admins',  'last_logout_at','VARCHAR(50)')
        _add_column_if_missing(conn, 'admins',  'avatar_url',    'VARCHAR(255) DEFAULT NULL')
        _add_column_if_missing(conn, 'password_reset_tokens', 'admin_id', 'INT')

        conn.commit()
        _ensure_default_admin(conn)
        conn.commit()

    except Exception as exc:
        print(f"❌ init_db error: {exc}")
        raise
    finally:
        conn.close()

    print(f"✅ MySQL DB ready  [{MYSQL_DB}@{MYSQL_HOST}:{MYSQL_PORT}]")


def _add_column_if_missing(conn: MySQLWrapper, table: str, column: str, definition: str):
    """Add a column to a table only if it does not already exist."""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s",
        (MYSQL_DB, table, column)
    ).fetchone()
    if row and row['c'] == 0:
        conn.execute(f"ALTER TABLE `{table}` ADD COLUMN `{column}` {definition}")
        conn.commit()
        print(f"  ↳ Added column {table}.{column}")


def _ensure_default_admin(conn: MySQLWrapper):
    """Insert a default admin account if the admins table is empty."""
    count = conn.execute("SELECT COUNT(*) AS c FROM admins").fetchone()['c']
    if count == 0:
        conn.execute(
            "INSERT INTO admins (username, email, password_hash, created_at) "
            "VALUES (%s, %s, %s, %s)",
            ("admin", "admin@interviewai.local", _hash_password("Admin@1234"), _now_str())
        )
        conn.commit()
        print("✅ Default admin created  username=admin  password=Admin@1234")


# ══════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════
def _now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M')


def _hash_password(pw: str) -> str:
    try:
        from werkzeug.security import generate_password_hash
        return generate_password_hash(pw, method='pbkdf2:sha256', salt_length=16)
    except ImportError:
        salt = secrets.token_hex(16)
        h    = hashlib.sha256((salt + pw).encode()).hexdigest()
        return f"sha256${salt}${h}"


def _check_password(pw: str, stored: str) -> bool:
    try:
        from werkzeug.security import check_password_hash
        if stored.startswith(('pbkdf2:', 'scrypt:')):
            return check_password_hash(stored, pw)
    except ImportError:
        pass
    try:
        _, salt, h = stored.split('$', 2)
        return hashlib.sha256((salt + pw).encode()).hexdigest() == h
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
#  VALIDATION
# ══════════════════════════════════════════════════════════════
def validate_password(pw: str) -> list:
    errs = []
    if not pw:                                         errs.append('Password is required.')
    if len(pw) < 8:                                    errs.append('Password must be at least 8 characters.')
    if len(pw) > 128:                                  errs.append('Password must be at most 128 characters.')
    if pw != pw.strip():                               errs.append('Password must not have leading/trailing spaces.')
    if not any(c.isupper()  for c in pw):              errs.append('Password must contain at least one uppercase letter.')
    if not any(c.islower()  for c in pw):              errs.append('Password must contain at least one lowercase letter.')
    if not any(c.isdigit()  for c in pw):              errs.append('Password must contain at least one digit.')
    if not any(c in string.punctuation for c in pw):   errs.append('Password must contain at least one special character.')
    return errs


def validate_email(email: str) -> list:
    import re
    errs  = []
    email = email.strip()
    if not email:
        return ['Email is required.']
    if len(email) > 254:
        errs.append('Email is too long.')
    if ' ' in email:
        errs.append('Email must not contain spaces.')
    parts = email.split('@')
    if len(parts) != 2:
        errs.append('Email must contain exactly one @ symbol.')
    else:
        if not parts[0]: errs.append('Local part before @ must not be empty.')
        if not parts[1]: errs.append('Domain part after @ must not be empty.')
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', email):
        if 'Please enter a valid email address.' not in errs:
            errs.append('Please enter a valid email address.')
    return errs


# ══════════════════════════════════════════════════════════════
#  USER MANAGEMENT
# ══════════════════════════════════════════════════════════════
def create_user(username: str, email: str, password: str):
    errs = validate_password(password) + validate_email(email)
    if errs:
        return None, ' '.join(errs)
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (username.strip(), email.strip().lower(), _hash_password(password), _now_str())
        )
        user_id = cur.lastrowid
        conn.execute(
            "INSERT INTO notifications "
            "(type, title, message, related_user, created_at) VALUES (%s,%s,%s,%s,%s)",
            ('registration', 'New User Registration',
             f'User {username.strip()} just registered.', username.strip(), _now_str())
        )
        conn.commit()
        return user_id, None
    except pymysql.err.IntegrityError as exc:
        msg = str(exc).lower()
        if 'username' in msg: return None, 'Username already taken.'
        if 'email'    in msg: return None, 'Email already registered.'
        return None, 'Registration failed.'
    finally:
        conn.close()


def verify_user(login_id: str, password: str):
    """
    Authenticate a user by username or email.
    Returns (user_dict, None) on success,
            (None, 'blocked') if account is blocked,
            (None, None) on bad credentials.
    """
    login_id = login_id.strip()
    conn = get_conn()
    try:
        # Try username first (case-insensitive via utf8mb4_unicode_ci)
        row = conn.execute(
            "SELECT * FROM users WHERE username = %s", (login_id,)
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM users WHERE email = %s", (login_id.lower(),)
            ).fetchone()
        if not row or not _check_password(password, row['password_hash']):
            return None, None
        if row.get('is_blocked') == 1:
            return None, 'blocked'
        conn.execute(
            "UPDATE users SET last_login_at = %s WHERE id = %s",
            (_now_str(), row['id'])
        )
        conn.commit()
        return dict(row), None
    finally:
        conn.close()


def block_user(user_id: int):
    conn = get_conn()
    conn.execute("UPDATE users SET is_blocked = 1 WHERE id = %s", (user_id,))
    conn.commit(); conn.close()


def unblock_user(user_id: int):
    conn = get_conn()
    conn.execute("UPDATE users SET is_blocked = 0 WHERE id = %s", (user_id,))
    conn.commit(); conn.close()


def is_user_blocked(user_id: int) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT is_blocked FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    conn.close()
    return row is not None and row.get('is_blocked') == 1


def record_user_logout(user_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET last_logout_at = %s WHERE id = %s", (_now_str(), user_id)
    )
    conn.commit(); conn.close()


def update_user_jobtitle(user_id: int, jobtitle: str):
    conn = get_conn()
    conn.execute(
        "UPDATE users SET last_jobtitle = %s WHERE id = %s", (jobtitle, user_id)
    )
    conn.commit(); conn.close()


def get_user_by_id(user_id: int):
    conn = get_conn()
    row  = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM users WHERE email = %s", (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM users WHERE username = %s", (username.strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_password(user_id: int, new_password: str):
    errs = validate_password(new_password)
    if errs:
        return False, ' '.join(errs)
    conn = get_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE id = %s", (user_id,)
    ).fetchone()
    if row and _check_password(new_password, row['password_hash']):
        conn.close()
        return False, "New password must be different from your current password."
    conn.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (_hash_password(new_password), user_id)
    )
    conn.commit(); conn.close()
    return True, None


def update_user_profile(user_id: int, new_username: str = None, new_email: str = None,
                        current_password: str = None, new_password: str = None):
    """Update username, email and/or password. Requires current_password for credential changes."""
    import re
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return False, "User not found."

    if current_password is not None:
        if not _check_password(current_password, user['password_hash']):
            conn.close()
            return False, "Current password is incorrect."

    updates = []
    params  = []

    if new_username and new_username.strip() != user['username']:
        nu = new_username.strip()
        if len(nu) < 3 or not re.match(r'^[A-Za-z0-9_]+$', nu):
            conn.close()
            return False, "Username must be at least 3 chars, letters/numbers/underscores only."
        existing = conn.execute(
            "SELECT id FROM users WHERE username = %s AND id != %s", (nu, user_id)
        ).fetchone()
        if existing:
            conn.close()
            return False, "Username already taken."
        updates.append("username = %s"); params.append(nu)

    if new_email and new_email.strip().lower() != user['email']:
        ne = new_email.strip().lower()
        errs = validate_email(ne)
        if errs:
            conn.close()
            return False, errs[0]
        existing = conn.execute(
            "SELECT id FROM users WHERE email = %s AND id != %s", (ne, user_id)
        ).fetchone()
        if existing:
            conn.close()
            return False, "Email already in use."
        updates.append("email = %s"); params.append(ne)

    if new_password:
        errs = validate_password(new_password)
        if errs:
            conn.close()
            return False, errs[0]
        if _check_password(new_password, user['password_hash']):
            conn.close()
            return False, "New password must be different from your current password."
        updates.append("password_hash = %s"); params.append(_hash_password(new_password))

    if not updates:
        conn.close()
        return True, "No changes made."

    params.append(user_id)
    conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = %s", params)
    conn.commit(); conn.close()
    return True, "Profile updated successfully."


def get_user_detail(user_id: int):
    """Full user profile + sessions + job-role history for the admin detail panel."""
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return None
    ud = dict(user)
    ud.pop('password_hash', None)
    sessions = conn.execute(
        "SELECT id, job_title, experience, created_at FROM sessions "
        "WHERE user_id = %s ORDER BY id DESC",
        (user_id,)
    ).fetchall()
    ud['sessions'] = [dict(s) for s in sessions]
    roles = conn.execute(
        "SELECT job_title, COUNT(*) AS count, "
        "MIN(created_at) AS first_at, MAX(created_at) AS last_at "
        "FROM sessions WHERE user_id = %s "
        "GROUP BY job_title ORDER BY last_at DESC",
        (user_id,)
    ).fetchall()
    ud['job_roles'] = [dict(r) for r in roles]
    conn.close()
    return ud


def delete_user(user_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM user_activity_log WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM users WHERE id = %s", (user_id,))
    conn.commit(); conn.close()


def delete_user_account(user_id: int, reasons: list, comment: str = "") -> tuple:
    """
    Self-deletion flow.
    Logs the deletion reason for auditing, then purges all user data.
    Returns (True, '') on success or (False, error_msg).
    """
    conn = get_conn()
    user = conn.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
    if not user:
        conn.close()
        return False, "Account not found."
    reasons_str = ", ".join(reasons) if reasons else "No reason given"
    conn.execute(
        "INSERT INTO account_deletions "
        "(user_id, username, email, reasons, comment, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (user_id, user['username'], user.get('email', ''),
         reasons_str, (comment or '').strip(), _now_str())
    )
    conn.execute(
        "DELETE FROM question_scores WHERE session_id IN "
        "(SELECT id FROM sessions WHERE user_id = %s)",
        (user_id,)
    )
    conn.execute("DELETE FROM sessions WHERE user_id = %s",              (user_id,))
    conn.execute("DELETE FROM user_activity_log WHERE user_id = %s",     (user_id,))
    conn.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
    conn.execute("DELETE FROM resumes WHERE user_id = %s",               (user_id,))
    conn.execute("DELETE FROM users WHERE id = %s",                      (user_id,))
    conn.commit(); conn.close()
    return True, ""


def get_all_users_with_stats():
    conn  = get_conn()
    users = conn.execute(
        "SELECT id, username, email, created_at, last_login_at, last_logout_at, "
        "last_jobtitle, is_blocked, avatar_url FROM users ORDER BY id DESC"
    ).fetchall()
    result = []
    for u in users:
        ud = dict(u)
        ud['total_sessions'] = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE user_id = %s", (u['id'],)
        ).fetchone()['c']
        result.append(ud)
    conn.close()
    return result


# ══════════════════════════════════════════════════════════════
#  ADMIN MANAGEMENT
# ══════════════════════════════════════════════════════════════
def verify_admin(username: str, password: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM admins WHERE username = %s", (username.strip(),)
    ).fetchone()
    if row and _check_password(password, row['password_hash']):
        conn.execute(
            "UPDATE admins SET last_login_at = %s WHERE id = %s",
            (_now_str(), row['id'])
        )
        conn.commit()
        conn.close()
        return dict(row)
    conn.close()
    return None


def record_admin_logout(admin_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE admins SET last_logout_at = %s WHERE id = %s", (_now_str(), admin_id)
    )
    conn.commit(); conn.close()


def get_admin_by_id(admin_id: int):
    conn = get_conn()
    row  = conn.execute("SELECT * FROM admins WHERE id = %s", (admin_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_admin_by_email(email: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM admins WHERE email = %s", (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_admin_by_username(username: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM admins WHERE username = %s", (username.strip(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_username_email_match(username: str, email: str, is_admin: bool = False):
    """Return the account only if username AND email both match the same row."""
    username = username.strip()
    email    = email.strip().lower()
    if not username or not email:
        return None
    conn  = get_conn()
    table = "admins" if is_admin else "users"
    row   = conn.execute(
        f"SELECT * FROM `{table}` WHERE username = %s AND email = %s",
        (username, email)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_admin_stats():
    conn = get_conn()
    total_users    = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()['c']
    total_sessions = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()['c']
    total_answers  = conn.execute("SELECT COUNT(*) AS c FROM question_scores").fetchone()['c']
    conn.close()
    return {
        'total_users':    total_users,
        'total_sessions': total_sessions,
        'total_answers':  total_answers,
    }


def update_admin_password(admin_id: int, new_password: str):
    errs = validate_password(new_password)
    if errs:
        return False, errs[0]
    conn = get_conn()
    row = conn.execute(
        "SELECT password_hash FROM admins WHERE id = %s", (admin_id,)
    ).fetchone()
    if row and _check_password(new_password, row['password_hash']):
        conn.close()
        return False, "New password must be different from your current password."
    conn.execute(
        "UPDATE admins SET password_hash = %s WHERE id = %s",
        (_hash_password(new_password), admin_id)
    )
    conn.commit(); conn.close()
    return True, None


def admin_reset_user_password(user_id: int, new_password: str):
    errs = validate_password(new_password)
    if errs:
        return False, errs[0]
    conn = get_conn()
    conn.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (_hash_password(new_password), user_id)
    )
    conn.commit(); conn.close()
    return True, None


def update_admin_profile(admin_id: int, current_password: str = None,
                         new_username: str = None, new_email: str = None,
                         new_password: str = None):
    import re
    conn  = get_conn()
    admin = conn.execute("SELECT * FROM admins WHERE id = %s", (admin_id,)).fetchone()
    if not admin:
        conn.close()
        return False, "Admin not found."

    if current_password is not None:
        if not _check_password(current_password, admin['password_hash']):
            conn.close()
            return False, "Current password is incorrect."

    updates = []
    params  = []

    if new_username and new_username.strip() != admin['username']:
        nu = new_username.strip()
        if len(nu) < 3 or not re.match(r'^[A-Za-z0-9_]+$', nu):
            conn.close()
            return False, "Username must be at least 3 chars."
        existing = conn.execute(
            "SELECT id FROM admins WHERE username = %s AND id != %s", (nu, admin_id)
        ).fetchone()
        if existing:
            conn.close()
            return False, "Username already taken."
        updates.append("username = %s"); params.append(nu)

    if new_email and new_email.strip().lower() != admin['email']:
        ne = new_email.strip().lower()
        errs = validate_email(ne)
        if errs:
            conn.close()
            return False, errs[0]
        existing = conn.execute(
            "SELECT id FROM admins WHERE email = %s AND id != %s", (ne, admin_id)
        ).fetchone()
        if existing:
            conn.close()
            return False, "Email already in use."
        updates.append("email = %s"); params.append(ne)

    if new_password:
        errs = validate_password(new_password)
        if errs:
            conn.close()
            return False, errs[0]
        updates.append("password_hash = %s"); params.append(_hash_password(new_password))

    if not updates:
        conn.close()
        return True, "No changes made."

    params.append(admin_id)
    conn.execute(f"UPDATE admins SET {', '.join(updates)} WHERE id = %s", params)
    conn.commit(); conn.close()
    return True, "Profile updated."


# ══════════════════════════════════════════════════════════════
#  REGISTRATION OTP
# ══════════════════════════════════════════════════════════════
def save_registration_otp(username: str, email: str, otp: str, expires_at: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO registration_otps "
        "(username, email, otp, expires_at, created_at) VALUES (%s, %s, %s, %s, %s)",
        (username.strip(), email.strip().lower(), otp, expires_at, _now_str())
    )
    conn.commit(); conn.close()


def get_registration_otp(email: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM registration_otps WHERE email = %s ORDER BY id DESC LIMIT 1",
        (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_registration_otp_verified(otp_id: int):
    conn = get_conn()
    conn.execute("UPDATE registration_otps SET verified = 1 WHERE id = %s", (otp_id,))
    conn.commit(); conn.close()


def delete_registration_otps(email: str):
    conn = get_conn()
    conn.execute(
        "DELETE FROM registration_otps WHERE email = %s", (email.strip().lower(),)
    )
    conn.commit(); conn.close()


# ══════════════════════════════════════════════════════════════
#  PASSWORD RESET TOKENS
# ══════════════════════════════════════════════════════════════
def generate_reset_token(user_id: int = None, admin_id: int = None):
    token   = secrets.token_urlsafe(32)
    otp     = ''.join(secrets.choice(string.digits) for _ in range(6))
    expires = (datetime.now() + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
    conn    = get_conn()
    if user_id:
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE user_id = %s AND used = 0",
            (user_id,)
        )
    if admin_id:
        conn.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE admin_id = %s AND used = 0",
            (admin_id,)
        )
    conn.execute(
        "INSERT INTO password_reset_tokens "
        "(user_id, admin_id, token, otp, expires_at, used, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 0, %s)",
        (user_id, admin_id, token, otp, expires, _now_str())
    )
    conn.commit(); conn.close()
    return token, otp


def verify_reset_otp(token: str, otp: str):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM password_reset_tokens WHERE token = %s AND used = 0", (token,)
    ).fetchone()
    conn.close()
    if not row:                                                       return None, None
    if row['otp'] != otp.strip():                                     return None, None
    if datetime.now() > datetime.strptime(row['expires_at'], '%Y-%m-%d %H:%M:%S'):
        return None, None
    return row['user_id'], row['admin_id']


def consume_reset_token(token: str):
    conn = get_conn()
    conn.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = %s", (token,))
    conn.commit(); conn.close()


# ══════════════════════════════════════════════════════════════
#  INTERVIEW SESSIONS
# ══════════════════════════════════════════════════════════════
def save_session(job_title: str, experience: str, questions_json: str,
                 user_id: int = None) -> int:
    if user_id:
        if not get_user_by_id(user_id):
            user_id = None
    conn = get_conn()
    cur  = conn.execute(
        "INSERT INTO sessions (user_id, job_title, experience, questions_json, created_at) "
        "VALUES (%s, %s, %s, %s, %s)",
        (user_id, job_title, experience, questions_json, _now_str())
    )
    sid = cur.lastrowid
    conn.commit(); conn.close()
    if user_id:
        update_user_jobtitle(user_id, job_title)
    return sid


def get_history(limit: int = 50, user_id: int = None) -> list:
    conn = get_conn()
    if user_id:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE user_id = %s ORDER BY id DESC LIMIT %s",
            (user_id, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY id DESC LIMIT %s", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_session(session_id: int, user_id: int = None):
    conn = get_conn()
    if user_id:
        conn.execute(
            "DELETE FROM sessions WHERE id = %s AND user_id = %s", (session_id, user_id)
        )
    else:
        conn.execute("DELETE FROM sessions WHERE id = %s", (session_id,))
    conn.execute("DELETE FROM question_scores WHERE session_id = %s", (session_id,))
    conn.commit(); conn.close()


def clear_history(user_id: int = None):
    conn = get_conn()
    if user_id:
        ids = conn.execute(
            "SELECT id FROM sessions WHERE user_id = %s", (user_id,)
        ).fetchall()
        for r in ids:
            conn.execute(
                "DELETE FROM question_scores WHERE session_id = %s", (r['id'],)
            )
        conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    else:
        conn.execute("DELETE FROM question_scores")
        conn.execute("DELETE FROM sessions")
    conn.commit(); conn.close()


def rate_question(session_id: int, question_index: int, rating, user_id: int = None):
    conn = get_conn()
    if user_id:
        row = conn.execute(
            "SELECT ratings_json FROM sessions WHERE id = %s AND user_id = %s",
            (session_id, user_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT ratings_json FROM sessions WHERE id = %s", (session_id,)
        ).fetchone()
    if not row:
        conn.close(); return
    ratings = json.loads(row['ratings_json'] or '{}')
    ratings[str(question_index)] = rating
    conn.execute(
        "UPDATE sessions SET ratings_json = %s WHERE id = %s",
        (json.dumps(ratings), session_id)
    )
    conn.commit(); conn.close()


# ══════════════════════════════════════════════════════════════
#  QUESTION SCORES
# ══════════════════════════════════════════════════════════════
def save_question_score(session_id: int, question_index: int, question_text: str,
                        score_label: str, score_pct: int):
    conn = get_conn()
    now  = _now_str()
    ex   = conn.execute(
        "SELECT id FROM question_scores WHERE session_id = %s AND question_index = %s",
        (session_id, question_index)
    ).fetchone()
    if ex:
        conn.execute(
            "UPDATE question_scores "
            "SET score_label = %s, score_pct = %s, answered_at = %s, question_text = %s "
            "WHERE id = %s",
            (score_label, score_pct, now, question_text, ex['id'])
        )
    else:
        conn.execute(
            "INSERT INTO question_scores "
            "(session_id, question_index, question_text, score_label, score_pct, answered_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (session_id, question_index, question_text, score_label, score_pct, now)
        )
    conn.commit(); conn.close()


def get_question_scores(session_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM question_scores WHERE session_id = %s ORDER BY question_index",
        (session_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════
#  RESUMES
# ══════════════════════════════════════════════════════════════
def save_resume(user_id: int, filename: str, file_size: int,
                resume_text: str, detected_role: str,
                ats_score: int, ats_report: str) -> int:
    if not get_user_by_id(user_id):
        raise ValueError("User does not exist")
    conn = get_conn()
    cur  = conn.execute(
        "INSERT INTO resumes "
        "(user_id, filename, file_size, detected_role, ats_score, ats_report, resume_text, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (user_id, filename, file_size, detected_role, ats_score, ats_report, resume_text, _now_str())
    )
    rid = cur.lastrowid
    conn.commit(); conn.close()
    return rid


def get_resume(resume_id: int, user_id: int):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM resumes WHERE id = %s AND user_id = %s", (resume_id, user_id)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_resumes(user_id: int) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, filename, file_size, detected_role, ats_score, created_at "
        "FROM resumes WHERE user_id = %s ORDER BY id DESC LIMIT 10",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_resume(resume_id: int, user_id: int):
    conn = get_conn()
    conn.execute(
        "DELETE FROM resumes WHERE id = %s AND user_id = %s", (resume_id, user_id)
    )
    conn.commit(); conn.close()


def create_admin_notification(notif_type: str, title: str, message: str, related_user: str = None, related_request_id: int = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO notifications "
        "(type, title, message, related_user, related_request_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (notif_type.strip(), title.strip(), message.strip(), related_user, related_request_id, _now_str())
    )
    conn.commit()
    conn.close()


def create_contact_request(username: str, email: str, subject: str,
                           message: str, request_type: str) -> int:
    conn = get_conn()
    cur  = conn.execute(
        "INSERT INTO contact_requests "
        "(username, email, subject, message, request_type, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (username.strip(), email.strip(), subject.strip(),
         message.strip(), request_type, _now_str())
    )
    req_id = cur.lastrowid
    conn.execute(
        "INSERT INTO notifications "
        "(type, title, message, related_user, related_request_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        ('contact', f'New {request_type}',
         f'From {username.strip()}: {subject.strip()}',
         username.strip(), req_id, _now_str())
    )
    conn.commit(); conn.close()
    return req_id


def get_admin_notifications() -> list:
    conn  = get_conn()
    rows  = conn.execute(
        "SELECT * FROM notifications ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_notification_read(notif_id: int):
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (notif_id,))
    conn.commit(); conn.close()


def delete_admin_notification(notif_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM notifications WHERE id = %s", (notif_id,))
    conn.commit(); conn.close()


def resolve_contact_request(req_id: int):
    conn = get_conn()
    conn.execute(
        "UPDATE contact_requests SET status = 'resolved' WHERE id = %s", (req_id,)
    )
    conn.commit(); conn.close()


def get_contact_request(req_id: int):
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM contact_requests WHERE id = %s", (req_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ══════════════════════════════════════════════════════════════
#  WEEKLY STATS (per-user or global)
# ══════════════════════════════════════════════════════════════
def get_weekly_stats(user_id: int = None) -> list:
    """
    Returns a 7-day activity summary.
    Dates are matched via LIKE on the VARCHAR created_at / answered_at columns
    (stored as 'YYYY-MM-DD HH:MM'), which is fast enough for typical data volumes.
    """
    conn  = get_conn()
    today = datetime.now().date()
    days  = [(today - timedelta(days=i)) for i in range(6, -1, -1)]
    result = []

    for day in days:
        ds = day.strftime('%Y-%m-%d')

        if user_id:
            sc = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions s "
                "WHERE s.user_id = %s AND s.created_at LIKE %s",
                (user_id, ds + '%')
            ).fetchone()['c']

            ar = conn.execute(
                "SELECT COUNT(*) AS c, AVG(qs.score_pct) AS a "
                "FROM question_scores qs JOIN sessions s ON qs.session_id = s.id "
                "WHERE s.user_id = %s AND qs.answered_at LIKE %s",
                (user_id, ds + '%')
            ).fetchone()

            def cnt(lbl):
                return conn.execute(
                    "SELECT COUNT(*) AS c "
                    "FROM question_scores qs JOIN sessions s ON qs.session_id = s.id "
                    "WHERE s.user_id = %s AND qs.answered_at LIKE %s AND qs.score_label = %s",
                    (user_id, ds + '%', lbl)
                ).fetchone()['c']
        else:
            sc = conn.execute(
                "SELECT COUNT(*) AS c FROM sessions s WHERE s.created_at LIKE %s",
                (ds + '%',)
            ).fetchone()['c']

            ar = conn.execute(
                "SELECT COUNT(*) AS c, AVG(qs.score_pct) AS a "
                "FROM question_scores qs JOIN sessions s ON qs.session_id = s.id "
                "WHERE qs.answered_at LIKE %s",
                (ds + '%',)
            ).fetchone()

            def cnt(lbl):
                return conn.execute(
                    "SELECT COUNT(*) AS c "
                    "FROM question_scores qs JOIN sessions s ON qs.session_id = s.id "
                    "WHERE qs.answered_at LIKE %s AND qs.score_label = %s",
                    (ds + '%', lbl)
                ).fetchone()['c']

        result.append({
            'date':       ds,
            'label':      day.strftime('%a'),
            'sessions':   sc,
            'answered':   ar['c'] or 0,
            'avg_score':  round(ar['a'] or 0),
            'excellent':  cnt('Excellent'),
            'good':       cnt('Good'),
            'partial':    cnt('Partial'),
            'needs_work': cnt('Needs Work'),
        })

    conn.close()
    return result


def update_user_avatar(user_id: int, avatar_url: str):
    conn = get_conn()
    conn.execute("UPDATE users SET avatar_url = %s WHERE id = %s", (avatar_url, user_id))
    conn.commit(); conn.close()


def update_admin_avatar(admin_id: int, avatar_url: str):
    conn = get_conn()
    conn.execute("UPDATE admins SET avatar_url = %s WHERE id = %s", (avatar_url, admin_id))
    conn.commit(); conn.close()

