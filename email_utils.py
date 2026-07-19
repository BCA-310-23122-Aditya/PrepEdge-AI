"""
email_utils.py — all email-sending logic for PrepEdge AI
Uses stdlib smtplib only (no Flask-Mail needed).

ROOT-CAUSE FIX:
  Previously SMTP_USER / SMTP_PASS were captured as module-level constants at
  import time.  If python-dotenv's load_dotenv() hadn't run yet (race condition
  or file-not-found), those variables were frozen as empty strings for the
  entire process lifetime — even after the env was properly loaded.

  Fix: all credential reads now happen INSIDE _get_smtp_config() which is
  called fresh on every send attempt, so they always reflect the live os.environ.
"""
import smtplib, os, pathlib
from email.mime.multipart import MIMEMultipart
from email.mime.text      import MIMEText
from datetime             import datetime

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


def _get_smtp_config() -> dict:
    """
    Read SMTP credentials fresh from os.environ on every call.
    Also attempts a one-shot dotenv load if credentials are still missing,
    so the module is self-healing even if imported before app.py calls load_dotenv().
    """
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    pw   = os.getenv("SMTP_PASS", "").strip()
    frm  = os.getenv("MAIL_FROM", user).strip() or user

    # Self-healing: if credentials are still missing, try to load dotenv now
    if not user or not pw:
        if load_dotenv:
            base = pathlib.Path(__file__).parent
            for candidate in [".env", "_env", ".env.local"]:
                p = base / candidate
                if p.exists():
                    load_dotenv(dotenv_path=p, override=True)
                    print(f"[email_utils] Loaded env from {p.name}")
                    break
            else:
                load_dotenv(override=True)
            # Re-read after loading
            user = os.getenv("SMTP_USER", "").strip()
            pw   = os.getenv("SMTP_PASS", "").strip()
            frm  = os.getenv("MAIL_FROM", user).strip() or user

    return {"host": host, "port": port, "user": user, "pw": pw, "from": frm}


def _send(to_email: str, subject: str, html_body: str) -> None:
    """Low-level SMTP send. Raises on failure."""
    cfg = _get_smtp_config()

    if not cfg["user"] or not cfg["pw"]:
        raise RuntimeError(
            "SMTP credentials not found. "
            "Make sure SMTP_USER and SMTP_PASS are set in your .env (or _env) file "
            "and that the file is in the same directory as app.py."
        )

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"PrepEdge AI <{cfg['from']}>"
    msg["To"]      = to_email
    msg["X-Mailer"] = "PrepEdge AI Mailer"
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(cfg["user"], cfg["pw"])
        s.sendmail(cfg["from"], to_email, msg.as_string())


# ══════════════════════════════════════════════════════════════
#  OTP / PASSWORD RESET EMAIL
# ══════════════════════════════════════════════════════════════
def send_registration_otp_email(to_email: str, username: str, otp: str) -> tuple[bool, str]:
    """
    Send a registration OTP email.
    Returns (True, '') on success or (False, error_message).
    """
    cfg  = _get_smtp_config()
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f5f6fa;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6fa;padding:40px 0">
<tr><td align="center">
<table width="480" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">
  <tr>
    <td align="center" style="background:linear-gradient(135deg, #1e1b4b, #312e81);padding:30px">
      <h2 style="margin:0;color:#fff;font-size:24px;letter-spacing:1px">Verify Registration</h2>
    </td>
  </tr>
  <tr>
    <td style="padding:40px 48px">
      <p style="margin:0 0 16px;font-size:16px;color:#374151">Hi <strong>{username}</strong>,</p>
      <p style="margin:0 0 24px;font-size:15px;color:#4b5563;line-height:1.6">
        Thank you for joining PrepEdge AI! Please use the 6-digit OTP below to verify your email address and complete your registration.
      </p>
      <div style="background:#f3f4f6;border:1px dashed #d1d5db;border-radius:12px;padding:24px;text-align:center;margin-bottom:32px">
        <span style="font-family:monospace;font-size:36px;font-weight:700;letter-spacing:12px;color:#4f46e5;margin-left:12px">
          {otp}
        </span>
      </div>
      <p style="margin:0 0 24px;font-size:14px;color:#6b7280;line-height:1.5">
        This OTP is valid for exactly <strong>10 minutes</strong>. Do not share it with anyone.
      </p>
      <p style="margin:0;font-size:14px;color:#9ca3af;border-top:1px solid #e5e7eb;padding-top:20px">
        If you did not request this, you can safely ignore this email.
      </p>
    </td>
  </tr>
</table>
</td></tr></table>
</body></html>"""
    try:
        _send(to_email, "PrepEdge AI - Verify your registration", html)
        return True, ""
    except Exception as e:
        err = str(e)
        if "getaddrinfo failed" in err or "Errno 11001" in err:
            return False, "Could not reach email server. Please check SMTP_HOST."
        if "Authentication" in err or "535" in err:
            return False, "Email authentication failed. Please check SMTP_USER and SMTP_PASS."
        return False, f"Failed to send email: {err}"


def send_reset_email(to_email: str, username: str, otp: str) -> tuple[bool, str]:
    """
    Send a password-reset OTP email.
    Returns (True, '') on success or (False, human-readable error).
    """
    cfg  = _get_smtp_config()
    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f5f6fa;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6fa;padding:40px 0">
<tr><td align="center">
<table width="480" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">

  <tr><td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 32px;text-align:center">
    <div style="font-size:32px">🔐</div>
    <div style="font-size:20px;font-weight:800;color:#fff;margin-top:8px">Password Reset</div>
    <div style="font-size:13px;color:rgba(255,255,255,.75);margin-top:4px">PrepEdge AI</div>
  </td></tr>

  <tr><td style="padding:32px">
    <p style="font-size:15px;color:#1a1523;margin-bottom:16px">
      Hi <strong>{username}</strong>,
    </p>
    <p style="font-size:14px;color:#4b4569;line-height:1.6;margin-bottom:24px">
      We received a request to reset your password.
      Use the OTP below to continue. It expires in <strong>15 minutes</strong>.
    </p>

    <div style="text-align:center;margin:24px 0">
      <div style="display:inline-block;background:#f5f3ff;
                  border:2px dashed #7c3aed;border-radius:14px;padding:18px 40px">
        <div style="font-size:11px;font-weight:700;color:#6d28d9;
                    text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">Your OTP</div>
        <div style="font-size:36px;font-weight:800;color:#4f46e5;
                    letter-spacing:10px;font-family:monospace">{otp}</div>
      </div>
    </div>

    <p style="font-size:13px;color:#8b85a0;line-height:1.6;margin-top:24px">
      If you did not request a password reset, please ignore this email.
      Your password will not change.
    </p>
  </td></tr>

  <tr><td style="padding:16px 32px;border-top:1px solid #f3f4f6;text-align:center">
    <p style="font-size:11px;color:#9ca3af">
      PrepEdge AI &nbsp;·&nbsp; {datetime.now().strftime('%d %b %Y, %I:%M %p')}
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""

    try:
        _send(to_email, "🔐 Password Reset OTP — PrepEdge AI", html)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, (
            "Gmail authentication failed. "
            "Make sure you are using a 16-character Gmail App Password "
            "(not your normal Gmail password). "
            "Enable 2-Step Verification, then generate an App Password at "
            "myaccount.google.com/apppasswords."
        )
    except smtplib.SMTPConnectError:
        return False, f"Cannot connect to {cfg['host']}:{cfg['port']}. Check your internet connection."
    except smtplib.SMTPRecipientsRefused:
        return False, f"Recipient address '{to_email}' was rejected by the mail server."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except RuntimeError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Email sending failed: {type(e).__name__}: {e}"


# ══════════════════════════════════════════════════════════════
#  SESSION REPORT EMAIL
# ══════════════════════════════════════════════════════════════
def build_report_html(session: dict, questions: list, q_scores: list) -> str:
    score_map  = {s["question_index"]: s for s in q_scores}
    attempted  = len(score_map)
    avg_score  = (
        round(sum(s["score_pct"] for s in score_map.values()) / attempted)
        if attempted else 0
    )
    excellent  = sum(1 for s in score_map.values() if s["score_label"] == "Excellent")
    good       = sum(1 for s in score_map.values() if s["score_label"] == "Good")
    needs_work = sum(1 for s in score_map.values() if s["score_label"] == "Needs Work")

    SCORE_CLR = {
        "Excellent": "#059669", "Good": "#2563eb",
        "Partial":   "#d97706", "Needs Work": "#dc2626",
    }
    CAT_CLR  = {"technical": "#1d4ed8", "behavioral": "#059669", "situational": "#b45309"}
    DIFF_CLR = {"easy": "#166534", "medium": "#92400e", "hard": "#991b1b"}

    q_rows = ""
    for i, q in enumerate(questions):
        sc     = score_map.get(i)
        cat_c  = CAT_CLR.get(q.get("category", ""),  "#6b7280")
        diff_c = DIFF_CLR.get(q.get("difficulty", ""), "#6b7280")
        score_td = (
            f'<span style="color:{SCORE_CLR.get(sc["score_label"],"#6b7280")};font-weight:700">'
            f'{sc["score_label"]} — {sc["score_pct"]}%</span>'
            if sc else '<span style="color:#9ca3af">Not attempted</span>'
        )
        hint_row = (
            f'<tr><td colspan="4" style="padding:2px 12px 10px;font-size:12px;'
            f'color:#6b7280;font-style:italic">💡 {q["hint"]}</td></tr>'
        ) if q.get("hint") else ""

        q_rows += f"""
        <tr style="border-bottom:1px solid #f3f4f6">
          <td style="padding:10px 12px;font-size:13px;font-weight:700;color:#4f46e5;width:32px">{i+1}</td>
          <td style="padding:10px 12px;font-size:13px;color:#111827;line-height:1.5">{q['question']}</td>
          <td style="padding:10px 12px;text-align:center;white-space:nowrap">
            <span style="font-size:10px;font-weight:700;color:{cat_c};background:#eff6ff;
                         padding:2px 7px;border-radius:4px;text-transform:uppercase">{q.get('category','')}</span>&nbsp;
            <span style="font-size:10px;font-weight:700;color:{diff_c};background:#fef9ec;
                         padding:2px 7px;border-radius:4px;text-transform:uppercase">{q.get('difficulty','')}</span>
          </td>
          <td style="padding:10px 12px;text-align:center">{score_td}</td>
        </tr>{hint_row}"""

    stats_cells = "".join(
        f'<td align="center" style="padding:12px 6px;background:#f8f7ff;border-radius:8px">'
        f'<div style="font-size:22px;font-weight:800;color:{clr}">{val}</div>'
        f'<div style="font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;'
        f'letter-spacing:.05em;margin-top:2px">{lbl}</div></td>'
        for val, lbl, clr in [
            (len(questions), "Total",     "#4f46e5"),
            (attempted,      "Attempted", "#2563eb"),
            (f"{avg_score}%", "Avg Score", "#059669"),
            (excellent,      "Excellent", "#059669"),
            (good,           "Good",      "#2563eb"),
            (needs_work,     "Needs Work","#dc2626"),
        ]
    )

    job_title  = session.get("job_title", "")
    experience = session.get("experience", "")
    created_at = session.get("created_at", "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"/></head>
<body style="margin:0;padding:0;background:#f5f6fa;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6fa;padding:32px 0">
<tr><td align="center">
<table width="620" cellpadding="0" cellspacing="0"
       style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,.08)">

  <tr><td style="background:linear-gradient(135deg,#4f46e5,#7c3aed);padding:28px 32px">
    <div style="font-size:22px;font-weight:800;color:#fff">📋 Interview Session Report</div>
    <div style="font-size:13px;color:rgba(255,255,255,.8);margin-top:5px">
      {job_title} &nbsp;·&nbsp; {experience} &nbsp;·&nbsp; {created_at}
    </div>
  </td></tr>

  <tr><td style="padding:24px 32px">
    <table width="100%" cellpadding="4" cellspacing="4"><tr>{stats_cells}</tr></table>
  </td></tr>

  <tr><td style="padding:0 32px 8px">
    <div style="font-size:12px;font-weight:700;color:#1e1b4b;text-transform:uppercase;
                letter-spacing:.07em;margin-bottom:10px">Questions &amp; Performance</div>
    <table width="100%" cellpadding="0" cellspacing="0"
           style="border:1px solid #e5e7eb;border-radius:10px;overflow:hidden">
      <tr style="background:#f5f3ff">
        <td style="padding:8px 12px;font-size:10px;font-weight:700;color:#4f46e5;text-transform:uppercase">#</td>
        <td style="padding:8px 12px;font-size:10px;font-weight:700;color:#4f46e5;text-transform:uppercase">Question</td>
        <td style="padding:8px 12px;font-size:10px;font-weight:700;color:#4f46e5;text-transform:uppercase;text-align:center">Tags</td>
        <td style="padding:8px 12px;font-size:10px;font-weight:700;color:#4f46e5;text-transform:uppercase;text-align:center">Score</td>
      </tr>
      {q_rows}
    </table>
  </td></tr>

  <tr><td style="padding:20px 32px;border-top:1px solid #f3f4f6">
    <div style="font-size:11px;color:#9ca3af;text-align:center">
      PrepEdge AI &nbsp;·&nbsp; {datetime.now().strftime('%d %b %Y, %I:%M %p')}
    </div>
  </td></tr>

</table>
</td></tr>
</table>
</body></html>"""


def send_report_email(
    to_email: str,
    session:  dict,
    questions: list,
    q_scores:  list,
) -> tuple[bool, str]:
    """Send the full session report to to_email. Returns (ok, error_msg)."""
    cfg  = _get_smtp_config()
    html = build_report_html(session, questions, q_scores)
    job  = session.get("job_title", "Interview Session")

    try:
        _send(to_email, f"📋 Interview Report — {job} | PrepEdge AI", html)
        return True, ""
    except smtplib.SMTPAuthenticationError:
        return False, (
            "Gmail authentication failed. "
            "Use a 16-character Gmail App Password, not your regular password. "
            "Generate one at myaccount.google.com/apppasswords."
        )
    except smtplib.SMTPConnectError:
        return False, f"Cannot connect to {cfg['host']}:{cfg['port']}. Check your internet connection."
    except smtplib.SMTPRecipientsRefused:
        return False, f"Recipient address '{to_email}' was rejected by the mail server."
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except RuntimeError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Email sending failed: {type(e).__name__}: {e}"
