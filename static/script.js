/* ═══════════════════════════════════════════════════════════════
   InterviewAI — script.js  (consolidated & fixed)
═══════════════════════════════════════════════════════════════ */

/* ── State ── */
const prepState = {
  activeTab: 'job',
  job: { questions: [], sessionId: null, title: '', meta: '' },
  resume: { questions: [], sessionId: null, title: '', meta: '' }
};

Object.defineProperty(window, 'currentQuestions', {
  get: () => prepState[prepState.activeTab].questions,
  set: (v) => { prepState[prepState.activeTab].questions = v; }
});
Object.defineProperty(window, 'currentSessionId', {
  get: () => prepState[prepState.activeTab].sessionId,
  set: (v) => { prepState[prepState.activeTab].sessionId = v; }
});

let chart = null;
let performanceData = [];

/* ── Mock state ── */
let _mockIdx = 0;
let _mockQs = [];
let _mockTimer = null;
let _mockSecs = 60;
let _transcript = '';
let _interim = '';
let _recognition = null;
let _micActive = false;
const MOCK_TOTAL = 60;

/* ══════════════════════════════════════════════════════════════
   UTILS
══════════════════════════════════════════════════════════════ */
function showToast(msg, duration = 2800) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._tid);
  t._tid = setTimeout(() => t.classList.remove('show'), duration);
}

/* ══════════════════════════════════════════════════════════════
   PREP MODE TABS (Job Title ↔ Resume)
══════════════════════════════════════════════════════════════ */
let _currentPrepTab = 'job';
let _uploadedResumeId = null;

function switchPrepTab(tab) {
  _currentPrepTab = tab;
  prepState.activeTab = tab;
  document.getElementById('prep-panel-job').style.display = tab === 'job' ? 'block' : 'none';
  document.getElementById('prep-panel-resume').style.display = tab === 'resume' ? 'block' : 'none';
  document.getElementById('tab-job').classList.toggle('active', tab === 'job');
  document.getElementById('tab-resume').classList.toggle('active', tab === 'resume');
  refreshActiveStateUI();
}

function refreshActiveStateUI() {
  const s = prepState[prepState.activeTab];
  if (s && s.questions && s.questions.length > 0) {
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('results-area').style.display = 'block';
    document.getElementById('normal-view').style.display = 'block';
    document.getElementById('mock-mode').style.display = 'none';

    document.getElementById('results-title').textContent = s.title || `${s.questions.length} questions`;
    document.getElementById('results-meta').textContent = s.meta || '';

    document.querySelectorAll('.filter-chip').forEach((c, i) => c.classList.toggle('active', i === 0));
    renderQuestions(s.questions);
  } else {
    document.getElementById('empty-state').style.display = 'block';
    document.getElementById('results-area').style.display = 'none';
  }
}

/* ══════════════════════════════════════════════════════════════
   RESUME DROPZONE
══════════════════════════════════════════════════════════════ */
function resumeDragOver(e) {
  e.preventDefault();
  document.getElementById('resume-dropzone').classList.add('drag-over');
}
function resumeDragLeave(e) {
  document.getElementById('resume-dropzone').classList.remove('drag-over');
}
function resumeDrop(e) {
  e.preventDefault();
  document.getElementById('resume-dropzone').classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) _handleResumeFile(file);
}
function onResumeFileSelected(input) {
  if (input.files && input.files[0]) _handleResumeFile(input.files[0]);
}

function _handleResumeFile(file) {
  // Frontend validation
  const allowed = ['application/pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword'];
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['pdf', 'docx', 'doc'].includes(ext)) {
    showToast('❌ Only PDF or DOCX files are allowed.');
    return;
  }
  if (file.size > 5 * 1024 * 1024) {
    showToast('❌ File too large. Maximum size is 5 MB.');
    return;
  }
  _uploadResume(file);
}

async function _uploadResume(file) {
  // Show progress bar
  const statusBar = document.getElementById('resume-upload-status');
  const fileName = document.getElementById('rsb-file-name');
  const progress = document.getElementById('rsb-progress');
  const label = document.getElementById('rsb-label');
  const spinner = document.getElementById('resume-spinner');
  const atsPanel = document.getElementById('ats-result-panel');
  const spinLabel = document.getElementById('resume-spinner-label');

  // Reset
  _uploadedResumeId = null;
  if (atsPanel) atsPanel.style.display = 'none';
  statusBar.style.display = 'block';
  fileName.textContent = file.name;
  progress.style.width = '0%';
  label.textContent = 'Uploading…';

  // Animate progress to 70% while uploading
  let pct = 0;
  const tick = setInterval(() => {
    if (pct < 70) { pct += 4; progress.style.width = pct + '%'; }
  }, 80);

  const targetInput = document.getElementById('resume-target-role');
  let targetRole = (targetInput?.value || '').trim();
  
  // If the target role was auto-populated from a previous upload, clear it so this new resume can be auto-detected correctly
  if (targetInput && targetInput.getAttribute('data-auto-populated') === 'true') {
    targetRole = '';
    targetInput.value = '';
    targetInput.removeAttribute('data-auto-populated');
  }

  const formData = new FormData();
  formData.append('resume', file);
  if (targetRole) formData.append('target_role', targetRole);

  try {
    const res = await fetch('/upload-resume', { method: 'POST', body: formData });
    clearInterval(tick);
    
    let data;
    try {
      data = await res.json();
    } catch (err) {
      // If parsing fails (e.g., HTML 500 error), extract text or fallback
      const text = await res.text().catch(() => '');
      data = { error: text.includes('<html') ? 'Server crashed (500 Error). Check terminal.' : 'Invalid response from server.' };
    }

    if (!res.ok || data.error) {
      progress.style.width = '100%';
      progress.style.background = '#ef4444';
      label.textContent = '❌ ' + (data.error || 'Upload failed.');
      if (spinner) spinner.style.display = 'none';
      return;
    }

    // Complete progress
    progress.style.width = '100%';
    label.textContent = '✅ Analysed successfully!';
    _uploadedResumeId = data.resume_id;

    // Show spinner while rendering
    if (spinner) { spinner.style.display = 'block'; spinLabel.textContent = 'Building ATS report…'; }

    // Fill detected role hint
    const detectedHint = document.getElementById('detected-role-hint');
    const targetInput = document.getElementById('resume-target-role');
    if (data.detected_role && targetInput && !targetInput.value) {
      targetInput.value = data.detected_role;
      targetInput.setAttribute('data-auto-populated', 'true');
    }
    
    // Listen for manual user edits to remove the auto-populated flag
    if (targetInput) {
      targetInput.addEventListener('input', function() {
        this.removeAttribute('data-auto-populated');
      }, { once: true });
    }
    if (detectedHint) {
      const all = (data.all_detected || []).join(', ');
      detectedHint.textContent = all ? `Detected: ${all}` : 'No role detected automatically.';
    }

    // Render ATS panel
    _renderAtsPanel(data.ats);

    if (spinner) spinner.style.display = 'none';
    if (atsPanel) atsPanel.style.display = 'block';

  } catch (e) {
    clearInterval(tick);
    progress.style.width = '100%';
    progress.style.background = '#ef4444';
    label.textContent = '❌ Network error. Please try again.';
    if (spinner) spinner.style.display = 'none';
  }
}

function _renderAtsPanel(ats) {
  if (!ats) return;
  const overall = ats.overall_score || 0;
  const grade = ats.grade || '—';
  const sub = ats.sub_scores || {};

  // Score circle
  const arc = document.getElementById('ats-arc');
  const num = document.getElementById('ats-score-num');
  const gradeEl = document.getElementById('ats-grade');
  if (arc) {
    const circumference = 2 * Math.PI * 18; // r=18 → ~113.1
    const offset = circumference - (overall / 100) * circumference;
    arc.style.strokeDashoffset = offset.toFixed(1);
    const clr = overall >= 75 ? '#34d399' : overall >= 55 ? '#a78bfa' : overall >= 40 ? '#fbbf24' : '#f87171';
    arc.style.stroke = clr;
  }
  if (num) num.textContent = overall;
  if (gradeEl) gradeEl.textContent = `${grade} · ${overall}/100`;

  // Sub-score bars
  const subsEl = document.getElementById('ats-sub-scores');
  if (subsEl) {
    const labels = { sections: 'Structure', keywords: 'Keywords', readability: 'Readability', completeness: 'Completeness', role_match: 'Role Match' };
    subsEl.innerHTML = Object.entries(labels).map(([k, label]) => {
      const v = sub[k] || 0;
      const clr = v >= 70 ? '#34d399' : v >= 50 ? '#7b68ee' : v >= 35 ? '#fbbf24' : '#f87171';
      return `<div class="ats-sub-row">
        <span class="ats-sub-label">${label}</span>
        <div class="ats-sub-bar-wrap"><div class="ats-sub-bar" style="width:${v}%;background:${clr}"></div></div>
        <span class="ats-sub-num">${v}</span>
      </div>`;
    }).join('');
  }

  // Strengths/Weaknesses/Suggestions
  function renderItems(listId, items, icon) {
    const el = document.getElementById(listId);
    if (!el) return;
    if (!items || items.length === 0) {
      el.innerHTML = `<div class="ats-item"><span class="ats-item-dot">—</span><span>None found.</span></div>`;
      return;
    }
    el.innerHTML = items.map(t =>
      `<div class="ats-item"><span class="ats-item-dot">${icon}</span><span>${escFe(t)}</span></div>`
    ).join('');
  }
  renderItems('ats-tab-strengths', ats.strengths, '✅');
  renderItems('ats-tab-weaknesses', ats.weaknesses, '⚠️');
  renderItems('ats-tab-suggestions', ats.suggestions, '💡');
}

function switchAtsTab(tab, btn) {
  ['strengths', 'weaknesses', 'suggestions'].forEach(t => {
    const el = document.getElementById('ats-tab-' + t);
    if (el) el.style.display = t === tab ? 'flex' : 'none';
  });
  document.querySelectorAll('.ats-stab').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
}

function escFe(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

/* ══════════════════════════════════════════════════════════════
   GENERATE FROM RESUME
══════════════════════════════════════════════════════════════ */
async function generateFromResume(isRegenerate = false) {
  if (!_uploadedResumeId) {
    showToast('Please upload your resume first.');
    return;
  }
  const jobTitle = (document.getElementById('resume-target-role')?.value || '').trim();
  const experience = document.getElementById('resume-experience')?.value || 'mid-level';
  const category = document.getElementById('resume-category')?.value || 'all';
  const difficulty = document.getElementById('resume-difficulty')?.value || 'mixed';
  const numQs = document.getElementById('resume-num_questions')?.value || 10;
  const btn = document.getElementById('resume-gen-btn');

  if (btn) { btn.disabled = true; btn.innerHTML = '<span>⏳</span> Generating…'; }

  const spinnerEl = document.getElementById('spinner');
  const emptyEl = document.getElementById('empty-state');
  const resultsEl = document.getElementById('results-area');

  if (spinnerEl) spinnerEl.classList.add('show');
  if (emptyEl) emptyEl.style.display = 'none';
  if (resultsEl) resultsEl.style.display = 'none';

  try {
    const res = await fetch('/generate-from-resume', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        resume_id: _uploadedResumeId,
        job_title: jobTitle,
        experience: experience,
        category: category,
        difficulty: difficulty,
        num_questions: parseInt(numQs, 10),
        variation: isRegenerate ? Date.now() : 0
      }),
    });
    const data = await res.json();
    if (data.error) {
      showToast('❌ ' + data.error);
      if (spinnerEl) spinnerEl.classList.remove('show');
      if (emptyEl) emptyEl.style.display = 'block';
      if (btn) { btn.disabled = false; btn.innerHTML = '<span>🎤</span> Generate Interview Questions'; }
      return;
    }

    // Store in resume state explicitly to ensure consistency even if user switched tabs mid-flight
    prepState.resume.questions = data.questions;
    prepState.resume.sessionId = data.session_id;
    prepState.resume.title = `${data.questions.length} questions — ${data.job_title}`;
    prepState.resume.meta = `${experience} · ${category} · ${difficulty}`;

    resetPerformance();

    // If we're still on the resume tab, refresh the UI
    if (prepState.activeTab === 'resume') {
      refreshActiveStateUI();
    }

    if (spinnerEl) spinnerEl.classList.remove('show');
    if (data.skill_hint) showToast('✅ Questions tailored using resume skills!');
  } catch (e) {
    showToast('❌ Network error.');
    if (spinnerEl) spinnerEl.classList.remove('show');
    if (emptyEl) emptyEl.style.display = 'block';
  }
  if (btn) { btn.disabled = false; btn.innerHTML = '<span>🎤</span> Generate Interview Questions'; }
}

/* ══════════════════════════════════════════════════════════════
   FEATURE 1 — LOGOUT CONFIRMATION MODAL
══════════════════════════════════════════════════════════════ */
function openLogoutModal() {
  const m = document.getElementById('logout-modal');
  if (m) { m.classList.add('open'); document.body.style.overflow = 'hidden'; }
}
function closeLogoutModal() {
  const m = document.getElementById('logout-modal');
  if (m) { m.classList.remove('open'); document.body.style.overflow = ''; }
}
function confirmLogout() {
  closeLogoutModal();
  window.location.href = '/logout';
}

/* ══════════════════════════════════════════════════════════════
   FEATURE 2 — DELETE ACCOUNT MODAL
══════════════════════════════════════════════════════════════ */
function openDeleteAccountModal() {
  const m = document.getElementById('delete-account-modal');
  if (!m) return;
  m.querySelectorAll('input[type="radio"]').forEach(cb => cb.checked = false);
  const ta = document.getElementById('da-comment');
  if (ta) ta.value = '';
  const stat = document.getElementById('da-status');
  if (stat) { stat.textContent = ''; stat.className = 'confirm-status'; }
  const btn = document.getElementById('da-confirm-btn');
  if (btn) { btn.disabled = false; btn.textContent = '🗑 Delete My Account'; }
  m.classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeDeleteAccountModal() {
  const m = document.getElementById('delete-account-modal');
  if (m) { m.classList.remove('open'); document.body.style.overflow = ''; }
}
async function submitDeleteAccount() {
  const stat = document.getElementById('da-status');
  const btn = document.getElementById('da-confirm-btn');
  const modal = document.getElementById('delete-account-modal');
  const selectedReason = modal.querySelector('input[type="radio"]:checked');
  if (!selectedReason) {
    if (stat) { stat.textContent = '❌ Please select a reason for leaving.'; stat.className = 'confirm-status err'; }
    return;
  }
  const reasons = [selectedReason.value];
  const comment = (document.getElementById('da-comment')?.value || '').trim();
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Deleting…'; }
  if (stat) { stat.textContent = ''; stat.className = 'confirm-status'; }
  try {
    const res = await fetch('/delete-account', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reasons, comment }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      if (stat) { stat.textContent = '❌ ' + (data.error || 'Failed. Please try again.'); stat.className = 'confirm-status err'; }
      if (btn) { btn.disabled = false; btn.textContent = '🗑 Delete My Account'; }
      return;
    }
    if (stat) { stat.textContent = '✓ Account deleted. Redirecting…'; stat.className = 'confirm-status ok'; }
    setTimeout(() => { window.location.href = '/login'; }, 1800);
  } catch (e) {
    if (stat) { stat.textContent = '❌ Network error. Please try again.'; stat.className = 'confirm-status err'; }
    if (btn) { btn.disabled = false; btn.textContent = '🗑 Delete My Account'; }
  }
}

/* ══════════════════════════════════════════════════════════════
   FEATURE 4 — FRONTEND JOB TITLE VALIDATION HELPERS
══════════════════════════════════════════════════════════════ */
const _FRONTEND_BLOCKED = new Set([
  'test', 'asdf', 'qwerty', 'zxcv', 'aaaa', 'bbbb', '1234', 'abcd', 'xxxx', 'dummy',
  'fake', 'temp', 'foo', 'bar', 'baz', 'idk', 'lol', 'lmao', 'wtf', 'omg', 'bruh',
  'hack', 'null', 'undefined', 'admin', 'password', 'blah', 'none',
]);
const _PROFANITY_FE = new Set([
  'fuck', 'shit', 'ass', 'bitch', 'cunt', 'dick', 'pussy', 'cock', 'bastard',
  'nigger', 'nigga', 'retard', 'whore', 'slut', 'piss', 'crap', 'twat',
]);

function _frontendValidateJobTitle(title) {
  const t = title.trim();
  if (!t) return 'Please enter a job title.';
  if (t.length < 3) return 'Job title must be at least 3 characters.';
  if (t.length > 80) return 'Job title must be less than 80 characters.';
  if (t.replace(/[^A-Za-z]/g, '').length < 3) return 'Job title must contain at least 3 letters.';
  if (/(.)\1{3,}/.test(t.toLowerCase())) return 'Please enter a valid job title.';
  const tl = t.toLowerCase();
  for (const w of _PROFANITY_FE) {
    if (new RegExp('\\b' + w + '\\b').test(tl)) return 'Please enter an appropriate and meaningful job title.';
  }
  for (const w of tl.split(/\s+/)) {
    const c = w.replace(/[^a-z]/g, '');
    if (_FRONTEND_BLOCKED.has(c)) return 'Please enter a meaningful job title relevant to a real profession.';
  }
  for (const w of (tl.match(/[a-z]{5,}/g) || [])) {
    if (!/[aeiou]/.test(w)) return 'Please enter a meaningful job title.';
  }
  return '';
}

function _showJobTitleWarning(msg) {
  let el = document.getElementById('job-title-warning');
  if (!el) {
    el = document.createElement('div');
    el.id = 'job-title-warning';
    const jt = document.getElementById('job_title');
    if (jt && jt.parentNode) jt.parentNode.insertBefore(el, jt.nextSibling);
  }
  if (msg) {
    el.innerHTML = '<span class="jw-icon">⚠️</span><span>' + msg + '</span>';
    el.classList.add('show');
  } else {
    el.classList.remove('show');
    el.innerHTML = '';
  }
}

/* ══════════════════════════════════════════════════════════════
   GENERATE
══════════════════════════════════════════════════════════════ */
async function generateQuestions(isRegenerate = false) {
  const jobTitleEl = document.getElementById('job_title');
  if (!jobTitleEl) return;
  const jobTitle = jobTitleEl.value.trim();
  if (!jobTitle) { showToast('Please enter a job title'); jobTitleEl.focus(); return; }

  // ── FEATURE 4: Frontend job title validation ────────────────────────────
  const validErr = _frontendValidateJobTitle(jobTitle);
  if (validErr) {
    _showJobTitleWarning(validErr);
    jobTitleEl.focus();
    return;
  }
  _showJobTitleWarning(''); // clear any previous warning

  document.getElementById('spinner').classList.add('show');
  document.getElementById('empty-state').style.display = 'none';
  document.getElementById('results-area').style.display = 'none';
  const btn = document.getElementById('gen-btn');
  btn.disabled = true;
  btn.innerHTML = '<span>⏳</span> Generating…';

  const payload = {
    job_title: jobTitle,
    experience: document.getElementById('experience').value,
    category: document.getElementById('category').value,
    difficulty: document.getElementById('difficulty').value,
    num_questions: document.getElementById('num_questions').value,
    variation: isRegenerate ? Date.now() : 0
  };

  try {
    const res = await fetch('/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    let data;
    try { data = await res.json(); }
    catch { showToast('Server error — check Flask terminal'); resetUI(); return; }

    if (data.error) {
      if (data.invalid_title) {
        _showJobTitleWarning(data.error);
      } else {
        showToast('Error: ' + data.error);
      }
      resetUI(); return;
    }

    prepState.job.questions = data.questions;
    prepState.job.sessionId = data.session_id;
    prepState.job.title = `${data.questions.length} questions — ${jobTitle}`;
    prepState.job.meta = `${payload.experience} · ${payload.category} · ${payload.difficulty}`;

    resetPerformance();

    if (prepState.activeTab === 'job') {
      refreshActiveStateUI();
    }

    resetUI();
    showToast('✨ Questions generated!');

  } catch (e) {
    console.error(e);
    showToast('Could not reach Flask. Run: python app.py');
    resetUI();
  }
}

function regenerateQuestions() {
  if (prepState.activeTab === 'resume') {
    generateFromResume(true);
  } else {
    generateQuestions(true);
  }
}

function resetUI() {
  document.getElementById('spinner').classList.remove('show');
  const btn = document.getElementById('gen-btn');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<span>✨</span> Generate Questions';
  }
}

/* ══════════════════════════════════════════════════════════════
   RENDER QUESTIONS
══════════════════════════════════════════════════════════════ */
function renderQuestions(qs) {
  /* Stats row */
  const row = document.getElementById('stats-row');
  if (row && currentQuestions.length) {
    const all = currentQuestions;
    const ct = (k, v) => all.filter(q => q[k] === v).length;
    row.innerHTML = `
      <div class="stat-card"><div class="stat-num s-total">${all.length}</div><div class="stat-lbl">Total</div></div>
      <div class="stat-card"><div class="stat-num s-tech">${ct('category', 'technical')}</div><div class="stat-lbl">Technical</div></div>
      <div class="stat-card"><div class="stat-num s-beh">${ct('category', 'behavioral')}</div><div class="stat-lbl">Behavioral</div></div>
      <div class="stat-card"><div class="stat-num s-sit">${ct('category', 'situational')}</div><div class="stat-lbl">Situational</div></div>
      <div class="stat-card"><div class="stat-num s-hard">${ct('difficulty', 'hard')}</div><div class="stat-lbl">Hard</div></div>
    `;
  }

  /* Question cards */
  const list = document.getElementById('questions-list');
  if (!list) return;
  if (!qs.length) {
    list.innerHTML = '<p style="text-align:center;color:var(--text3);padding:3rem;font-size:14px">No questions match this filter.</p>';
    return;
  }
  const all = currentQuestions.length ? currentQuestions : qs;
  list.innerHTML = qs.map((q, i) => {
    const idx = all.indexOf(q);
    return `
    <div class="q-card" style="animation:fadeSlide .22s ease ${i * 0.04}s both">
      <div class="q-card-top">
        <div class="q-num-badge">${i + 1}</div>
        <div style="flex:1">
          <div class="q-text">${q.question}</div>
          <div class="badges">
            <span class="badge b-${q.category}">${q.category}</span>
            <span class="badge b-${q.difficulty}">${q.difficulty}</span>
          </div>
          ${q.hint ? `
          <div class="hint-toggle" onclick="toggleHint(${idx})">
            <span id="hint-arrow-${idx}">▶</span> Answer Hint
          </div>
          <div class="hint-box" id="hint-${idx}">💡 ${q.hint}</div>` : ''}
        </div>
      </div>
      <div class="rating-row">
        <span class="rating-label">Rate this Q:</span>
        ${[1, 2, 3, 4, 5].map(s =>
      `<span class="star" id="star-${idx}-${s}" onclick="rateQ(${idx},${s})">★</span>`
    ).join('')}
        <span id="q-score-${idx}" class="q-score-badge" style="display:none;margin-left:auto;padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;font-family:'Syne',sans-serif;letter-spacing:.04em;align-items:center"></span>
      </div>
    </div>`;
  }).join('');

  // Restore in-memory scores
  if (window._questionScores) {
    const cm = { Excellent: 'green', Good: 'blue', Partial: 'amber', 'Needs Work': 'red' };
    Object.entries(window._questionScores).forEach(([idx, s]) => {
      refreshQuestionScoreBadge(parseInt(idx), s.score_label, s.score_pct,
        s.color || cm[s.score_label] || 'gray');
    });
  }
  if (currentSessionId) loadQuestionScores(currentSessionId);
}

function filterBy(type, btn) {
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  btn.classList.add('active');
  const filtered = type === 'all'
    ? currentQuestions
    : currentQuestions.filter(q => q.category === type || q.difficulty === type);
  renderQuestions(filtered);
}

function toggleHint(idx) {
  const box = document.getElementById('hint-' + idx);
  const arrow = document.getElementById('hint-arrow-' + idx);
  if (!box) return;
  const open = box.classList.toggle('open');
  box.style.display = open ? 'block' : 'none';
  if (arrow) arrow.textContent = open ? '▼' : '▶';
}

async function rateQ(qIdx, stars) {
  for (let s = 1; s <= 5; s++) {
    const el = document.getElementById(`star-${qIdx}-${s}`);
    if (el) el.classList.toggle('lit', s <= stars);
  }
  if (currentSessionId) {
    await fetch('/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: currentSessionId, question_index: qIdx, rating: stars }),
    }).catch(() => { });
  }
  showToast('Rating saved ★');
}

function copyAll() {
  if (!currentQuestions.length) return;
  const text = currentQuestions.map((q, i) =>
    `${i + 1}. [${q.category.toUpperCase()}] [${q.difficulty.toUpperCase()}]\n   ${q.question}` +
    (q.hint ? `\n   Hint: ${q.hint}` : '')
  ).join('\n\n');
  navigator.clipboard.writeText(text)
    .then(() => showToast('Copied!'))
    .catch(() => showToast('Copy failed'));
}

function exportTxt() {
  if (currentSessionId) window.location.href = `/export/${currentSessionId}`;
  else showToast('Generate or load a session first');
}

function exportPdf() {
  if (currentSessionId) window.location.href = `/export_pdf/${currentSessionId}`;
  else showToast('Generate or load a session first');
}

function openDashboard() {
  window.open('/dashboard', '_blank');
}

/* ══════════════════════════════════════════════════════════════
   THEME TOGGLE
══════════════════════════════════════════════════════════════ */
/* ── Password eye-toggle helper (reusable, idempotent) ── */
const _EYE_OPEN = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>`;
const _EYE_SHUT = `<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>`;

function _attachPwEye(inputId) {
  const input = document.getElementById(inputId);
  if (!input || input.parentNode.querySelector('.pw-eye-btn')) return; // idempotent
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'pw-eye-btn';
  btn.setAttribute('aria-label', 'Show password');
  btn.setAttribute('aria-pressed', 'false');
  btn.innerHTML = _EYE_OPEN;
  input.parentNode.appendChild(btn);
  btn.addEventListener('click', function () {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    btn.innerHTML = show ? _EYE_SHUT : _EYE_OPEN;
    btn.setAttribute('aria-pressed', show ? 'true' : 'false');
    btn.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
  });
}

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('prepedge-theme', next);
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = next === 'light' ? '☀️' : '🌙';
  showToast(next === 'light' ? '☀️ Light mode on' : '🌙 Dark mode on', 1800);
}

/* ══════════════════════════════════════════════════════════════
   PROFILE MODAL
══════════════════════════════════════════════════════════════ */
async function openProfileModal() {
  const modal = document.getElementById('profile-modal');
  if (!modal) return;

  // Force modal to be visible (bypass missing CSS class)
  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';

  // Clear previous status and password fields
  const stat = document.getElementById('profile-status');
  if (stat) { stat.textContent = ''; stat.className = 'pm-status'; }
  document.getElementById('prof-current-pw').value = '';
  document.getElementById('prof-new-pw').value = '';

  const saveBtn = document.getElementById('prof-save-btn');
  if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '💾 Save Changes'; }

  // Attach eye‑toggle buttons (idempotent)
  _attachPwEye('prof-current-pw');
  _attachPwEye('prof-new-pw');

  // Load current data from /me
  try {
    const res = await fetch('/me');
    const data = await res.json();
    document.getElementById('prof-username').value = data.username || '';
    document.getElementById('prof-email').value = data.email || '';
    const av = document.getElementById('profile-avatar-big');
    if (av) {
      if (data.avatar_url) {
        av.outerHTML = `<img id="profile-avatar-big" class="pm-avatar-img" src="${data.avatar_url}" alt="Avatar">`;
      } else if (data.username) {
        // Ensure it's a div (in case it was replaced by an img previously)
        if (av.tagName === 'IMG') {
          av.outerHTML = `<div id="profile-avatar-big" class="pm-avatar-big">${data.username[0].toUpperCase()}</div>`;
        } else {
          av.textContent = data.username[0].toUpperCase();
        }
      }
    }
  } catch (_) { }
}

function closeProfileModal() {
  const modal = document.getElementById('profile-modal');
  if (modal) modal.style.display = 'none';
  document.body.style.overflow = '';
}

async function saveProfile() {
  const username = (document.getElementById('prof-username')?.value || '').trim();
  const email = (document.getElementById('prof-email')?.value || '').trim();
  const currentPw = document.getElementById('prof-current-pw')?.value || '';
  const newPw = document.getElementById('prof-new-pw')?.value || '';
  const status = document.getElementById('profile-status');
  const saveBtn = document.getElementById('prof-save-btn');

  if (!currentPw) {
    showProfileStatus('Current password is required to save changes.', 'err');
    return;
  }
  if (!username || username.length < 3) {
    showProfileStatus('Username must be at least 3 characters.', 'err');
    return;
  }
  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) {
    showProfileStatus('Please enter a valid email address.', 'err');
    return;
  }

  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.textContent = '⏳ Saving…';
  }

  try {
    // ✅ correct endpoint
    const res = await fetch('/profile/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username,
        email,
        current_password: currentPw,
        new_password: newPw || null,
        confirm_password: newPw || null   // ✅ required for backend validation
      })
    });
    const data = await res.json();
    if (data.error) {
      showProfileStatus(data.error, 'err');
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = '💾 Save Changes';
      }
      return;
    }
    showProfileStatus('✓ Profile updated successfully!', 'ok');
    // Update UI
    const nameEl = document.querySelector('.user-name');
    if (nameEl) nameEl.textContent = data.username;
    const avatarEl = document.querySelector('.user-avatar');
    if (avatarEl) avatarEl.textContent = data.username[0].toUpperCase();
    const avBig = document.getElementById('profile-avatar-big');
    if (avBig) avBig.textContent = data.username[0].toUpperCase();
    if (saveBtn) saveBtn.textContent = '✓ Saved!';
    setTimeout(closeProfileModal, 1800);
    showToast('✓ Profile updated!');
  } catch (e) {
    showProfileStatus('Network error. Is Flask running?', 'err');
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.textContent = '💾 Save Changes';
    }
  }
}

function showProfileStatus(msg, type) {
  const el = document.getElementById('profile-status');
  if (!el) return;
  el.textContent = msg;
  el.className = 'pm-status' + (type === 'ok' ? ' ok' : type === 'err' ? ' err' : ' ok');
}

/* ══════════════════════════════════════════════════════════════
   PROFILE AVATAR UPLOAD
══════════════════════════════════════════════════════════════ */
function triggerAvatarUpload() {
  const input = document.getElementById('profile-avatar-input');
  if (input) input.click();
}

async function uploadAvatar() {
  const input = document.getElementById('profile-avatar-input');
  if (!input || !input.files || !input.files[0]) return;
  const file = input.files[0];

  // Client-side validation
  const allowed = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'];
  if (!allowed.includes(file.type)) {
    showToast('❌ Only PNG, JPG, WEBP or GIF images allowed.');
    return;
  }
  if (file.size > 2 * 1024 * 1024) {
    showToast('❌ Image too large. Max 2 MB.');
    return;
  }

  const formData = new FormData();
  formData.append('avatar', file);

  try {
    showToast('⏳ Uploading…', 1500);
    const res = await fetch('/profile/avatar', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) { showToast('❌ ' + data.error); return; }

    // Update modal avatar
    const avBig = document.getElementById('profile-avatar-big');
    if (avBig) {
      avBig.outerHTML = `<img id="profile-avatar-big" class="pm-avatar-img" src="${data.avatar_url}" alt="Avatar">`;
    }
    // Update header avatar
    const headerAv = document.getElementById('header-avatar');
    if (headerAv) {
      headerAv.outerHTML = `<img id="header-avatar" class="user-avatar-img" src="${data.avatar_url}" alt="Avatar">`;
    }
    showToast('✅ Profile picture updated!');
  } catch (e) {
    showToast('❌ Upload failed. Check your connection.');
  }
  // Clear input so same file can be re-selected
  input.value = '';
}

/* ══════════════════════════════════════════════════════════════
   EMAIL REPORT MODAL
══════════════════════════════════════════════════════════════ */
async function openEmailModal() {
  if (!currentSessionId) { showToast('Generate or load a session first'); return; }
  const modal = document.getElementById('email-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  document.getElementById('email-status').textContent = '';
  const btn = document.getElementById('email-send-btn');
  if (btn) { btn.disabled = false; btn.textContent = '📧 Send Report'; }
  const inp = document.getElementById('email-input');
  if (inp) {
    inp.value = ''; inp.placeholder = 'Loading your email…';
    try {
      const res = await fetch('/me');
      const data = await res.json();
      inp.value = data.email || ''; inp.placeholder = 'you@example.com';
    } catch (_) { inp.placeholder = 'you@example.com'; }
    setTimeout(() => inp.focus(), 80);
  }
}

function closeEmailModal() {
  const modal = document.getElementById('email-modal');
  if (modal) modal.style.display = 'none';
}

async function sendEmailReport() {
  const email = (document.getElementById('email-input')?.value || '').trim();
  const status = document.getElementById('email-status');
  const btn = document.getElementById('email-send-btn');

  if (!email || !/^[^@\s]+@[^@\s]+\.[^@\s]{2,}$/.test(email)) {
    if (status) { status.style.color = 'var(--red)'; status.textContent = '⚠ Valid email required.'; }
    return;
  }
  if (!currentSessionId) {
    if (status) { status.style.color = 'var(--red)'; status.textContent = '⚠ No session loaded.'; }
    return;
  }
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Sending…'; }
  if (status) { status.style.color = 'var(--text2)'; status.textContent = 'Sending your report…'; }

  try {
    const res = await fetch('/send_email', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, session_id: currentSessionId })
    });
    const data = await res.json();
    if (data.error) {
      if (status) { status.style.color = 'var(--red)'; status.textContent = `⚠ ${data.error}`; }
      if (btn) { btn.disabled = false; btn.textContent = '📧 Send Report'; }
    } else {
      if (status) { status.style.color = '#34d399'; status.textContent = `✓ Sent to ${email}`; }
      if (btn) btn.textContent = '✓ Sent!';
      setTimeout(closeEmailModal, 2200);
      showToast(`📧 Report sent to ${email}`, 3500);
    }
  } catch (e) {
    if (status) { status.style.color = 'var(--red)'; status.textContent = '⚠ Network error.'; }
    if (btn) { btn.disabled = false; btn.textContent = '📧 Send Report'; }
  }
}

/* ══════════════════════════════════════════════════════════════
   QUESTION SCORE BADGES
══════════════════════════════════════════════════════════════ */
function refreshQuestionScoreBadge(qIdx, label, pct, color) {
  const el = document.getElementById(`q-score-${qIdx}`);
  if (!el) return;
  const bg = { green: 'rgba(52,211,153,.15)', blue: 'rgba(96,165,250,.15)', amber: 'rgba(251,191,36,.15)', red: 'rgba(248,113,113,.15)', gray: 'rgba(255,255,255,.08)' };
  const clr = { green: '#6ee7b7', blue: '#93c5fd', amber: '#fcd34d', red: '#fca5a5', gray: '#9ba3c2' };
  el.style.display = 'inline-flex';
  el.style.background = bg[color] || bg.gray;
  el.style.color = clr[color] || clr.gray;
  el.textContent = `${label}  ${pct}%`;
}

async function loadQuestionScores(sessionId) {
  if (!sessionId) return;
  try {
    const data = await (await fetch(`/question_scores/${sessionId}`)).json();
    if (!window._questionScores) window._questionScores = {};
    const cm = { Excellent: 'green', Good: 'blue', Partial: 'amber', 'Needs Work': 'red' };
    data.forEach(s => {
      window._questionScores[s.question_index] = s;
      refreshQuestionScoreBadge(s.question_index, s.score_label, s.score_pct, cm[s.score_label] || 'gray');
    });
  } catch (_) { }
}

/* ══════════════════════════════════════════════════════════════
   MOCK INTERVIEW
══════════════════════════════════════════════════════════════ */
function startMockInterview() {
  if (!currentQuestions.length) { showToast('Generate questions first!'); return; }
  _mockQs = [...currentQuestions];
  _mockIdx = 0;
  document.getElementById('normal-view').style.display = 'none';
  document.getElementById('mock-mode').style.display = 'block';
  loadMockQuestion();
}

function loadMockQuestion() {
  /* Update progress bar */
  const fill = document.getElementById('mock-q-fill');
  if (fill && _mockQs.length) {
    const pct = Math.round((_mockIdx / _mockQs.length) * 100);
    fill.style.width = Math.max(pct, 5) + '%';
  }

  if (_mockIdx >= _mockQs.length) {
    exitMock();
    showToast('🎉 Mock interview complete! Great job.');
    return;
  }

  const q = _mockQs[_mockIdx];
  document.getElementById('mock-counter').textContent =
    `Question ${_mockIdx + 1} of ${_mockQs.length}`;
  document.getElementById('mock-question').textContent = q.question;

  _transcript = '';
  _interim = '';
  refreshTranscript();
  switchScreen('ready');
}

/* Screen switcher — shows one screen, hides all others */
function switchScreen(name) {
  ['ready', 'answering', 'evaluating', 'feedback'].forEach(s => {
    const el = document.getElementById('mock-screen-' + s);
    if (el) el.style.display = (s === name) ? 'block' : 'none';
  });
}

/* ── Start answering ── */
function mockStart() {
  switchScreen('answering');
  startTimer();
  startMic();
}

/* ── Timer ── */
function startTimer() {
  clearInterval(_mockTimer);
  _mockSecs = MOCK_TOTAL;
  renderTimer();
  _mockTimer = setInterval(() => {
    _mockSecs--;
    renderTimer();
    if (_mockSecs <= 0) { clearInterval(_mockTimer); mockDoneAnswering(); }
  }, 1000);
}

function renderTimer() {
  const el = document.getElementById('mic-timer');
  if (!el) return;
  const m = String(Math.floor(_mockSecs / 60)).padStart(2, '0');
  const s = String(_mockSecs % 60).padStart(2, '0');
  el.textContent = `${m}:${s}`;
  el.classList.toggle('warn', _mockSecs <= 20);
}

/* ── Microphone / Speech Recognition ── */
function startMic() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) {
    showToast('Speech recognition not supported. Use Chrome.');
    return;
  }

  _micActive = true;
  _recognition = new SR();
  _recognition.continuous = true;
  _recognition.interimResults = true;
  _recognition.lang = 'en-US';

  _recognition.onstart = () => setMicState('listening');

  _recognition.onresult = (event) => {
    _interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        _transcript += event.results[i][0].transcript + ' ';
      } else {
        _interim += event.results[i][0].transcript;
      }
    }
    refreshTranscript();
  };

  _recognition.onerror = (e) => {
    if (e.error === 'not-allowed') {
      showToast('Microphone access denied. Allow mic in Chrome settings.');
      _micActive = false;
    } else if (e.error === 'no-speech' && _micActive) {
      try { _recognition.start(); } catch (_) { }
    }
  };

  _recognition.onend = () => {
    if (_micActive) {
      try { _recognition.start(); } catch (_) { }
    }
  };

  try { _recognition.start(); } catch (e) { showToast('Mic error: ' + e.message); }
}

function stopMic() {
  _micActive = false;
  if (_recognition) { try { _recognition.stop(); } catch (_) { } _recognition = null; }
}

function setMicState(state) {
  const orb = document.getElementById('mic-orb');
  const label = document.getElementById('mic-status-label');
  if (orb) orb.classList.toggle('recording', state === 'listening');
  if (label) {
    if (state === 'listening') {
      label.innerHTML = '<span class="mic-live-dot"></span> Listening…';
      label.style.color = 'var(--green)';
      startWaveform();
    } else {
      label.innerHTML = '<span class="mic-live-dot" style="background:#555e82"></span> Waiting…';
      label.style.color = 'var(--text3)';
    }
  }
}

let _waveInterval = null;
function startWaveform() {
  stopWaveform();
  const bars = document.querySelectorAll('.wave-bar');
  if (!bars.length) return;
  _waveInterval = setInterval(() => {
    bars.forEach(bar => {
      const h = Math.random() * 32 + 6;
      bar.style.height = h + 'px';
      bar.style.opacity = (0.4 + Math.random() * 0.6).toFixed(2);
    });
  }, 100);
}

function stopWaveform() {
  if (_waveInterval) { clearInterval(_waveInterval); _waveInterval = null; }
  const bars = document.querySelectorAll('.wave-bar');
  bars.forEach(bar => { bar.style.height = '6px'; bar.style.opacity = '0.2'; });
}

function refreshTranscript() {
  const box = document.getElementById('transcript-box');
  if (!box) return;
  const fin = _transcript.trim();
  const words = (fin + ' ' + _interim).trim().split(/\s+/).filter(Boolean);
  const wc = document.getElementById('word-count');
  if (wc) wc.textContent = `${words.length} word${words.length !== 1 ? 's' : ''}`;

  if (fin || _interim) {
    box.innerHTML =
      `<span class="transcript-final">${fin}</span>` +
      (_interim ? ` <span class="transcript-interim">${_interim}</span>` : '');
  } else {
    box.innerHTML = '<span class="transcript-placeholder">Start speaking — your words will appear here in real time…</span>';
  }
  box.scrollTop = box.scrollHeight;
}

/* ── Done / Skip ── */
async function mockDoneAnswering() {
  clearInterval(_mockTimer);
  stopMic();
  const fullAnswer = (_transcript + ' ' + _interim).trim();
  switchScreen('evaluating');
  await evalAnswer(fullAnswer);
}

function mockSkip() {
  clearInterval(_mockTimer);
  stopMic();
  mockNextQuestion();
}

/* ── Evaluate via Flask ── */
async function evalAnswer(answer) {
  const q = _mockQs[_mockIdx];
  const realIdx = currentQuestions.findIndex(cq => cq.question === q.question);
  const qIdx = realIdx >= 0 ? realIdx : _mockIdx;
  try {
    const res = await fetch('/check_answer', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question: q.question, hint: q.hint || '', answer,
        session_id: currentSessionId, question_index: qIdx
      })
    });
    const data = await res.json();
    showFeedback(data, answer, qIdx);
  } catch (e) {
    showFeedback({
      score: 'Error', color: 'gray', percent: 0,
      feedback: 'Could not evaluate. Check Flask is running.', tip: q.hint || ''
    }, answer, qIdx);
  }
}

/* ── Show feedback ── */
function showFeedback(data, spoken, qIdx) {
  switchScreen('feedback');

  // Per-question score tracking
  if (qIdx !== undefined) {
    if (!window._questionScores) window._questionScores = {};
    window._questionScores[qIdx] = { score_label: data.score, score_pct: data.percent || 0, color: data.color };
    refreshQuestionScoreBadge(qIdx, data.score, data.percent || 0, data.color);
  }

  /* Performance tracking */
  const score = data.percent || 0;
  const confidence = Math.round(Math.min(100, score + Math.random() * 10));
  const clarity = Math.round(Math.min(100, score - Math.random() * 10));
  const fluency = Math.round(Math.min(100, score + (Math.random() * 5 - 2)));

  performanceData.push({ score, confidence, clarity, fluency });
  savePerformance();
  updateChart();
  updateInsights();

  /* Score badge */
  const clsMap = {
    green: 'sc-excellent', blue: 'sc-good',
    amber: 'sc-partial', red: 'sc-needswork', gray: 'sc-gray'
  };
  const iconMap = { green: '🟢', blue: '🔵', amber: '🟡', red: '🔴', gray: '⚪' };
  const barClr = {
    green: 'linear-gradient(90deg,#34d399,#059669)',
    blue: 'linear-gradient(90deg,#60a5fa,#2563eb)',
    amber: 'linear-gradient(90deg,#fbbf24,#d97706)',
    red: 'linear-gradient(90deg,#f87171,#dc2626)',
    gray: 'linear-gradient(90deg,#9ca3af,#6b7280)'
  };

  const cls = clsMap[data.color] || 'sc-gray';
  const icon = iconMap[data.color] || '⚪';
  const pct = Math.max(0, Math.min(100, data.percent || 0));
  const bar = document.getElementById('pct-bar');

  document.getElementById('score-badge').className = `score-badge ${cls}`;
  document.getElementById('score-badge').innerHTML = `${icon} ${data.score}`;

  const pctLabel = document.getElementById('pct-label');
  if (pctLabel) pctLabel.textContent = `${pct}% accuracy`;

  if (bar) {
    bar.style.width = '0%';
    bar.style.background = barClr[data.color] || barClr.gray;
    setTimeout(() => { bar.style.width = pct + '%'; }, 80);
  }

  document.getElementById('fb-text').textContent = data.feedback || '';
  document.getElementById('fb-tip').innerHTML = `<strong>💡 Tip:</strong> ${data.tip || ''}`;

  /* Ideal answer */
  const idealBox = document.getElementById('ideal-answer-box');
  const idealBtn = document.getElementById('toggle-ideal-btn');
  if (idealBox) {
    if (data.ideal_answer) {
      idealBox.innerHTML = `<strong>🧠 Ideal Answer:</strong><br><br>${data.ideal_answer}`;
      idealBox.style.display = 'none';
      if (idealBtn) { idealBtn.textContent = '🧠 Show Ideal Answer'; idealBtn.style.display = 'inline-flex'; }
    } else {
      idealBox.innerHTML = '';
      if (idealBtn) idealBtn.style.display = 'none';
    }
  }

  /* Spoken answer */
  const spokenBox = document.getElementById('spoken-box');
  const spokenBtn = document.getElementById('toggle-spoken-btn');
  if (spokenBox) {
    spokenBox.textContent = spoken || '(No answer detected)';
    spokenBox.style.display = 'none';
  }
  if (spokenBtn) spokenBtn.textContent = '▶ 🔎 Show what you said';

  // Stop waveform animation
  stopWaveform();

  // Update Next button label based on position
  const nextBtn = document.getElementById('btn-next-q');
  if (nextBtn) {
    const remaining = _mockQs.length - 1 - _mockIdx;
    if (remaining === 1) {
      nextBtn.textContent = '⚑ Last Question';
      nextBtn.style.background = 'linear-gradient(135deg,#f59e0b,#d97706)';
      nextBtn.style.boxShadow = '0 4px 16px rgba(245,158,11,.4)';
    } else if (remaining === 0) {
      nextBtn.textContent = '🏁 Finish Interview';
      nextBtn.style.background = 'linear-gradient(135deg,#34d399,#059669)';
      nextBtn.style.boxShadow = '0 4px 16px rgba(52,211,153,.4)';
    } else {
      nextBtn.textContent = 'Next Question →';
      nextBtn.style.background = '';
      nextBtn.style.boxShadow = '';
    }
  }
}

function toggleSpoken() {
  const box = document.getElementById('spoken-box');
  const btn = document.getElementById('toggle-spoken-btn');
  if (!box) return;
  const open = box.style.display === 'block';
  box.style.display = open ? 'none' : 'block';
  if (btn) btn.textContent = open ? '▶ 🔎 Show what you said' : '▼ Hide what you said';
}

function toggleIdeal() {
  const box = document.getElementById('ideal-answer-box');
  const btn = document.getElementById('toggle-ideal-btn');
  if (!box) return;
  const open = box.style.display === 'block';
  box.style.display = open ? 'none' : 'block';
  if (btn) btn.textContent = open ? '🧠 Show Ideal Answer' : '🧠 Hide Ideal Answer';
}

function mockNextQuestion() {
  _mockIdx++;
  if (_mockIdx >= _mockQs.length) {
    exitMock();
    showToast('🎉 Interview complete! Great job finishing all questions.', 4000);
  } else {
    loadMockQuestion();
  }
}

function exitMock() {
  clearInterval(_mockTimer);
  stopMic();
  document.getElementById('mock-mode').style.display = 'none';
  document.getElementById('normal-view').style.display = 'block';
}

/* ══════════════════════════════════════════════════════════════
   CHART & INSIGHTS
══════════════════════════════════════════════════════════════ */
function updateChart() {
  const ctx = document.getElementById('performanceChart');
  if (!ctx) return;
  if (chart) { chart.destroy(); chart = null; }
  if (!performanceData.length) return;

  const labels = performanceData.map((_, i) => `Q${i + 1}`);

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Score', data: performanceData.map(d => d.score), borderColor: '#a78bfa', backgroundColor: 'rgba(167,139,250,.08)', tension: 0.4, fill: true },
        { label: 'Confidence', data: performanceData.map(d => d.confidence), borderColor: '#34d399', backgroundColor: 'transparent', tension: 0.4 },
        { label: 'Clarity', data: performanceData.map(d => d.clarity), borderColor: '#fbbf24', backgroundColor: 'transparent', tension: 0.4 },
        { label: 'Fluency', data: performanceData.map(d => d.fluency), borderColor: '#f87171', backgroundColor: 'transparent', tension: 0.4 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'top',
          labels: { color: '#9ba3c2', font: { size: 11 }, boxWidth: 12 }
        }
      },
      scales: {
        y: {
          min: 0, max: 100,
          ticks: { color: '#555e82', font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,.05)' }
        },
        x: {
          ticks: { color: '#555e82', font: { size: 10 } },
          grid: { color: 'rgba(255,255,255,.05)' }
        }
      }
    }
  });
}

function updateInsights() {
  if (performanceData.length < 2) return;
  const first = performanceData[0].score;
  const last = performanceData[performanceData.length - 1].score;
  const improvement = last - first;

  let msg = '';
  if (improvement > 0) msg = `📈 Great progress! You improved by +${improvement}% from your first answer.`;
  else if (improvement < 0) msg = `📉 Slight drop of ${Math.abs(improvement)}%. Try focusing on clarity.`;
  else msg = `⚖️ Your performance is consistent. Try pushing for improvement.`;

  msg += `<br><br>💡 Confidence: ${avg('confidence')}% | Clarity: ${avg('clarity')}% | Fluency: ${avg('fluency')}%`;
  document.getElementById('insight-text').innerHTML = msg;
}

function avg(key) {
  if (!performanceData.length) return 0;
  return Math.round(performanceData.reduce((a, b) => a + b[key], 0) / performanceData.length);
}

function resetPerformance() {
  performanceData = [];
  window._questionScores = {};
  if (chart) { chart.destroy(); chart = null; }
  try { localStorage.removeItem('performance'); } catch (_) { }
  const el = document.getElementById('insight-text');
  if (el) el.innerHTML = 'No data yet — complete a mock interview to see insights.';
  const cv = document.getElementById('performanceChart');
  if (cv) cv.getContext('2d').clearRect(0, 0, cv.width, cv.height);
}

function savePerformance() {
  try { localStorage.setItem('performance', JSON.stringify(performanceData)); } catch (_) { }
}

function loadPerformance() {
  try {
    const data = localStorage.getItem('performance');
    if (data) { performanceData = JSON.parse(data); updateChart(); updateInsights(); }
  } catch (_) { }
}

/* ══════════════════════════════════════════════════════════════
   HISTORY MODAL
══════════════════════════════════════════════════════════════ */
async function openHistory() {
  const modal = document.getElementById('history-modal');
  if (!modal) return;
  const list = document.getElementById('history-list');
  list.innerHTML = '<p style="text-align:center;padding:2rem;color:var(--text3)">Loading…</p>';
  modal.style.display = 'flex';

  try {
    const res = await fetch('/history_json');
    const data = await res.json();

    if (!data.length) {
      list.innerHTML = `<div style="text-align:center;padding:3rem">
        <div style="font-size:40px;margin-bottom:1rem">📭</div>
        <div style="color:var(--text3);font-size:14px">No sessions yet. Generate some questions!</div>
      </div>`;
      return;
    }

    window._historyData = data;
    list.innerHTML = data.map(s => {
      const count = JSON.parse(s.questions_json).length;
      return `
      <div class="history-item">
        <div class="h-icon">💼</div>
        <div class="h-info">
          <div class="h-meta">${s.job_title}</div>
          <div class="h-date">
            <span>${s.experience}</span><span>·</span>
            <span>${s.created_at}</span><span>·</span>
            <span>${count} questions</span>
          </div>
        </div>
        <div class="h-actions">
          <button class="btn-load" onclick="loadHistorySession(${s.id})">Load</button>
          <button class="btn-del-hist" onclick="deleteHistorySession(${s.id})">🗑</button>
        </div>
      </div>`;
    }).join('');

  } catch (e) {
    list.innerHTML = '<p style="text-align:center;padding:2rem;color:var(--red)">Failed to load history.</p>';
  }
}

function closeHistory() {
  const modal = document.getElementById('history-modal');
  if (modal) modal.style.display = 'none';
}

function loadHistorySession(id) {
  const s = (window._historyData || []).find(x => x.id === id);
  if (!s) { showToast('Session not found'); return; }

  // Load into the ACTIVE tab so user can use it right away
  const parsed = JSON.parse(s.questions_json);
  prepState[prepState.activeTab].questions = parsed;
  prepState[prepState.activeTab].sessionId = s.id;
  prepState[prepState.activeTab].title = `${parsed.length} questions — ${s.job_title}`;
  prepState[prepState.activeTab].meta = `${s.experience} · loaded from history`;

  resetPerformance();
  refreshActiveStateUI();

  closeHistory();
  showToast('Session loaded!');
}

/* ── Generic Confirm Modal ── */
let genericConfirmCallback = null;
function showGenericConfirm(title, text, isDanger, callback) {
  const mod = document.getElementById('generic-confirm-modal');
  if (!mod) return;
  document.getElementById('gcm-title').textContent = title;
  document.getElementById('gcm-text').textContent = text;

  const icon = document.getElementById('gcm-icon');
  const btn = document.getElementById('gcm-ok-btn');
  if (isDanger) {
    icon.className = 'confirm-icon confirm-icon-danger';
    icon.textContent = '🗑';
    btn.className = 'confirm-btn-ok confirm-btn-danger';
  } else {
    icon.className = 'confirm-icon confirm-icon-warn';
    icon.textContent = '⚠️';
    btn.className = 'confirm-btn-ok confirm-btn-warn';
  }

  genericConfirmCallback = callback;
  mod.style.display = 'flex';
  mod.classList.add('open');
  document.body.style.overflow = 'hidden';
}

function closeGenericConfirm() {
  const mod = document.getElementById('generic-confirm-modal');
  if (mod) {
    mod.classList.remove('open');
    setTimeout(() => { mod.style.display = 'none'; }, 300);
  }
  document.body.style.overflow = '';
  genericConfirmCallback = null;
}

document.addEventListener('DOMContentLoaded', () => {
  const gcmOkBtn = document.getElementById('gcm-ok-btn');
  if (gcmOkBtn) {
    gcmOkBtn.addEventListener('click', () => {
      if (genericConfirmCallback) genericConfirmCallback();
      closeGenericConfirm();
    });
  }
});

async function deleteHistorySession(id) {
  showGenericConfirm('Delete Session?', 'Are you sure you want to delete this session?', true, async () => {
    await fetch(`/delete/${id}`, { method: 'POST' }).catch(() => { });
    window._historyData = (window._historyData || []).filter(x => x.id !== id);
    openHistory();
    showToast('Deleted');
  });
}

async function clearAllHistory() {
  showGenericConfirm('Clear ALL history?', 'This cannot be undone. All your past sessions will be deleted.', true, async () => {
    await fetch('/clear_history', { method: 'POST' }).catch(() => { });
    const list = document.getElementById('history-list');
    if (list) list.innerHTML = `<p style="text-align:center;padding:2rem;color:var(--text3);font-size:14px">History cleared.</p>`;
    showToast('All history cleared');
  });
}

/* ══════════════════════════════════════════════════════════════
   DEEP OCEAN CANVAS — waves + bioluminescent particles
══════════════════════════════════════════════════════════════ */
function initParticles() {
  const canvas = document.getElementById('particle-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  let W, H, t = 0;
  const pts = [];

  function mkPt() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      r: Math.random() * 2 + 0.3,
      vx: (Math.random() - 0.5) * 0.2,
      vy: (Math.random() - 0.5) * 0.12,
      alpha: Math.random() * 0.5 + 0.1,
      pulse: Math.random() * Math.PI * 2,
      pulseSpeed: 0.02 + Math.random() * 0.025,
      color: Math.random() > 0.5 ? 'rgba(56,189,248,' : 'rgba(99,240,200,'
    };
  }

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
    pts.length = 0;
    for (let i = 0; i < 70; i++) pts.push(mkPt());
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);

    /* ── Wave layers (bottom to top) ── */
    const waveLayers = [
      { yBase: 0.80, amp: 22, freq: 0.006, speed: 0.0007, alpha: 0.09 },
      { yBase: 0.68, amp: 18, freq: 0.008, speed: 0.0009, alpha: 0.07 },
      { yBase: 0.55, amp: 14, freq: 0.010, speed: 0.0011, alpha: 0.05 },
      { yBase: 0.42, amp: 10, freq: 0.012, speed: 0.0013, alpha: 0.04 },
      { yBase: 0.28, amp: 7, freq: 0.015, speed: 0.0015, alpha: 0.03 },
    ];

    waveLayers.forEach(({ yBase, amp, freq, speed, alpha }, li) => {
      ctx.beginPath();
      ctx.moveTo(0, H);
      for (let x = 0; x <= W; x += 4) {
        const y = H * yBase
          + Math.sin(x * freq + t * speed * 1000 + li * 0.8) * amp
          + Math.sin(x * freq * 2.1 + t * speed * 700 + li) * amp * 0.4
          + Math.sin(x * freq * 0.5 + t * speed * 500) * amp * 0.25;
        ctx.lineTo(x, y);
      }
      ctx.lineTo(W, H);
      ctx.closePath();

      /* Ocean gradient fill per layer */
      const grad = ctx.createLinearGradient(0, H * yBase - amp, 0, H);
      grad.addColorStop(0, `rgba(0,${80 + li * 20},${160 + li * 10},${alpha})`);
      grad.addColorStop(1, `rgba(0,20,60,0)`);
      ctx.fillStyle = grad;
      ctx.fill();

      /* Crest highlight line */
      ctx.beginPath();
      ctx.strokeStyle = `rgba(56,189,248,${alpha * 0.6})`;
      ctx.lineWidth = 0.8;
      ctx.moveTo(0, H * yBase);
      for (let x = 0; x <= W; x += 4) {
        const y = H * yBase
          + Math.sin(x * freq + t * speed * 1000 + li * 0.8) * amp
          + Math.sin(x * freq * 2.1 + t * speed * 700 + li) * amp * 0.4;
        ctx.lineTo(x, y);
      }
      ctx.stroke();
    });

    /* ── Bioluminescent particles ── */
    pts.forEach(p => {
      p.pulse += p.pulseSpeed;
      const a = p.alpha * (0.4 + 0.6 * Math.sin(p.pulse));

      /* Glow halo */
      const grd = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
      grd.addColorStop(0, p.color + a * 0.8 + ')');
      grd.addColorStop(1, p.color + '0)');
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r * 4, 0, Math.PI * 2);
      ctx.fillStyle = grd;
      ctx.fill();

      /* Core dot */
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fillStyle = p.color + Math.min(a * 1.5, 1) + ')';
      ctx.fill();

      p.x += p.vx;
      p.y += p.vy;
      if (p.x < -10) p.x = W + 10;
      if (p.x > W + 10) p.x = -10;
      if (p.y < -10) p.y = H + 10;
      if (p.y > H + 10) p.y = -10;
    });

    t++;
    requestAnimationFrame(draw);
  }

  window.addEventListener('resize', resize);
  resize();
  draw();
}

/* ══════════════════════════════════════════════════════════════
   PROFILE DROPDOWN (NEW)
══════════════════════════════════════════════════════════════ */
function toggleProfileDropdown(show) {
  const container = document.getElementById('profile-dropdown');
  if (!container) return;
  if (show === undefined) {
    container.classList.toggle('open');
  } else if (show) {
    container.classList.add('open');
  } else {
    container.classList.remove('open');
  }
}

function closeProfileDropdown() {
  toggleProfileDropdown(false);
}

function onDropdownAction(action) {
  switch (action) {
    case 'edit-profile':
      openProfileModal();
      break;
    case 'session-history':
      openHistory();
      break;
    case 'dashboard':
      openDashboard();
      break;
    case 'delete-account':
      openDeleteAccountModal();
      break;
    case 'logout':
      openLogoutModal();
      break;
  }
  closeProfileDropdown();
}

/* ══════════════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════════════ */
window.addEventListener('load', () => {
  loadPerformance();
  initParticles();
});

document.addEventListener('DOMContentLoaded', () => {
  const inp = document.getElementById('job_title');
  if (inp) {
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') generateQuestions(); });
    inp.addEventListener('input', () => _showJobTitleWarning(''));
  }

  const hModal = document.getElementById('history-modal');
  if (hModal) hModal.addEventListener('click', e => { if (e.target === hModal) closeHistory(); });

  const pModal = document.getElementById('profile-modal');
  if (pModal) pModal.addEventListener('click', e => { if (e.target === pModal) closeProfileModal(); });

  const eModal = document.getElementById('email-modal');
  if (eModal) eModal.addEventListener('click', e => { if (e.target === eModal) closeEmailModal(); });

  // ── New modals ───────────────────────────────────────────────────────────
  const lModal = document.getElementById('logout-modal');
  if (lModal) lModal.addEventListener('click', e => { if (e.target === lModal) closeLogoutModal(); });

  const daModal = document.getElementById('delete-account-modal');
  if (daModal) daModal.addEventListener('click', e => { if (e.target === daModal) closeDeleteAccountModal(); });

  // Dropdown event listeners
  const trigger = document.getElementById('profile-trigger');
  const dropdown = document.getElementById('profile-dropdown');
  const menu = document.getElementById('dropdown-menu');

  if (trigger && dropdown) {
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleProfileDropdown();
    });

    document.addEventListener('click', (e) => {
      if (!dropdown.contains(e.target)) {
        closeProfileDropdown();
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && dropdown.classList.contains('open')) {
        closeProfileDropdown();
      }
    });

    if (menu) {
      menu.addEventListener('click', (e) => {
        const item = e.target.closest('.dropdown-item');
        if (item) {
          e.preventDefault();
          const action = item.getAttribute('data-action');
          if (action) onDropdownAction(action);
        }
      });
    }
  }
});

/* ══════════════════════════════════════════════════════════════
   FAQ ACCORDION
══════════════════════════════════════════════════════════════ */
function toggleFaqCard(btn) {
  const card = btn.closest('.faq-card');
  if (!card) return;
  const isOpen = card.classList.contains('open');

  // Close all other FAQ cards (accordion behavior)
  document.querySelectorAll('.faq-card.open').forEach(c => {
    if (c !== card) c.classList.remove('open');
  });

  // Toggle the clicked card
  card.classList.toggle('open', !isOpen);
}

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    closeHistory();
    closeEmailModal();
    closeProfileModal();
    closeLogoutModal();
    closeDeleteAccountModal();
  }
});