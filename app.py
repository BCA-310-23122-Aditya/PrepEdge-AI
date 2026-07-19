"""
app.py — PrepEdgeAI Flask backend (Enhanced)
All features: auth, admin auth, forgot-password OTP, question gen, mock eval,
              session history, PDF export, email report, weekly stats,
              admin dashboard, profile editing, admin forgot password.
"""
from flask import (Flask, render_template, request, jsonify, send_file,
                   redirect, url_for, flash, session as flask_session)
from generator import generate_questions
from database  import (
    init_db, get_conn,
    create_user, verify_user, get_user_by_id, get_user_by_email,
    get_user_by_username, update_password, update_user_profile,
    validate_password, validate_email,
    generate_reset_token, verify_reset_otp, consume_reset_token,
    save_session, get_history, delete_session, clear_history, rate_question,
    save_question_score, get_question_scores, get_weekly_stats,
    record_user_logout, delete_user, get_user_detail, delete_user_account,
    save_resume, get_resume, get_user_resumes, delete_resume,
    # Admin
    verify_admin, get_admin_by_id, get_admin_by_email, get_admin_by_username,
    get_admin_stats, get_all_users_with_stats,
    update_admin_password, admin_reset_user_password, update_admin_profile,
    record_admin_logout, verify_username_email_match,is_user_blocked, block_user, unblock_user,
    create_contact_request, get_admin_notifications, mark_notification_read, delete_admin_notification,
    resolve_contact_request, get_contact_request,
    update_user_avatar, update_admin_avatar, create_admin_notification
)
from resume_analyzer import (
    extract_resume_text, detect_roles, run_ats_analysis, TECH_KEYWORDS
)
from email_utils import send_report_email
import json, io, re, os
from datetime import datetime, timedelta, timezone
from functools import wraps

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                    Table, TableStyle, HRFlowable)
    from reportlab.lib.enums import TA_CENTER
except ImportError:
    pass

# ── Load .env ──────────────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    import pathlib
    _base = pathlib.Path(__file__).parent
    # Support both ".env" and "_env" filenames
    _env_file = None
    for _candidate in [".env", "_env", ".env.local"]:
        _p = _base / _candidate
        if _p.exists():
            _env_file = _p
            break
    if _env_file:
        load_dotenv(dotenv_path=_env_file, override=True)
        print(f"✅ Loaded env from: {_env_file.name}")
    else:
        load_dotenv(override=True)   # fallback: search default locations
        print("✅ .env loaded (default search)")
except ImportError:
    print("⚠️  python-dotenv not installed — set env vars manually")

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "interviewai-secret-change-in-prod")
init_db()

@app.before_request
def check_blocked_user():
    if 'user_id' in flask_session:
        uid = flask_session['user_id']
        if is_user_blocked(uid):
            flask_session.clear()
            flash("Your account has been temporarily blocked. Please contact the administrator.", "error")
            return redirect(url_for('login'))

# ── API Keys ───────────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY",   "")

# ── AI clients ─────────────────────────────────────────────────────────────────
_groq_eval = None
try:
    from groq import Groq
    if GROQ_API_KEY:
        _groq_eval = Groq(api_key=GROQ_API_KEY)
        print("✅ Groq eval ready")
except Exception as e:
    print(f"⚠️  Groq init: {e}")

_gemini_eval = None
try:
    from google import genai as _gai
    if GEMINI_API_KEY:
        _gemini_eval = _gai.Client(api_key=GEMINI_API_KEY)
        print("✅ Gemini eval ready")
except Exception as e:
    print(f"⚠️  Gemini init: {e}")


# ══════════════════════════════════════════════════════════════
#  IST TIMEZONE HELPER
# ══════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))

def to_ist(dt_str):
    """Convert stored datetime string to IST formatted string."""
    if not dt_str:
        return None
    try:
        dt = datetime.strptime(str(dt_str).strip(), '%Y-%m-%d %H:%M')
    except Exception:
        try:
            dt = datetime.strptime(str(dt_str).strip(), '%Y-%m-%d %H:%M:%S')
        except Exception:
            return str(dt_str)
    return dt.strftime('%d %b %Y, %I:%M %p IST')

app.jinja_env.globals['to_ist'] = to_ist


# ══════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        uid = get_uid()
        if not uid or not get_user_by_id(uid):
            flask_session.clear()
            flash("Please log in to continue.", "info")
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        aid = get_aid()
        if not aid or not get_admin_by_id(aid):
            flask_session.clear()
            flash("Admin access required.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def get_uid():
    return flask_session.get("user_id")

def get_aid():
    return flask_session.get("admin_id")

def current_user():
    uid = get_uid()
    return get_user_by_id(uid) if uid else None

def current_admin():
    aid = get_aid()
    return get_admin_by_id(aid) if aid else None


# ══════════════════════════════════════════════════════════════
#  AI EVAL HELPERS
# ══════════════════════════════════════════════════════════════
_BLOCKED_TERMS = {
    # profanity / abusive
    "fuck","porn","sex","adult","shit","ass","asshole","bitch","cunt","dick","pussy","cock","bastard",
    "motherfucker","faggot","nigger","nigga","retard","whore","slut","piss","crap",
    "damn","hell","bollocks","twat","wanker","tosser","prick","arsehole",
    # generic nonsense / test inputs
    "test","asdf","qwerty","zxcv","aaaa","bbbb","cccc","1234","abcd","xxxx","yyyy",
    "asdfjkl","jjjj","kkkk","llll","hahaha","lolol","xoxo","blah","bleh","meh",
    "foo","bar","baz","qux","dummy","fake","temp","none","null","undefined","nope",
    # not a job title
    "idk","lol","lmao","wtf","omg","bruh","yolo","swag","admin","delete","drop",
    "select","insert","update","table","script","alert","hack","password","login",
}


# Professional keywords for job title validation (non-exhaustive but covers most roles)
PROFESSIONAL_KEYWORDS = {
    'engineer', 'developer', 'programmer', 'coder', 'architect', 'designer',
    'manager', 'director', 'executive', 'officer', 'lead', 'supervisor',
    'coordinator', 'specialist', 'analyst', 'consultant', 'advisor',
    'administrator', 'associate', 'assistant', 'representative', 'agent',
    'planner', 'scheduler', 'dispatcher', 'operator', 'technician',
    'mechanic', 'electrician', 'plumber', 'carpenter', 'welder', 'chef',
    'cook', 'baker', 'server', 'bartender', 'cashier', 'driver', 'pilot',
    'attendant', 'nurse', 'doctor', 'physician', 'surgeon', 'therapist',
    'counselor', 'psychologist', 'teacher', 'professor', 'instructor',
    'trainer', 'librarian', 'artist', 'writer', 'editor', 'journalist',
    'photographer', 'scientist', 'researcher', 'analyst', 'specialist',
    'coordinator', 'supervisor', 'principal', 'staff', 'clerk', 'worker',
    'laborer', 'helper', 'operator', 'technician', 'engineer', 'developer',
    'programmer', 'coder', 'architect', 'designer', 'manager', 'director',
    'executive', 'officer', 'lead', 'supervisor', 'coordinator', 'specialist',
    'analyst', 'consultant', 'advisor', 'administrator', 'associate',
    'assistant', 'representative', 'agent', 'planner', 'scheduler',
    'dispatcher', 'operator', 'technician', 'mechanic', 'electrician',
    'plumber', 'carpenter', 'welder', 'chef', 'cook', 'baker', 'server',
    'bartender', 'cashier', 'driver', 'pilot', 'attendant', 'nurse',
    'doctor', 'physician', 'surgeon', 'therapist', 'counselor',
    'psychologist', 'teacher', 'professor', 'instructor', 'trainer',
    'librarian', 'artist', 'writer', 'editor', 'journalist', 'photographer',
    'scientist', 'researcher', 'analyst', 'specialist', 'coordinator',
    'supervisor', 'principal', 'staff', 'clerk', 'worker', 'laborer',
    'helper', 'operator', 'technician', 'engineer', 'developer',
    'programmer', 'coder', 'architect', 'designer', 'manager',
    # additional common roles
    'product', 'project', 'program', 'quality', 'data', 'software',
    'hardware', 'network', 'system', 'database', 'cloud', 'devops',
    'security', 'support', 'sales', 'marketing', 'hr', 'human resources',
    'finance', 'account', 'legal', 'operations', 'logistics', 'supply',
    'procurement', 'research', 'science', 'tech', 'technology',
}

# Single-word professional roles that are acceptable alone
SINGLE_WORD_ROLES = {
    'doctor', 'lawyer', 'teacher', 'nurse', 'engineer', 'analyst',
    'designer', 'developer', 'manager', 'director', 'executive', 'officer',
    'lead', 'supervisor', 'coordinator', 'specialist', 'consultant',
    'advisor', 'administrator', 'associate', 'assistant', 'representative',
    'agent', 'planner', 'scheduler', 'dispatcher', 'operator', 'technician',
    'mechanic', 'electrician', 'plumber', 'carpenter', 'welder', 'chef',
    'cook', 'baker', 'server', 'bartender', 'cashier', 'driver', 'pilot',
    'attendant', 'nurse', 'doctor', 'physician', 'surgeon', 'therapist',
    'counselor', 'psychologist', 'teacher', 'professor', 'instructor',
    'trainer', 'librarian', 'artist', 'writer', 'editor', 'journalist',
    'photographer', 'scientist', 'researcher',
}

def is_valid_job_title(title: str) -> tuple[bool, str]:
    """
    Returns (is_valid: bool, reason: str).
    Validates that the job title is a professional role (not random text or test input).
    """
    t = title.strip()

    if len(t) < 3:
        return False, "Job title must be at least 3 characters."
    if len(t) > 80:
        return False, "Job title must be less than 80 characters."

    # Minimum alphabetic characters
    alpha_chars = re.sub(r"[^A-Za-z]", "", t)
    if len(alpha_chars) < 3:
        return False, "Job title must contain at least 3 letters."

    # Allowed characters: letters, numbers, spaces, and symbols: / + - . # ( ) & , _
    if not re.fullmatch(r"[A-Za-z0-9\s/\+\-\.#\(\)&,_']+", t):
        return False, "Job title contains unsupported characters. Use letters, numbers and common symbols."

    # Block repetitive characters (keyboard mash)
    if re.search(r"(.)\1{3,}", t.lower()):
        return False, "Please enter a valid job title."

    # Block high-entropy random strings (no vowels in long word)
    words = re.findall(r"[A-Za-z]{4,}", t)
    for w in words:
        wl = w.lower()
        if not re.search(r"[aeiou]", wl) and len(wl) >= 5:
            return False, "Please enter a meaningful job title."

    # Block profanity / test words (using existing _BLOCKED_TERMS)
    t_lower = t.lower()
    for term in _BLOCKED_TERMS:
        if re.search(r"\b" + re.escape(term) + r"\b", t_lower):
            return False, "Please enter an appropriate and meaningful job title."

    # --- Professional role validation ---
    # Split into words and check for at least one professional keyword
    words_lower = re.findall(r"[A-Za-z]+", t_lower)
    found_keyword = False
    for w in words_lower:
        if w in PROFESSIONAL_KEYWORDS:
            found_keyword = True
            break
        # Also check if any multi-word phrase matches a keyword (e.g., "human resources")
        # Simple: join all words and check against set
    if not found_keyword:
        # Try whole title as a single token if it's short and in SINGLE_WORD_ROLES
        if t_lower in SINGLE_WORD_ROLES:
            found_keyword = True
        else:
            return False, "Please enter a real professional job role (e.g., 'Software Engineer', 'Data Analyst', 'Marketing Manager')."

    # Additional check: if the title is too generic like "Worker" but that is accepted? Let's allow.
    # Optionally require at least two words unless it's a recognized single-word role.
    if len(words_lower) < 2 and t_lower not in SINGLE_WORD_ROLES:
        # This catches "Developer" (which is in SINGLE_WORD_ROLES) but allows it.
        # For "Engineer" -> allowed. For "Person" -> blocked because not in set.
        return False, "Please be more specific. Job titles like 'Software Engineer' are preferred."

    return True, ""


def _parse_eval_json(raw):
    raw = raw.strip()
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"^```\s*",     "", raw)
    raw = re.sub(r"\s*```$",     "", raw)
    return json.loads(raw)

def _generate_ideal_from_hint(question, hint):
    hc = hint.strip().rstrip(".")
    qc = question.strip().rstrip("?")
    return (
        f"To answer this question well, I would first explain the core concept clearly. "
        f"{hc}. In practice, this means structuring your response with a clear definition, "
        f"followed by a real example from your experience. For instance, when asked '{qc}', "
        f"a strong candidate would also discuss the trade-offs, limitations, and relate it "
        f"back to the specific role and how it adds value professionally."
    )

def _build_result(result, hint, question=""):
    color_map = {"Excellent":"green","Good":"blue","Partial":"amber","Needs Work":"red"}
    score = result.get("score", "Partial")
    tip   = result.get("tip", hint)
    ideal = result.get("ideal_answer", "").strip()
    if not ideal or len(ideal) < 40 or ideal.lower() == tip.lower():
        ideal = _generate_ideal_from_hint(question, hint)
    return {
        "score":        score,
        "color":        color_map.get(score, "gray"),
        "percent":      max(0, min(100, int(result.get("percent", 50)))),
        "feedback":     result.get("feedback", ""),
        "tip":          tip,
        "ideal_answer": ideal,
    }

EVAL_PROMPT = """You are an expert interview coach evaluating a candidate's spoken answer.

Question: {question}
Key points to cover (hint): {hint}
Candidate's spoken answer: {answer}

Respond ONLY with a valid JSON object — no markdown, no code fences.
{{
  "score":        one of "Excellent" | "Good" | "Partial" | "Needs Work",
  "percent":      integer 0-100,
  "feedback":     "2-3 sentences analysing the candidate's actual answer",
  "tip":          "ONE short coaching sentence for next time",
  "ideal_answer": "Complete ideal spoken answer — 5-7 sentences"
}}"""

def _eval_with_groq(prompt):
    if not _groq_eval: return None
    try:
        r = _groq_eval.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role":"user","content":prompt}],
            temperature=0.4, max_tokens=600)
        return _parse_eval_json(r.choices[0].message.content)
    except Exception as e:
        print(f"⚠️  Groq eval: {e}"); return None

def _eval_with_gemini(prompt):
    if not _gemini_eval: return None
    try:
        r = _gemini_eval.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        return _parse_eval_json(r.text)
    except Exception as e:
        print(f"⚠️  Gemini eval: {e}"); return None

def _local_eval(question, hint, answer):
    al = answer.lower(); hl = hint.lower()
    sw = {"a","an","the","is","are","was","were","be","been","have","has","do","does",
          "will","would","should","may","can","to","of","in","on","at","by","for",
          "with","and","or","but","if","that","this","it","you","they"}
    hw = [w for w in re.findall(r"[a-z]+", hl) if len(w)>3 and w not in sw]
    matched = sum(1 for w in hw if w in al) if hw else 1
    pct = min(int((matched / (len(hw) or 1)) * 100), 78)
    score, color = (("Good","blue") if pct>=65 else ("Partial","amber") if pct>=40 else ("Needs Work","red"))
    return {
        "score":score,"color":color,"percent":pct,
        "feedback":"AI evaluation temporarily unavailable. Score based on keyword matching.",
        "tip":f"Next time, mention key concepts like: {hint[:150]}.",
        "ideal_answer":_generate_ideal_from_hint(question, hint),
    }

from email_utils import send_registration_otp_email
import secrets
from datetime import datetime, timedelta

@app.route("/send-register-otp", methods=["POST"])
def send_register_otp():
    try:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        email = data.get("email", "").strip().lower()
        allow_unrecommended = data.get("allow_unrecommended_email", False)

        if not username or not email:
            return jsonify({"error": "Username and email are required."}), 400

        # Structural validation
        if " " in email:
            return jsonify({"error": "Email must not contain spaces."}), 400
        parts = email.split("@")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return jsonify({"error": "Invalid email structure."}), 400
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$", email):
            return jsonify({"error": "Please enter a valid email address."}), 400

        # Allowed endings validation
        allowed_endings = [".com", ".in", ".co", ".net", ".org", ".edu", ".gov", ".io", ".ai", ".dev", ".tech", ".me", ".info", ".biz", ".co.in"]
        if not any(email.endswith(ending) for ending in allowed_endings):
            if not allow_unrecommended:
                return jsonify({"error": "This email does not end with one of the supported domains."}), 400

        # Check uniqueness
        conn = get_conn()
        existing_user = conn.execute("SELECT id FROM users WHERE username=? COLLATE NOCASE OR email=? COLLATE NOCASE", (username, email)).fetchone()
        conn.close()
        
        if existing_user:
            return jsonify({"error": "Username or email is already taken."}), 400

        # Generate OTP
        otp = ''.join(secrets.choice("0123456789") for _ in range(6))
        expires_at = (datetime.utcnow() + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')

        from database import save_registration_otp
        save_registration_otp(username, email, otp, expires_at)

        success, err_msg = send_registration_otp_email(email, username, otp)
        if not success:
            return jsonify({"error": err_msg}), 500

        return jsonify({"message": "OTP sent successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/verify-register-otp", methods=["POST"])
def verify_register_otp():
    try:
        data = request.get_json() or {}
        email = data.get("email", "").strip().lower()
        otp = data.get("otp", "").strip()

        if not email or not otp:
            return jsonify({"error": "Email and OTP are required."}), 400

        from database import get_registration_otp, mark_registration_otp_verified
        record = get_registration_otp(email)
        
        if not record:
            return jsonify({"error": "No OTP request found for this email."}), 400
        
        if record["verified"]:
            return jsonify({"error": "OTP already verified."}), 400
            
        if record["otp"] != otp:
            return jsonify({"error": "Invalid OTP."}), 400
            
        if datetime.utcnow() > datetime.strptime(record["expires_at"], '%Y-%m-%d %H:%M:%S'):
            return jsonify({"error": "OTP has expired."}), 400

        mark_registration_otp_verified(record["id"])
        return jsonify({"message": "OTP verified successfully."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ══════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════

@app.route("/register", methods=["GET","POST"])
def register():
    if get_uid(): return redirect(url_for("app_page"))
    if get_aid(): return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username","").strip()
        email    = request.form.get("email","").strip().lower()
        password = request.form.get("password","")
        confirm  = request.form.get("confirm","")

        errors = []
        if len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if not re.match(r"^[A-Za-z0-9_]+$", username):
            errors.append("Username may only contain letters, numbers, and underscores.")
        errors += validate_email(email)
        errors += validate_password(password)
        if password != confirm:
            errors.append("Passwords do not match.")

        if errors:
            for e in errors: flash(e, "error")
            return render_template("register.html", username=username, email=email)

        # Ensure OTP was verified
        from database import get_registration_otp, delete_registration_otps
        record = get_registration_otp(email)
        if not record or not record["verified"] or record["username"].lower() != username.lower():
            flash("You must verify your email with an OTP before registering.", "error")
            return render_template("register.html", username=username, email=email)

        uid, err = create_user(username, email, password)
        if err:
            flash(err, "error")
            return render_template("register.html", username=username, email=email)

        # Clean up OTP records
        delete_registration_otps(email)

        # Do NOT auto-login — redirect to login with success message
        flash("Registration successful! Please log in to continue.", "success")
        return redirect(url_for("login"))

    return render_template("register.html", username="", email="")


@app.route("/login", methods=["GET","POST"])
def login():
    if get_uid(): return redirect(url_for("index"))
    if get_aid(): return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        login_id   = request.form.get("username","").strip()
        password   = request.form.get("password","")
        login_type = request.form.get("login_type","user")

        if not login_id or not password:
            flash("Please enter your credentials.", "error")
            return render_template("login.html", username=login_id)

        if login_type == "admin":
            admin = verify_admin(login_id, password)
            if not admin:
                flash("Invalid admin credentials.", "error")
                return render_template("login.html", username=login_id)
            flask_session["admin_id"]       = admin["id"]
            flask_session["admin_username"] = admin["username"]
            flask_session["admin_email"]    = admin.get("email","")
            flask_session["role"]           = "admin"
            flash(f"Welcome, Admin {admin['username']}!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            user, block_status = verify_user(login_id, password)
            if block_status == "blocked":
                flash('Your account has been temporarily blocked. <a href="#" onclick="openContactModal(\'Unblock Request\'); return false;" style="color:var(--cyan);text-decoration:underline;">Contact Admin</a> to request unblocking.', "error")
                return render_template("login.html", username=login_id)
            if not user:
                flash("Invalid username/email or password.", "error")
                return render_template("login.html", username=login_id)
            flask_session["user_id"]  = user["id"]
            flask_session["username"] = user["username"]
            flask_session["email"]    = user.get("email","")
            flask_session["role"]     = "user"
            nxt = request.args.get("next", url_for("app_page"))
            flash(f"Welcome back, {user['username']}!", "success")
            return redirect(nxt)

    return render_template("login.html", username="")

@app.route("/admin/block-user/<int:user_id>", methods=["POST"])
@admin_required
def admin_block_user(user_id):
    try:
        block_user(user_id)
        return jsonify({"status": "ok", "message": "User blocked."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/admin/unblock-user/<int:user_id>", methods=["POST"])
@admin_required
def admin_unblock_user(user_id):
    try:
        unblock_user(user_id)
        return jsonify({"status": "ok", "message": "User unblocked."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/logout")
def logout():
    uid = get_uid()
    aid = get_aid()
    if uid:
        record_user_logout(uid)
    if aid:
        record_admin_logout(aid)
    flask_session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


# ── Forgot Password (Users) ────────────────────────────────────────────────────
@app.route("/forgot-password", methods=["GET"])
def forgot_password():
    if get_uid(): return redirect(url_for("index"))
    return render_template("forgot_password.html", is_admin=False)


@app.route("/send-reset-otp", methods=["POST"])
def send_reset_otp():
    data     = request.get_json()
    username = (data.get("username") or "").strip()
    email    = (data.get("email") or "").strip().lower()

    # --- strict server-side validation ---
    if not username:
        return jsonify({"error": "Username is required."}), 400
    errs = validate_email(email)
    if errs:
        return jsonify({"error": errs[0]}), 400

    # Verify username + email belong to the same account
    account = verify_username_email_match(username, email, is_admin=False)
    if account:
        token, otp = generate_reset_token(user_id=account["id"])
        from email_utils import send_reset_email
        ok, err = send_reset_email(email, account["username"], otp)
        if not ok:
            print(f"[OTP SEND FAIL] user={username} email={email}: {err}")
            return jsonify({"error": "Failed to send OTP email. Check your SMTP settings."}), 500
        flask_session["reset_token"]    = token
        flask_session["reset_email"]    = email
        flask_session["reset_username"] = username
    else:
        # Log server-side but return generic message to prevent user enumeration
        print(f"[OTP BLOCKED] username='{username}' email='{email}' — no matching account")

    # Generic response regardless of match — prevents account enumeration
    return jsonify({"status": "ok", "message": "If those credentials match a registered account, an OTP has been sent."})


@app.route("/verify-reset-otp", methods=["POST"])
def verify_reset_otp_route():
    data  = request.get_json()
    otp   = (data.get("otp") or "").strip()
    token = flask_session.get("reset_token","")
    if not token:
        return jsonify({"error":"Session expired. Please start over."}), 400
    if not otp or len(otp) != 6 or not otp.isdigit():
        return jsonify({"error":"Please enter the 6-digit OTP."}), 400
    user_id, admin_id = verify_reset_otp(token, otp)
    if not user_id and not admin_id:
        return jsonify({"error":"Invalid or expired OTP. Please request a new one."}), 400
    flask_session["reset_verified_uid"]   = user_id
    flask_session["reset_verified_admin"] = admin_id
    return jsonify({"status":"ok","valid":True})


@app.route("/reset-password", methods=["POST"])
def reset_password():
    data    = request.get_json()
    new_pw  = data.get("password","")
    confirm = data.get("confirm","")
    uid     = flask_session.get("reset_verified_uid")
    admin_id= flask_session.get("reset_verified_admin")
    token   = flask_session.get("reset_token","")
    if not uid and not admin_id:
        return jsonify({"error":"Session expired. Please restart the reset process."}), 400
    if new_pw != confirm:
        return jsonify({"error":"Passwords do not match."}), 400
    if uid:
        ok, err = update_password(uid, new_pw)
    else:
        ok, err = update_admin_password(admin_id, new_pw)
    if not ok:
        return jsonify({"error": err}), 400
    consume_reset_token(token)
    flask_session.pop("reset_token",        None)
    flask_session.pop("reset_email",        None)
    flask_session.pop("reset_verified_uid", None)
    flask_session.pop("reset_verified_admin", None)
    return jsonify({"status":"ok","message":"Password updated! Please log in."})


# ── Admin Forgot Password ──────────────────────────────────────────────────────
@app.route("/admin-forgot-password", methods=["GET"])
def admin_forgot_password_page():
    return render_template("forgot_password.html", is_admin=True)


@app.route("/admin-send-reset-otp", methods=["POST"])
def admin_send_reset_otp():
    data     = request.get_json()
    username = (data.get("username") or "").strip()
    email    = (data.get("email") or "").strip().lower()

    if not username:
        return jsonify({"error": "Admin username is required."}), 400
    errs = validate_email(email)
    if errs:
        return jsonify({"error": errs[0]}), 400

    account = verify_username_email_match(username, email, is_admin=True)
    if account:
        token, otp = generate_reset_token(admin_id=account["id"])
        from email_utils import send_reset_email
        ok, err = send_reset_email(email, account["username"], otp)
        if not ok:
            print(f"[ADMIN OTP SEND FAIL] admin={username} email={email}: {err}")
            return jsonify({"error": "Failed to send OTP email. Check your SMTP settings."}), 500
        flask_session["reset_token"]      = token
        flask_session["reset_email"]      = email
        flask_session["reset_username"]   = username
        flask_session["reset_is_admin"]   = True
    else:
        print(f"[ADMIN OTP BLOCKED] username='{username}' email='{email}' — no matching admin account")

    return jsonify({"status": "ok", "message": "If those credentials match a registered admin account, an OTP has been sent."})


# ── Current user endpoint ──────────────────────────────────────────────────────
@app.route("/me")
@login_required
def me():
    u = current_user()
    if not u: return jsonify({"error":"Not authenticated"}), 401
    return jsonify({"id":u["id"],"username":u["username"],"email":u.get("email",""),"avatar_url":u.get("avatar_url","")})

@app.route("/admin/me")
@admin_required
def admin_me():
    a = current_admin()
    if not a: return jsonify({"error":"Not authenticated"}), 401
    return jsonify({"id":a["id"],"username":a["username"],"email":a.get("email",""),"avatar_url":a.get("avatar_url","")})


# ── Profile Update (Users) ─────────────────────────────────────────────────────
@app.route("/profile/update", methods=["POST"])
@login_required
def update_profile():
    data            = request.get_json()
    new_username    = (data.get("username") or "").strip()
    new_email       = (data.get("email") or "").strip().lower()
    current_pw      = data.get("current_password","")
    new_pw          = data.get("new_password","")
    confirm_pw      = data.get("confirm_password","")

    if new_pw and new_pw != confirm_pw:
        return jsonify({"error":"New passwords do not match."}), 400

    uid = get_uid()
    ok, msg = update_user_profile(
        uid,
        new_username=new_username or None,
        new_email=new_email or None,
        current_password=current_pw or None,
        new_password=new_pw or None
    )
    if not ok:
        return jsonify({"error": msg}), 400

    # Refresh session data
    u = get_user_by_id(uid)
    if u:
        flask_session["username"] = u["username"]
        flask_session["email"]    = u.get("email","")

    return jsonify({"status":"ok","message": msg,
                    "username": flask_session.get("username",""),
                    "email": flask_session.get("email","")})


# ── Profile Update (Admins) ────────────────────────────────────────────────────
@app.route("/admin/profile/update", methods=["POST"])
@admin_required
def update_admin_profile_route():
    data         = request.get_json()
    new_username = (data.get("username") or "").strip()
    new_email    = (data.get("email") or "").strip().lower()
    current_pw   = data.get("current_password","")
    new_pw       = data.get("new_password","")
    confirm_pw   = data.get("confirm_password","")

    if new_pw and new_pw != confirm_pw:
        return jsonify({"error":"New passwords do not match."}), 400

    aid = get_aid()
    ok, msg = update_admin_profile(
        aid,
        current_password=current_pw or None,
        new_username=new_username or None,
        new_email=new_email or None,
        new_password=new_pw or None
    )
    if not ok:
        return jsonify({"error": msg}), 400

    a = get_admin_by_id(aid)
    if a:
        flask_session["admin_username"] = a["username"]
        flask_session["admin_email"]    = a.get("email","")

    return jsonify({"status":"ok","message": msg,
                    "username": flask_session.get("admin_username",""),
                    "email": flask_session.get("admin_email","")})


# ══════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════
@app.route("/admin")
@admin_required
def admin_dashboard():
    admin = current_admin()
    users = get_all_users_with_stats()
    stats = get_admin_stats()
    return render_template("admin.html", admin=admin, users=users, stats=stats)


@app.route("/admin/delete-user/<int:user_id>", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    try:
        delete_user(user_id)
        return jsonify({"status":"ok"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/user/<int:user_id>/detail")
@admin_required
def admin_user_detail(user_id):
    """Return full user detail (profile + sessions + job-role history) for admin panel."""
    detail = get_user_detail(user_id)
    if not detail:
        return jsonify({"error": "User not found."}), 404
    # Convert all datetime strings to IST-formatted display strings
    for field in ("created_at", "last_login_at", "last_logout_at"):
        detail[f"{field}_ist"] = to_ist(detail.get(field)) or "Not available"
    for s in detail.get("sessions", []):
        s["created_at_ist"] = to_ist(s.get("created_at")) or "Not available"
    for r in detail.get("job_roles", []):
        r["first_at_ist"] = to_ist(r.get("first_at")) or "Not available"
        r["last_at_ist"]  = to_ist(r.get("last_at"))  or "Not available"
    return jsonify(detail)


@app.route("/admin/reset-user-password/<int:user_id>", methods=["POST"])
@admin_required
def admin_reset_user_pw(user_id):
    data   = request.get_json()
    new_pw = data.get("password","")
    ok, err = admin_reset_user_password(user_id, new_pw)
    if not ok:
        return jsonify({"error": err}), 400
    return jsonify({"status":"ok","message":"Password reset successfully."})


@app.route("/admin/users")
@admin_required
def admin_users():
    users = get_all_users_with_stats()
    return render_template("admin_users.html", users=users)

@app.route("/admin/notifications")
@admin_required
def admin_notifications_route():
    notifs = get_admin_notifications()
    return jsonify(notifs)

@app.route("/admin/notifications/<int:notif_id>/read", methods=["POST"])
@admin_required
def read_notification(notif_id):
    mark_notification_read(notif_id)
    return jsonify({"status": "ok"})

@app.route("/admin/notifications/<int:notif_id>/delete", methods=["DELETE"])
@admin_required
def delete_notification(notif_id):
    delete_admin_notification(notif_id)
    return jsonify({"status": "ok"})

@app.route("/admin/contact_requests/<int:req_id>/resolve", methods=["POST"])
@admin_required
def admin_resolve_request(req_id):
    req = get_contact_request(req_id)
    if not req:
        return jsonify({"error": "Request not found."}), 404
        
    if req['request_type'] == 'Unblock Request':
        user = get_user_by_username(req['username'])
        if user:
            unblock_user(user['id'])
            
    resolve_contact_request(req_id)
    return jsonify({"status": "ok"})

@app.route("/contact_admin", methods=["POST"])
def contact_admin():
    data = request.get_json()
    username = data.get("username", "")
    email = data.get("email", "")
    subject = data.get("subject", "")
    message = data.get("message", "")
    req_type = data.get("request_type", "Contact Request")
    
    import re
    if not username or not message or not email:
        return jsonify({"error": "Username, email, and message are required."}), 400
    if not re.match(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
        return jsonify({"error": "Invalid email format."}), 400
        
    create_contact_request(username, email, subject, message, req_type)
    return jsonify({"status": "ok", "message": "Request sent successfully. The admin will review it soon."})


# ══════════════════════════════════════════════════════════════
#  MAIN PAGES
# ══════════════════════════════════════════════════════════════
@app.route("/")
def index():
    uid = get_uid()
    if uid:
        if get_user_by_id(uid):
            return redirect(url_for("app_page"))
        else:
            flask_session.clear()
    return render_template("landing.html")

@app.route("/app")
@login_required
def app_page():
    return render_template("index.html", user=current_user())


@app.route("/history")
@login_required
def history_page():
    return render_template("history.html", sessions=get_history(user_id=get_uid()))


@app.route("/results/<int:session_id>")
@login_required
def results(session_id):
    sessions = get_history(user_id=get_uid())
    session  = next((s for s in sessions if s["id"] == session_id), None)
    if not session:
        flash("Session not found.", "error")
        return redirect(url_for("history_page"))
    return render_template("results.html",
        job_title=session["job_title"], experience=session["experience"],
        session_id=session_id, questions=json.loads(session["questions_json"]))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("user_dashboard.html", user=current_user(),
                           total_sessions=len(get_history(user_id=get_uid())),
                           recent_sessions=get_history(limit=5, user_id=get_uid()),
                           role_data=[], weekly_stats=get_weekly_stats(user_id=get_uid()))


# ══════════════════════════════════════════════════════════════
#  API — QUESTIONS
# ══════════════════════════════════════════════════════════════
@app.route("/delete-account", methods=["POST"])
@login_required
def delete_account():
    """User deletes their own account with optional reasons."""
    data    = request.get_json()
    reasons = data.get("reasons", [])  # list of strings
    comment = (data.get("comment") or "").strip()
    uid     = get_uid()

    # Safety: ensure the uid is valid
    user = get_user_by_id(uid)
    if not user:
        return jsonify({"error": "Account not found."}), 404

    ok, err = delete_user_account(uid, reasons, comment)
    if not ok:
        return jsonify({"error": err}), 500

    flask_session.clear()
    return jsonify({"status": "ok", "message": "Your account has been deleted."})


@app.route("/generate", methods=["POST"])
@login_required
def generate():
    data          = request.get_json()
    job_title     = data.get("job_title","").strip()
    experience    = data.get("experience","fresher")
    category      = data.get("category","all")
    difficulty    = data.get("difficulty","mixed")
    num_questions = int(data.get("num_questions",10))
    variation     = data.get("variation","")

    if not job_title:       return jsonify({"error":"Job title is required."}), 400
    if len(job_title) > 80: return jsonify({"error":"Job title must be less than 80 characters."}), 400

    valid, reason = is_valid_job_title(job_title)
    if not valid:
        return jsonify({"error": reason, "invalid_title": True}), 400

    questions = generate_questions(job_title, experience, category, difficulty,
                                   num_questions, variation)
    if isinstance(questions, dict) and "error" in questions:
        return jsonify(questions), 500

    sid = save_session(job_title, experience, json.dumps(questions), user_id=get_uid())
    try:
        u = current_user()
        username = u["username"] if u else "Unknown User"
        email = u.get("email") or "Unknown Email"
        notif_title = f"Interview Generated: {job_title}"
        notif_msg = (
            f"User <strong>{username}</strong> ({email}) generated a new mock interview.<br>"
            f"• <strong>Role</strong>: {job_title}<br>"
            f"• <strong>Experience</strong>: {experience.capitalize()}<br>"
            f"• <strong>Difficulty</strong>: {difficulty.capitalize()}<br>"
            f"• <strong>Category</strong>: {category.capitalize()}<br>"
            f"• <strong>Method</strong>: Manual Job Title Entry<br>"
            f"• <strong>Total Questions</strong>: {num_questions}"
        )
        create_admin_notification(
            notif_type="generation",
            title=notif_title,
            message=notif_msg,
            related_user=username,
            related_request_id=sid
        )
    except Exception as ne:
        print(f"[ERROR] Failed to create admin notification for generation: {ne}")
    return jsonify({"session_id": sid, "questions": questions})


@app.route("/check_answer", methods=["POST"])
@login_required
def check_answer():
    data           = request.get_json()
    question       = data.get("question","").strip()
    hint           = data.get("hint","").strip()
    answer         = data.get("answer","").strip()
    session_id     = data.get("session_id")
    question_index = data.get("question_index")

    if not answer or len(answer) < 5:
        return jsonify({
            "score":"No Answer","color":"gray","percent":0,
            "feedback":"No spoken answer detected. Allow mic access and try again.",
            "tip":hint,"ideal_answer":"Please attempt the question by speaking clearly.",
        })

    prompt = EVAL_PROMPT.format(question=question, hint=hint, answer=answer)
    result = _eval_with_groq(prompt)
    if result:
        print("✅ Groq"); final = _build_result(result, hint, question)
    else:
        result = _eval_with_gemini(prompt)
        final  = _build_result(result, hint, question) if result else _local_eval(question, hint, answer)

    if session_id and question_index is not None:
        try:
            save_question_score(int(session_id), int(question_index),
                                question, final["score"], final["percent"])
        except Exception as e:
            print(f"⚠️  save_question_score: {e}")

    return jsonify(final)


# ══════════════════════════════════════════════════════════════
#  API — HISTORY / SCORES / STATS
# ══════════════════════════════════════════════════════════════
@app.route("/history_json")
@login_required
def history_json():
    return jsonify(get_history(user_id=get_uid()))

@app.route("/question_scores/<int:session_id>")
@login_required
def question_scores(session_id):
    return jsonify(get_question_scores(session_id))

@app.route("/weekly_stats")
@login_required
def weekly_stats():
    return jsonify(get_weekly_stats(user_id=get_uid()))

@app.route("/rate", methods=["POST"])
@login_required
def rate():
    data = request.get_json()
    rate_question(data["session_id"], data["question_index"],
                  data["rating"], user_id=get_uid())
    return jsonify({"status":"ok"})

@app.route("/delete/<int:session_id>", methods=["POST"])
@login_required
def delete(session_id):
    delete_session(session_id, user_id=get_uid())
    if request.content_type and 'application/json' in request.content_type:
        return jsonify({"status":"ok"})
    flash("Session deleted.", "success")
    return redirect(url_for("history_page"))

@app.route("/clear_history", methods=["POST"])
@login_required
def clear_history_route():
    clear_history(user_id=get_uid())
    if request.content_type and 'application/json' in request.content_type:
        return jsonify({"status":"ok"})
    flash("All history cleared.", "success")
    return redirect(url_for("history_page"))


# ══════════════════════════════════════════════════════════════
#  EXPORT — TXT
# ══════════════════════════════════════════════════════════════
@app.route("/export/<int:session_id>")
@login_required
def export(session_id):
    sessions = get_history(user_id=get_uid())
    session  = next((s for s in sessions if s["id"] == session_id), None)
    if not session: return "Not found", 404
    questions = json.loads(session["questions_json"])
    lines = [
        f"Interview Questions — {session['job_title']} ({session['experience']})",
        f"Generated on: {session['created_at']}", "="*60, "",
    ]
    for i, q in enumerate(questions, 1):
        lines.append(f"\n{i}. [{q.get('category','').upper()}] [{q.get('difficulty','').upper()}]")
        lines.append(f"   Q: {q['question']}")
        if q.get("hint"): lines.append(f"   Hint: {q['hint']}")
    buf = io.BytesIO("\n".join(lines).encode("utf-8"))
    return send_file(buf, mimetype="text/plain",
                     download_name=f"questions_{session_id}.txt", as_attachment=True)


# ══════════════════════════════════════════════════════════════
#  EXPORT — PDF
# ══════════════════════════════════════════════════════════════
@app.route("/export_pdf/<int:session_id>")
@login_required
def export_pdf(session_id):
    try:

        sessions = get_history(user_id=get_uid())
        session  = next((s for s in sessions if s["id"] == session_id), None)
        if not session: return "Not found", 404

        questions = json.loads(session["questions_json"])
        score_map = {s["question_index"]: s for s in get_question_scores(session_id)}

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm,
                                topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()

        def ps(name, **kw):
            return ParagraphStyle(name, parent=styles["Normal"], **kw)

        title_s = ps("T",  fontSize=20, textColor=colors.HexColor("#4f46e5"),
                     spaceAfter=4, alignment=TA_CENTER, fontName="Helvetica-Bold")
        sub_s   = ps("S",  fontSize=10, textColor=colors.HexColor("#6b7280"),
                     alignment=TA_CENTER, spaceAfter=2)
        sec_s   = ps("Se", fontSize=13, textColor=colors.HexColor("#1e1b4b"),
                     spaceBefore=14, spaceAfter=6, fontName="Helvetica-Bold")
        q_s     = ps("Q",  fontSize=11, textColor=colors.HexColor("#111827"),
                     leading=16, spaceAfter=4)
        hint_s  = ps("H",  fontSize=9,  textColor=colors.HexColor("#4f46e5"),
                     leading=14, leftIndent=12)
        note_s  = ps("N",  fontSize=8,  textColor=colors.HexColor("#9ca3af"))
        SCLR    = {"Excellent":colors.HexColor("#059669"),"Good":colors.HexColor("#2563eb"),
                   "Partial":colors.HexColor("#d97706"),"Needs Work":colors.HexColor("#dc2626")}

        attempted  = len(score_map)
        avg_score  = round(sum(s["score_pct"] for s in score_map.values())/attempted) if attempted else 0
        excellent  = sum(1 for s in score_map.values() if s["score_label"]=="Excellent")
        good       = sum(1 for s in score_map.values() if s["score_label"]=="Good")
        needs_work = sum(1 for s in score_map.values() if s["score_label"]=="Needs Work")

        story = [Spacer(1, 0.2*cm)]
        story.append(Paragraph("Interview Session Report", title_s))
        story.append(Paragraph(
            f"{session['job_title']}  ·  {session['experience']}  ·  {session['created_at']}", sub_s))
        story.append(HRFlowable(width="100%", thickness=1,
                                color=colors.HexColor("#e5e7eb"), spaceAfter=12))

        tbl = Table(
            [["Total Qs","Attempted","Avg Score","Excellent","Good","Needs Work"],
             [len(questions), attempted, f"{avg_score}%", excellent, good, needs_work]],
            colWidths=[2.8*cm]*6)
        tbl.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#f5f3ff")),
            ("TEXTCOLOR", (0,0),(-1,0),colors.HexColor("#4f46e5")),
            ("FONTNAME",  (0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,0),9),
            ("FONTNAME",  (0,1),(-1,1),"Helvetica-Bold"),("FONTSIZE",(0,1),(-1,1),14),
            ("ALIGN",     (0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
            ("BOX",       (0,0),(-1,-1),0.5,colors.HexColor("#e5e7eb")),
            ("INNERGRID", (0,0),(-1,-1),0.5,colors.HexColor("#e5e7eb")),
            ("TOPPADDING",(0,0),(-1,-1),8),("BOTTOMPADDING",(0,0),(-1,-1),8),
        ]))
        story.append(tbl); story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("Questions &amp; Performance", sec_s))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                color=colors.HexColor("#e5e7eb"), spaceAfter=8))

        for i, q in enumerate(questions):
            sc   = score_map.get(i)
            cc   = {"technical":"#1d4ed8","behavioral":"#059669","situational":"#b45309"}.get(q.get("category",""),"#6b7280")
            dc   = {"easy":"#166534","medium":"#92400e","hard":"#991b1b"}.get(q.get("difficulty",""),"#6b7280")
            stxt = f"{sc['score_label']}  {sc['score_pct']}%" if sc else "Not attempted"
            sclr = SCLR.get(sc["score_label"], colors.HexColor("#6b7280")) if sc else colors.HexColor("#9ca3af")
            row  = Table([[
                Paragraph(f"<b>Q{i+1}</b>", ps(f"n{i}",fontSize=11,textColor=colors.HexColor("#4f46e5"),fontName="Helvetica-Bold")),
                Paragraph(q.get("category","").upper(), ps(f"c{i}",fontSize=8,textColor=colors.HexColor(cc),alignment=TA_CENTER)),
                Paragraph(q.get("difficulty","").upper(), ps(f"d{i}",fontSize=8,textColor=colors.HexColor(dc),alignment=TA_CENTER)),
                Paragraph(f"<b>{stxt}</b>", ps(f"s{i}",fontSize=9,textColor=sclr,alignment=TA_CENTER)),
            ]], colWidths=[1.2*cm,2.8*cm,2*cm,3.5*cm])
            row.setStyle(TableStyle([
                ("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"MIDDLE"),
                ("BACKGROUND",(1,0),(1,0),colors.HexColor("#eff6ff")),
                ("BACKGROUND",(2,0),(2,0),colors.HexColor("#fef3c7")),
                ("BACKGROUND",(3,0),(3,0),colors.HexColor("#f9fafb")),
                ("BOX",(0,0),(-1,-1),0.3,colors.HexColor("#e5e7eb")),
                ("INNERGRID",(0,0),(-1,-1),0.3,colors.HexColor("#e5e7eb")),
                ("TOPPADDING",(0,0),(-1,-1),5),("BOTTOMPADDING",(0,0),(-1,-1),5),
            ]))
            story.append(row); story.append(Spacer(1,3))
            story.append(Paragraph(q["question"], q_s))
            if q.get("hint"): story.append(Paragraph(f"Hint: {q['hint']}", hint_s))
            story.append(Spacer(1,8))

        story.append(HRFlowable(width="100%",thickness=0.5,
                                color=colors.HexColor("#e5e7eb"),spaceBefore=10,spaceAfter=6))
        story.append(Paragraph(
            f"Generated by My InterviewAI  ·  {datetime.now().strftime('%Y-%m-%d %H:%M')}", note_s))
        doc.build(story); buf.seek(0)
        safe = re.sub(r"[^a-z0-9]+","_", session["job_title"].lower())
        return send_file(buf, mimetype="application/pdf",
                         download_name=f"report_{safe}_{session_id}.pdf", as_attachment=True)

    except ImportError:
        return jsonify({"error":"Install reportlab: pip install reportlab"}), 500
    except Exception as e:
        print(f"PDF error: {e}"); return jsonify({"error":str(e)}), 500

ALLOWED_RESUME_EXTENSIONS = {'.pdf', '.docx', '.doc'}
MAX_RESUME_SIZE_BYTES      = 5 * 1024 * 1024   # 5 MB


@app.route("/upload-resume", methods=["POST"])
@login_required
def upload_resume():
    """Upload + parse + ATS-score a resume. Returns JSON."""
    try:
        if 'resume' not in request.files:
            return jsonify({"error": "No file uploaded. Please select a PDF or DOCX file."}), 400

        f        = request.files['resume']
        filename = f.filename.strip() if f.filename else ""

        if not filename:
            return jsonify({"error": "No file selected."}), 400

        # Extension check
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_RESUME_EXTENSIONS:
            return jsonify({"error": f"Unsupported file type '{ext}'. Please upload a PDF or DOCX file."}), 400

        # Read bytes
        file_bytes = f.read()
        file_size  = len(file_bytes)

        if file_size == 0:
            return jsonify({"error": "The uploaded file is empty."}), 400
        if file_size > MAX_RESUME_SIZE_BYTES:
            return jsonify({"error": f"File too large ({file_size // 1024}KB). Maximum allowed size is 5MB."}), 400

        # Parse text
        try:
            resume_text = extract_resume_text(file_bytes, filename)
        except (ValueError, RuntimeError) as e:
            return jsonify({"error": str(e)}), 400

        if not resume_text or len(resume_text.strip()) < 50:
            return jsonify({"error": "Could not extract meaningful text from this file. Make sure the resume is not a scanned image."}), 400

        # Get target role if supplied alongside upload
        target_role = (request.form.get("target_role") or "").strip()

        # ATS analysis
        report       = run_ats_analysis(resume_text, target_role)
        detected     = report["detected_roles"][0] if report["detected_roles"] else ""
        final_role   = target_role or detected

        # Save to DB (text stored for question generation)
        try:
            resume_id = save_resume(
                user_id      = get_uid(),
                filename     = filename,
                file_size    = file_size,
                resume_text  = resume_text[:20000],   # cap at 20k chars
                detected_role= final_role,
                ats_score    = report["overall_score"],
                ats_report   = json.dumps(report),
            )
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400

        return jsonify({
            "status":        "ok",
            "resume_id":     resume_id,
            "filename":      filename,
            "detected_role": final_role,
            "all_detected":  report["detected_roles"],
            "ats":           report,
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"Server crash during processing: {str(e)}"}), 500


@app.route("/resume/<int:resume_id>/ats", methods=["GET"])
@login_required
def get_ats_report(resume_id):
    """Return stored ATS report for a resume."""
    row = get_resume(resume_id, get_uid())
    if not row:
        return jsonify({"error": "Resume not found."}), 404
    try:
        report = json.loads(row.get("ats_report") or "{}")
    except Exception:
        report = {}
    return jsonify({"status": "ok", "ats": report, "filename": row["filename"]})


@app.route("/resume/<int:resume_id>/delete", methods=["POST"])
@login_required
def delete_resume_route(resume_id):
    delete_resume(resume_id, get_uid())
    return jsonify({"status": "ok"})


@app.route("/my-resumes", methods=["GET"])
@login_required
def my_resumes():
    resumes = get_user_resumes(get_uid())
    return jsonify(resumes)


@app.route("/generate-from-resume", methods=["POST"])
@login_required
def generate_from_resume():
    """Generate questions using stored resume context."""
    data       = request.get_json()
    resume_id  = data.get("resume_id")
    job_title  = (data.get("job_title") or "").strip()
    experience = data.get("experience", "mid-level")
    category   = data.get("category",   "all")
    difficulty = data.get("difficulty", "mixed")
    num_q      = int(data.get("num_questions", 10))
    variation  = data.get("variation", 0)

    row = get_resume(int(resume_id), get_uid()) if resume_id else None
    if not row:
        return jsonify({"error": "Resume not found. Please upload your resume first."}), 404

    # Decide final job title
    final_title = job_title or row.get("detected_role") or "Software Professional"

    # Build personalized prompt hint from resume skills
    resume_text   = row.get("resume_text", "")
    skill_hint    = _extract_skill_summary(resume_text)

    questions = generate_questions(
        final_title, experience, category, difficulty, num_q,
        variation=f"resume_{resume_id}_{final_title}_{variation}"
    )
    if isinstance(questions, dict) and "error" in questions:
        return jsonify(questions), 500

    sid = save_session(final_title, experience, json.dumps(questions), user_id=get_uid())
    try:
        u = current_user()
        username = u["username"] if u else "Unknown User"
        email = u.get("email") or "Unknown Email"
        notif_title = f"Interview Generated (Resume): {final_title}"
        notif_msg = (
            f"User <strong>{username}</strong> ({email}) generated a new mock interview via resume upload.<br>"
            f"• <strong>Role</strong>: {final_title}<br>"
            f"• <strong>Experience</strong>: {experience.capitalize()}<br>"
            f"• <strong>Difficulty</strong>: {difficulty.capitalize()}<br>"
            f"• <strong>Category</strong>: {category.capitalize()}<br>"
            f"• <strong>Method</strong>: Resume Upload ({row.get('filename') or 'Uploaded Resume'})<br>"
            f"• <strong>Total Questions</strong>: {num_q}"
        )
        create_admin_notification(
            notif_type="generation",
            title=notif_title,
            message=notif_msg,
            related_user=username,
            related_request_id=sid
        )
    except Exception as ne:
        print(f"[ERROR] Failed to create admin notification for resume generation: {ne}")
    return jsonify({
        "session_id":   sid,
        "questions":    questions,
        "job_title":    final_title,
        "skill_hint":   skill_hint,
        "resume_used":  True,
    })


def _extract_skill_summary(resume_text: str) -> str:
    """Extract a short comma-separated skill list from resume text."""
    text_lower = resume_text.lower()
    found = [k.title() for k in TECH_KEYWORDS if k in text_lower]
    return ", ".join(found[:12]) if found else ""


# ══════════════════════════════════════════════════════════════
#  EMAIL REPORT
# ══════════════════════════════════════════════════════════════
@app.route("/send_email", methods=["POST"])
@login_required
def send_email():
    data       = request.get_json()
    to_email   = (data.get("email") or "").strip()
    session_id = data.get("session_id")

    if not to_email or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$", to_email):
        return jsonify({"error":"Please enter a valid email address."}), 400
    if not session_id:
        return jsonify({"error":"No session selected."}), 400

    sessions = get_history(user_id=get_uid())
    session  = next((s for s in sessions if s["id"] == int(session_id)), None)
    if not session:
        return jsonify({"error":"Session not found."}), 404

    questions = json.loads(session["questions_json"])
    q_scores  = get_question_scores(int(session_id))
    ok, err   = send_report_email(to_email, session, questions, q_scores)
    if not ok:
        return jsonify({"error":err}), 500
    return jsonify({"status":"ok","message":f"Report sent to {to_email}"})


# ══════════════════════════════════════════════════════════════
#  PROFILE AVATAR UPLOAD
# ══════════════════════════════════════════════════════════════
ALLOWED_AVATAR_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
AVATAR_UPLOAD_DIR = os.path.join(os.path.dirname(__file__), 'static', 'uploads', 'avatars')
os.makedirs(AVATAR_UPLOAD_DIR, exist_ok=True)


@app.route("/profile/avatar", methods=["POST"])
@login_required
def upload_user_avatar():
    """Upload a profile picture for the current user."""
    if 'avatar' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    f = request.files['avatar']
    if not f.filename:
        return jsonify({"error": "No file selected."}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({"error": f"Unsupported image type '{ext}'. Use PNG, JPG, WEBP, or GIF."}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_AVATAR_SIZE:
        return jsonify({"error": "Image too large. Maximum size is 2 MB."}), 400
    if len(file_bytes) == 0:
        return jsonify({"error": "The uploaded file is empty."}), 400

    uid = get_uid()
    # Remove any existing avatar files for this user
    for old in os.listdir(AVATAR_UPLOAD_DIR):
        if old.startswith(f"user_{uid}."):
            os.remove(os.path.join(AVATAR_UPLOAD_DIR, old))

    filename = f"user_{uid}{ext}"
    filepath = os.path.join(AVATAR_UPLOAD_DIR, filename)
    with open(filepath, 'wb') as out:
        out.write(file_bytes)

    import time as _time
    avatar_url = f"/static/uploads/avatars/{filename}?t={int(_time.time())}"
    update_user_avatar(uid, avatar_url)
    return jsonify({"status": "ok", "avatar_url": avatar_url})


@app.route("/admin/profile/avatar", methods=["POST"])
@admin_required
def upload_admin_avatar():
    """Upload a profile picture for the current admin."""
    if 'avatar' not in request.files:
        return jsonify({"error": "No file uploaded."}), 400
    f = request.files['avatar']
    if not f.filename:
        return jsonify({"error": "No file selected."}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        return jsonify({"error": f"Unsupported image type '{ext}'. Use PNG, JPG, WEBP, or GIF."}), 400

    file_bytes = f.read()
    if len(file_bytes) > MAX_AVATAR_SIZE:
        return jsonify({"error": "Image too large. Maximum size is 2 MB."}), 400
    if len(file_bytes) == 0:
        return jsonify({"error": "The uploaded file is empty."}), 400

    aid = get_aid()
    # Remove any existing avatar files for this admin
    for old in os.listdir(AVATAR_UPLOAD_DIR):
        if old.startswith(f"admin_{aid}."):
            os.remove(os.path.join(AVATAR_UPLOAD_DIR, old))

    filename = f"admin_{aid}{ext}"
    filepath = os.path.join(AVATAR_UPLOAD_DIR, filename)
    with open(filepath, 'wb') as out:
        out.write(file_bytes)

    import time as _time
    avatar_url = f"/static/uploads/avatars/{filename}?t={int(_time.time())}"
    update_admin_avatar(aid, avatar_url)
    return jsonify({"status": "ok", "avatar_url": avatar_url})


if __name__ == "__main__":
    print("\n  PrepEdgeAI → http://127.0.0.1:5000\n")
    app.run(debug=True, use_reloader=False)
