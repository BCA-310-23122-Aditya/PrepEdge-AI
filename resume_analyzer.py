"""
resume_analyzer.py — Resume parsing, ATS scoring, role detection.
Dependencies: PyMuPDF (fitz), python-docx
Install: pip install PyMuPDF python-docx
"""
import re, json, io
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

try:
    from docx import Document
except ImportError:
    Document = None

# ── Text extraction ────────────────────────────────────────────────────────────

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF bytes using PyMuPDF."""
    try:
        if fitz is None:
            raise ImportError("PyMuPDF not installed. Run: pip install PyMuPDF")
        doc  = fitz.open(stream=file_bytes, filetype="pdf")
        text = "\n".join(page.get_text() for page in doc)
        doc.close()
        return text.strip()
    except ImportError as e:
        raise RuntimeError(str(e))
    except Exception as e:
        raise RuntimeError(f"PDF parsing failed: {e}")


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX bytes using python-docx."""
    try:
        if Document is None:
            raise ImportError("python-docx not installed. Run: pip install python-docx")
        doc  = Document(io.BytesIO(file_bytes))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return text.strip()
    except ImportError as e:
        raise RuntimeError(str(e))
    except Exception as e:
        raise RuntimeError(f"DOCX parsing failed: {e}")


def extract_resume_text(file_bytes: bytes, filename: str) -> str:
    """Route to correct parser by file extension."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        return extract_text_from_docx(file_bytes)
    else:
        raise ValueError(f"Unsupported file type: {ext}. Use PDF or DOCX.")


# ── Role detection ─────────────────────────────────────────────────────────────

# Roles and their keyword signals, split by strength tier:
# PRIMARY = strong title-level keywords (high weight 4)
# SECONDARY = supporting keywords that confirm the role (weight 2)
# CONTEXT = peripheral terms that weakly suggest the role (weight 1)
ROLE_SIGNALS = {
    "Software Engineer": {
        "primary":   ["software engineer", "software developer", "backend developer", "backend engineer", "swe"],
        "secondary": ["object-oriented", "system design", "api development", "rest api", "microservices"],
        "context":   ["python", "java", "c++", "golang", "spring boot", "django", "flask"]
    },
    "Frontend Developer": {
        "primary":   ["frontend developer", "front-end developer", "ui developer", "react developer", "vue developer", "angular developer"],
        "secondary": ["react", "angular", "vue", "html5", "css3", "javascript", "typescript", "webpack"],
        "context":   ["ui design", "web performance", "responsive design", "sass", "tailwind"]
    },
    "Full Stack Developer": {
        "primary":   ["full stack developer", "fullstack developer", "full-stack developer"],
        "secondary": ["full stack", "fullstack", "full-stack"],
        "context":   ["frontend", "backend", "node.js", "react", "express"]
    },
    "Data Scientist": {
        "primary":   ["data scientist", "machine learning engineer", "ml engineer", "ai engineer", "research scientist"],
        "secondary": ["machine learning", "deep learning", "nlp", "computer vision", "predictive modeling"],
        "context":   ["python", "tensorflow", "pytorch", "scikit-learn", "pandas", "statistics"]
    },
    "Data Analyst": {
        "primary":   ["data analyst", "business analyst", "bi analyst", "analytics engineer"],
        "secondary": ["tableau", "power bi", "data visualization", "business intelligence", "looker", "pivot table", "google analytics"],
        "context":   ["excel", "reporting", "dashboard", "kpi", "sql"]
    },
    "Data Engineer": {
        "primary":   ["data engineer", "etl developer", "data pipeline engineer"],
        "secondary": ["data pipeline", "apache spark", "airflow", "hadoop", "kafka", "etl", "dbt"],
        "context":   ["data warehouse", "snowflake", "bigquery", "redshift"]
    },
    "DevOps Engineer": {
        "primary":   ["devops engineer", "site reliability engineer", "sre", "platform engineer", "infrastructure engineer"],
        "secondary": ["kubernetes", "docker", "ci/cd", "terraform", "ansible", "jenkins"],
        "context":   ["cloud infrastructure", "deployment", "monitoring", "helm", "prometheus"]
    },
    "Cloud Architect": {
        "primary":   ["cloud architect", "solutions architect", "aws architect", "azure architect", "gcp architect"],
        "secondary": ["aws", "azure", "google cloud", "cloud migration", "cloud-native"],
        "context":   ["lambda", "ec2", "s3", "serverless", "vpc"]
    },
    "Cybersecurity Analyst": {
        "primary":   ["cybersecurity analyst", "security analyst", "penetration tester", "soc analyst", "information security officer", "security engineer"],
        "secondary": ["penetration testing", "vulnerability assessment", "siem", "incident response", "malware analysis", "threat intelligence"],
        "context":   ["firewall", "intrusion detection", "ceh", "cissp", "oscp", "ethical hacking"]
    },
    "Mobile Developer": {
        "primary":   ["android developer", "ios developer", "mobile developer", "flutter developer", "react native developer"],
        "secondary": ["android", "ios development", "swift", "kotlin", "flutter", "react native"],
        "context":   ["xcode", "android studio", "mobile app", "app store"]
    },
    "QA Engineer": {
        "primary":   ["qa engineer", "quality assurance engineer", "test engineer", "sdet", "automation engineer"],
        "secondary": ["test automation", "selenium", "cypress", "jest", "quality assurance"],
        "context":   ["test plan", "regression testing", "bug tracking", "jira"]
    },
    "Product Manager": {
        "primary":   ["product manager", "product owner", "head of product"],
        "secondary": ["product roadmap", "product strategy", "stakeholder management", "go-to-market"],
        "context":   ["agile", "scrum", "user research", "a/b testing", "okr"]
    },
    "Project Manager": {
        "primary":   ["project manager", "program manager", "scrum master", "agile coach", "pmp"],
        "secondary": ["project management", "project planning", "risk management", "project delivery"],
        "context":   ["ms project", "gantt", "stakeholders", "budget management"]
    },
    "UI/UX Designer": {
        "primary":   ["ux designer", "ui designer", "product designer", "ui/ux designer", "interaction designer"],
        "secondary": ["user experience", "user research", "wireframing", "prototyping", "usability testing"],
        "context":   ["figma", "sketch", "adobe xd", "invision", "zeplin"]
    },
    "Graphic Designer": {
        "primary":   ["graphic designer", "visual designer", "brand designer", "creative designer"],
        "secondary": ["brand identity", "visual design", "print design", "illustration"],
        "context":   ["adobe illustrator", "photoshop", "indesign", "branding"]
    },
    "Machine Learning Engineer": {
        "primary":   ["machine learning engineer", "mlops engineer", "ai/ml engineer"],
        "secondary": ["model deployment", "mlops", "model training", "feature engineering"],
        "context":   ["kubernetes", "docker", "mlflow", "model serving", "sagemaker"]
    },
    "Database Administrator": {
        "primary":   ["database administrator", "dba", "database engineer"],
        "secondary": ["database management", "database optimization", "sql tuning"],
        "context":   ["postgresql", "mysql", "oracle", "sql server", "backup"]
    },
    "Network Engineer": {
        "primary":   ["network engineer", "network administrator", "network architect"],
        "secondary": ["cisco", "ccna", "ccnp", "routing", "switching", "vpn"],
        "context":   ["tcp/ip", "bgp", "ospf", "firewall", "lan", "wan"]
    },
    "Embedded Engineer": {
        "primary":   ["embedded engineer", "firmware engineer", "embedded systems engineer"],
        "secondary": ["rtos", "microcontroller", "firmware development", "embedded c"],
        "context":   ["iot", "arduino", "raspberry pi", "arm cortex", "fpga"]
    },
    "Blockchain Developer": {
        "primary":   ["blockchain developer", "web3 developer", "smart contract developer"],
        "secondary": ["solidity", "ethereum", "web3.js", "smart contracts"],
        "context":   ["defi", "nft", "dapp", "metamask", "truffle"]
    },
    "Business Development": {
        "primary":   ["business development manager", "bd manager", "growth manager", "sales manager"],
        "secondary": ["business development", "revenue growth", "client acquisition", "partnerships"],
        "context":   ["crm", "pipeline", "lead generation", "account management"]
    },
    "Marketing Manager": {
        "primary":   ["marketing manager", "digital marketing manager", "growth hacker", "seo specialist", "content marketer"],
        "secondary": ["digital marketing", "seo", "sem", "content strategy", "email marketing"],
        "context":   ["google analytics", "hubspot", "social media", "campaign management"]
    },
    "HR Manager": {
        "primary":   ["hr manager", "human resources manager", "talent acquisition", "recruiter", "people operations"],
        "secondary": ["recruitment", "talent management", "employee relations", "onboarding"],
        "context":   ["hris", "payroll", "performance management", "learning and development"]
    },
    "Financial Analyst": {
        "primary":   ["financial analyst", "finance analyst", "investment analyst", "fp&a analyst"],
        "secondary": ["financial modeling", "valuation", "financial reporting", "budgeting"],
        "context":   ["excel", "bloomberg", "accounting", "cfa"]
    },
    "Accountant": {
        "primary":   ["accountant", "chartered accountant", "cpa", "tax consultant", "auditor"],
        "secondary": ["accounting", "tax filing", "financial statements", "audit"],
        "context":   ["quickbooks", "tally", "gst", "ifrs", "gaap"]
    },
    "Content Writer": {
        "primary":   ["content writer", "copywriter", "technical writer", "content strategist"],
        "secondary": ["content writing", "copywriting", "seo writing", "editorial"],
        "context":   ["blog", "cms", "wordpress", "storytelling"]
    },
    "Customer Success": {
        "primary":   ["customer success manager", "customer support manager", "client success manager"],
        "secondary": ["customer success", "customer support", "client onboarding", "churn reduction"],
        "context":   ["zendesk", "intercom", "nps", "customer satisfaction"]
    },
    "Operations Manager": {
        "primary":   ["operations manager", "supply chain manager", "logistics manager"],
        "secondary": ["operations management", "supply chain", "procurement", "inventory management"],
        "context":   ["erp", "lean", "six sigma", "process improvement"]
    },
    "Legal Counsel": {
        "primary":   ["lawyer", "attorney", "legal counsel", "solicitor", "corporate counsel"],
        "secondary": ["legal advisory", "contract drafting", "compliance", "litigation"],
        "context":   ["intellectual property", "mergers", "due diligence", "gdpr"]
    },
    "IT Support Analyst": {
        "primary":   ["service desk", "help desk", "it support", "technical support", "desktop support",
                      "application support", "system support"],
        "secondary": ["troubleshooting", "incident management", "itil", "ticketing system",
                      "remote support", "technical troubleshooting"],
        "context":   ["windows", "active directory", "vpn", "customer queries"]
    },
    "System Administrator": {
        "primary":   ["system administrator", "sysadmin", "linux administrator",
                      "windows administrator", "it administrator"],
        "secondary": ["active directory", "group policy", "server management", "patch management"],
        "context":   ["windows server", "linux", "vmware", "backup", "monitoring"]
    },
}

# Keep the old ROLE_PATTERNS for backward-compat with _score_keywords / _score_role_match
ROLE_PATTERNS = {role: list(sig["primary"]) + sig["secondary"] for role, sig in ROLE_SIGNALS.items()}


# ── Seeking statement extraction ───────────────────────────────────────────────

_PHRASE_MAP = [
    (["service desk", "help desk", "it support", "technical support", "desktop support",
      "application support", "system support", "customer support specialist",
      "customer support executive"], "IT Support Analyst"),
    (["software engineer", "software developer", "software development",
      "application development", "software & application", "software and application",
      "backend developer", "backend engineer", "swe"], "Software Engineer"),
    (["full stack", "fullstack", "full-stack"], "Full Stack Developer"),
    (["frontend", "front-end", "ui developer", "react developer", "web developer"], "Frontend Developer"),
    (["data scientist", "machine learning", "ml engineer", "ai engineer"], "Data Scientist"),
    (["data analyst", "business analyst", "data analytics"], "Data Analyst"),
    (["data engineer", "data pipeline", "etl developer"], "Data Engineer"),
    (["devops", "site reliability", "platform engineer", "cloud engineer"], "DevOps Engineer"),
    (["cloud architect", "solutions architect", "aws architect"], "Cloud Architect"),
    (["android developer", "ios developer", "mobile developer", "flutter developer",
      "react native developer"], "Mobile Developer"),
    (["cybersecurity", "security analyst", "penetration tester", "soc analyst"], "Cybersecurity Analyst"),
    (["ux designer", "ui designer", "product designer", "ui/ux"], "UI/UX Designer"),
    (["product manager", "product owner"], "Product Manager"),
    (["project manager", "program manager", "scrum master"], "Project Manager"),
    (["qa engineer", "test engineer", "quality assurance", "automation engineer"], "QA Engineer"),
    (["network engineer", "network administrator"], "Network Engineer"),
    (["system administrator", "sysadmin", "it administrator", "linux administrator"], "System Administrator"),
    (["database administrator", "dba", "database engineer"], "Database Administrator"),
    (["embedded", "firmware engineer", "iot engineer"], "Embedded Engineer"),
    (["blockchain developer", "web3", "smart contract"], "Blockchain Developer"),
    (["business development", "sales manager", "account executive"], "Business Development"),
    (["marketing manager", "digital marketing", "seo specialist"], "Marketing Manager"),
    (["financial analyst", "finance manager", "investment analyst"], "Financial Analyst"),
    (["hr manager", "human resources", "recruiter", "talent acquisition"], "HR Manager"),
    (["content writer", "copywriter", "technical writer"], "Content Writer"),
    (["graphic designer", "visual designer"], "Graphic Designer"),
    (["customer success", "client success"], "Customer Success"),
]


def _map_phrase_to_role(phrase: str) -> str:
    """Map a free-text role phrase to the best matching canonical role name."""
    phrase_lower = phrase.lower()
    for keywords, role in _PHRASE_MAP:
        if any(kw in phrase_lower for kw in keywords):
            return role
    return ""


def _extract_seeking_role(text: str) -> str:
    """
    Detect explicitly stated target role from common resume phrases like:
    - 'Seeking a Service Desk / Customer Support role at Capgemini'
    - 'Looking for a Software Development position'
    - 'Aspiring Full Stack Developer'
    - 'Objective: To obtain a Data Analyst role'
    Returns the canonical role name if matched, else empty string.
    """
    patterns = [
        # "Seeking/Looking for/Applying for a X role/position"
        r'(?:seeking|looking for|applying for|targeting|interested in)\s+(?:a\s+|an\s+)?'
        r'([\w\s/&,.-]{3,60}?)\s+(?:role|position|opportunity|job|internship)',
        # "Aspiring X Developer/Engineer/Analyst"
        r'aspiring\s+([\w\s/&]{3,40}?)\s+(?:developer|engineer|analyst|designer|manager|professional)',
        # "Objective: To get/obtain a X position"
        r'objective[\s:]+to\s+(?:obtain|get|secure|land|join|work as)\s+(?:a\s+|an\s+)?'
        r'([\w\s/&]{3,50}?)\s+(?:role|position)',
        # "To work as a / To join as a"
        r'to\s+(?:work|join|serve)\s+as\s+(?:a\s+|an\s+)?([\w\s/&]{3,50}?)(?:\s+at\b|\s+in\b|\.|$)',
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).strip().rstrip(".,;")
            mapped = _map_phrase_to_role(raw)
            if mapped:
                return mapped
    return ""


def _extract_header_text(text: str) -> str:
    """
    Precisely extract the resume header block — the first section before any
    standard resume section heading appears (Experience, Education, Skills, etc.).
    This is where the candidate's actual job title is stated.
    """
    section_markers = re.compile(
        r'^\s*(work\s+experience|experience|employment|education|skills|summary|objective|'
        r'projects|certifications|achievements|profile|professional\s+summary|'
        r'technical\s+skills|soft\s+skills|publications|volunteer|awards|interests)\s*$',
        re.IGNORECASE | re.MULTILINE
    )
    # Find the first section marker
    match = section_markers.search(text)
    if match:
        header = text[:match.start()]
    else:
        # Fall back to first 20 lines
        header = "\n".join(text.splitlines()[:20])
    return header.lower()


def _extract_title_lines(text: str) -> list[str]:
    """
    Extract ONLY lines that look like professional job title declarations
    from the resume header (before the first section heading).
    Strict filters prevent email/phone/URL lines from being included.
    """
    header = _extract_header_text(text)
    lines = header.splitlines()
    title_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip lines with email addresses
        if re.search(r'[\w.+%-]+@[\w.-]+\.\w+', stripped):
            continue
        # Skip lines with phone numbers (many digits)
        if re.search(r'[\d]{3}[\s.()-]{0,2}[\d]{3,}', stripped):
            continue
        # Skip lines with URLs
        if re.search(r'https?://|linkedin\.com|github\.com|www\.', stripped):
            continue
        # Skip lines that are clearly just a name (single word or all caps short)
        words = stripped.split()
        if len(words) < 2 or len(words) > 7:
            continue
        # Skip lines that are mostly numbers or special characters
        alpha_chars = sum(c.isalpha() for c in stripped)
        if alpha_chars < len(stripped) * 0.6:
            continue
        title_lines.append(stripped)

    return title_lines


def detect_roles(text: str) -> list[str]:
    """Return list of detected roles, ordered by confidence."""
    text_lower = text.lower()

    # --- Pass 0: Seeking/Objective statement (HIGHEST PRIORITY) ---
    # If the resume explicitly says "Seeking a X role", trust that completely.
    seeking_role = _extract_seeking_role(text)
    if seeking_role:
        # Return it as primary; still run scoring to suggest alternates
        results = [seeking_role]
    else:
        results = []

    # --- Pass 1: Direct exact-match scan of ENTIRE text for primary phrases ---
    direct_hits: dict[str, int] = {}
    for role, signals in ROLE_SIGNALS.items():
        for p in signals["primary"]:
            occurrences = text_lower.count(p)
            if occurrences > 0:
                direct_hits[role] = direct_hits.get(role, 0) + occurrences

    # --- Pass 2: Weighted header-area title match ---
    title_lines = _extract_title_lines(text)
    title_blob  = " ".join(title_lines)

    scores: dict[str, float] = {}

    for role, signals in ROLE_SIGNALS.items():
        score = 0.0

        # Direct hit bonus (×6 per occurrence)
        if role in direct_hits:
            score += direct_hits[role] * 6

        # Primary signals in header title block (×10 each)
        for p in signals["primary"]:
            if p in title_blob:
                score += 10

        # Secondary signals (role-specific tools/concepts) — ×1.5 each
        secondary_hits = sum(1 for p in signals["secondary"] if p in text_lower)
        score += secondary_hits * 1.5

        # Context signals — capped at 2, weight 0.5 (prevents pollution)
        context_hits = sum(1 for p in signals["context"] if p in text_lower)
        score += min(context_hits, 2) * 0.5

        if score > 0:
            scores[role] = score

    if not scores and not results:
        return ["Software Professional"]

    # Sort by score
    sorted_roles = sorted(scores, key=lambda r: scores[r], reverse=True)

    if seeking_role:
        # Already have a primary — add scored alternatives (excluding duplicates)
        for r in sorted_roles:
            if r not in results:
                results.append(r)
            if len(results) >= 3:
                break
        return results[:3]

    # No seeking statement — use scores only, with 20% threshold
    top_score = scores[sorted_roles[0]]
    filtered  = [r for r in sorted_roles[:6] if scores[r] >= top_score * 0.20]
    return filtered[:3]


# ── ATS Scoring ────────────────────────────────────────────────────────────────

SECTION_HEADERS = [
    "experience", "work experience", "employment", "education", "skills",
    "summary", "objective", "projects", "certifications", "achievements",
    "publications", "languages", "volunteer", "awards", "interests",
    "profile", "professional summary", "technical skills", "soft skills",
]

POWER_VERBS = [
    "led", "managed", "developed", "designed", "implemented", "built",
    "created", "improved", "increased", "reduced", "optimized", "delivered",
    "launched", "architected", "streamlined", "automated", "mentored",
    "negotiated", "collaborated", "executed", "achieved", "spearheaded",
    "coordinated", "facilitated", "established", "generated", "transformed",
]

TECH_KEYWORDS = [
    "python", "java", "javascript", "typescript", "react", "angular", "vue",
    "node.js", "django", "flask", "spring", "sql", "mysql", "postgresql",
    "mongodb", "redis", "aws", "azure", "gcp", "docker", "kubernetes",
    "terraform", "ci/cd", "git", "linux", "rest", "api", "microservices",
    "machine learning", "tensorflow", "pytorch", "pandas", "numpy",
    "scala", "spark", "hadoop", "kafka", "elasticsearch", "graphql",
    "swift", "kotlin", "flutter", "react native", "c++", "c#", "go",
    "rust", "php", "ruby", "html", "css", "sass", "webpack", "agile",
    "scrum", "jira", "figma", "sketch", "tableau", "power bi",
]


def _score_sections(text: str) -> dict:
    """Check which standard resume sections are present."""
    text_lower = text.lower()
    found = [h for h in SECTION_HEADERS if h in text_lower]
    critical = {"experience", "education", "skills"}
    has_critical = critical.issubset(set(found))
    score = min(100, int((len(found) / max(len(SECTION_HEADERS), 1)) * 140))
    missing = [h.title() for h in SECTION_HEADERS[:8] if h not in text_lower]
    return {
        "score":        min(score, 100),
        "found":        [h.title() for h in found],
        "missing":      missing[:4],
        "has_critical": has_critical,
    }


def _score_keywords(text: str, target_role: str = "") -> dict:
    """Score based on presence of tech/professional keywords."""
    text_lower = text.lower()
    found_tech = [k for k in TECH_KEYWORDS if k in text_lower]
    found_verbs = [v for v in POWER_VERBS if v in text_lower]

    # Role-specific keyword bonus
    role_bonus = 0
    if target_role:
        role_lower = target_role.lower()
        for role, patterns in ROLE_PATTERNS.items():
            if role_lower in role.lower() or any(p in role_lower for p in patterns):
                role_specific = [p for p in patterns if p in text_lower]
                role_bonus = min(20, len(role_specific) * 5)
                break

    kw_score  = min(50, len(found_tech) * 4)
    verb_score = min(30, len(found_verbs) * 3)
    total = min(100, kw_score + verb_score + role_bonus)

    return {
        "score":        total,
        "tech_keywords": found_tech[:10],
        "power_verbs":  found_verbs[:8],
        "keyword_count": len(found_tech),
        "verb_count":   len(found_verbs),
    }


def _score_readability(text: str) -> dict:
    """Score readability: sentence length, word variety, bullet points."""
    words      = re.findall(r'\b\w+\b', text)
    sentences  = re.split(r'[.!?]+', text)
    sentences  = [s.strip() for s in sentences if len(s.strip()) > 10]
    avg_sent_len = (sum(len(s.split()) for s in sentences) / max(len(sentences), 1))

    bullet_lines = len(re.findall(r'^\s*[\•\-\*\◦\▪]\s', text, re.MULTILINE))
    unique_ratio = len(set(w.lower() for w in words)) / max(len(words), 1)

    # Score components
    length_score    = 100 if 8 <= avg_sent_len <= 20 else max(0, 100 - abs(avg_sent_len - 14) * 5)
    bullet_score    = min(100, bullet_lines * 8)
    variety_score   = min(100, int(unique_ratio * 120))
    total           = int((length_score * 0.35 + bullet_score * 0.35 + variety_score * 0.30))

    issues = []
    if avg_sent_len > 25:  issues.append("Some sentences are too long — aim for under 20 words.")
    if avg_sent_len < 5:   issues.append("Sentences are too short — add more detail.")
    if bullet_lines < 5:   issues.append("Use more bullet points to improve scannability.")
    if unique_ratio < 0.4: issues.append("Too many repeated words — vary your vocabulary.")

    return {
        "score":          min(total, 100),
        "avg_sentence_len": round(avg_sent_len, 1),
        "bullet_points":  bullet_lines,
        "word_count":     len(words),
        "issues":         issues,
    }


def _score_completeness(text: str) -> dict:
    """Check for contact info, quantified achievements, dates."""
    has_email    = bool(re.search(r'[\w.+-]+@[\w-]+\.\w+', text))
    has_phone    = bool(re.search(r'[\+\(]?\d[\d\s\-\(\)]{7,}', text))
    has_linkedin = "linkedin" in text.lower()
    has_github   = "github" in text.lower()
    has_numbers  = bool(re.search(r'\b\d+[%x+]?\b', text))   # quantified achievements
    has_dates    = bool(re.search(r'\b(19|20)\d{2}\b', text))
    word_count   = len(text.split())

    contact_score     = sum([has_email * 25, has_phone * 25, has_linkedin * 25, has_github * 25])
    achievement_score = 60 if has_numbers else 20
    length_score      = min(100, int((word_count / 600) * 100))
    total             = int(contact_score * 0.3 + achievement_score * 0.4 + length_score * 0.3)

    missing_contact = []
    if not has_email:    missing_contact.append("Email address")
    if not has_phone:    missing_contact.append("Phone number")
    if not has_linkedin: missing_contact.append("LinkedIn URL")

    return {
        "score":          min(total, 100),
        "has_email":      has_email,
        "has_phone":      has_phone,
        "has_linkedin":   has_linkedin,
        "has_github":     has_github,
        "has_numbers":    has_numbers,
        "has_dates":      has_dates,
        "word_count":     word_count,
        "missing_contact": missing_contact,
    }


def _score_role_match(text: str, target_role: str) -> dict:
    """How well does the resume match the target role?"""
    if not target_role:
        return {"score": 50, "message": "No target role specified.", "matched_patterns": []}

    text_lower      = target_role.lower()
    role_patterns   = []
    for role, patterns in ROLE_PATTERNS.items():
        if text_lower in role.lower() or any(p in text_lower for p in patterns):
            role_patterns = patterns
            break

    if not role_patterns:
        # Generic: check if target words appear in text
        words = re.findall(r'\b\w+\b', target_role.lower())
        matched = [w for w in words if w in text.lower() and len(w) > 3]
        score = min(100, len(matched) * 25)
        return {"score": score, "message": f"Partial match for '{target_role}'.", "matched_patterns": matched}

    found = [p for p in role_patterns if p in text.lower()]
    score = min(100, int((len(found) / max(len(role_patterns), 1)) * 100) + 10)
    return {
        "score":            min(score, 100),
        "matched_patterns": found,
        "total_patterns":   len(role_patterns),
        "message":          f"Matched {len(found)}/{len(role_patterns)} role signals.",
    }


def run_ats_analysis(resume_text: str, target_role: str = "") -> dict:
    """
    Full ATS analysis. Returns a structured dict with sub-scores and recommendations.
    """
    sections    = _score_sections(resume_text)
    keywords    = _score_keywords(resume_text, target_role)
    readability = _score_readability(resume_text)
    completeness= _score_completeness(resume_text)
    role_match  = _score_role_match(resume_text, target_role)

    # Weighted overall score
    overall = int(
        sections["score"]     * 0.20 +
        keywords["score"]     * 0.30 +
        readability["score"]  * 0.15 +
        completeness["score"] * 0.20 +
        role_match["score"]   * 0.15
    )

    # Strengths
    strengths = []
    if sections["score"]     >= 70: strengths.append("Well-structured with clear section headers.")
    if keywords["score"]     >= 65: strengths.append(f"Good keyword density ({keywords['keyword_count']} tech skills detected).")
    if readability["score"]  >= 65: strengths.append("Readable format with good use of bullet points.")
    if completeness["has_email"] and completeness["has_phone"]: strengths.append("Contact information is complete.")
    if completeness["has_numbers"]:  strengths.append("Includes quantified achievements (numbers/percentages).")
    if completeness["has_linkedin"]: strengths.append("LinkedIn profile is referenced.")
    if keywords["verb_count"] >= 5:  strengths.append(f"Uses {keywords['verb_count']} action verbs — strong impact language.")

    # Weaknesses
    weaknesses = []
    if sections["score"]      < 60: weaknesses.append("Missing important resume sections.")
    if keywords["score"]      < 50: weaknesses.append("Low keyword density — add more relevant technical skills.")
    if readability["score"]   < 50: weaknesses.append("Readability needs improvement.")
    if completeness["score"]  < 50: weaknesses.append("Resume feels incomplete — add more detail.")
    if not completeness["has_numbers"]: weaknesses.append("No quantified achievements — add numbers to show impact.")
    if completeness["missing_contact"]: weaknesses.append(f"Missing contact info: {', '.join(completeness['missing_contact'])}.")
    if role_match["score"]    < 50: weaknesses.append(f"Resume may not be well-targeted for '{target_role}'." if target_role else "Consider targeting a specific role.")
    weaknesses.extend(readability["issues"])

    # Suggestions
    suggestions = []
    if sections["missing"]:
        suggestions.append(f"Add these missing sections: {', '.join(sections['missing'][:3])}.")
    if not completeness["has_github"]:
        suggestions.append("Add a GitHub profile URL to showcase your projects.")
    if not completeness["has_linkedin"]:
        suggestions.append("Add your LinkedIn profile URL.")
    if keywords["keyword_count"] < 8:
        suggestions.append("Add more technical skills relevant to your target role.")
    if keywords["verb_count"] < 5:
        suggestions.append("Start bullet points with strong action verbs (Led, Built, Designed, Improved, etc.).")
    if not completeness["has_numbers"]:
        suggestions.append("Quantify your achievements: 'Improved performance by 40%', 'Led a team of 8', etc.")
    if completeness["word_count"] < 300:
        suggestions.append("Resume is too short — aim for 400–700 words for a strong impression.")
    elif completeness["word_count"] > 900:
        suggestions.append("Resume may be too long — consider trimming to 1–2 pages (500–700 words).")

    return {
        "overall_score":    overall,
        "grade":            _grade(overall),
        "sub_scores": {
            "sections":     sections["score"],
            "keywords":     keywords["score"],
            "readability":  readability["score"],
            "completeness": completeness["score"],
            "role_match":   role_match["score"],
        },
        "details": {
            "sections":     sections,
            "keywords":     keywords,
            "readability":  readability,
            "completeness": completeness,
            "role_match":   role_match,
        },
        "strengths":    strengths,
        "weaknesses":   weaknesses,
        "suggestions":  suggestions,
        "detected_roles": detect_roles(resume_text),
        "target_role":    target_role,
    }


def _grade(score: int) -> str:
    if score >= 85: return "Excellent"
    if score >= 70: return "Good"
    if score >= 55: return "Fair"
    if score >= 40: return "Needs Work"
    return "Poor"
