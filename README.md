# PrepEdge AI — AI-Powered Interview Preparation Platform

PrepEdge AI is a comprehensive, premium web application designed to help job seekers excel in interviews. Using advanced Gemini and Groq AI engines, it analyzes resumes, computes ATS scores, generates customized mock interview questions, evaluates spoken/written answers, tracks candidate performance trends, and delivers professional PDF/email feedback reports.

---

## 🚀 Features

### 🔐 Authentication & Security
- **OTP Verification**: Secure email registration and password reset via SMTP-delivered 6-digit OTP codes.
- **Secure Hashing**: Password storage using PBKDF2 with SHA-256 salts via Werkzeug.
- **Admin Authentication**: Separate login and access controls for system administrators.

### 📄 ATS Resume Analyzer
- **ATS Parsing**: Extract text from uploaded resumes (PDF format).
- **Role Detection & Analysis**: Match resume text against a bank of professional keywords, identify suitable job roles, calculate ATS compliance scores, and deliver optimization recommendations.

### 🤖 Smart Interview Question Generator
- **Dual LLM Integration**: Uses Google Gemini (`gemini-2.5-flash-lite`) with a fallback to Groq (`llama-3.3-70b-versatile`) to generate customized interview questions.
- **Customizable Criteria**: Select target job role, experience level, question category (Technical, Behavioral, Situational), and difficulty level (Easy, Medium, Hard).
- **Variations & Hints**: Generates unique question sets each time and provides helpful hints for answers.

### 🎙️ Interactive Mock Evaluation
- **Timer Mode**: Interactive countdown timer for each mock question.
- **Speech-to-Text Integration**: Support for spoken answers using Web Speech API.
- **Instant AI Feedback**: AI-powered score assignment (`Excellent`, `Good`, `Partial`, `Needs Work`), percentage score, detailed feedback, coaching tips, and a generated **Ideal Answer**.

### 📊 Dashboard & Performance Metrics
- **User Dashboard**: Track cumulative session counts, average scores, weekly activity stats, and load past session history.
- **Report Export**: Generate and download a professionally formatted PDF scorecard using ReportLab.
- **Email Report**: Email scorecard results directly to the user's inbox.

### 🛡️ Admin Console
- **User Management**: View comprehensive user tables, last login times, and block/unblock inactive or abusive accounts.
- **Analytics & Logs**: Monitor overall platform sign-ups, session completion statistics, and audit activity logs.
- **Support Portal**: Resolve user-submitted contact/support inquiries.

---

## 🛠️ Technology Stack
- **Backend**: Python 3.10+, Flask
- **Database**: MySQL (PyMySQL) — *Fully dynamic database creation on first boot*
- **AI Integrations**: Google GenAI SDK, Groq SDK
- **PDF Generation**: ReportLab
- **UI/UX**: HTML5, Vanilla CSS3 (Custom Glassmorphic Dark Theme), Vanilla JavaScript

---

## ⚙️ Project Structure
```text
PrepEdge-AI/
├── app.py                     # Main Flask application (Routes, Auth, AI Eval, PDF Export)
├── database.py                # Database wrapper & PyMySQL schema initialization
├── generator.py               # Gemini & Groq API question generation logic
├── resume_analyzer.py         # PDF text parsing & ATS matching engine
├── email_utils.py             # SMTP client for OTP and PDF scorecard emails
├── build_academic_report.py   # Code to compile project report structure
├── compile_docx.py            # Converts markdown reports to DOCX
├── requirements.txt           # Python library dependencies
├── static/
│   ├── style.css              # Custom styling, responsive grid, glassmorphism UI
│   └── script.js              # State management, audio recording, Speech-to-Text
└── templates/
    ├── landing.html           # Brand homepage
    ├── login.html             # Secure login form (User & Admin toggles)
    ├── register.html          # Registration form with OTP validation
    ├── index.html             # Mock interview workshop interface
    ├── user_dashboard.html    # Weekly statistics and session history
    ├── admin.html             # Admin console homepage and notification feed
    ├── admin_users.html       # User list with blocking mechanisms
    └── admin_profile.html     # Admin profile configuration
```

---

## 🔌 Setup & Installation

### Prerequisites
- Python 3.10 or higher
- MySQL Server (v8.0+ recommended)

### 1. Clone & Enter Project
```bash
git clone https://github.com/BCA-310-23122-Aditya/PrepEdge-AI.git
cd PrepEdge-AI
```

### 2. Configure Environment Variables
Create a `.env` file in the root directory and define the following variables:
```env
SECRET_KEY=your_flask_secret_key

# MySQL Configuration
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your_mysql_password
MYSQL_DB=PrepEdgeAI

# AI API Keys
GEMINI_API_KEY=your_google_gemini_api_key
GROQ_API_KEY=your_groq_api_key

# SMTP Configuration (For OTPs & PDF scorecards)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your_email@gmail.com
SMTP_PASS=your_app_password
MAIL_FROM=your_email@gmail.com
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Application
Start the Flask development server:
```bash
python app.py
```
*Note: The MySQL database and all required tables will be automatically initialized and set up on the first run.*

### 5. Access PrepEdge AI
Open your browser and navigate to:
```text
http://127.0.0.1:5000
```
- **Default Admin Account**: Username: `admin` | Password: `Admin@1234` (Change immediately after login)
