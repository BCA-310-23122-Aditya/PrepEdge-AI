from google import genai
from groq import Groq
import json, re, os, random

# ── API Keys — paste yours here ───────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY",   ="")
# ─────────────────────────────────────────────────────────────────────────────

# Gemini client — always initialise
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Groq client — safe init, won't crash if key is bad or package missing
groq_client = None
try:
    from groq import Groq
    if GROQ_API_KEY and "YOUR_" not in GROQ_API_KEY:
        groq_client = Groq(api_key=GROQ_API_KEY)
        print("✅ Groq ready (fallback enabled)")
    else:
        print("⚠️  Groq key not set — fallback disabled")
except Exception as e:
    print(f"⚠️  Groq init failed: {e} — fallback disabled")

CATEGORY_LABELS = {
    'all':         'technical, behavioral, and situational',
    'technical':   'technical only',
    'behavioral':  'behavioral only',
    'situational': 'situational only',
}
DIFFICULTY_LABELS = {
    'mixed':  'a mix of easy, medium, and hard',
    'easy':   'easy',
    'medium': 'medium',
    'hard':   'hard',
}

def build_prompt(job_title, experience, category, difficulty, num_questions):
    cat_text  = CATEGORY_LABELS.get(category, 'technical, behavioral, and situational')
    diff_text = DIFFICULTY_LABELS.get(difficulty, 'a mix of easy, medium, and hard')

    # randomness
    seed = random.randint(1, 100000)

    return f"""
You are an expert HR interviewer and technical recruiter.

Generate EXACTLY {num_questions} UNIQUE interview questions for a {experience}-level {job_title} candidate.

IMPORTANT:
- Do NOT repeat common or generic questions
- Make this set DIFFERENT from previous ones
- Use a different angle or variation each time
- Random seed: {seed}

- Categories to include: {cat_text}
- Difficulty level: {diff_text}

Return ONLY a valid JSON array. No explanation.

Each object must have:
"question", "category", "difficulty", "hint"

Generate now.
"""


def clean_json(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r'^```json\s*', '', raw)
    raw = re.sub(r'^```\s*',     '', raw)
    raw = re.sub(r'\s*```$',     '', raw)
    return raw.strip()


def try_groq(prompt):
    if not groq_client:
        return None
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Groq failed: {e}")
        return None


def generate_questions(job_title, experience, category, difficulty, num_questions, variation=None):
    prompt = build_prompt(job_title, experience, category, difficulty, num_questions)
    # 🔥 ADD THIS
    if variation:
        prompt += f"\nGenerate a DIFFERENT set than before. Variation ID: {variation}"
    raw    = None

    # Try Gemini first
    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=prompt,
            config={
                "temperature": 0.9,   # 🔥 more creativity
                "top_p": 0.95
            }
        )
        raw = response.text
        print("✅ Gemini responded")
    except Exception as e:
        print(f"⚠️  Gemini failed: {e} — trying Groq...")
        raw = try_groq(prompt)

    if not raw:
        return {'error': 'Both Gemini and Groq failed. Check your API keys and internet.'}

    try:
        questions = json.loads(clean_json(raw))
        validated = []
        for q in questions:
            if isinstance(q, dict) and 'question' in q:
                validated.append({
                    'question':   str(q.get('question', '')),
                    'category':   q.get('category',   'technical').lower(),
                    'difficulty': q.get('difficulty', 'medium').lower(),
                    'hint':       str(q.get('hint', '')),
                })
        if not validated:
            return {'error': 'AI returned empty or invalid questions. Try again.'}
        return validated
    except json.JSONDecodeError as e:
        return {'error': f'Could not parse AI response: {str(e)}'}
    except Exception as e:
        return {'error': f'Unexpected error: {str(e)}'}
