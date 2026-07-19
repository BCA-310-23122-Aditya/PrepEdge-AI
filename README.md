# InterviewAI — Question Generator
BCA Final Year Project | Python + Flask + Gemini API

## Setup Instructions

### Step 1 — Get your free Gemini API key
1. Go to https://aistudio.google.com/app/apikey
2. Sign in with your Google account
3. Click "Create API Key" and copy it

### Step 2 — Add your API key
Open generator.py and replace:
    GEMINI_API_KEY = "YOUR_GEMINI_API_KEY_HERE"
with your actual key.

### Step 3 — Install dependencies
    pip install -r requirements.txt

### Step 4 — Run the app
    python app.py

### Step 5 — Open in browser
    http://127.0.0.1:5000

---

## Project Structure
    interview_generator/
    ├── app.py           → Flask routes and entry point
    ├── generator.py     → Gemini API integration + prompt logic
    ├── database.py      → SQLite: save sessions, history, ratings
    ├── requirements.txt → Python dependencies
    ├── questions.db     → Auto-created on first run
    ├── email_utils.py
    ├── resume_analyzer.py
    └── templates/
        └── index.html   → Complete frontend UI
        └── admin.html
        └── admin_profile.html
        └── admin_users.html
        └── forgot_password.html
        └── landing.html
        └── login.html
        └── register.html
        └── results.html
        └── user_dashboard.html
    └── static/
        └── script.js
        └── style.css

## Features
- Generate 5–20 interview questions for any job role
- Filter by category: technical / behavioral / situational
- Filter by difficulty: easy / medium / hard
- Answer hints for every question
- Mock interview mode with 2-minute countdown timer
- Star rating for each question
- Session history — reload past sessions
- Download questions as .txt file
- Copy all questions to clipboard
- Fully responsive mobile UI

## Tech Stack
- Backend: Python 3.10+, Flask, google-generativeai, MySQL
- Frontend: HTML5, CSS3, Vanilla JavaScript
- AI: Google Gemini 1.5 Flash (free tier)
