// Meeting brief, AI job status, audio, and propensity
let aiJobPollTimer = null;
let lastAiJobSnapshot = '';
window.currentBriefJobId = null;
window.currentBriefId = null;
let currentBriefData = null;

function hasActiveAiJobs(jobs) {
    return jobs.some(job => ['queued', 'running', 'retrying'].includes(job.status));
}

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
                loadPropensityData();
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
    const briefingContent = document.getElementById('briefing-content');
    briefingContent.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; color:var(--text-secondary); font-size:0.9rem;">
            <div class="spinner" style="width:20px; height:20px; border-width:2px; margin:0;"></div>
            <span>Checking briefing status...</span>
        </div>
    `;

    try {
        const briefingRes = await fetch(`${API_BASE}/api/intelligence/brief/${personId}`, {
            headers: { 'Accept': 'application/json' }
        });
        const data = await briefingRes.json();

        if (data.status === 'completed' && data.briefing) {
            window._briefingCached = data.cached || false;
            window.currentBriefJobId = null;
            window.currentBriefId = data.brief_id || (data.briefing && data.briefing.brief_id) || null;
            renderBriefing(data.briefing);
            return;
        }

        if (['queued', 'running', 'retrying', 'processing'].includes(data.status)) {
            window.currentBriefJobId = data.job_id;
            window.currentBriefId = null;
            briefingContent.innerHTML = `
                <div class="event-notes-card">
                    <strong>Briefing is processing in the background.</strong>
                    <div style="margin-top:0.5rem; color:var(--text-secondary);">You can keep using the CRM while AI prepares the brief.</div>
                </div>
            `;
            startAiJobPolling();
            loadAiJobs();
            return;
        }

        briefingContent.innerHTML = '<p style="color:var(--text-secondary);">Briefing currently unavailable.</p>';
    } catch (err) {
        console.error('Briefing load failed:', err);
        briefingContent.innerHTML = '<p style="color:var(--text-secondary);">Briefing currently unavailable.</p>';
    }
}

async function forceRefreshBriefing() {
    const btn = document.getElementById('btn-brief-regen') || document.getElementById('regen-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Queuing...';
        btn.style.opacity = '0.5';
    }

    document.getElementById('briefing-content').innerHTML = `
        <div class="event-notes-card">
            <strong>Queued briefing refresh.</strong>
            <div style="margin-top:0.5rem; color:var(--text-secondary);">The brief will update when background processing completes.</div>
        </div>`;

    try {
        const res = await fetch(`${API_BASE}/api/intelligence/brief/${personId}`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to queue briefing');
        const data = await res.json();
        window.currentBriefJobId = data.job_id;
        window.currentBriefId = null;
        startAiJobPolling();
        loadAiJobs();
    } catch (err) {
        console.error('Brief queue failed:', err);
        document.getElementById('briefing-content').innerHTML = '<p style="color:var(--text-secondary);">Briefing queue failed.</p>';
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = 'Regenerate';
            btn.style.opacity = '1';
        }
    }
}
function briefSection(content, title, iconClass, color, isFullWidth = false) {
    let displayContent = content;
    if (!content || content === 'No specific data recorded.' || content === 'Not available.') {
        displayContent = '<span style="opacity:0.4; font-style:italic; font-size:0.8rem;">Nothing specific recorded yet.</span>';
    }

    let html = '';
    if (Array.isArray(displayContent)) {
        html = '<ul style="margin:0; padding-left:0; list-style:none;">' +
            displayContent.map(b => `<li style="position:relative; padding-left:1.25rem; margin-bottom:0.5rem; color:#fff; font-size:0.875rem; line-height:1.6; opacity:0.9;">
                        <span style="position:absolute; left:0; color:${color}; font-weight:bold;">&rsaquo;</span> ${b}
                    </li>`).join('') +
            '</ul>';
    } else {
        html = `<p style="color:#fff; font-size:0.92rem; line-height:1.6; margin:0; font-weight:500; opacity:0.95;">${displayContent}</p>`;
    }

    return `
        <div style="grid-column: ${isFullWidth ? 'span 2' : 'span 1'};
                    padding: 1.25rem;
                    background: rgba(255,255,255,0.03);
                    border: 1px solid rgba(255,255,255,0.1);
                    border-top: 2px solid ${color};
                    border-radius: 12px;
                    transition: transform 0.2s ease;">
            <div style="font-size:0.65rem; text-transform:uppercase; letter-spacing:1.8px; color:${color}; font-weight:800; margin-bottom:1rem; display:flex; align-items:center; gap:0.5rem;">
                <i class="${iconClass}" style="font-size:0.9rem;"></i> ${title}
            </div>
            ${html}
        </div>`;
}

function renderBriefing(briefing) {
    const container = document.getElementById('briefing-content');
    if (!container) return;

    if (!briefing) {
        container.innerHTML = '<div style="padding:1rem; opacity:0.6; font-size:0.85rem;">No briefing generated yet.</div>';
        return;
    }

    const isCached = window._briefingCached === true;
    const refreshHTML = `
        <div style="display:flex; justify-content:flex-end; gap:8px; margin-bottom:1rem; align-items:center;">
            ${isCached ? '<span style="font-size:0.65rem; color:var(--accent-blue); opacity:0.7; font-weight:700; text-transform:uppercase; letter-spacing:1px;">Cached</span>' : '<span style="font-size:0.65rem; color:var(--accent-cyan); opacity:0.7; font-weight:700; text-transform:uppercase; letter-spacing:1px;">Fresh Generation</span>'}
        </div>
    `;

    currentBriefData = briefing;
    window.currentBriefId = briefing.brief_id || window.currentBriefId || null;
    const labelRecruitment = briefing.label_recruitment || 'Recruitment & Talent';
    const labelObe = briefing.label_obe || 'OBE Focus';

    container.innerHTML = refreshHTML + `
        <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.25rem;">
            ${briefSection(briefing.business_focus, 'Business Focus', 'fas fa-chart-line', '#3b82f6')}
            ${briefSection(briefing.recruitment_talent, labelRecruitment, 'fas fa-users-cog', '#fbbf24')}
            ${briefSection(briefing.personal_rapport, 'Personal Rapport', 'fas fa-heart', '#f472b6')}
            ${briefSection(briefing.obe_focus, labelObe, 'fas fa-star', '#a78bfa')}
            ${briefSection(briefing.strategic_hypotheses, 'Strategic Hypotheses', 'fas fa-brain', '#a78bfa', true)}
        </div>
        <div style="margin-top: 1.5rem; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.75rem;">
            <div style="font-size:0.6rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:1px;">
                Platinum Standard Strategic Brief
            </div>
        </div>
    `;

    if (briefing.voice) {
        const vSelect = document.getElementById('select-brief-voice');
        if (vSelect) vSelect.value = briefing.voice;
    }

    window.currentBriefAudioScript = briefing.audio_script || '';
}

function buildBriefAudioScript(b) {
    if (b && b.audio_script && b.audio_script !== 'Not available.') {
        return b.audio_script;
    }

    if (!b) return 'No briefing available.';
    const sections = [];
    if (b.personal_rapport) sections.push(`Personal Rapport: ${b.personal_rapport}`);
    if (b.business_focus) sections.push(`Business Focus: ${b.business_focus}`);
    if (b.recruitment_talent) sections.push(`Recruitment and Talent: ${b.recruitment_talent}`);
    if (b.obe_focus) sections.push(`OBE Focus: ${b.obe_focus}`);
    if (b.strategic_hypotheses) sections.push(`Strategic Hypotheses: ${b.strategic_hypotheses}`);
    return sections.join('\n\n');
}

async function generateBriefAudio() {
    if (!currentBriefData) {
        alert('Generate the brief first with Regenerate');
        return;
    }
    const btn = document.getElementById('btn-brief-listen');
    btn.textContent = 'Recording...';
    btn.disabled = true;
    try {
        const script = buildBriefAudioScript(currentBriefData);
        const voice = document.getElementById('select-brief-voice')?.value || 'shimmer';
        const res = await fetch(`${API_BASE}/api/intelligence/tts/${personId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: script, voice: voice })
        });
        const data = await res.json();
        if (data.audio_url) {
            const player = document.getElementById('brief-audio-player');
            player.src = data.audio_url;
            player.style.display = 'block';
            player.play();
            btn.textContent = 'Playing';
            player.onended = () => { btn.textContent = 'Listen'; btn.disabled = false; };
        } else {
            alert('Audio generation failed: ' + (data.detail || 'Unknown error'));
            btn.textContent = 'Listen';
            btn.disabled = false;
        }
    } catch (e) {
        alert('Error: ' + e.message);
        btn.textContent = 'Listen';
        btn.disabled = false;
    }
}

async function loadPropensityData() {
    try {
        const res = await fetch(`${API_BASE}/api/analytics/propensity/${personId}`);
        if (!res.ok) return;
        const data = await res.json();

        const healthScore = document.getElementById('health-score');
        const healthBar = document.getElementById('health-bar');
        const velocityScore = document.getElementById('velocity-score');
        const nextAction = document.getElementById('next-action');

        if (healthScore) healthScore.innerText = `${data.health || 0}%`;
        if (healthBar) healthBar.style.width = `${data.health || 0}%`;
        if (velocityScore) velocityScore.innerText = data.recent_hits_14d || 0;
        if (nextAction) nextAction.innerText = `AI Recommended: ${data.next_best_action}`;
    } catch (err) {
        console.error('Failed to load propensity:', err);
    }
}




