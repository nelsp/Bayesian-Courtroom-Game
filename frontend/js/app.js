/**
 * Main application — screen navigation, API interaction, game state.
 */
const App = {

  // Game state
  gameId: null,
  playerId: null,
  caseSlug: null,
  caseData: null,
  evidenceList: [],
  currentEvidenceIdx: 0,
  currentDb: 0,
  priorDb: 0,
  thresholdDb: 20,
  tolerance: 100,
  inputMethod: 'slider',
  responses: [],

  // ---- Screen Navigation ----

  showScreen(name) {
    const screens = document.querySelectorAll('.screen');
    const target = document.getElementById('screen-' + name);
    if (!target) return;

    screens.forEach(s => {
      if (s.classList.contains('active')) {
        s.classList.remove('active');
      }
    });

    target.classList.add('active');

    if (name === 'case-select') this.loadCases();
    window.scrollTo(0, 0);
  },

  // ---- API Helpers ----

  async api(path, opts) {
    const res = await fetch('/api' + path, {
      headers: { 'Content-Type': 'application/json' },
      ...opts
    });
    return res.json();
  },

  // ---- Case Selection ----

  async loadCases() {
    const container = document.getElementById('case-list');
    container.innerHTML = '<div class="loading">Loading cases...</div>';

    const data = await this.api('/cases');
    if (!data.success || !data.cases.length) {
      container.innerHTML = '<div class="loading">No cases found.</div>';
      return;
    }

    const iconMap = {
      'robbery': '🔫', 'murder': '🔪', 'heist': '💎',
      'theft': '📷', 'poison': '☠️', 'default': '⚖️'
    };

    container.innerHTML = data.cases.map(c => {
      const badgeClass = 'badge-' + (c.difficulty || 'intermediate');
      const icon = iconMap[c.tags?.[0]] || iconMap.default;
      const imgHtml = c.image
        ? `<img src="${c.image}" alt="${c.name}" onerror="this.parentElement.innerHTML='${icon}'">`
        : icon;

      return `
        <div class="case-card" onclick="App.selectCase('${c.slug}')">
          <div class="case-card-img">${imgHtml}</div>
          <div class="case-card-body">
            <h3>${c.name}</h3>
            <div class="case-card-meta">
              <span class="badge ${badgeClass}">${c.difficulty}</span>
              <span style="font-size:0.78rem;color:var(--text-muted)">~${c.estimated_minutes} min · ${c.evidence_count} evidence</span>
            </div>
            <p class="case-card-summary">${c.summary}</p>
          </div>
        </div>`;
    }).join('');
  },

  selectCase(slug) {
    this.caseSlug = slug;
    this.showScreen('standard');
  },

  // ---- Threshold ----

  setThreshold(tolerance) {
    this.tolerance = tolerance;
    this.thresholdDb = Viz.calcThresholdDb(tolerance);

    document.querySelectorAll('.threshold-btn').forEach(btn => {
      btn.classList.toggle('selected', parseInt(btn.dataset.tolerance) === tolerance);
    });
    document.getElementById('threshold-db').textContent = this.thresholdDb.toFixed(1) + ' dB';
  },

  setInputMethod(method) {
    this.inputMethod = method;
    document.querySelectorAll('.toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.method === method);
    });
  },

  // ---- Start Case ----

  async startCase() {
    // Create game
    let data = await this.api('/games', {
      method: 'POST',
      body: JSON.stringify({ case_slug: this.caseSlug })
    });
    if (!data.success) { alert('Failed to create game: ' + data.error); return; }
    this.gameId = data.game_id;

    // Register player
    data = await this.api(`/games/${this.gameId}/player`, {
      method: 'POST',
      body: JSON.stringify({
        name: 'Player',
        guilt_tolerance: this.tolerance,
        use_rating_scale: this.inputMethod === 'slider'
      })
    });
    if (!data.success) { alert('Failed to register player'); return; }
    this.playerId = data.player_id;

    // Get case data
    const caseRes = await this.api(`/games/${this.gameId}/case`);
    this.caseData = caseRes;
    this.priorDb = caseRes.prior_info.db;
    this.currentDb = caseRes.prior_info.db;
    this.responses = [];
    this.currentEvidenceIdx = 0;

    // Get evidence list
    const evRes = await this.api(`/games/${this.gameId}/evidence`);
    this.evidenceList = evRes.evidence;

    this.renderCasePresentation();
    this.showScreen('case-presentation');
  },

  renderCasePresentation() {
    const ci = this.caseData.case_info;
    const pi = this.caseData.prior_info;

    document.getElementById('case-title').textContent = ci.name;

    const imgContainer = document.getElementById('case-image-container');
    if (ci.image_url || ci.image) {
      const src = ci.image_url || `/cases/images/${ci.image}`;
      imgContainer.innerHTML = `<img src="${src}" alt="${ci.name}" onerror="this.parentElement.style.display='none'">`;
    } else {
      imgContainer.style.display = 'none';
    }

    document.getElementById('case-setting').textContent = ci.setting || '';
    document.getElementById('case-description').textContent = ci.description;
    document.getElementById('case-details').textContent = ci.details || '';

    const oddsDesc = pi.odds_description || pi.odds || '';
    const priorHtml = `
      <p><strong>Prior odds:</strong> ${oddsDesc}</p>
      <p><strong>Starting dB:</strong> ${pi.db} dB</p>
      ${pi.reasoning ? `<p>${pi.reasoning}</p>` : ''}`;
    document.getElementById('prior-info').innerHTML = priorHtml;

    const ctx = this.caseData.context_sections || [];
    const ctxContainer = document.getElementById('context-sections');
    ctxContainer.innerHTML = ctx.map(s =>
      `<div class="context-section"><h4>${s.title}</h4><p>${s.content}</p></div>`
    ).join('');

    this.renderEvidencePreview();
  },

  renderEvidencePreview() {
    const list = document.getElementById('evidence-preview-list');
    document.getElementById('evidence-count-text').textContent =
      `${this.evidenceList.length} pieces of evidence to evaluate`;

    list.innerHTML = this.evidenceList.map((ev, i) =>
      `<div class="evidence-preview-card">
        <div class="ev-number">Evidence ${i + 1}</div>
        <h4>${ev.name}</h4>
        <p>${ev.summary}</p>
      </div>`
    ).join('');
  },

  // ---- Evidence Evaluation ----

  async beginEvaluation() {
    this.currentEvidenceIdx = 0;
    await this.loadEvidence(0);
    this.showScreen('evidence-eval');
  },

  async loadEvidence(idx) {
    const data = await this.api(`/games/${this.gameId}/evidence/${idx}`);
    if (!data.success) return;

    const ev = data.evidence;
    this.currentEvidenceIdx = idx;

    const total = this.evidenceList.length;
    const pct = ((idx + 1) / total) * 100;
    document.getElementById('evidence-progress').style.width = pct + '%';
    document.getElementById('evidence-progress-label').textContent =
      `Evidence ${idx + 1} of ${total}`;

    document.getElementById('evidence-title').textContent = ev.name;
    document.getElementById('evidence-description-text').textContent = ev.description;

    // Guidance prompts
    const guidance = ev.guidance || {};
    document.getElementById('guilty-prompt').textContent =
      guidance.guilty_prompt || 'How likely is this evidence if the defendant is GUILTY?';
    document.getElementById('innocent-prompt').textContent =
      guidance.innocent_prompt || 'How likely is this evidence if the defendant is INNOCENT?';

    // Reset inputs
    EvidenceInput.init(this.inputMethod);
    EvidenceInput.reset();

    // Update meter
    Viz.updateMeter('running-meter-fill', 'running-meter-threshold', 'running-meter-value',
      this.currentDb, this.thresholdDb);

    this.updateLiveCalc();
  },

  updateLiveCalc() {
    const vals = EvidenceInput.getValues();
    const lr = vals.prob_guilty / vals.prob_innocent;
    const dbUpdate = Viz.calcDbUpdate(vals.prob_guilty, vals.prob_innocent);
    const newDb = this.currentDb + dbUpdate;
    const newProb = Viz.dbToProb(newDb) * 100;

    document.getElementById('calc-lr').textContent = lr.toFixed(2);

    const dbFmt = Viz.formatDb(dbUpdate);
    const dbEl = document.getElementById('calc-db');
    dbEl.textContent = dbFmt.text;
    dbEl.className = dbFmt.cls;

    document.getElementById('calc-new-prob').textContent = newProb.toFixed(2) + '%';
  },

  async confirmEvidence() {
    const vals = EvidenceInput.getValues();
    const dbUpdate = Viz.calcDbUpdate(vals.prob_guilty, vals.prob_innocent);

    const body = {
      player_id: this.playerId,
      prob_guilty: vals.prob_guilty,
      prob_innocent: vals.prob_innocent,
      guilty_rating: vals.guilty_rating,
      innocent_rating: vals.innocent_rating
    };

    const data = await this.api(`/games/${this.gameId}/evidence/${this.currentEvidenceIdx}`, {
      method: 'POST',
      body: JSON.stringify(body)
    });

    if (!data.success) { alert('Error: ' + data.error); return; }

    this.currentDb += dbUpdate;
    this.responses.push({
      name: this.evidenceList[this.currentEvidenceIdx].name,
      db_update: dbUpdate,
      prob_guilty: vals.prob_guilty,
      prob_innocent: vals.prob_innocent
    });

    Viz.updateMeter('running-meter-fill', 'running-meter-threshold', 'running-meter-value',
      this.currentDb, this.thresholdDb);

    const nextIdx = this.currentEvidenceIdx + 1;
    if (nextIdx < this.evidenceList.length) {
      await this.loadEvidence(nextIdx);
    } else {
      await this.showVerdict();
    }
  },

  goBackFromEvidence() {
    if (this.currentEvidenceIdx === 0) {
      this.showScreen('evidence-preview');
    } else {
      // Can't truly go back after submitting, but let them re-view the current evidence description
      window.scrollTo(0, 0);
    }
  },

  // ---- Verdict ----

  async showVerdict() {
    const data = await this.api(`/games/${this.gameId}/verdict`);

    document.getElementById('verdict-case-name').textContent =
      this.caseData.case_info.name;

    // Evidence summary table
    const tableEl = document.getElementById('evidence-summary-table');
    tableEl.innerHTML = this.responses.map(r => {
      const cls = r.db_update >= 0 ? 'ev-db-positive' : 'ev-db-negative';
      const sign = r.db_update >= 0 ? '+' : '';
      return `<div class="ev-summary-row">
        <span class="ev-name">${r.name}</span>
        <span class="${cls}">${sign}${r.db_update.toFixed(1)} dB</span>
      </div>`;
    }).join('');

    // Final meter
    Viz.updateMeter('final-meter-fill', 'final-meter-threshold', 'final-meter-value',
      this.currentDb, this.thresholdDb);

    // Verdict announcement
    const isGuilty = this.currentDb >= this.thresholdDb;
    const finalProb = Viz.dbToProb(this.currentDb) * 100;
    const ann = document.getElementById('verdict-announcement');

    if (isGuilty) {
      ann.className = 'verdict-announcement verdict-guilty';
      ann.innerHTML = `
        <h2>GUILTY</h2>
        <p>The evidence reached ${this.currentDb.toFixed(1)} dB (${finalProb.toFixed(2)}% certainty),
        exceeding your threshold of ${this.thresholdDb.toFixed(1)} dB.</p>`;
    } else {
      const needed = this.thresholdDb - this.currentDb;
      ann.className = 'verdict-announcement verdict-not-guilty';
      ann.innerHTML = `
        <h2>NOT GUILTY</h2>
        <p>The evidence reached ${this.currentDb.toFixed(1)} dB (${finalProb.toFixed(2)}% certainty),
        but your standard required ${this.thresholdDb.toFixed(1)} dB.
        You would need ${needed.toFixed(1)} more dB of evidence to convict.</p>`;
    }

    // Reference comparison
    const refEl = document.getElementById('reference-comparison');
    if (data.success && data.game_state?.verdict?.reference_comparison) {
      const ref = data.game_state.verdict.reference_comparison;
      if (ref.reference_evidence && ref.reference_evidence.length > 0) {
        const refProb = Viz.dbToProb(ref.reference_final_db) * 100;
        const refGuilty = ref.reference_final_db >= this.thresholdDb;
        refEl.innerHTML = `
          <h3>Reference Comparison</h3>
          <p style="font-size:0.85rem;color:var(--text-muted);margin-bottom:12px">
            Using the case file's reference probabilities, the result would be:
            <strong style="color:${refGuilty ? 'var(--guilty-soft)' : 'var(--innocent-soft)'}">${refGuilty ? 'GUILTY' : 'NOT GUILTY'}</strong>
            at ${ref.reference_final_db.toFixed(1)} dB (${refProb.toFixed(2)}%)
          </p>
          ${ref.reference_evidence.map(e => {
            const cls = e.db_update >= 0 ? 'ev-db-positive' : 'ev-db-negative';
            const sign = e.db_update >= 0 ? '+' : '';
            return `<div class="ref-row">
              <span>${e.name}</span>
              <span class="${cls}">${sign}${e.db_update.toFixed(1)} dB</span>
            </div>`;
          }).join('')}`;
      } else {
        refEl.innerHTML = '';
      }
    } else {
      refEl.innerHTML = '';
    }

    // Detailed JSON
    document.getElementById('detailed-results-json').textContent =
      JSON.stringify({
        game_id: this.gameId,
        case: this.caseData.case_info.name,
        prior_db: this.priorDb,
        final_db: this.currentDb,
        threshold_db: this.thresholdDb,
        tolerance: this.tolerance,
        verdict: isGuilty ? 'GUILTY' : 'NOT GUILTY',
        responses: this.responses
      }, null, 2);

    this.showScreen('verdict');
  },

  playAgain() {
    this.gameId = null;
    this.playerId = null;
    this.caseData = null;
    this.responses = [];
    this.currentDb = 0;
    this.showScreen('case-select');
  },

  // ---- Utility ----

  adjustProb(which, delta) {
    EvidenceInput.adjustProb(which, delta);
  }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  App.setThreshold(100);
});
