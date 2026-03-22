const API = typeof API_BASE !== 'undefined' ? API_BASE : '';
        let allItems = [];
        const relationshipTemperatureApi = window.RelationshipTemperature;
        const INTELLIGENCE_SETTINGS_ENDPOINT = `${API}/api/settings/intelligence`;
        const RUNTIME_SETTINGS_ENDPOINT = `${API}/api/settings/runtime`;
        let intelligenceSettings = null;
        let runtimeSettings = null;
        let transcriptGuidanceEditorState = {
            knowledge_buckets: [],
            stage_relationship: [],
            stage_opportunity: []
        };

        // ===== BOOT =====
        async function boot() {
            const res = await fetch(`${API}/api/taxonomy/all`);
            allItems = await res.json();
            renderAll();
            await renderRuntimeApiSettings();
            await renderIntelligenceFrameworkSettings();
            await renderBackupSettings();
            renderRelationshipHealthSettings();
            renderBackgroundSettings();
            updateStats();
        }

        function updateStats() {
            const active = allItems.filter(i => i.is_active);
            const cat = active.filter(i => i.category_type === 'cat').length;
            const env = active.filter(i => i.category_type === 'env').length;
            const disc = active.filter(i => i.category_type === 'disc').length;
            document.getElementById('stat-cat').textContent = cat;
            document.getElementById('stat-env').textContent = env;
            document.getElementById('stat-disc').textContent = disc;
            document.getElementById('stat-total').textContent = cat + env + disc;
        }

        function intelligenceFallbackSettings() {
            return {
                schema_version: 'stage-settings-v1',
                chatbot_only_inputs: true,
                legacy_scoring_enabled: false,
                layers: [
                    {
                        layer_id: 'stage1_knowledge_bank',
                        label: 'Stage 1 Knowledge Bank Build',
                        description: 'Track completeness and gaps across approved knowledge boxes.',
                        enabled: true,
                        status: 'active'
                    },
                    {
                        layer_id: 'stage2_relationship_flow',
                        label: 'Stage 2 Relationship and Business Flow',
                        description: 'Track relationship stage (S1-S9) and mature-cycle opportunity stage (O1-O7).',
                        enabled: true,
                        status: 'active'
                    }
                ],
                stage1_calibration: {
                    profile: 'balanced',
                    coverage_weight_pct: 60,
                    confidence_weight_pct: 25,
                    recency_weight_pct: 10,
                    density_weight_pct: 5,
                    recency_windows_days: {
                        fresh: 60,
                        recent: 180,
                        aged: 365
                    }
                },
                transcript_tagging: {
                    knowledge_buckets: [],
                    stage_relationship: [],
                    stage_opportunity: [],
                    stage_rules: [],
                    stage_from_knowledge_map: {}
                }
            };
        }

        async function loadIntelligenceSettings() {
            try {
                const res = await fetch(INTELLIGENCE_SETTINGS_ENDPOINT);
                if (!res.ok) throw new Error('Unable to load intelligence settings');
                const payload = await res.json();
                intelligenceSettings = payload.settings || intelligenceFallbackSettings();
                return payload;
            } catch (_err) {
                intelligenceSettings = intelligenceFallbackSettings();
                return { settings: intelligenceSettings, updated_at: '' };
            }
        }

        function runtimeSettingsFallback() {
            return {
                openai: {
                    configured: false,
                    masked_key: '',
                    relationship_story_model: '',
                    updated_at: ''
                }
            };
        }

        async function loadRuntimeSettings() {
            try {
                const res = await fetch(RUNTIME_SETTINGS_ENDPOINT, { cache: 'no-store' });
                if (!res.ok) throw new Error('Unable to load runtime settings');
                const payload = await res.json();
                runtimeSettings = payload && typeof payload === 'object' ? payload : runtimeSettingsFallback();
                return runtimeSettings;
            } catch (_err) {
                runtimeSettings = runtimeSettingsFallback();
                return runtimeSettings;
            }
        }

        async function renderRuntimeApiSettings(options = {}) {
            const shouldReload = options.reload !== false;
            const state = shouldReload || !runtimeSettings
                ? await loadRuntimeSettings()
                : runtimeSettings;
            const container = document.getElementById('section-runtime-api');
            if (!container) return;

            const openai = state?.openai || {};
            const configured = !!openai.configured;
            const masked = String(openai.masked_key || '').trim();
            const model = String(openai.relationship_story_model || 'gpt-5.2').trim();
            const updatedAt = String(openai.updated_at || '').trim();
            const updatedLabel = updatedAt ? formatBackupDate(updatedAt) : 'Not recorded';
            const statusBadge = configured
                ? '<span class="count-badge">Configured</span>'
                : '<span class="count-badge" style="background:#7f1d1d;color:#fecaca;border-color:#ef4444;">Missing</span>';

            container.innerHTML = `
  <div class="section relationship-health-section" id="sec-runtime-api">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon relationship-health-icon">&#128273;</div>
        <div>
          <h2>Runtime API Key ${statusBadge}</h2>
          <p>Set the OpenAI key used by transcript tagging and relationship intelligence.</p>
        </div>
      </div>
      <div class="relationship-health-actions">
        <button class="btn btn-ghost btn-sm" type="button" onclick="renderRuntimeApiSettings()">Refresh</button>
        <button id="runtime-openai-save-btn" class="btn btn-primary btn-sm" type="button" onclick="saveOpenAiApiKey()">Save API Key</button>
      </div>
    </div>
    <div class="relationship-health-grid">
      <label class="relationship-health-field" style="grid-column: 1 / -1;">
        <span>OpenAI API key</span>
        <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap;">
          <input id="openai-api-key-input" class="editable" type="password" placeholder="sk-proj-..." autocomplete="off" style="flex:1; min-width:280px;">
          <button class="btn btn-ghost btn-sm" type="button" onclick="toggleOpenAiKeyVisibility()">Show</button>
        </div>
        <small>${configured ? `Current key: ${escHtml(masked || '(hidden)')}` : 'No key is currently configured.'}</small>
      </label>
      <div class="relationship-health-field">
        <span>Model</span>
        <strong>${escHtml(model)}</strong>
        <small>Current model used for relationship-story transcript tagging.</small>
      </div>
      <div class="relationship-health-field">
        <span>Updated</span>
        <strong>${escHtml(updatedLabel)}</strong>
        <small>Timestamp from local <code>.env</code> file modification.</small>
      </div>
    </div>
  </div>`;
        }

        function toggleOpenAiKeyVisibility() {
            const input = document.getElementById('openai-api-key-input');
            if (!input) return;
            input.type = input.type === 'password' ? 'text' : 'password';
        }

        async function saveOpenAiApiKey() {
            const input = document.getElementById('openai-api-key-input');
            const button = document.getElementById('runtime-openai-save-btn');
            const key = String(input?.value || '').trim();
            if (!key) {
                toast('OpenAI API key is required', 'error');
                return;
            }
            if (!key.startsWith('sk-') || key.length < 20) {
                toast("OpenAI API key must look like a valid 'sk-...' key", 'error');
                return;
            }

            if (button) {
                button.disabled = true;
                button.textContent = 'Saving...';
            }
            try {
                const res = await fetch(`${RUNTIME_SETTINGS_ENDPOINT}/openai-key`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ openai_api_key: key })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Could not save OpenAI API key');
                runtimeSettings = data;
                if (input) {
                    input.value = '';
                    input.type = 'password';
                }
                await renderRuntimeApiSettings({ reload: false });
                toast('OpenAI API key saved and applied', 'success');
            } catch (error) {
                toast(`Save failed: ${error.message}`, 'error');
            } finally {
                const currentButton = document.getElementById('runtime-openai-save-btn');
                if (currentButton) {
                    currentButton.disabled = false;
                    currentButton.textContent = 'Save API Key';
                }
            }
        }

        function readInt(id, fallback, min = 0, max = 1000) {
            const raw = document.getElementById(id)?.value;
            const parsed = Number.parseInt(raw, 10);
            if (Number.isNaN(parsed)) return fallback;
            return Math.max(min, Math.min(max, parsed));
        }

        function prettyJson(value, fallback = []) {
            try {
                return JSON.stringify(value ?? fallback, null, 2);
            } catch (_err) {
                return JSON.stringify(fallback, null, 2);
            }
        }

        function readJsonField(id, fallback) {
            const raw = document.getElementById(id)?.value;
            if (raw == null || String(raw).trim() === '') return fallback;
            try {
                return JSON.parse(raw);
            } catch (_err) {
                throw new Error(`Invalid JSON in ${id}`);
            }
        }

        function parseGuidanceIncludes(value) {
            if (Array.isArray(value)) {
                return value
                    .map((item) => String(item || '').trim())
                    .filter(Boolean)
                    .slice(0, 16);
            }
            if (typeof value === 'string') {
                return value
                    .split(/[\n,;]+/)
                    .map((item) => String(item || '').trim())
                    .filter(Boolean)
                    .slice(0, 16);
            }
            return [];
        }

        function normalizeGuidanceBucket(item = {}) {
            return {
                ...item,
                box_id: Number(item.box_id || 0) || 0,
                code: String(item.code || '').trim().toUpperCase(),
                box_key: String(item.box_key || '').trim(),
                box_title: String(item.box_title || item.box_key || '').trim(),
                keywords: Array.isArray(item.keywords) ? item.keywords : [],
                what_it_is: String(item.what_it_is || '').trim(),
                includes: parseGuidanceIncludes(item.includes),
                good_content_looks_like: String(item.good_content_looks_like || '').trim()
            };
        }

        function normalizeGuidanceStage(item = {}) {
            return {
                ...item,
                code: String(item.code || '').trim().toUpperCase(),
                label: String(item.label || item.code || '').trim(),
                summary: String(item.summary || '').trim(),
                what_it_is: String(item.what_it_is || '').trim(),
                includes: parseGuidanceIncludes(item.includes),
                good_content_looks_like: String(item.good_content_looks_like || '').trim()
            };
        }

        function syncTranscriptGuidanceTextareas() {
            const kb = document.getElementById('transcript-knowledge-buckets-json');
            const rel = document.getElementById('transcript-stage-relationship-json');
            const opp = document.getElementById('transcript-stage-opportunity-json');
            if (kb) kb.value = prettyJson(transcriptGuidanceEditorState.knowledge_buckets || [], []);
            if (rel) rel.value = prettyJson(transcriptGuidanceEditorState.stage_relationship || [], []);
            if (opp) opp.value = prettyJson(transcriptGuidanceEditorState.stage_opportunity || [], []);
        }

        function refreshTranscriptGuidanceEditorsFromJson(showToast = false) {
            try {
                transcriptGuidanceEditorState = {
                    knowledge_buckets: (readJsonField('transcript-knowledge-buckets-json', []) || [])
                        .filter((row) => row && typeof row === 'object')
                        .map(normalizeGuidanceBucket),
                    stage_relationship: (readJsonField('transcript-stage-relationship-json', []) || [])
                        .filter((row) => row && typeof row === 'object')
                        .map(normalizeGuidanceStage),
                    stage_opportunity: (readJsonField('transcript-stage-opportunity-json', []) || [])
                        .filter((row) => row && typeof row === 'object')
                        .map(normalizeGuidanceStage)
                };
                renderTranscriptGuidanceEditors();
                if (showToast) toast('Guidance cards refreshed from JSON.', 'success');
            } catch (error) {
                toast(error.message || 'Could not parse guidance JSON.', 'error');
            }
        }

        function renderTranscriptGuidanceEditors() {
            const knowledgeRoot = document.getElementById('guidance-editor-knowledge');
            const stageRoot = document.getElementById('guidance-editor-stage');
            if (!knowledgeRoot || !stageRoot) return;

            const knowledgeRows = (transcriptGuidanceEditorState.knowledge_buckets || []).map((item, index) => `
                <article class="guidance-card">
                  <div class="guidance-card-head">
                    <strong>${escHtml(item.code || `K${index + 1}`)} ${escHtml(item.box_title || item.box_key || 'Knowledge Bucket')}</strong>
                    <span>${escHtml(item.box_key || '')}</span>
                  </div>
                  <label class="guidance-field">
                    <span>What it is</span>
                    <textarea class="editable guidance-textarea" oninput="updateTranscriptGuidanceBucketField(${index}, 'what_it_is', this.value)">${escHtml(item.what_it_is || '')}</textarea>
                  </label>
                  <label class="guidance-field">
                    <span>Includes (one per line)</span>
                    <textarea class="editable guidance-textarea" oninput="updateTranscriptGuidanceBucketIncludes(${index}, this.value)">${escHtml((item.includes || []).join('\n'))}</textarea>
                  </label>
                  <label class="guidance-field">
                    <span>Good content looks like</span>
                    <textarea class="editable guidance-textarea" oninput="updateTranscriptGuidanceBucketField(${index}, 'good_content_looks_like', this.value)">${escHtml(item.good_content_looks_like || '')}</textarea>
                  </label>
                </article>
            `).join('');

            knowledgeRoot.innerHTML = knowledgeRows || '<div class="intelligence-layer-empty">No knowledge buckets available.</div>';

            const stageSection = (title, rows, mode) => `
              <section class="guidance-stage-group">
                <h4>${escHtml(title)}</h4>
                ${(rows || []).map((item, index) => `
                  <article class="guidance-card">
                    <div class="guidance-card-head">
                      <strong>${escHtml(item.code || 'Stage')} ${escHtml(item.label || item.code || '')}</strong>
                    </div>
                    <label class="guidance-field">
                      <span>What it is</span>
                      <textarea class="editable guidance-textarea" oninput="updateTranscriptGuidanceStageField('${mode}', ${index}, 'what_it_is', this.value)">${escHtml(item.what_it_is || '')}</textarea>
                    </label>
                    <label class="guidance-field">
                      <span>Includes (one per line)</span>
                      <textarea class="editable guidance-textarea" oninput="updateTranscriptGuidanceStageIncludes('${mode}', ${index}, this.value)">${escHtml((item.includes || []).join('\n'))}</textarea>
                    </label>
                    <label class="guidance-field">
                      <span>Good content looks like</span>
                      <textarea class="editable guidance-textarea" oninput="updateTranscriptGuidanceStageField('${mode}', ${index}, 'good_content_looks_like', this.value)">${escHtml(item.good_content_looks_like || '')}</textarea>
                    </label>
                  </article>
                `).join('')}
              </section>
            `;

            stageRoot.innerHTML = [
                stageSection('Relationship Stages (S1-S9)', transcriptGuidanceEditorState.stage_relationship || [], 'relationship'),
                stageSection('Opportunity Stages (O1-O7)', transcriptGuidanceEditorState.stage_opportunity || [], 'opportunity')
            ].join('');
        }

        function updateTranscriptGuidanceBucketField(index, field, value) {
            const row = transcriptGuidanceEditorState.knowledge_buckets[index];
            if (!row) return;
            row[field] = String(value || '').trim();
            syncTranscriptGuidanceTextareas();
        }

        function updateTranscriptGuidanceBucketIncludes(index, value) {
            const row = transcriptGuidanceEditorState.knowledge_buckets[index];
            if (!row) return;
            row.includes = parseGuidanceIncludes(value);
            syncTranscriptGuidanceTextareas();
        }

        function updateTranscriptGuidanceStageField(mode, index, field, value) {
            const list = mode === 'opportunity'
                ? transcriptGuidanceEditorState.stage_opportunity
                : transcriptGuidanceEditorState.stage_relationship;
            const row = list[index];
            if (!row) return;
            row[field] = String(value || '').trim();
            syncTranscriptGuidanceTextareas();
        }

        function updateTranscriptGuidanceStageIncludes(mode, index, value) {
            const list = mode === 'opportunity'
                ? transcriptGuidanceEditorState.stage_opportunity
                : transcriptGuidanceEditorState.stage_relationship;
            const row = list[index];
            if (!row) return;
            row.includes = parseGuidanceIncludes(value);
            syncTranscriptGuidanceTextareas();
        }

        function renderIntelligenceLayers() {
            const rows = (intelligenceSettings?.layers || []).map(layer => {
                const layerId = escHtml(layer.layer_id || '');
                const label = escHtml(layer.label || layer.layer_id || 'Layer');
                const status = escHtml(layer.status || 'planned');
                const description = escHtml(layer.description || '');
                const enabled = layer.enabled ? 'checked' : '';
                const removeDisabled = ['stage1_knowledge_bank', 'stage2_relationship_flow'].includes(layer.layer_id) ? 'disabled' : '';
                return `
  <div class="intelligence-layer-row">
    <div class="intelligence-layer-main">
      <strong>${label}</strong>
      <span class="intelligence-layer-meta">${layerId} | ${status}</span>
      <small>${description || 'No description yet.'}</small>
    </div>
    <label class="toggle intelligence-layer-toggle" title="Enable or disable this layer">
      <input type="checkbox" ${enabled} onchange="toggleIntelligenceLayer('${layerId}', this.checked)">
      <div class="toggle-track"></div>
      <div class="toggle-thumb"></div>
    </label>
    <button class="btn btn-ghost btn-sm" type="button" ${removeDisabled} onclick="removeIntelligenceLayer('${layerId}')">Remove</button>
  </div>`;
            });
            return rows.join('') || '<div class="intelligence-layer-empty">No layers configured.</div>';
        }

        async function renderIntelligenceFrameworkSettings(options = {}) {
            const shouldReload = options.reload !== false;
            const payload = shouldReload || !intelligenceSettings
                ? await loadIntelligenceSettings()
                : { settings: intelligenceSettings, updated_at: '' };
            const container = document.getElementById('section-intelligence-framework');
            if (!container) return;

            const stage1 = intelligenceSettings.stage1_calibration || {};
            const windows = stage1.recency_windows_days || {};
            const transcriptTagging = intelligenceSettings.transcript_tagging || {};
            const lastUpdated = payload.updated_at ? formatBackupDate(payload.updated_at) : 'Not saved yet';
            const knowledgeBucketsJson = prettyJson(transcriptTagging.knowledge_buckets || [], []);
            const stageRelationshipJson = prettyJson(transcriptTagging.stage_relationship || [], []);
            const stageOpportunityJson = prettyJson(transcriptTagging.stage_opportunity || [], []);
            const stageRulesJson = prettyJson(transcriptTagging.stage_rules || [], []);

            container.innerHTML = `
  <div class="section relationship-health-section" id="sec-intelligence-framework">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon relationship-health-icon">&#129504;</div>
        <div>
          <h2>Intelligence Framework <span class="count-badge">${(intelligenceSettings.layers || []).length} layers</span></h2>
          <p>Central scoring controls for current and future relationship-intelligence layers.</p>
        </div>
      </div>
      <div class="relationship-health-actions">
        <button class="btn btn-ghost btn-sm" type="button" onclick="resetIntelligenceSettings()">Reset</button>
        <button class="btn btn-primary btn-sm" type="button" onclick="saveIntelligenceSettings()">Save</button>
      </div>
    </div>
    <div class="relationship-health-grid intelligence-settings-grid">
      <label class="relationship-health-field">
        <span>Chatbot-only inputs</span>
        <select id="intelligence-chatbot-only" class="editable">
          <option value="true" ${intelligenceSettings.chatbot_only_inputs ? 'selected' : ''}>Enabled</option>
          <option value="false" ${!intelligenceSettings.chatbot_only_inputs ? 'selected' : ''}>Disabled</option>
        </select>
        <small>When enabled, intelligence scoring uses chatbot-sourced uploads and transcripts only.</small>
      </label>
      <label class="relationship-health-field">
        <span>Legacy scoring</span>
        <select id="intelligence-legacy-scoring" class="editable">
          <option value="false" ${!intelligenceSettings.legacy_scoring_enabled ? 'selected' : ''}>Disabled</option>
          <option value="true" ${intelligenceSettings.legacy_scoring_enabled ? 'selected' : ''}>Enabled</option>
        </select>
        <small>Keep disabled to avoid polluting the rebuilt intelligence model.</small>
      </label>
      <label class="relationship-health-field">
        <span>Stage 1 profile</span>
        <select id="stage1-profile" class="editable">
          <option value="strict" ${stage1.profile === 'strict' ? 'selected' : ''}>Strict</option>
          <option value="balanced" ${stage1.profile !== 'strict' && stage1.profile !== 'lenient' ? 'selected' : ''}>Balanced</option>
          <option value="lenient" ${stage1.profile === 'lenient' ? 'selected' : ''}>Lenient</option>
        </select>
        <small>Controls how aggressively completeness decays with low confidence or stale evidence.</small>
      </label>
      <div class="relationship-health-field">
        <span>Last updated</span>
        <strong>${escHtml(lastUpdated)}</strong>
        <small>Saved centrally for all users of this environment.</small>
      </div>
    </div>
    <div class="relationship-health-grid intelligence-settings-grid">
      <label class="relationship-health-field">
        <span>Coverage weight (%)</span>
        <input id="stage1-weight-coverage" class="editable" type="number" min="0" max="100" step="1" value="${Number(stage1.coverage_weight_pct || 60)}">
      </label>
      <label class="relationship-health-field">
        <span>Confidence weight (%)</span>
        <input id="stage1-weight-confidence" class="editable" type="number" min="0" max="100" step="1" value="${Number(stage1.confidence_weight_pct || 25)}">
      </label>
      <label class="relationship-health-field">
        <span>Recency weight (%)</span>
        <input id="stage1-weight-recency" class="editable" type="number" min="0" max="100" step="1" value="${Number(stage1.recency_weight_pct || 10)}">
      </label>
      <label class="relationship-health-field">
        <span>Density weight (%)</span>
        <input id="stage1-weight-density" class="editable" type="number" min="0" max="100" step="1" value="${Number(stage1.density_weight_pct || 5)}">
      </label>
      <label class="relationship-health-field">
        <span>Fresh window (days)</span>
        <input id="stage1-window-fresh" class="editable" type="number" min="7" max="365" step="1" value="${Number(windows.fresh || 60)}">
      </label>
      <label class="relationship-health-field">
        <span>Recent window (days)</span>
        <input id="stage1-window-recent" class="editable" type="number" min="8" max="730" step="1" value="${Number(windows.recent || 180)}">
      </label>
      <label class="relationship-health-field">
        <span>Aged window (days)</span>
        <input id="stage1-window-aged" class="editable" type="number" min="9" max="1460" step="1" value="${Number(windows.aged || 365)}">
      </label>
      <div class="relationship-health-field">
        <span>Weight guidance</span>
        <small>Weights are auto-normalized to total 100% on save.</small>
      </div>
    </div>
    <div class="intelligence-layers-wrap">
      <div class="intelligence-layers-header">
        <h3>Knowledge and Stage Context Registry</h3>
        <p>Edit the sentence-tagging context used by Knowledge and Stage views without code changes.</p>
      </div>
      <div class="relationship-health-grid intelligence-settings-grid">
        <label class="relationship-health-field" style="grid-column: 1 / -1;">
          <span>Knowledge buckets JSON</span>
          <textarea id="transcript-knowledge-buckets-json" class="editable intelligence-json"></textarea>
          <small>Array of 11 knowledge buckets with <code>box_id</code>, <code>code</code>, <code>box_key</code>, <code>box_title</code>, <code>keywords</code>, <code>what_it_is</code>, <code>includes</code>, and <code>good_content_looks_like</code>. AI reads these directly during analysis.</small>
          <small>Example: <code>{"box_key":"challenges_demands","what_it_is":"Current pressures...","includes":["growth pressure","hiring pressure"],"good_content_looks_like":"Specific operational pain points..."}</code></small>
        </label>
        <label class="relationship-health-field" style="grid-column: 1 / -1;">
          <span>Relationship stages JSON</span>
          <textarea id="transcript-stage-relationship-json" class="editable intelligence-json"></textarea>
          <small>Array of relationship stages (<code>S1</code> to <code>S9</code>) with <code>label</code>, <code>summary</code>, plus optional <code>what_it_is</code>, <code>includes</code>, and <code>good_content_looks_like</code>.</small>
        </label>
        <label class="relationship-health-field" style="grid-column: 1 / -1;">
          <span>Opportunity stages JSON</span>
          <textarea id="transcript-stage-opportunity-json" class="editable intelligence-json"></textarea>
          <small>Array of opportunity stages (<code>O1/O2/O3/O4/O5/O6/O7</code>) with the same guidance fields used above.</small>
        </label>
        <label class="relationship-health-field" style="grid-column: 1 / -1;">
          <span>Stage sentence rules JSON</span>
          <textarea id="transcript-stage-rules-json" class="editable intelligence-json"></textarea>
          <small>Sentence-level stage matcher rules with <code>code</code>, <code>label</code>, and <code>keywords</code>.</small>
        </label>
      </div>
    </div>
    <div class="intelligence-layers-wrap">
      <div class="intelligence-layers-header">
        <h3>Transcript Guidance Cards (Recommended)</h3>
        <p>Edit bucket and stage guidance in plain language. These fields sync to JSON and are passed to the LLM as <code>transcript_guidance</code>.</p>
      </div>
      <div class="relationship-health-actions" style="padding: 0 0 0.75rem 0;">
        <button class="btn btn-ghost btn-sm" type="button" onclick="refreshTranscriptGuidanceEditorsFromJson(true)">Reload Cards From JSON</button>
      </div>
      <div class="guidance-editor-grid">
        <section class="guidance-editor-section">
          <h4>Knowledge Buckets</h4>
          <div id="guidance-editor-knowledge"></div>
        </section>
        <section class="guidance-editor-section">
          <h4>Stages</h4>
          <div id="guidance-editor-stage"></div>
        </section>
      </div>
    </div>
    <div class="intelligence-layers-wrap">
      <div class="intelligence-layers-header">
        <h3>Layer Registry</h3>
        <p>Add future scoring layers now, then activate as we build each one.</p>
      </div>
      <div class="intelligence-layers-list">${renderIntelligenceLayers()}</div>
      <div class="intelligence-layer-add">
        <input id="new-layer-id" class="editable" placeholder="layer_2_strategy" />
        <input id="new-layer-label" class="editable" placeholder="Layer 2 Strategy Lens" />
        <input id="new-layer-description" class="editable" placeholder="Short purpose of this layer" />
        <button class="btn btn-ghost btn-sm" type="button" onclick="addIntelligenceLayer()">Add Layer</button>
      </div>
    </div>
  </div>`;
            const kbTextarea = document.getElementById('transcript-knowledge-buckets-json');
            const relTextarea = document.getElementById('transcript-stage-relationship-json');
            const oppTextarea = document.getElementById('transcript-stage-opportunity-json');
            const rulesTextarea = document.getElementById('transcript-stage-rules-json');
            if (kbTextarea) kbTextarea.value = knowledgeBucketsJson;
            if (relTextarea) relTextarea.value = stageRelationshipJson;
            if (oppTextarea) oppTextarea.value = stageOpportunityJson;
            if (rulesTextarea) rulesTextarea.value = stageRulesJson;
            refreshTranscriptGuidanceEditorsFromJson(false);
        }

        function toggleIntelligenceLayer(layerId, enabled) {
            intelligenceSettings.layers = (intelligenceSettings.layers || []).map(layer => {
                if (layer.layer_id !== layerId) return layer;
                return { ...layer, enabled: Boolean(enabled) };
            });
        }

        function removeIntelligenceLayer(layerId) {
            if (['stage1_knowledge_bank', 'stage2_relationship_flow'].includes(layerId)) return;
            intelligenceSettings.layers = (intelligenceSettings.layers || []).filter(layer => layer.layer_id !== layerId);
            renderIntelligenceFrameworkSettings({ reload: false });
        }

        function addIntelligenceLayer() {
            const idInput = document.getElementById('new-layer-id');
            const labelInput = document.getElementById('new-layer-label');
            const descriptionInput = document.getElementById('new-layer-description');
            const layerId = (idInput?.value || '').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '_');
            const label = (labelInput?.value || '').trim();
            const description = (descriptionInput?.value || '').trim();

            if (!layerId) {
                toast('Layer id is required', 'error');
                return;
            }
            if ((intelligenceSettings.layers || []).some(layer => layer.layer_id === layerId)) {
                toast('Layer id already exists', 'error');
                return;
            }
            intelligenceSettings.layers = [
                ...(intelligenceSettings.layers || []),
                {
                    layer_id: layerId,
                    label: label || layerId.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
                    description,
                    enabled: false,
                    status: 'planned'
                }
            ];
            if (idInput) idInput.value = '';
            if (labelInput) labelInput.value = '';
            if (descriptionInput) descriptionInput.value = '';
            renderIntelligenceFrameworkSettings({ reload: false });
        }

        async function saveIntelligenceSettings() {
            if (!intelligenceSettings) intelligenceSettings = intelligenceFallbackSettings();
            const stage1 = intelligenceSettings.stage1_calibration || {};
            const transcriptTaggingCurrent = intelligenceSettings.transcript_tagging || {};
            syncTranscriptGuidanceTextareas();
            let transcriptTaggingPayload = transcriptTaggingCurrent;
            try {
                transcriptTaggingPayload = {
                    knowledge_buckets: readJsonField('transcript-knowledge-buckets-json', transcriptTaggingCurrent.knowledge_buckets || []),
                    stage_relationship: readJsonField('transcript-stage-relationship-json', transcriptTaggingCurrent.stage_relationship || []),
                    stage_opportunity: readJsonField('transcript-stage-opportunity-json', transcriptTaggingCurrent.stage_opportunity || []),
                    stage_rules: readJsonField('transcript-stage-rules-json', transcriptTaggingCurrent.stage_rules || []),
                    stage_from_knowledge_map: {}
                };
            } catch (error) {
                toast(error.message, 'error');
                return;
            }
            const payload = {
                ...intelligenceSettings,
                chatbot_only_inputs: document.getElementById('intelligence-chatbot-only')?.value === 'true',
                legacy_scoring_enabled: document.getElementById('intelligence-legacy-scoring')?.value === 'true',
                stage1_calibration: {
                    ...stage1,
                    profile: document.getElementById('stage1-profile')?.value || 'balanced',
                    coverage_weight_pct: readInt('stage1-weight-coverage', Number(stage1.coverage_weight_pct || 60), 0, 100),
                    confidence_weight_pct: readInt('stage1-weight-confidence', Number(stage1.confidence_weight_pct || 25), 0, 100),
                    recency_weight_pct: readInt('stage1-weight-recency', Number(stage1.recency_weight_pct || 10), 0, 100),
                    density_weight_pct: readInt('stage1-weight-density', Number(stage1.density_weight_pct || 5), 0, 100),
                    recency_windows_days: {
                        fresh: readInt('stage1-window-fresh', Number((stage1.recency_windows_days || {}).fresh || 60), 7, 365),
                        recent: readInt('stage1-window-recent', Number((stage1.recency_windows_days || {}).recent || 180), 8, 730),
                        aged: readInt('stage1-window-aged', Number((stage1.recency_windows_days || {}).aged || 365), 9, 1460)
                    }
                },
                transcript_tagging: transcriptTaggingPayload
            };

            try {
                const res = await fetch(INTELLIGENCE_SETTINGS_ENDPOINT, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ settings: payload, merge: false })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Could not save intelligence settings');
                intelligenceSettings = data.settings || payload;
                await renderIntelligenceFrameworkSettings();
                toast('Saved intelligence framework settings', 'success');
            } catch (e) {
                toast(`Save failed: ${e.message}`, 'error');
            }
        }

        async function resetIntelligenceSettings() {
            try {
                const res = await fetch(`${INTELLIGENCE_SETTINGS_ENDPOINT}/reset`, {
                    method: 'POST'
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Could not reset intelligence settings');
                intelligenceSettings = data.settings || intelligenceFallbackSettings();
                await renderIntelligenceFrameworkSettings();
                toast('Restored default intelligence framework settings', 'success');
            } catch (e) {
                toast(`Reset failed: ${e.message}`, 'error');
            }
        }

        // ===== RENDER =====
        const SECTION_DEFS = [
            {
                type: 'cat',
                icon: '🏷️',
                iconBg: 'rgba(99,102,241,0.15)',
                title: 'Contact Categories',
                desc: 'Pipeline classification for each contact (e.g. OBE Member, Target Client)',
                containerId: 'section-cat'
            },
            {
                type: 'env',
                icon: '🏢',
                iconBg: 'rgba(34,211,238,0.12)',
                title: 'Environments',
                desc: 'Organisation type (e.g. Developer - Gov, Main Contractor)',
                containerId: 'section-env'
            },
            {
                type: 'disc',
                icon: '🔧',
                iconBg: 'rgba(52,211,153,0.12)',
                title: 'Disciplines',
                desc: 'Professional specialism (e.g. Commercial, Design, Delivery)',
                containerId: 'section-disc'
            }
        ];

        function renderAll() {
            SECTION_DEFS.forEach(def => {
                const items = allItems.filter(i => i.category_type === def.type);
                document.getElementById(def.containerId).innerHTML = renderSection(def, items);
            });
            attachEvents();
        }

        function getRelationshipHealthSettings() {
            return relationshipTemperatureApi.getSettings();
        }

        function renderRelationshipHealthSettings() {
            const settings = getRelationshipHealthSettings();
            const container = document.getElementById('section-relationship-health');
            if (!container) return;
            container.innerHTML = `
  <div class="section relationship-health-section" id="sec-relationship-health">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon relationship-health-icon">&#128293;</div>
        <div>
          <h2>Relationship Temperature Engine <span class="count-badge">Dashboard</span></h2>
          <p>Set relationship cadence by warmth and choose which statuses should freeze temperature warnings.</p>
        </div>
      </div>
      <div class="relationship-health-actions">
        <button class="btn btn-ghost btn-sm" type="button" onclick="resetRelationshipHealthSettings()">Reset</button>
        <button class="btn btn-primary btn-sm" type="button" onclick="saveRelationshipHealthSettings()">Save</button>
      </div>
    </div>
    <div class="relationship-health-grid">
      <label class="relationship-health-field">
        <span>Hot cadence</span>
        <input id="temperature-hot-days" class="editable" type="number" min="3" step="1" value="${settings.hotCadenceDays}">
        <small>How often high-priority relationships should feel meaningful contact.</small>
      </label>
      <label class="relationship-health-field">
        <span>Warm cadence</span>
        <input id="temperature-warm-days" class="editable" type="number" min="3" step="1" value="${settings.warmCadenceDays}">
        <small>The default cadence for most active relationships.</small>
      </label>
      <label class="relationship-health-field">
        <span>Cold cadence</span>
        <input id="temperature-cold-days" class="editable" type="number" min="3" step="1" value="${settings.coldCadenceDays}">
        <small>Longer-cycle or lower-temperature relationships can breathe more here.</small>
      </label>
      <label class="relationship-health-field" style="grid-column: 1 / -1;">
        <span>Freeze statuses</span>
        <input id="temperature-freeze-statuses" class="editable" type="text" value="${settings.freezeStatuses.join(', ')}">
        <small>Comma-separated statuses that mute warnings entirely, for example Frozen, Parked, Paused, Dormant.</small>
      </label>
    </div>
  </div>`;
        }

        function saveRelationshipHealthSettings() {
            const settings = relationshipTemperatureApi.saveSettings({
                hotCadenceDays: document.getElementById('temperature-hot-days')?.value,
                warmCadenceDays: document.getElementById('temperature-warm-days')?.value,
                coldCadenceDays: document.getElementById('temperature-cold-days')?.value,
                freezeStatuses: document.getElementById('temperature-freeze-statuses')?.value
            });
            renderRelationshipHealthSettings();
            toast('Saved relationship temperature settings', 'success');
        }

        function resetRelationshipHealthSettings() {
            relationshipTemperatureApi.resetSettings();
            renderRelationshipHealthSettings();
            toast('Restored default relationship temperature settings', 'success');
        }

        function getBackgroundApi() {
            return window.AntigravityBackground || null;
        }

        function renderBackgroundSettings() {
            const backgroundApi = getBackgroundApi();
            const container = document.getElementById('section-visual-theme');
            if (!container || !backgroundApi) return;
            const settings = backgroundApi.getSettings();
            const usingCustom = settings.mode === 'custom';

            container.innerHTML = `
  <div class="section" id="sec-visual-theme">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon relationship-health-icon">&#128247;</div>
        <div>
          <h2>Backdrop Theme <span class="count-badge">Saved on this browser</span></h2>
          <p>Pick the default scenery, use profile photos on profile pages, or upload a custom backdrop.</p>
        </div>
      </div>
      <div class="relationship-health-actions">
        <button class="btn btn-ghost btn-sm" type="button" onclick="resetBackgroundSettings()">Reset</button>
        <button class="btn btn-primary btn-sm" type="button" onclick="saveBackgroundSettings()">Save</button>
      </div>
    </div>
    <div class="relationship-health-grid background-settings-grid">
      <label class="relationship-health-field background-choice ${settings.mode === 'daily' ? 'is-selected' : ''}">
        <input type="radio" name="background-mode" value="daily" ${settings.mode === 'daily' ? 'checked' : ''}>
        <span>Daily scenery</span>
        <small>Use the shared rotating landscape background across the app.</small>
      </label>
      <label class="relationship-health-field background-choice ${settings.mode === 'profile-photo' ? 'is-selected' : ''}">
        <input type="radio" name="background-mode" value="profile-photo" ${settings.mode === 'profile-photo' ? 'checked' : ''}>
        <span>Profile photo backdrop</span>
        <small>On profile pages, let the contact photo softly fill the background shell.</small>
      </label>
      <label class="relationship-health-field background-choice ${settings.mode === 'custom' ? 'is-selected' : ''}">
        <input type="radio" name="background-mode" value="custom" ${settings.mode === 'custom' ? 'checked' : ''}>
        <span>Custom upload</span>
        <small>Upload your own branded image for this browser.</small>
      </label>
      <div class="relationship-health-field background-upload-field" style="grid-column: 1 / -1;">
        <span>Custom image</span>
        <div class="background-upload-actions">
          <input id="background-image-input" type="file" accept="image/*">
          <button class="btn btn-ghost btn-sm" type="button" onclick="clearBackgroundImage()">Clear custom image</button>
        </div>
        <small>${usingCustom && settings.customImage ? 'Custom image ready. Saving keeps it active.' : 'Select an image, then save to make it your active backdrop.'}</small>
      </div>
    </div>
  </div>`;
        }

        async function renderBackupSettings() {
            const container = document.getElementById('section-backups');
            if (!container) return;

            let backup = {
                exists: false,
                last_backup_at: null,
                label: null,
                filename: null,
                timezone: 'UTC',
                hour: 3,
                minute: 0,
                next_backup_at: null
            };

            try {
                const res = await fetch(`${API}/api/health/backups/status`);
                if (res.ok) {
                    backup = await res.json();
                }
            } catch (_err) {
                // Keep default fallback state for the UI.
            }

            container.innerHTML = `
  <div class="section relationship-health-section" id="sec-backups">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon relationship-health-icon">&#128190;</div>
        <div>
          <h2>Backup Control <span class="count-badge">${backup.exists ? 'Protected' : 'No Backup Found'}</span></h2>
          <p>Daily backups now run on a fixed schedule instead of drifting with app restarts.</p>
        </div>
      </div>
      <div class="relationship-health-actions">
        <button class="btn btn-ghost btn-sm" type="button" onclick="renderBackupSettings()">Refresh</button>
        <button class="btn btn-primary btn-sm" type="button" onclick="runBackupNow()">Run Backup Now</button>
      </div>
    </div>
    <div class="relationship-health-grid">
      <div class="relationship-health-field">
        <span>Latest backup</span>
        <strong>${backup.last_backup_at ? formatBackupDate(backup.last_backup_at) : 'Not available yet'}</strong>
        <small>${backup.filename || 'No backup artifact has been written yet.'}</small>
      </div>
      <div class="relationship-health-field">
        <span>Schedule</span>
        <strong>${formatScheduleTime(backup.hour, backup.minute)} ${backup.timezone || 'UTC'}</strong>
        <small>Fixed daily schedule used by the in-app backup worker.</small>
      </div>
      <div class="relationship-health-field">
        <span>Next run</span>
        <strong>${backup.next_backup_at ? formatBackupDate(backup.next_backup_at) : 'Waiting for scheduler'}</strong>
        <small>${backup.label ? `Latest label: ${backup.label}` : 'The next run will assign daily, weekly, or monthly automatically.'}</small>
      </div>
    </div>
  </div>`;
        }

        function formatScheduleTime(hour, minute) {
            const date = new Date();
            date.setHours(Number(hour || 0), Number(minute || 0), 0, 0);
            return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
        }

        function formatBackupDate(value) {
            try {
                return new Date(value).toLocaleString([], {
                    year: 'numeric',
                    month: 'short',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit'
                });
            } catch (_err) {
                return value || 'Unknown';
            }
        }

        async function runBackupNow() {
            try {
                const res = await fetch(`${API}/api/health/backups/run`, { method: 'POST' });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || data.message || 'Backup failed');
                await renderBackupSettings();
                toast(`Backup complete: ${data.filename || 'archive created'}`, 'success');
            } catch (e) {
                toast(`Backup failed: ${e.message}`, 'error');
            }
        }

        async function saveBackgroundSettings() {
            const backgroundApi = getBackgroundApi();
            if (!backgroundApi) return;

            const selectedMode = document.querySelector('input[name="background-mode"]:checked')?.value || 'daily';
            const imageInput = document.getElementById('background-image-input');
            try {
                if (selectedMode === 'custom' && imageInput?.files?.[0]) {
                    await backgroundApi.saveCustomImage(imageInput.files[0]);
                } else {
                    backgroundApi.saveSettings({ mode: selectedMode });
                    backgroundApi.applyBackground();
                }
                renderBackgroundSettings();
                toast('Saved backdrop settings', 'success');
            } catch (e) {
                toast(`Background save failed: ${e.message}`, 'error');
            }
        }

        function resetBackgroundSettings() {
            const backgroundApi = getBackgroundApi();
            if (!backgroundApi) return;
            backgroundApi.saveSettings({ mode: 'daily', customImage: '' });
            backgroundApi.applyBackground();
            renderBackgroundSettings();
            toast('Restored default backdrop', 'success');
        }

        function clearBackgroundImage() {
            const backgroundApi = getBackgroundApi();
            if (!backgroundApi) return;
            backgroundApi.clearCustomImage();
            renderBackgroundSettings();
            toast('Removed custom backdrop', 'success');
        }

        function renderSection(def, items) {
            const activeCount = items.filter(i => i.is_active).length;
            return `
  <div class="section" id="sec-${def.type}">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon" style="background:${def.iconBg}">${def.icon}</div>
        <div>
          <h2>${def.title} <span class="count-badge">${activeCount} active</span></h2>
          <p>${def.desc}</p>
        </div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="toggleAddForm('${def.type}')">+ Add New</button>
    </div>

    <div class="col-header">
      <span>Color</span>
      <span>Label</span>
      <span>Short Code</span>
      <span>Active</span>
      <span></span>
      <span></span>
    </div>

    <div class="tax-table" id="list-${def.type}">
      ${items.map(item => renderRow(item)).join('')}
    </div>

    <!-- ADD FORM -->
    <div class="add-form" id="add-form-${def.type}">
      <div class="color-dot new-color" id="new-color-${def.type}" style="background:#63b3ed;">
        <input type="color" value="#63b3ed" onchange="updateNewColor('${def.type}', this.value)">
      </div>
      <input class="editable" id="new-label-${def.type}" placeholder="e.g. Strategic Partner" />
      <input class="editable value-field" id="new-value-${def.type}" placeholder="e.g. STP" />
      <div></div>
      <button class="btn btn-primary btn-sm" onclick="addItem('${def.type}')">Save</button>
      <button class="btn btn-ghost btn-sm" onclick="toggleAddForm('${def.type}')">Cancel</button>
    </div>
  </div>`;
        }

        function renderRow(item) {
            return `
  <div class="tax-row ${item.is_active ? '' : 'inactive'}" id="row-${item.config_id}" data-id="${item.config_id}">
    <div class="color-dot" style="background:${item.color || '#666'};" title="Click to change color">
      <input type="color" value="${item.color || '#666666'}"
        onchange="updateColor('${item.config_id}', this.value, this.parentElement)">
    </div>

    <input class="editable" value="${escHtml(item.label)}"
      onblur="saveField('${item.config_id}', 'label', this.value)"
      onkeydown="if(event.key==='Enter')this.blur()"
      title="Click to edit label" />

    <input class="editable value-field" value="${escHtml(item.value)}"
      onblur="saveField('${item.config_id}', 'value', this.value)"
      onkeydown="if(event.key==='Enter')this.blur()"
      title="Click to edit short code" />

    <div class="col-toggle">
      <label class="toggle" title="${item.is_active ? 'Active — click to deactivate' : 'Inactive — click to activate'}">
        <input type="checkbox" ${item.is_active ? 'checked' : ''}
          onchange="toggleActive('${item.config_id}', this.checked)">
        <div class="toggle-track"></div>
        <div class="toggle-thumb"></div>
      </label>
    </div>

    <div></div>

    <div class="row-actions">
      ${item.is_active
                    ? `<button class="btn btn-danger btn-sm" onclick="deleteItem('${item.config_id}')">Remove</button>`
                    : `<button class="btn btn-success btn-sm" onclick="restoreItem('${item.config_id}')">Restore</button>`
                }
    </div>
  </div>`;
        }

        // ===== EVENTS =====
        function attachEvents() {
            // nothing extra needed — events are inline
        }

        function toggleAddForm(type) {
            const form = document.getElementById(`add-form-${type}`);
            form.classList.toggle('visible');
            if (form.classList.contains('visible')) {
                document.getElementById(`new-label-${type}`).focus();
            }
        }

        function updateNewColor(type, hex) {
            document.getElementById(`new-color-${type}`).style.background = hex;
        }

        function updateColor(id, hex, dot) {
            dot.style.background = hex;
            saveField(id, 'color', hex);
        }

        // ===== API ACTIONS =====
        async function saveField(id, field, value) {
            const item = allItems.find(i => i.config_id === id);
            if (item && item[field] === value) return; // no change
            const body = {};
            body[field] = value;
            try {
                const res = await fetch(`${API}/api/taxonomy/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!res.ok) throw new Error('Save failed');
                if (item) item[field] = value;
                toast('✓ Saved', 'success');
                updateStats();
            } catch (e) {
                toast('Save failed: ' + e.message, 'error');
            }
        }

        async function toggleActive(id, active) {
            try {
                await fetch(`${API}/api/taxonomy/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: active ? 1 : 0 })
                });
                const item = allItems.find(i => i.config_id === id);
                if (item) item.is_active = active ? 1 : 0;
                // re-render row
                const row = document.getElementById(`row-${id}`);
                if (row) row.outerHTML = renderRow(item);
                updateStats();
                toast(active ? '✓ Activated' : '✓ Deactivated', 'success');
            } catch (e) {
                toast('Error: ' + e.message, 'error');
            }
        }

        async function deleteItem(id) {
            if (!confirm('Deactivate this taxonomy entry? It will be hidden from dropdowns but preserved in historical data.')) return;
            await toggleActive(id, false);
        }

        async function restoreItem(id) {
            await toggleActive(id, true);
        }

        async function addItem(type) {
            const label = document.getElementById(`new-label-${type}`).value.trim();
            const value = document.getElementById(`new-value-${type}`).value.trim();
            const colorEl = document.getElementById(`new-color-${type}`);
            const color = colorEl.querySelector('input[type=color]').value;

            if (!label) { toast('Label is required', 'error'); return; }
            if (!value) { toast('Short code is required', 'error'); return; }

            try {
                const res = await fetch(`${API}/api/taxonomy`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category_type: type, label, value, color, is_active: 1 })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Add failed');

                // Add to local state
                allItems.push({ config_id: data.config_id, category_type: type, label, value, color, is_active: 1 });

                // Refresh section
                const def = SECTION_DEFS.find(d => d.type === type);
                const items = allItems.filter(i => i.category_type === type);
                document.getElementById(`section-${type}`).innerHTML = renderSection(def, items);

                updateStats();
                toast('✓ Added: ' + label, 'success');
            } catch (e) {
                toast('Error: ' + e.message, 'error');
            }
        }

        // ===== UTILITIES =====
        function escHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        let toastTimer;
        function toast(msg, type = 'success') {
            const el = document.getElementById('toast');
            el.textContent = msg;
            el.className = `show ${type}`;
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => { el.className = ''; }, 2800);
        }

        // ===== BOOT =====
        boot();
