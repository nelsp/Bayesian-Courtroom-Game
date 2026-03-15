/**
 * Main application — screen navigation, API interaction, game state,
 * multiplayer Socket.IO, sidebar, lobby, reconnection.
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

  // Multiplayer state
  isMultiplayer: false,
  isHost: false,
  joinCode: null,
  socket: null,
  players: {},
  sidebarOpen: false,
  hasSubmittedCurrentEvidence: false,

  // ---- Screen Navigation ----

  showScreen(name) {
    const screens = document.querySelectorAll('.screen');
    const target = document.getElementById('screen-' + name);
    if (!target) return;

    screens.forEach(s => s.classList.remove('active'));
    target.classList.add('active');

    if (name === 'case-select') this.loadCases();

    const gameScreens = ['case-presentation', 'evidence-preview', 'evidence-eval', 'verdict'];
    const sidebar = document.getElementById('player-sidebar');
    if (this.isMultiplayer && gameScreens.includes(name)) {
      sidebar.classList.remove('hidden');
    } else {
      sidebar.classList.add('hidden');
    }

    this._updateHostControls();
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
    const joinDbEl = document.getElementById('join-threshold-db');
    if (joinDbEl) joinDbEl.textContent = this.thresholdDb.toFixed(1) + ' dB';
  },

  setInputMethod(method) {
    this.inputMethod = method;
    document.querySelectorAll('.toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.method === method);
    });
  },

  // ---- Join Game (guest flow) ----

  showJoinInput() {
    document.getElementById('join-input-area').classList.remove('hidden');
    document.getElementById('join-btn').style.display = 'none';
    document.getElementById('join-code-input').focus();
  },

  joinGameByCode() {
    const code = (document.getElementById('join-code-input').value || '').toUpperCase().trim();
    const name = (document.getElementById('join-name-input').value || '').trim() || 'Juror';

    if (code.length !== 4) {
      alert('Enter a 4-letter room code');
      return;
    }

    this.isMultiplayer = true;
    this.isHost = false;

    this._connectSocket(() => {
      this.socket.emit('join_room_by_code', {
        join_code: code,
        name: name,
        guilt_tolerance: this.tolerance,
        use_rating_scale: this.inputMethod === 'slider',
      });
    });
  },

  // ---- Start Case (solo) ----

  async startCase() {
    this.isMultiplayer = false;
    this.isHost = false;

    let data = await this.api('/games', {
      method: 'POST',
      body: JSON.stringify({ case_slug: this.caseSlug })
    });
    if (!data.success) { alert('Failed to create game: ' + data.error); return; }
    this.gameId = data.game_id;

    const hostName = (document.getElementById('host-name').value || '').trim() || 'Player';
    data = await this.api(`/games/${this.gameId}/player`, {
      method: 'POST',
      body: JSON.stringify({
        name: hostName,
        guilt_tolerance: this.tolerance,
        use_rating_scale: this.inputMethod === 'slider'
      })
    });
    if (!data.success) { alert('Failed to register player'); return; }
    this.playerId = data.player_id;

    const caseRes = await this.api(`/games/${this.gameId}/case`);
    this.caseData = caseRes;
    this.priorDb = caseRes.prior_info.db;
    this.currentDb = caseRes.prior_info.db;
    this.responses = [];
    this.currentEvidenceIdx = 0;

    const evRes = await this.api(`/games/${this.gameId}/evidence`);
    this.evidenceList = evRes.evidence;

    this.renderCasePresentation();
    this.showScreen('case-presentation');
  },

  // ---- Create Multiplayer Room (host flow) ----

  createMultiplayerRoom() {
    this.isMultiplayer = true;
    this.isHost = true;

    const hostName = (document.getElementById('host-name').value || '').trim() || 'Host';

    this._connectSocket(() => {
      this.socket.emit('create_room', {
        case_slug: this.caseSlug,
        name: hostName,
        guilt_tolerance: this.tolerance,
        use_rating_scale: this.inputMethod === 'slider',
      });
    });
  },

  // ---- Lobby ----

  _renderLobby(state, joinCode) {
    this.joinCode = joinCode || this.joinCode;
    document.getElementById('room-code-text').textContent = this.joinCode || '----';

    this._updateLobbyPlayers(state);

    const startBtn = document.getElementById('lobby-start-btn');
    const waitingMsg = document.getElementById('lobby-waiting');
    if (this.isHost) {
      startBtn.style.display = '';
      waitingMsg.style.display = 'none';
    } else {
      startBtn.style.display = 'none';
      waitingMsg.style.display = '';
    }

    this.showScreen('lobby');
  },

  _updateLobbyPlayers(state) {
    this.players = state.players || {};
    const list = document.getElementById('lobby-player-list');
    const count = Object.keys(this.players).length;
    document.getElementById('lobby-player-count').textContent = `${count} of 12 jurors`;

    list.innerHTML = Object.entries(this.players).map(([pid, p]) => {
      const isHost = pid === state.host_player_id;
      const isYou = pid === this.playerId;
      return `<div class="lobby-player ${isYou ? 'you' : ''}">
        <span class="lobby-player-name">${p.name}${isHost ? ' (Host)' : ''}${isYou ? ' (You)' : ''}</span>
        <span class="lobby-player-status ${p.is_connected ? 'connected' : 'disconnected'}">
          ${p.is_connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>`;
    }).join('');
  },

  copyRoomCode() {
    if (this.joinCode) {
      navigator.clipboard.writeText(this.joinCode).catch(() => {});
      const el = document.getElementById('room-code-display');
      el.classList.add('copied');
      setTimeout(() => el.classList.remove('copied'), 1200);
    }
  },

  hostStartGame() {
    if (!this.socket || !this.isHost) return;
    this.socket.emit('start_game', { game_id: this.gameId });
  },

  leaveLobby() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
    this.isMultiplayer = false;
    this.isHost = false;
    this.gameId = null;
    this.playerId = null;
    this.joinCode = null;
    this.showScreen('welcome');
  },

  // ---- Case Presentation / Evidence Preview (multiplayer phase advances) ----

  advanceToEvidencePreview() {
    if (this.isMultiplayer) {
      if (!this.isHost) return;
      this.socket.emit('advance_phase', { game_id: this.gameId });
    } else {
      this.showScreen('evidence-preview');
    }
  },

  async beginEvaluation() {
    if (this.isMultiplayer) {
      if (!this.isHost) return;
      this.socket.emit('advance_phase', { game_id: this.gameId });
    } else {
      this.currentEvidenceIdx = 0;
      await this.loadEvidence(0);
      this.showScreen('evidence-eval');
    }
  },

  // ---- Host Control Visibility ----

  _updateHostControls() {
    if (!this.isMultiplayer) {
      document.querySelectorAll('.host-control').forEach(el => el.classList.remove('hidden'));
      document.querySelectorAll('.host-waiting-msg').forEach(el => el.classList.add('hidden'));
      return;
    }

    document.querySelectorAll('.host-control').forEach(el => {
      el.classList.toggle('hidden', !this.isHost);
    });
    document.querySelectorAll('.host-waiting-msg').forEach(el => {
      el.classList.toggle('hidden', this.isHost);
    });
  },

  // ---- Rendering ----

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

  async loadEvidence(idx) {
    const data = await this.api(`/games/${this.gameId}/evidence/${idx}`);
    if (!data.success) return;

    const ev = data.evidence;
    this.currentEvidenceIdx = idx;
    this.hasSubmittedCurrentEvidence = false;

    const total = this.evidenceList.length;
    const pct = ((idx + 1) / total) * 100;
    document.getElementById('evidence-progress').style.width = pct + '%';
    document.getElementById('evidence-progress-label').textContent =
      `Evidence ${idx + 1} of ${total}`;

    document.getElementById('evidence-title').textContent = ev.name;
    document.getElementById('evidence-description-text').textContent = ev.description;

    const guidance = ev.guidance || {};
    document.getElementById('guilty-prompt').textContent =
      guidance.guilty_prompt || 'How likely is this evidence if the defendant is GUILTY?';
    document.getElementById('innocent-prompt').textContent =
      guidance.innocent_prompt || 'How likely is this evidence if the defendant is INNOCENT?';

    EvidenceInput.init(this.inputMethod);
    EvidenceInput.reset();

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

    if (this.isMultiplayer && this.socket) {
      this.socket.emit('submit_evidence', {
        game_id: this.gameId,
        prob_guilty: vals.prob_guilty,
        prob_innocent: vals.prob_innocent,
        guilty_rating: vals.guilty_rating,
        innocent_rating: vals.innocent_rating,
      });

      this.hasSubmittedCurrentEvidence = true;
      this.currentDb += dbUpdate;
      this.responses.push({
        name: this.evidenceList[this.currentEvidenceIdx].name,
        db_update: dbUpdate,
        prob_guilty: vals.prob_guilty,
        prob_innocent: vals.prob_innocent
      });

      Viz.updateMeter('running-meter-fill', 'running-meter-threshold', 'running-meter-value',
        this.currentDb, this.thresholdDb);

      this._showWaiting('Waiting for other jurors...');
    } else {
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
    }
  },

  goBackFromEvidence() {
    if (this.currentEvidenceIdx === 0) {
      this.showScreen('evidence-preview');
    } else {
      window.scrollTo(0, 0);
    }
  },

  // ---- Waiting Overlay ----

  _showWaiting(text, progress) {
    document.getElementById('waiting-text').textContent = text || 'Waiting...';
    document.getElementById('waiting-progress-text').textContent = progress || '';
    document.getElementById('waiting-overlay').classList.remove('hidden');
  },

  _hideWaiting() {
    document.getElementById('waiting-overlay').classList.add('hidden');
  },

  // ---- Player Sidebar ----

  toggleSidebar() {
    this.sidebarOpen = !this.sidebarOpen;
    document.getElementById('sidebar-panel').classList.toggle('open', this.sidebarOpen);
  },

  _updateSidebar(state) {
    if (!this.isMultiplayer) return;
    const list = document.getElementById('sidebar-player-list');
    const players = state.players || {};
    const count = Object.keys(players).length;

    document.getElementById('sidebar-badge').textContent = count;

    const phase = state.phase;

    list.innerHTML = Object.entries(players).map(([pid, p]) => {
      let status = '';
      if (phase === 'evidence_review') {
        status = 'Evaluating...';
      } else if (phase === 'verdict' || phase === 'completed') {
        status = 'Done';
      } else {
        status = 'Reading...';
      }
      if (!p.is_connected) status = 'Disconnected';

      const isYou = pid === this.playerId;
      return `<div class="sidebar-player ${isYou ? 'you' : ''} ${p.is_connected ? '' : 'disconnected'}">
        <span class="sp-name">${p.name}${isYou ? ' (You)' : ''}</span>
        <span class="sp-status">${status}</span>
      </div>`;
    }).join('');
  },

  // ---- Verdict ----

  async showVerdict() {
    const data = await this.api(`/games/${this.gameId}/verdict`);

    document.getElementById('verdict-case-name').textContent =
      this.caseData.case_info.name;

    const tableEl = document.getElementById('evidence-summary-table');
    tableEl.innerHTML = this.responses.map(r => {
      const cls = r.db_update >= 0 ? 'ev-db-positive' : 'ev-db-negative';
      const sign = r.db_update >= 0 ? '+' : '';
      return `<div class="ev-summary-row">
        <span class="ev-name">${r.name}</span>
        <span class="${cls}">${sign}${r.db_update.toFixed(1)} dB</span>
      </div>`;
    }).join('');

    Viz.updateMeter('final-meter-fill', 'final-meter-threshold', 'final-meter-value',
      this.currentDb, this.thresholdDb);

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

    // Jury Panel Results (multiplayer)
    this._renderJuryTable(data);

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

  _renderJuryTable(data) {
    const panel = document.getElementById('jury-panel-results');
    const verdictData = data?.game_state?.verdict;
    const playerVerdicts = verdictData?.player_verdicts;

    if (!playerVerdicts || playerVerdicts.length <= 1) {
      panel.classList.add('hidden');
      return;
    }

    panel.classList.remove('hidden');
    const tbody = document.getElementById('jury-table-body');
    tbody.innerHTML = playerVerdicts.map(pv => {
      const prob = pv.final_probability.toFixed(1);
      const verdictText = pv.would_convict ? 'Guilty' : 'Not Guilty';
      const verdictClass = pv.would_convict ? 'jv-guilty' : 'jv-not-guilty';
      const isYou = pv.player_id === this.playerId;
      return `<tr class="${isYou ? 'jury-row-you' : ''}">
        <td>${pv.name}${isYou ? ' (You)' : ''}</td>
        <td>${pv.final_db.toFixed(1)} dB</td>
        <td>${prob}%</td>
        <td class="${verdictClass}">${verdictText}</td>
      </tr>`;
    }).join('');

    const stats = verdictData.statistics;
    const banner = document.getElementById('group-verdict-banner');
    const groupVerdict = verdictData.group_verdict;
    if (groupVerdict === 'GUILTY') {
      banner.className = 'group-verdict-banner gv-guilty';
      banner.innerHTML = `<strong>GUILTY</strong> (Unanimous)`;
    } else {
      banner.className = 'group-verdict-banner gv-not-guilty';
      banner.innerHTML = `<strong>NOT GUILTY</strong> — ${stats.guilty_votes} of ${stats.total_players} jurors would convict`;
    }
  },

  playAgain() {
    if (this.socket) {
      this.socket.disconnect();
      this.socket = null;
    }
    this.gameId = null;
    this.playerId = null;
    this.caseData = null;
    this.responses = [];
    this.currentDb = 0;
    this.isMultiplayer = false;
    this.isHost = false;
    this.joinCode = null;
    this.players = {};
    sessionStorage.removeItem('bcg_gameId');
    sessionStorage.removeItem('bcg_playerId');
    this.showScreen('case-select');
  },

  // ---- Socket.IO Connection ----

  _connectSocket(onConnect) {
    if (this.socket && this.socket.connected) {
      onConnect();
      return;
    }

    this.socket = io({ transports: ['websocket', 'polling'] });

    this.socket.on('connect', () => {
      if (onConnect) onConnect();
    });

    this.socket.on('error', (data) => {
      alert(data.message || 'Socket error');
    });

    // Room created (host)
    this.socket.on('room_created', (data) => {
      this.gameId = data.game_id;
      this.playerId = data.player_id;
      this.joinCode = data.join_code;
      this._saveSession();
      this._renderLobby(data.game_state, data.join_code);
    });

    // Join success (guest)
    this.socket.on('join_success', (data) => {
      this.gameId = data.game_id;
      this.playerId = data.player_id;
      this.joinCode = data.join_code;
      this._saveSession();
      this._renderLobby(data.game_state, data.join_code);
    });

    this.socket.on('player_joined', (data) => {
      this._updateLobbyPlayers(data.game_state);
      if (this.isMultiplayer) this._updateSidebar(data.game_state);
    });

    this.socket.on('player_left', (data) => {
      this._updateLobbyPlayers(data.game_state);
      if (this.isMultiplayer) this._updateSidebar(data.game_state);
    });

    this.socket.on('game_started', async (data) => {
      const state = data.game_state;
      const caseRes = await this.api(`/games/${this.gameId}/case`);
      this.caseData = caseRes;
      this.priorDb = caseRes.prior_info.db;
      this.currentDb = caseRes.prior_info.db;
      this.responses = [];
      this.currentEvidenceIdx = 0;

      const evRes = await this.api(`/games/${this.gameId}/evidence`);
      this.evidenceList = evRes.evidence;

      this.renderCasePresentation();
      this.showScreen('case-presentation');
      this._updateSidebar(state);
    });

    this.socket.on('phase_advanced', async (data) => {
      const state = data.game_state;
      if (state.phase === 'evidence_preview') {
        this.showScreen('evidence-preview');
      } else if (state.phase === 'evidence_review') {
        this.currentEvidenceIdx = 0;
        await this.loadEvidence(0);
        this.showScreen('evidence-eval');
      }
      this._updateSidebar(state);
    });

    this.socket.on('player_submitted', (data) => {
      if (!this.hasSubmittedCurrentEvidence) return;
      this._showWaiting(
        'Waiting for other jurors...',
        `${data.responses_received} of ${data.total_players} submitted`
      );
    });

    this.socket.on('evidence_advanced', async (data) => {
      this._hideWaiting();
      const nextIdx = data.next_evidence_index;
      await this.loadEvidence(nextIdx);
      this._updateSidebar(data.game_state);
    });

    this.socket.on('verdict_ready', async (data) => {
      this._hideWaiting();
      this._updateSidebar(data.game_state);
      await this.showVerdict();
    });

    // Reconnection
    this.socket.on('state_restored', async (data) => {
      this.gameId = data.game_id;
      if (data.player_id) this.playerId = data.player_id;

      const state = data.game_state;
      this.isHost = state.host_player_id === this.playerId;

      if (state.phase === 'setup') {
        this._renderLobby(state);
      } else {
        const caseRes = await this.api(`/games/${this.gameId}/case`);
        this.caseData = caseRes;
        this.priorDb = caseRes.prior_info.db;

        const evRes = await this.api(`/games/${this.gameId}/evidence`);
        this.evidenceList = evRes.evidence;

        if (data.player_state) {
          this.currentDb = data.player_state.current_evidence_db;
          this.thresholdDb = data.player_state.guilt_threshold_db;
          this.responses = (data.player_state.running_snapshots || []).map(s => ({
            name: s.evidence_name,
            db_update: s.db_update,
          }));
        } else {
          this.currentDb = caseRes.prior_info.db;
        }

        this.renderCasePresentation();

        if (state.phase === 'case_presentation') {
          this.showScreen('case-presentation');
        } else if (state.phase === 'evidence_preview') {
          this.showScreen('evidence-preview');
        } else if (state.phase === 'evidence_review') {
          this.currentEvidenceIdx = state.current_evidence_index;
          await this.loadEvidence(state.current_evidence_index);
          this.showScreen('evidence-eval');
        } else if (state.phase === 'verdict' || state.phase === 'completed') {
          await this.showVerdict();
        }
        this._updateSidebar(state);
      }
    });

    this.socket.on('disconnect', () => {
      // Will auto-reconnect via Socket.IO
    });

    this.socket.on('reconnect', () => {
      const savedGameId = sessionStorage.getItem('bcg_gameId');
      const savedPlayerId = sessionStorage.getItem('bcg_playerId');
      if (savedGameId && savedPlayerId) {
        this.socket.emit('request_state', {
          game_id: savedGameId,
          player_id: savedPlayerId,
        });
      }
    });
  },

  _saveSession() {
    sessionStorage.setItem('bcg_gameId', this.gameId);
    sessionStorage.setItem('bcg_playerId', this.playerId);
  },

  _tryReconnect() {
    const savedGameId = sessionStorage.getItem('bcg_gameId');
    const savedPlayerId = sessionStorage.getItem('bcg_playerId');
    if (savedGameId && savedPlayerId) {
      this.isMultiplayer = true;
      this._connectSocket(() => {
        this.socket.emit('request_state', {
          game_id: savedGameId,
          player_id: savedPlayerId,
        });
      });
    }
  },

  // ---- Utility ----

  adjustProb(which, delta) {
    EvidenceInput.adjustProb(which, delta);
  }
};

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  App.setThreshold(100);
  App._tryReconnect();
});
