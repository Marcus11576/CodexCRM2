// Meeting brief, AI job status, audio, and propensity
let aiJobPollTimer = null;
let lastAiJobSnapshot = '';
window.currentBriefJobId = null;
window.currentBriefId = null;
let currentBriefData = null;
let currentBriefFeedbackMode = null;

const BRIEF_BUSINESS_SUBTOPICS = (window.BUSINESS_SUBTOPIC_OPTIONS || [
    { value: 'business_interests', label: 'Business Interests' },
    { value: 'market_pulse', label: 'Market Pulse' },
    { value: 'leadership_view', label: 'Leadership View' },
    { value: 'commercial_position', label: 'Commercial Position' },
    { value: 'operational_pressure', label: 'Operational Pressure' },
]);

function hasActiveAiJobs(jobs) {
    return jobs.some(job => ['queued', 'running', 'retrying'].includes(job.status));
}

window.addEventListener('ag:intelligence-updated', () => {
    if (currentBriefData) {
        renderBriefing(currentBriefData);
    }
});

function jobTypeLabel(job) {
    if (job.job_type === 'transcription') return 'Transcription';
    if (job.job_type === 'signal_extraction') return 'Signal Extraction';
    if (job.job_type === 'brief_generation') return 'Brief Generation';
    return job.job_type;
}

function startAiJobPolling() {
    if (aiJobPollTimer) return;
    aiJobPollTimer = setInterval(() => {
        if (personId) loadAiJobs();
    }, 2500);
}

function stopAiJobPolling() {
    if (!aiJobPollTimer) return;
    clearInterval(aiJobPollTimer);
    aiJobPollTimer = null;
}

function ensureBriefFeedbackModal() {
    let modal = document.getElementById('brief-feedback-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'brief-feedback-modal';
    modal.style.cssText = 'position:fixed; inset:0; background:rgba(2,6,23,0.7); display:none; align-items:center; justify-content:center; z-index:1200; padding:1rem;';
    modal.innerHTML = `
        <div style="width:min(100%, 680px); background:linear-gradient(180deg, rgba(15,23,42,0.92), rgba(30,41,59,0.82)); border:1px solid rgba(255,255,255,0.16); border-radius:20px; box-shadow:0 20px 60px rgba(2,8,23,0.35); padding:1rem; display:flex; flex-direction:column; gap:0.85rem;">
            <div style="display:flex; align-items:center; justify-content:space-between; gap:0.75rem;">
                <div>
                    <div id="brief-feedback-modal-title" style="font-size:1rem; font-weight:800; color:white;">Brief feedback</div>
                    <div id="brief-feedback-modal-subtitle" style="font-size:0.78rem; color:var(--text-secondary); margin-top:0.2rem;">Add the change you want and save it.</div>
                </div>
                <button type="button" onclick="closeBriefFeedbackModal()" style="width:36px; height:36px; border-radius:10px; border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.05); color:white; cursor:pointer;">&times;</button>
            </div>
            <textarea id="brief-feedback-input" style="width:100%; min-height:220px; resize:vertical; border-radius:14px; border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.04); color:white; padding:0.9rem; line-height:1.5; font-size:0.9rem;" placeholder="Describe the correction or edit here..."></textarea>
            <div style="display:flex; justify-content:flex-end; gap:0.65rem;">
                <button type="button" onclick="closeBriefFeedbackModal()" style="padding:0.7rem 1rem; border-radius:12px; border:1px solid rgba(255,255,255,0.12); background:rgba(255,255,255,0.05); color:white; cursor:pointer;">Cancel</button>
                <button type="button" id="brief-feedback-submit" onclick="submitBriefFeedbackModal()" style="padding:0.7rem 1rem; border-radius:12px; border:1px solid rgba(56,189,248,0.3); background:rgba(14,165,233,0.16); color:white; cursor:pointer; font-weight:800;">Save</button>
            </div>
        </div>`;
    modal.addEventListener('click', (event) => {
        if (event.target === modal) closeBriefFeedbackModal();
    });
    document.body.appendChild(modal);
    return modal;
}

function setBriefFeedbackState(mode) {
    const row = document.getElementById('briefing-feedback');
    const approveBtn = document.getElementById('brief-feedback-approve');
    const correctBtn = document.getElementById('brief-feedback-correct');
    const editBtn = document.getElementById('brief-feedback-edit');
    if (!row || !approveBtn || !correctBtn || !editBtn) return;

    row.style.display = 'flex';
    const ready = mode === 'ready';

    approveBtn.disabled = !ready;
    correctBtn.disabled = !ready;
    editBtn.disabled = !ready;
    correctBtn.style.opacity = ready ? '1' : '0.45';
    editBtn.style.opacity = ready ? '1' : '0.45';
    approveBtn.style.opacity = ready ? '1' : '0.7';
    correctBtn.style.cursor = ready ? 'pointer' : 'not-allowed';
    editBtn.style.cursor = ready ? 'pointer' : 'not-allowed';
    approveBtn.style.cursor = ready ? 'pointer' : 'not-allowed';

    const label = row.querySelector('div');
    if (label) {
        label.textContent = ready
            ? 'Was this brief accurate?'
            : 'Brief feedback becomes available once generation finishes.';
    }
}

function buildBriefSummaryText(briefing) {
    if (!briefing) return '';
    const summary = (briefing.audio_script || '').trim();
    if (summary && summary !== 'Not available.' && summary !== 'Briefing unavailable right now.') {
        return summary;
    }

    return [
        briefing.business_focus,
        briefing.recruitment_talent,
        briefing.personal_rapport,
        briefing.obe_focus
    ].filter(Boolean).join(' ');
}

function normalizeBriefText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function firstSentences(value, count = 2, maxLength = 320) {
    const normalized = normalizeBriefText(value);
    if (!normalized) return '';
    const sentences = normalized.split(/(?<=[.!?])\s+/).filter(Boolean);
    const preferred = sentences.slice(0, count).join(' ').trim() || normalized;
    if (preferred.length <= maxLength) return preferred;
    return `${preferred.slice(0, maxLength - 3).replace(/\s+\S*$/, '')}...`;
}

function compactBriefLine(value, maxLength = 180) {
    const normalized = normalizeBriefText(value);
    if (!normalized) return '';
    if (normalized.length <= maxLength) return normalized;
    return `${normalized.slice(0, maxLength - 3).replace(/\s+\S*$/, '')}...`;
}

function isGenericBriefNarrative(value) {
    const normalized = normalizeBriefText(value).toLowerCase();
    if (!normalized) return true;
    const genericFragments = [
        "today, you're meeting with",
        "focus on discussing",
        "be prepared to address",
        "while personal details are limited",
        "consider engaging",
        "this could provide valuable insights",
        "strategic priorities and decision-making processes",
    ];
    return genericFragments.some((fragment) => normalized.includes(fragment));
}

function cleanInteractionExcerpt(item) {
    const raw = String(item?.summary || item?.raw_text || '').replace(/\r/g, '\n');
    const lines = raw
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .filter((line) => !/^_{4,}$/.test(line))
        .filter((line) => !/^microsoft teams/i.test(line))
        .filter((line) => !/^join the meeting/i.test(line))
        .filter((line) => !/^meeting id:/i.test(line))
        .filter((line) => !/^passcode:/i.test(line))
        .filter((line) => !/^need help\?/i.test(line));

    if (!lines.length) return '';

    const filtered = lines.filter((line, index) => {
        if (index === 0 && /^(sent email:|received email:|accepted:|declined:|tentative:)/i.test(line)) {
            return false;
        }
        return true;
    });

    const usable = (filtered.length ? filtered : lines)
        .filter((line) => line.length > 8)
        .slice(0, 2)
        .join(' ');

    return compactBriefLine(usable, 180);
}

function buildRecentEvidenceTopics() {
    const history = Array.isArray(window.currentProfileRecentHistory) ? window.currentProfileRecentHistory : [];
    const meaningful = history
        .filter((item) => String(item?.channel || '').toLowerCase() !== 'system_audit')
        .map((item) => ({
            channel: String(item?.channel || 'Interaction'),
            text: cleanInteractionExcerpt(item),
            date: item?.interaction_at || item?.created_at || item?.date || '',
        }))
        .filter((item) => item.text)
        .filter((item) => !/^(accepted|declined|tentative)\b/i.test(item.text))
        .slice(0, 4);

    return meaningful.map((item, index) => ({
        label: index === 0 ? 'Latest evidence' : `${item.channel} follow-up`,
        text: item.text,
    }));
}

function buildQuickBriefModel(briefing) {
    const person = window.currentPersonData || {};
    const context = person.network_score_context || {};
    const task = window.currentProfilePrimaryTask || null;
    const signalTopics = [
        { label: 'Business focus', text: compactBriefLine(briefing.business_focus) },
        { label: 'Recruitment & talent', text: compactBriefLine(briefing.recruitment_talent) },
        { label: 'Personal context', text: compactBriefLine(briefing.personal_rapport) },
        { label: 'OBE focus', text: compactBriefLine(briefing.obe_focus) },
    ].filter((item) => item.text);
    const evidenceTopics = buildRecentEvidenceTopics();
    const topTopics = (signalTopics.length ? signalTopics : evidenceTopics).slice(0, 3);
    const summaryText = buildBriefSummaryText(briefing);
    const currentPicture = !isGenericBriefNarrative(summaryText)
        ? firstSentences(summaryText, 2, 300)
        : (topTopics[0]?.text || 'No grounded current picture has been surfaced from the latest record yet.');
    const whyNow = compactBriefLine(
        context.follow_up_confirmation_reason
        || context.queue_reason
        || context.cover_reason
        || 'No clear current pressure has been recorded.',
        220
    );

    let direction = '';
    if (task?.task_text) {
        const due = typeof formatTaskDistanceLabel === 'function' ? formatTaskDistanceLabel(task) : '';
        direction = `Resolve the current task: ${task.task_text}${due ? ` (${due})` : ''}.`;
    } else if (context.follow_up_confirmation_prompt) {
        direction = compactBriefLine(context.follow_up_confirmation_prompt, 220);
    } else if (topTopics[0]?.text) {
        direction = `Use the latest live thread in the record: ${topTopics[0].text}`;
    } else if (context.has_future_cover) {
        direction = compactBriefLine(context.cover_reason || 'There is already future cover in place.', 220);
    } else {
        direction = 'Lock the next step and capture any change in need, timing, or relationship signal.';
    }

    const statusChips = [
        context.score_band ? { tone: String(context.score_band).toLowerCase().replace(/\s+/g, '-'), text: context.score_band } : null,
        Number.isFinite(Number(context.network_health_score)) ? { tone: 'score', text: `${context.network_health_score}% attention` } : null,
        task?.task_text ? { tone: 'task', text: 'Current task live' } : null,
        context.follow_up_confirmation_needed ? { tone: 'watch', text: 'Outcome update needed' } : null,
    ].filter(Boolean);

    return {
        currentPicture,
        whyNow,
        direction,
        topTopics,
        statusChips,
    };
}

function renderQuickBrief(briefing, generationBadge) {
    const model = buildQuickBriefModel(briefing);
    return `
        <div class="event-notes-card brief-quick-card">
            <div class="brief-summary-head">
                <div class="brief-summary-copy">
                    <div class="brief-summary-label">Quick Background</div>
                    <div class="brief-summary-subtitle">Fast context and direction for the next conversation.</div>
                </div>
                <div class="brief-summary-meta">
                    ${generationBadge}
                </div>
            </div>
            <div class="brief-quick-grid">
                <section class="brief-quick-panel">
                    <div class="brief-quick-label">Current Picture</div>
                    <div class="brief-quick-text">${escapeHtml(model.currentPicture || 'No reliable current picture has been generated yet.')}</div>
                </section>
                <section class="brief-quick-panel">
                    <div class="brief-quick-label">Why It Needs Attention</div>
                    <div class="brief-quick-text">${escapeHtml(model.whyNow)}</div>
                </section>
                <section class="brief-quick-panel">
                    <div class="brief-quick-label">Direction</div>
                    <div class="brief-quick-text">${escapeHtml(model.direction)}</div>
                </section>
                <section class="brief-quick-panel">
                    <div class="brief-quick-label">Topics In Play</div>
                    <div class="brief-quick-topic-list">
                        ${model.topTopics.length ? model.topTopics.map((topic) => `
                            <div class="brief-quick-topic">
                                <strong>${escapeHtml(topic.label)}:</strong> ${escapeHtml(topic.text)}
                            </div>
                        `).join('') : '<div class="brief-quick-text">No strong live topics have been surfaced yet.</div>'}
                    </div>
                </section>
            </div>
            ${model.statusChips.length ? `<div class="brief-quick-chip-row">${model.statusChips.map((chip) => `<span class="brief-quick-chip tone-${escapeHtml(chip.tone)}">${escapeHtml(chip.text)}</span>`).join('')}</div>` : ''}
        </div>
    `;
}

function buildBriefWorkingText(briefing) {
    if (!briefing) return '';
    return [
        `Summary Brief\n${buildBriefSummaryText(briefing)}`,
        `Business Focus\n${briefing.business_focus || ''}`,
        `Recruitment & Talent\n${briefing.recruitment_talent || ''}`,
        `Personal Rapport\n${briefing.personal_rapport || ''}`,
        `OBE Focus\n${briefing.obe_focus || ''}`
    ].join('\n\n');
}

function openBriefFeedbackModal(mode) {
    if (!currentBriefData) {
        toast('Wait for the brief to finish generating first.', 'info');
        return;
    }

    currentBriefFeedbackMode = mode;
    const modal = ensureBriefFeedbackModal();
    const title = document.getElementById('brief-feedback-modal-title');
    const subtitle = document.getElementById('brief-feedback-modal-subtitle');
    const input = document.getElementById('brief-feedback-input');
    const submit = document.getElementById('brief-feedback-submit');

    if (mode === 'correction') {
        title.textContent = 'Request Brief Correction';
        subtitle.textContent = 'Describe what is wrong or what should change. Saving will log feedback and queue a fresh brief.';
        input.value = '';
        input.placeholder = 'Example: The personal rapport section is incorrect. Replace it with the latest discussion about project staffing and remove the family reference.';
        submit.textContent = 'Request Correction';
    } else {
        title.textContent = 'Manual Brief Edit';
        subtitle.textContent = 'Edit the working draft below. Saving logs your manual version and shows it locally as the active working draft.';
        input.value = currentBriefData.manual_edit_text || buildBriefWorkingText(currentBriefData);
        input.placeholder = 'Edit the brief text here...';
        submit.textContent = 'Save Manual Draft';
    }

    modal.style.display = 'flex';
    setTimeout(() => input.focus(), 0);
}

function closeBriefFeedbackModal() {
    const modal = document.getElementById('brief-feedback-modal');
    if (modal) modal.style.display = 'none';
    currentBriefFeedbackMode = null;
}

async function submitBriefApproval() {
    if (!currentBriefData) {
        toast('Wait for the brief to finish generating first.', 'info');
        return;
    }
    await logAiFeedback('brief', 'approve', {
        brief_id: window.currentBriefId,
        source: 'brief_feedback_quick'
    });
}

async function submitBriefFeedbackModal() {
    const input = document.getElementById('brief-feedback-input');
    const submit = document.getElementById('brief-feedback-submit');
    if (!input || !submit || !currentBriefFeedbackMode) return;

    const text = input.value.trim();
    if (!text) {
        toast('Add some detail before saving.', 'info');
        input.focus();
        return;
    }

    submit.disabled = true;
    submit.style.opacity = '0.7';

    try {
        if (currentBriefFeedbackMode === 'correction') {
            await logAiFeedback('brief', 'reject', {
                brief_id: window.currentBriefId,
                requested_change: text,
                source: 'brief_feedback_modal'
            });
            closeBriefFeedbackModal();
            await forceRefreshBriefing();
            toast('Correction request saved and a fresh brief has been queued.', 'success');
        } else {
            currentBriefData.manual_edit_text = text;
            await logAiFeedback('brief', 'edit', {
                brief_id: window.currentBriefId,
                manual_edit: text,
                source: 'brief_feedback_modal'
            });
            renderBriefing(currentBriefData);
            closeBriefFeedbackModal();
            toast('Manual brief draft saved.', 'success');
        }
    } catch (err) {
        console.error(err);
        toast('Unable to save brief feedback.', 'error');
    } finally {
        submit.disabled = false;
        submit.style.opacity = '1';
    }
}

async function retryAiJob(jobId) {
    try {
        await fetch(`${API_BASE}/api/ai/jobs/${jobId}/retry`, { method: 'POST' });
        toast('AI job queued for retry', 'success');
        startAiJobPolling();
        await loadAiJobs();
    } catch (err) {
        console.error(err);
        toast('Retry failed', 'error');
    }
}

async function loadAiJobs() {
    if (!personId) return;
    const list = document.getElementById('ai-job-status-list');
    if (!list) return;

    try {
        const res = await fetch(`${API_BASE}/api/ai/jobs/person/${personId}`);
        const data = await res.json();
        const jobs = data.jobs || [];
        renderAiJobs(jobs);

        const active = hasActiveAiJobs(jobs);
        const snapshot = JSON.stringify(jobs.map(job => ({ id: job.job_id, status: job.status })));
        if (!active) {
            if (lastAiJobSnapshot && lastAiJobSnapshot !== snapshot) {
                await loadPersonQuiet();
                await loadBriefing();
            }
            stopAiJobPolling();
        } else {
            startAiJobPolling();
        }
        lastAiJobSnapshot = snapshot;
    } catch (err) {
        console.error('AI jobs failed to load:', err);
    }
}

function renderAiJobs(jobs) {
    const list = document.getElementById('ai-job-status-list');
    if (!list) return;

    if (!jobs.length) {
        list.innerHTML = '<div class="event-notes-card">No background AI jobs yet.</div>';
        return;
    }

    list.innerHTML = jobs.map((job) => `
        <div class="profile-event-row">
            <div>
                <div class="event-person-name">${jobTypeLabel(job)}</div>
                <div class="profile-event-meta">Status: ${job.status} · Attempts: ${job.attempts}/${job.max_attempts}</div>
                ${job.error_text ? `<div class="profile-event-meta" style="color:var(--accent-red);">${job.error_text}</div>` : ''}
            </div>
            <div class="profile-event-actions">
                <span class="event-status-pill event-status-${job.status === 'failed' ? 'target' : job.status === 'completed' ? 'confirmed' : 'invited'}">${job.status}</span>
                ${job.status === 'failed' ? `<button type="button" class="events-ghost-btn compact" onclick="retryAiJob('${job.job_id}')">Retry</button>` : ''}
            </div>
        </div>
    `).join('');
}

async function loadBriefing() {
    return loadRelationshipIntelligence({ forceRefresh: false });
}

async function forceRefreshBriefing() {
    return loadRelationshipIntelligence({ forceRefresh: true });
}

const STAGE1_BOX_ORDER = [
    { key: 'family_status', code: 'K1', title: 'Family Status' },
    { key: 'family_interests', code: 'K2', title: 'Family Interests' },
    { key: 'personal_interests', code: 'K3', title: 'Personal Interests' },
    { key: 'business_understanding', code: 'K4', title: 'Business Understanding' },
    { key: 'challenges_demands', code: 'K5', title: 'Challenges and Demands' },
    { key: 'recruitment_signals', code: 'K6', title: 'Recruitment Signals' },
    { key: 'market_intelligence', code: 'K7', title: 'Market Intelligence' },
    { key: 'taylor_sterling_positioning', code: 'K8', title: 'Taylor Sterling Positioning' },
    { key: 'obe_interest', code: 'K9', title: 'OBE Interest' },
    { key: 'action_follow_up', code: 'K10', title: 'Action / Follow-Up' },
    { key: 'relationship_signal', code: 'K11', title: 'Relationship Signal' },
];

const STAGE2_RELATIONSHIP_ORDER = ['S1', 'S2', 'S3', 'S4', 'S5', 'S6', 'S7', 'S8', 'S9'];
const STAGE2_OPPORTUNITY_ORDER = ['O1', 'O2', 'O3', 'O4', 'O5', 'O6', 'O7'];
const STAGE2_RELATIONSHIP_LABELS = {
    S1: 'S1 Introduction',
    S2: 'S2 Understand',
    S3: 'S3 Position',
    S4: 'S4 Nurture',
    S5: 'S5 Problem Identified',
    S6: 'S6 Active Discussion',
    S7: 'S7 Conversion Pending',
    S8: 'S8 Active Client',
    S9: 'S9 Active Nurture',
};
const STAGE2_OPPORTUNITY_LABELS = {
    O1: 'O1 Mature Problem Identified',
    O2: 'O2 Mature Active Discussion',
    O3: 'O3 Mature Conversion Pending',
    O4: 'O4 Mature Problem Identified',
    O5: 'O5 Mature Active Discussion',
    O6: 'O6 Mature Conversion Pending',
    O7: 'O7 Mature Active Client',
};

const LEGACY_OPPORTUNITY_STAGE_CODE_MAP = {
    S5: 'O1',
    S6: 'O2',
    S7: 'O3',
    S5M: 'O4',
    S6M: 'O5',
    S7M: 'O6',
    S8: 'O7',
    R1: 'O1',
    R2: 'O2',
    R3: 'O3',
    R4: 'O4',
    R5: 'O5',
    R6: 'O6',
    R7: 'O7',
};

function normalizeOpportunityStageCode(code) {
    const normalized = String(code || '').trim().toUpperCase();
    return LEGACY_OPPORTUNITY_STAGE_CODE_MAP[normalized] || normalized;
}

function safeHtml(value) {
    const text = String(value ?? '');
    if (typeof escapeHtml === 'function') return escapeHtml(text);
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function scoreTone(score) {
    const n = Number(score || 0);
    if (n >= 81) return 'rgba(16,185,129,0.26)';
    if (n >= 61) return 'rgba(59,130,246,0.24)';
    if (n >= 41) return 'rgba(34,211,238,0.2)';
    if (n >= 21) return 'rgba(245,158,11,0.2)';
    return 'rgba(239,68,68,0.2)';
}

function normalizeStage1Boxes(stage1) {
    const incoming = Array.isArray(stage1?.boxes) ? stage1.boxes : [];
    const byKey = Object.fromEntries(incoming.map((box) => [String(box.box_key || ''), box]));
    return STAGE1_BOX_ORDER.map((expected) => {
        const box = byKey[expected.key] || {};
        return {
            box_key: expected.key,
            code: String(box.code || expected.code || '').trim().toUpperCase(),
            box_title: box.box_title || expected.title,
            completeness_pct: Number(box.completeness_pct || 0),
            confidence_pct: Number(box.confidence_pct || 0),
            last_updated: String(box.last_updated || ''),
            what_is_known: Array.isArray(box.what_is_known) ? box.what_is_known : [],
            what_is_missing: Array.isArray(box.what_is_missing) ? box.what_is_missing : [],
        };
    });
}

function renderStageColumn(title, order, currentCode, labels, payloadStage) {
    const summary = String(payloadStage?.summary || '').trim();
    const confidence = Number(payloadStage?.confidence_pct || 0);
    const generatedRows = order.map((code) => {
        const active = code === currentCode;
        return `
            <div class="brief-subtopic-entry" style="${active ? 'border-color: rgba(34,211,238,0.55); background: rgba(34,211,238,0.13);' : ''}">
                <div class="brief-subtopic-entry-top">
                    <div class="brief-subtopic-entry-meta">${active ? 'Current' : 'Stage'}</div>
                </div>
                <div class="brief-subtopic-entry-text">
                    <strong>${active ? '[CURRENT] ' : ''}${safeHtml(labels[code] || code)}</strong>
                </div>
            </div>
        `;
    }).join('');

    return `
        <section class="brief-subtopic-card">
            <div class="brief-subtopic-title-row">
                <div class="brief-subtopic-title">${safeHtml(title)}</div>
            </div>
            <div class="brief-subtopic-body">
                ${generatedRows || '<div class="brief-subtopic-empty">No stage retained yet.</div>'}
            </div>
            ${summary ? `<div class="brief-subtopic-entry-evidence" style="padding:0.2rem 0.15rem 0 0.15rem;"><strong>Current read:</strong> ${safeHtml(summary)}${confidence ? ` (${confidence}% confidence)` : ''}</div>` : ''}
        </section>
    `;
}

function renderStage2(stage2) {
    const relationshipStage = stage2?.relationship_stage || {};
    const opportunityStage = stage2?.opportunity_stage || {};
    const relationshipCode = String(relationshipStage.code || '');
    const opportunityCode = normalizeOpportunityStageCode(opportunityStage.code || '');

    return `
        <div class="event-notes-card brief-quick-card">
            <div class="brief-summary-head">
                <div class="brief-summary-copy">
                    <div class="brief-summary-label">Stages</div>
                    <div class="brief-summary-subtitle">Relationship and opportunity flow side by side.</div>
                </div>
                <div class="brief-summary-meta">
                    <span class="brief-generation-badge is-fresh">Stage 2</span>
                </div>
            </div>
            <div class="brief-subtopic-matrix" style="display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:0.85rem;">
                ${renderStageColumn('Relationship Stage', STAGE2_RELATIONSHIP_ORDER, relationshipCode, STAGE2_RELATIONSHIP_LABELS, relationshipStage)}
                ${renderStageColumn('Opportunity Stage', STAGE2_OPPORTUNITY_ORDER, opportunityCode, STAGE2_OPPORTUNITY_LABELS, opportunityStage)}
            </div>
        </div>
    `;
}

function renderScrollableBucketList(items, emptyMessage, className) {
    const list = Array.isArray(items) ? items.filter((item) => String(item || '').trim()) : [];
    if (!list.length) {
        return `<div class="${className}">${safeHtml(emptyMessage)}</div>`;
    }
    return `
        <div class="${className}">
            ${list.map((item) => `<div class="brief-bucket-item">${safeHtml(item)}</div>`).join('')}
        </div>
    `;
}

function renderStage1(stage1) {
    const boxes = normalizeStage1Boxes(stage1);
    return `
        <div class="event-notes-card brief-summary-card">
            <div class="brief-summary-head">
                <div class="brief-summary-copy">
                    <div class="brief-summary-label">Knowledge Buckets</div>
                    <div class="brief-summary-subtitle">Stage 1 completeness by approved bucket.</div>
                </div>
                <div class="brief-summary-meta">
                    <span class="brief-generation-badge is-fresh">Stage 1</span>
                </div>
            </div>
            <div class="brief-subtopic-matrix" style="display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:0.85rem;">
                ${boxes.map((box) => `
                    <section class="brief-subtopic-card" style="border-top:2px solid ${scoreTone(box.completeness_pct)};">
                        <div class="brief-subtopic-title-row">
                            <div class="brief-subtopic-title">${safeHtml(`${box.code ? `${box.code} ` : ''}${box.box_title}`)}</div>
                        </div>
                        <div class="brief-subtopic-entry-text">
                            <strong>${box.completeness_pct}%</strong> completeness
                            <span style="opacity:0.8;"> | ${box.confidence_pct}% confidence</span>
                        </div>
                        <div class="brief-subtopic-entry-meta" style="margin-top:0.35rem;">
                            Last updated: ${safeHtml(box.last_updated || 'Not set')}
                        </div>
                        <div class="brief-subtopic-entry-evidence" style="margin-top:0.55rem;">
                            <strong>Known:</strong>
                            ${renderScrollableBucketList(box.what_is_known, 'No retained evidence yet.', 'brief-bucket-scroll brief-bucket-scroll-known')}
                        </div>
                        <div class="brief-subtopic-entry-evidence">
                            <strong>Missing:</strong>
                            ${renderScrollableBucketList(box.what_is_missing, 'No explicit gap listed.', 'brief-bucket-scroll')}
                        </div>
                    </section>
                `).join('')}
            </div>
        </div>
    `;
}

function renderBriefing(payload) {
    const container = document.getElementById('briefing-content');
    if (!container) return;
    const forceRefresh = !!payload?.forceRefresh;
    const assetRevision = '20260321m';
    const existingFrame = container.querySelector('#lab-profile-embed');
    if (existingFrame && !forceRefresh) {
        try {
            const frameUrl = new URL(String(existingFrame.getAttribute('src') || ''), window.location.origin);
            if (String(frameUrl.searchParams.get('asset_rev') || '') === assetRevision) return;
        } catch (_error) {
            return;
        }
    }
    const profileId = String(personId || '').trim();
    if (!profileId) {
        container.innerHTML = '<p style="color:var(--text-secondary);">Lab profile is unavailable until a contact is selected.</p>';
        return;
    }
    const params = new URLSearchParams();
    params.set('embedded', '1');
    params.set('asset_rev', assetRevision);
    if (forceRefresh) params.set('refresh_ts', String(Date.now()));
    const src = `/network-lab/profile/${encodeURIComponent(profileId)}?${params.toString()}`;
    currentBriefData = { forceRefresh: false };
    window.currentBriefId = null;
    container.innerHTML = `
        <iframe
            id="lab-profile-embed"
            title="Lab Profile"
            src="${safeHtml(src)}"
            loading="lazy"
            scrolling="yes"
            style="width:100%; height:min(72vh, 760px); min-height:520px; border:1px solid rgba(255,255,255,0.12); border-radius:14px; background:rgba(9,16,29,0.7);"
        ></iframe>
    `;
}

async function loadRelationshipIntelligence({ forceRefresh = false } = {}) {
    const btn = document.getElementById('btn-brief-regen') || document.getElementById('regen-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Refreshing...';
        btn.style.opacity = '0.5';
    }
    const briefingContent = document.getElementById('briefing-content');
    if (!briefingContent) return;

    briefingContent.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; color:var(--text-secondary); font-size:0.9rem;">
            <div class="spinner" style="width:20px; height:20px; border-width:2px; margin:0;"></div>
            <span>Loading Lab Profile...</span>
        </div>
    `;

    try {
        renderBriefing({ forceRefresh });
    } catch (err) {
        console.error('Lab profile load failed:', err);
        briefingContent.innerHTML = '<p style="color:var(--text-secondary);">Lab profile is currently unavailable.</p>';
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = 'Reload';
            btn.style.opacity = '1';
        }
    }
}

async function generateBriefAudio() {
    if (typeof toast === 'function') {
        toast('Audio briefing is disabled. This panel now runs Stage 1 + Stage 2 only.', 'info');
    }
}

window.regenerateBrief = forceRefreshBriefing;
window.loadBriefing = loadBriefing;
window.generateBriefAudio = generateBriefAudio;

