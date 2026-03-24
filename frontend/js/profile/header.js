// Profile header rendering, taxonomy controls, and header editor

function deriveRelationshipTemperaturePerson(person) {
    const sourceDate = person?.last_success_at || person?.last_contact_datetime || person?.last_meeting_date || '';
    let lastSuccessAgeDays = Number(person?.last_success_age_days);
    if (!Number.isFinite(lastSuccessAgeDays) && sourceDate) {
        const parsed = new Date(String(sourceDate).replace(' ', 'T'));
        if (!Number.isNaN(parsed.getTime())) {
            lastSuccessAgeDays = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / (1000 * 60 * 60 * 24)));
        }
    }
    return {
        ...person,
        last_success_age_days: Number.isFinite(lastSuccessAgeDays) ? lastSuccessAgeDays : null,
        last_successful_contact_at: person?.last_success_at || person?.last_contact_datetime || person?.last_meeting_date || null,
    };
}

const PROFILE_ASSISTANT_PROMPT_KEY = 'crm.profile.assistantPrompt.v1';

function getNetworkScorePresentation(person) {
    const context = person?.network_score_context;
    if (!context) return null;

    const band = String(context.score_band || 'Monitor');
    const palette = {
        'Act Now': { accent: '#ef4444', soft: 'rgba(239, 68, 68, 0.18)' },
        Priority: { accent: '#f97316', soft: 'rgba(249, 115, 22, 0.18)' },
        Maintain: { accent: '#38bdf8', soft: 'rgba(56, 189, 248, 0.18)' },
        Monitor: { accent: '#94a3b8', soft: 'rgba(148, 163, 184, 0.18)' },
    };
    const tone = palette[band] || palette.Monitor;
    const summaryReasons = Array.isArray(context.score_reason_summary) ? context.score_reason_summary : [];
    const firstReason = summaryReasons.length ? String(summaryReasons[0]?.text || '').trim() : '';
    const details = [];
    if (Number.isFinite(Number(context.recency_days))) {
        details.push(`${context.recency_days}d since meaningful contact`);
    }
    details.push(context.has_future_cover ? 'Future cover in place' : 'No next step booked');
    if (Number(context.opportunity_readiness || 0) >= 60) {
        details.push('Live opportunity pressure');
    }
    return {
        accent: tone.accent,
        softAccent: tone.soft,
        stateLabel: band,
        headline: context.queue_reason || firstReason || 'Priority score is available for this relationship',
        detail: details.join(' | '),
        score: Number(context.network_health_score || 0),
        recommendation: firstReason || context.queue_reason || 'Review the live relationship signals behind this score.',
        kicker: 'Relationship Priority',
        metaLabel: 'Attention Score',
    };
}

function networkLabProfileHref(person) {
    const id = String(person?.person_id || '').trim();
    return id ? `/network-lab/profile/${encodeURIComponent(id)}` : '/network-lab';
}

function clampActionScore(value) {
    const score = Number(value);
    if (!Number.isFinite(score)) return 0;
    return Math.max(0, Math.min(100, Math.round(score)));
}

function parseProfileDate(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    const parsed = new Date(text.replace(' ', 'T'));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function daysSinceProfileDate(value) {
    const parsed = value instanceof Date ? value : parseProfileDate(value);
    if (!parsed) return null;
    return Math.max(0, Math.floor((Date.now() - parsed.getTime()) / (1000 * 60 * 60 * 24)));
}

function relationshipStageCodeFromPerson(person = {}) {
    const context = person?.network_score_context || {};
    return String(
        person?.relationship_stage_override
        || context?.relationship_stage_code
        || context?.relationship_stage
        || ''
    ).trim().toUpperCase();
}

function cadenceDaysForRelationshipStage(stageCode) {
    const code = String(stageCode || '').trim().toUpperCase();
    if (code === 'S1') return 30;
    if (code === 'S2') return 21;
    if (code === 'S3') return 14;
    if (code === 'S4') return 10;
    if (code === 'S5') return 7;
    if (code === 'S6') return 5;
    if (code === 'S7') return 4;
    if (code === 'S8' || code === 'S9') return 4;
    return 10;
}

function actionBandFromScore(score) {
    const normalized = clampActionScore(score);
    if (normalized >= 70) return { className: 'band-red', label: 'Needs Action' };
    if (normalized >= 40) return { className: 'band-green', label: 'In Motion' };
    return { className: 'band-blue', label: 'Stable' };
}

function isLegacyScoringDisabledContext(context = {}) {
    const scoreBand = String(context?.score_band || '').trim().toLowerCase();
    const queueReason = String(context?.queue_reason || '').trim().toLowerCase();
    return scoreBand === 'disabled' || queueReason.includes('legacy scoring disabled');
}

function parseTaskDueAt(task = {}) {
    const date = String(task?.due_date || '').trim();
    if (!date) return null;
    const time = String(task?.due_time || '').trim();
    const parsed = new Date(`${date}T${time || '23:59:59'}`);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function computeHeaderActionPriority(person = {}, briefing = {}) {
    const context = person?.network_score_context || {};
    const stageCode = relationshipStageCodeFromPerson(person);
    const stageLabel = String(context?.relationship_stage_label || '').trim();
    const cadenceDays = cadenceDaysForRelationshipStage(stageCode);
    const lastContactDays = Number.isFinite(Number(context?.recency_days))
        ? Math.max(0, Number(context.recency_days))
        : daysSinceProfileDate(person?.last_success_at || person?.last_contact_datetime || person?.last_meeting_date);
    const allTasks = Array.isArray(briefing?.open_loops) ? briefing.open_loops : [];
    const activeTasks = allTasks.filter((task) => {
        const status = String(task?.status || '').trim().toLowerCase();
        return status === 'open' || status === 'in_progress' || !status;
    });
    const now = new Date();
    const overdueTasks = activeTasks.filter((task) => {
        const due = parseTaskDueAt(task);
        return !!due && due.getTime() < now.getTime();
    });
    const contextActiveTaskCount = Number.isFinite(Number(context?.open_task_count))
        ? Math.max(0, Math.round(Number(context.open_task_count)))
        : null;
    const contextOverdueTaskCount = Number.isFinite(Number(context?.overdue_open_task_count))
        ? Math.max(0, Math.round(Number(context.overdue_open_task_count)))
        : null;
    const activeTaskCount = contextActiveTaskCount ?? activeTasks.length;
    const overdueTaskCount = Math.min(activeTaskCount, contextOverdueTaskCount ?? overdueTasks.length);
    const dueSoonTaskCount = Math.max(0, activeTaskCount - overdueTaskCount);
    const healthScore = clampActionScore(context?.network_health_score ?? person?.relationship_health_score ?? 55);
    const healthPressure = clampActionScore(100 - healthScore);
    const hasFutureCover = Boolean(context?.has_future_cover);
    const queueKey = String(context?.queue_key || '').trim().toLowerCase();
    const interactionCount = Number.isFinite(Number(context?.interaction_count))
        ? Math.max(0, Math.round(Number(context.interaction_count)))
        : 0;
    const rawRecencyDays = context?.recency_days;
    const recencyDays = (rawRecencyDays !== null && rawRecencyDays !== undefined && Number.isFinite(Number(rawRecencyDays)))
        ? Math.max(0, Number(rawRecencyDays))
        : null;
    const hasEvidence = Number.isFinite(recencyDays) || interactionCount > 0;
    const legacyDisabled = isLegacyScoringDisabledContext(context);
    const actionDefined = !!(
        context?.follow_up_confirmation_needed
        || String(context?.follow_up_confirmation_reason || '').trim()
        || String(context?.follow_up_confirmation_prompt || '').trim()
        || String(context?.primary_open_task_text || '').trim()
        || activeTaskCount > 0
    );
    const primaryTask = getPrimaryOpenTask(activeTasks);

    if (legacyDisabled || !hasEvidence) {
        const disabledReason = 'Scoring is disabled while the new chatbot-native intelligence model is being implemented.';
        const noEvidenceReason = 'No transcript or interaction evidence captured yet.';
        return {
            hasScore: false,
            score: null,
            band: { className: 'band-none', label: 'No Score' },
            stageCode,
            stageLabel,
            cadenceDays,
            lastContactDays: null,
            healthScore,
            activeTaskCount,
            overdueTaskCount,
            dueSoonTaskCount,
            primaryTask,
            reasonText: legacyDisabled ? disabledReason : noEvidenceReason,
        };
    }

    let contactUrgency = 82;
    if (lastContactDays !== null && lastContactDays !== undefined) {
        if (lastContactDays <= Math.floor(cadenceDays * 0.6)) contactUrgency = 16;
        else if (lastContactDays <= cadenceDays) contactUrgency = 34;
        else if (lastContactDays <= Math.ceil(cadenceDays * 1.5)) contactUrgency = 58;
        else if (lastContactDays <= cadenceDays * 2) contactUrgency = 76;
        else contactUrgency = 92;
    }

    let taskUrgency = 28;
    if (overdueTaskCount > 0) taskUrgency = Math.min(100, 70 + (overdueTaskCount * 12));
    else if (activeTaskCount > 0 && !hasFutureCover) taskUrgency = 46;
    else if (activeTaskCount > 0) taskUrgency = 28;
    else if (actionDefined) taskUrgency = 84;

    let actionUrgency = 30;
    if (actionDefined && activeTaskCount === 0) actionUrgency = 88;
    else if (actionDefined && overdueTaskCount > 0) actionUrgency = 78;
    else if (actionDefined && activeTaskCount > 0) actionUrgency = 42;
    else if (!hasFutureCover) actionUrgency = 62;

    let score = Math.round(
        (contactUrgency * 0.34)
        + (taskUrgency * 0.28)
        + (actionUrgency * 0.2)
        + (healthPressure * 0.18)
    );
    if (activeTaskCount > 0 && overdueTaskCount === 0 && Number.isFinite(lastContactDays) && lastContactDays <= cadenceDays) score -= 10;
    if (hasFutureCover && overdueTaskCount === 0) score -= 6;
    if (queueKey === 'act_now') score += 14;
    else if (queueKey === 'maintain') score += 2;
    else if (queueKey === 'preserve') score -= 8;
    else if (queueKey === 'monitor') score -= 14;
    score = clampActionScore(score);

    const reasonParts = [];
    if (overdueTaskCount > 0) reasonParts.push(`${overdueTaskCount} overdue task${overdueTaskCount === 1 ? '' : 's'}`);
    if (Number.isFinite(lastContactDays) && lastContactDays > cadenceDays) reasonParts.push(`contact gap ${lastContactDays}d (target ${cadenceDays}d)`);
    if (activeTaskCount === 0 && actionDefined) reasonParts.push('defined action with no scheduled task');
    if (!hasFutureCover) reasonParts.push('no dated next step booked');
    if (!reasonParts.length) reasonParts.push('Cadence and tasks are aligned for this relationship.');

    return {
        hasScore: true,
        score,
        band: actionBandFromScore(score),
        stageCode,
        stageLabel,
        cadenceDays,
        lastContactDays: Number.isFinite(lastContactDays) ? Number(lastContactDays) : null,
        healthScore,
        activeTaskCount,
        overdueTaskCount,
        dueSoonTaskCount,
        primaryTask,
        reasonText: reasonParts.join(' | '),
    };
}

function renderHeaderActionPriorityWidget(person = {}, briefing = {}, agendaHref = '/agenda') {
    const root = document.getElementById('profile-action-priority-widget');
    if (!root) return;
    const model = computeHeaderActionPriority(person, briefing);
    root.classList.remove('is-loading', 'band-blue', 'band-green', 'band-red', 'band-none');
    root.classList.add(model.band.className);

    const taskSummary = model.activeTaskCount
        ? `${model.activeTaskCount} active | ${model.overdueTaskCount} overdue | ${model.dueSoonTaskCount} due soon`
        : 'No active tasks';
    const contactSummary = model.lastContactDays === null
        ? `No contact date (target ${model.cadenceDays}d)`
        : `${model.lastContactDays}d since contact (target ${model.cadenceDays}d)`;
    const stageSummary = model.stageCode
        ? (model.stageLabel || model.stageCode)
        : 'Unknown';
    const nextTask = model.primaryTask
        ? `${String(model.primaryTask.task_text || 'Untitled task').trim()} (${formatTaskDistanceLabel(model.primaryTask)})`
        : 'No active task scheduled.';
    const barWidth = model.hasScore ? clampActionScore(model.score) : 0;
    const scoreText = model.hasScore ? `${model.score}%` : '--';

    root.innerHTML = `
        <div class="action-priority-head">
            <div class="action-priority-score-wrap">
                <div class="action-priority-kicker">Action Priority</div>
                <div class="action-priority-score">${scoreText}</div>
                <div class="action-priority-band">${escapeHtml(model.band.label)}</div>
            </div>
            <div class="action-priority-progress">
                <div class="action-priority-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${model.hasScore ? model.score : 0}">
                    <span style="width:${barWidth}%"></span>
                </div>
                <div class="action-priority-reason">${escapeHtml(model.reasonText)}</div>
            </div>
        </div>
        <div class="action-priority-meta-row">
            <span class="action-priority-chip">${escapeHtml(contactSummary)}</span>
            <span class="action-priority-chip">${escapeHtml(taskSummary)}</span>
            <span class="action-priority-chip">Stage ${escapeHtml(stageSummary)}</span>
            <span class="action-priority-chip">Health ${model.healthScore}%</span>
        </div>
        <div class="action-priority-next"><strong>Next task:</strong> ${escapeHtml(nextTask)}</div>
        <div class="action-priority-links">
            <a href="${escapeHtml(agendaHref)}">Open in Agenda</a>
        </div>
    `;
}

function renderRelationshipTemperature(person) {
    const api = window.RelationshipTemperature;
    const networkScore = getNetworkScorePresentation(person);
    if (!networkScore && !api) return;

    const enrichedPerson = deriveRelationshipTemperaturePerson(person);
    const temperature = networkScore || api.getTemperature(enrichedPerson);
    const relationshipTone = String(person?.contact_value || '').toLowerCase();
    const labHref = networkLabProfileHref(person);
    const hasLabProfileLink = !!String(person?.person_id || '').trim();

    const topTarget = document.getElementById('relationship-temperature-display');
    if (topTarget) {
        const cardInner = `
            <div class="panel health temperature-pill relationship-${escapeHtml(relationshipTone || 'cold')}" style="--temperature-accent:${temperature.accent}; --temperature-soft:${temperature.softAccent};">
                <div class="panel-kicker temperature-pill-kicker">${escapeHtml(temperature.kicker || 'Relationship Health')}</div>
                <div class="panel-head temperature-pill-head">
                    <div class="temperature-pill-copy">
                        <strong class="panel-title">${escapeHtml(temperature.stateLabel)}</strong>
                        <span class="panel-copy">${escapeHtml(temperature.headline || temperature.detail)}</span>
                    </div>
                    <div class="panel-score lg temperature-pill-score">
                        <strong>${temperature.score}%</strong>
                        <span>${escapeHtml(temperature.metaLabel || 'Score')}</span>
                    </div>
                </div>
                <div class="temperature-pill-meta panel-copy" id="relationship-temperature-meta">
                    <span class="temperature-inline-chip">${escapeHtml(temperature.detail)} | ${escapeHtml(temperature.recommendation)}</span>
                </div>
            </div>
        `;
        topTarget.innerHTML = hasLabProfileLink
            ? `<a class="temperature-pill-link" href="${escapeHtml(labHref)}" title="Open this relationship in Network Lab">${cardInner}<span class="temperature-pill-link-cta">Open in Network Lab</span></a>`
            : cardInner;
    }

    const healthCard = document.querySelector('.health-card');
    if (healthCard) {
        healthCard.style.setProperty('--temperature-accent', temperature.accent);
        healthCard.style.setProperty('--temperature-soft', temperature.softAccent);
        if (hasLabProfileLink) {
            healthCard.classList.add('is-network-score-link');
            healthCard.setAttribute('role', 'link');
            healthCard.setAttribute('tabindex', '0');
            healthCard.setAttribute('data-network-lab-href', labHref);
            healthCard.onclick = () => { window.location.href = labHref; };
            healthCard.onkeydown = (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    window.location.href = labHref;
                }
            };
        } else {
            healthCard.classList.remove('is-network-score-link');
            healthCard.removeAttribute('role');
            healthCard.removeAttribute('tabindex');
            healthCard.removeAttribute('data-network-lab-href');
            healthCard.onclick = null;
            healthCard.onkeydown = null;
        }
        const headerMarkup = `
            <div class="temperature-health-header">
                <div>
                    <div class="temperature-health-label">
                        <i class="fas fa-thermometer-half"></i> ${escapeHtml(temperature.kicker || 'Relationship Temperature')}
                    </div>
                    <div class="temperature-health-state">${escapeHtml(temperature.stateLabel)}</div>
                    <div class="temperature-health-meta">${escapeHtml(temperature.headline)}</div>
                </div>
                <div id="health-score" style="font-family:'Outfit'; font-weight:900; font-size:1.4rem;">${temperature.score}%</div>
            </div>
        `;
        const existingHeader = healthCard.querySelector('.temperature-health-header');
        if (existingHeader) {
            existingHeader.outerHTML = headerMarkup;
        } else {
            healthCard.insertAdjacentHTML('afterbegin', headerMarkup);
        }
    }

    const healthBar = document.getElementById('health-bar');
    const nextAction = document.getElementById('next-action');
    if (healthBar) healthBar.style.width = `${temperature.score}%`;
    if (nextAction) nextAction.textContent = `${temperature.detail}. ${temperature.recommendation}.`;
}

function getPrimaryOpenTask(tasks) {
    const list = Array.isArray(tasks) ? [...tasks] : [];
    const priorityRank = { high: 0, medium: 1, low: 2 };
    list.sort((a, b) => {
        const aDate = a?.due_date ? new Date(`${a.due_date}T${a.due_time || '00:00'}`) : null;
        const bDate = b?.due_date ? new Date(`${b.due_date}T${b.due_time || '00:00'}`) : null;
        if (aDate && bDate && aDate.getTime() !== bDate.getTime()) return aDate - bDate;
        if (aDate && !bDate) return -1;
        if (!aDate && bDate) return 1;
        const aRank = priorityRank[String(a?.priority || 'medium').toLowerCase()] ?? 1;
        const bRank = priorityRank[String(b?.priority || 'medium').toLowerCase()] ?? 1;
        return aRank - bRank;
    });
    return list[0] || null;
}

function formatTaskDistanceLabel(task) {
    if (!task?.due_date) return 'No date';
    const due = new Date(`${task.due_date}T${task.due_time || '00:00'}`);
    if (Number.isNaN(due.getTime())) return formatDate(task.due_date);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(due);
    target.setHours(0, 0, 0, 0);
    const diffDays = Math.round((target - today) / (1000 * 60 * 60 * 24));
    if (diffDays < 0) return `${Math.abs(diffDays)}d past`;
    if (diffDays === 0) return 'Today';
    return `${diffDays}d out`;
}

function buildTaskFeedbackPrompt(person, task) {
    if (!task) return '';
    const context = person?.network_score_context || {};
    const taskText = String(task.task_text || 'Untitled task').trim();
    const taskStatus = String(task.status || 'open').replace(/_/g, ' ').trim();
    const dueLabel = formatTaskDistanceLabel(task);
    const parts = [
        `Help me log the outcome for ${person?.full_name || 'this contact'}.`,
        `Task: ${taskText}.`,
        `Status: ${taskStatus}.`,
        `Timing: ${dueLabel}.`,
    ];

    if (context.queue_reason) {
        parts.push(`Attention reason: ${String(context.queue_reason).trim()}.`);
    }
    if (context.follow_up_confirmation_reason) {
        parts.push(`Follow-through watch: ${String(context.follow_up_confirmation_reason).trim()}.`);
    } else if (context.cover_reason) {
        parts.push(`Current cover: ${String(context.cover_reason).trim()}.`);
    }

    parts.push('Capture what happened, any commercial or relationship intelligence, what changed, and the next best next step.');
    return parts.join(' ');
}

function openCurrentTaskFeedbackPrompt() {
    const task = window.currentProfilePrimaryTask;
    const person = window.currentPersonData || {};
    if (!task) {
        if (typeof toast === 'function') {
            toast('No current task is available to update yet.', 'info');
        }
        return;
    }

    if (typeof openChat === 'function') {
        openChat();
    }

    const input = document.getElementById('chat-input');
    if (!input) {
        if (typeof toast === 'function') {
            toast('Profile assistant is not available on this page.', 'error');
        }
        return;
    }

    window.currentProfileAssistantContext = null;
    const existingContext = document.querySelector('.assistant-message.topic-resolution-context');
    if (existingContext) existingContext.remove();
    input.placeholder = 'Ask or tell me something...';
    input.value = buildTaskFeedbackPrompt(person, task);
    input.focus();
    if (typeof input.setSelectionRange === 'function') {
        const len = input.value.length;
        input.setSelectionRange(len, len);
    }
    if (typeof toast === 'function') {
        toast('Task follow-through loaded into the assistant.', 'success');
    }
}

window.openCurrentTaskFeedbackPrompt = openCurrentTaskFeedbackPrompt;

function clearProfileAssistantResolutionContext() {
    window.currentProfileAssistantContext = null;
    const existingContext = document.querySelector('.assistant-message.topic-resolution-context');
    if (existingContext) existingContext.remove();
    const input = document.getElementById('chat-input');
    if (input) {
        input.placeholder = 'Ask or tell me something...';
    }
}

window.clearProfileAssistantResolutionContext = clearProfileAssistantResolutionContext;

function buildAssistantContextIntro(payload = {}, person = {}) {
    const context = payload?.assistant_context || {};
    if (String(context.type || '') !== 'relationship_topic_resolution') {
        return '';
    }
    const name = String(person?.full_name || 'this contact').trim();
    const title = String(context.title || payload.topic_title || 'Relationship topic').trim();
    const status = String(context.tracking_status_label || context.status_label || '').trim();
    const stage = String(context.stage || '').trim();
    const whyItMatters = String(context.why_it_matters || '').trim();
    const currentRead = String(context.current_read || '').trim();
    const question = String(context.question || '').trim();
    const evidence = Array.isArray(context.evidence) ? context.evidence.filter(Boolean).slice(0, 2) : [];
    const evidenceDetails = Array.isArray(context.evidence_details) ? context.evidence_details.filter(Boolean).slice(0, 3) : [];

    const lines = [
        `<strong>Reviewing topic for ${escapeHtml(name)}:</strong> ${escapeHtml(title)}`,
        status || stage ? `${escapeHtml([status, stage].filter(Boolean).join(' | '))}` : '',
        currentRead && currentRead !== title ? `<strong>Current read:</strong> ${escapeHtml(currentRead)}` : '',
        whyItMatters ? `<strong>Why it matters:</strong> ${escapeHtml(whyItMatters)}` : '',
        question ? `<strong>Clarification:</strong> ${escapeHtml(question)}` : '',
        ...evidenceDetails.map((detail) => {
            const parts = [
                String(detail.channel || '').trim(),
                String(detail.date_label || '').trim(),
                String(detail.preview || '').trim(),
            ].filter(Boolean);
            return parts.length ? `<strong>Context:</strong> ${escapeHtml(parts.join(' | '))}` : '';
        }),
        evidence.length ? `<strong>Evidence:</strong> ${escapeHtml(evidence.join(' | '))}` : '',
        'Tell me what changed, whether this topic is still open or now resolved, and what the next step should be if there is one.',
    ].filter(Boolean);

    return lines.join('<br>');
}

function injectAssistantContextIntro(payload, person) {
    const intro = buildAssistantContextIntro(payload, person);
    if (!intro) return false;
    const history = document.getElementById('chat-history');
    if (!history) return false;
    const existing = history.querySelector('.assistant-message.topic-resolution-context');
    if (existing) existing.remove();
    const message = document.createElement('div');
    message.className = 'assistant-message topic-resolution-context';
    message.innerHTML = intro;
    history.appendChild(message);
    history.scrollTop = history.scrollHeight;
    return true;
}

function consumePendingProfileAssistantPrompt(person) {
    if (!person?.person_id) return;
    let payload = null;
    try {
        payload = JSON.parse(window.sessionStorage.getItem(PROFILE_ASSISTANT_PROMPT_KEY) || 'null');
    } catch (_error) {
        payload = null;
    }
    if (!payload) return;
    if (String(payload.person_id || '') !== String(person.person_id || '')) return;

    try {
        window.sessionStorage.removeItem(PROFILE_ASSISTANT_PROMPT_KEY);
    } catch (_error) {
        // ignore
    }

    const prompt = String(payload.prompt || '').trim();
    window.currentProfileAssistantContext = payload.assistant_context || null;
    if (!prompt && !window.currentProfileAssistantContext) return;

    const applyPrompt = () => {
        if (typeof openChat === 'function') {
            openChat();
        }
        const input = document.getElementById('chat-input');
        if (!input) return false;
        const hasTopicResolutionContext = String(payload?.assistant_context?.type || '') === 'relationship_topic_resolution';
        if (hasTopicResolutionContext) {
            injectAssistantContextIntro(payload, person);
            input.value = '';
            input.placeholder = `Add the latest detail for ${String(payload?.assistant_context?.title || 'this topic').trim()}...`;
        } else {
            input.value = prompt;
            input.placeholder = 'Ask or tell me something...';
        }
        input.focus();
        if (!hasTopicResolutionContext && typeof input.setSelectionRange === 'function') {
            const len = input.value.length;
            input.setSelectionRange(len, len);
        }
        if (typeof toast === 'function') {
            toast(`Topic review loaded into the assistant for ${person.full_name || 'this contact'}.`, 'success');
        }
        return true;
    };

    if (!applyPrompt()) {
        window.setTimeout(applyPrompt, 200);
    }
}

function renderCurrentTaskCard(briefing, agendaHref, person) {
    const target = document.getElementById('profile-current-task');
    if (!target) return;

    const task = getPrimaryOpenTask(briefing?.open_loops || []);
    window.currentProfilePrimaryTask = task
        ? {
            task_id: task.task_id || '',
            task_text: task.task_text || '',
            status: task.status || '',
            due_date: task.due_date || '',
            due_time: task.due_time || '',
            priority: task.priority || '',
        }
        : null;
    const context = person?.network_score_context || {};
    const followThroughLabel = context.follow_up_confirmation_needed ? 'Update Outcome' : 'Prompt Update';
    const showAddTask = !task;
    const actionMarkup = `
        <div class="profile-current-task-actions action-strip">
            ${task ? `<button type="button" class="profile-task-btn micro-btn is-follow-through" onclick="openCurrentTaskFeedbackPrompt()">${followThroughLabel}</button>` : ''}
            ${showAddTask ? `<button type="button" class="profile-task-btn micro-btn primary" onclick="openTaskModal()">Add Task</button>` : ''}
            <button type="button" class="profile-task-btn micro-btn" onclick="window.location.href='${agendaHref}'">Agenda</button>
        </div>
    `;

    if (!task) {
        target.innerHTML = `
            <div class="panel profile-current-task-card is-empty">
                <div class="profile-current-task-head">
                    <div class="profile-current-task-heading">
                        <div class="panel-kicker profile-current-task-kicker">Current Task</div>
                        <div class="profile-current-task-state">No open loop</div>
                    </div>
                    ${actionMarkup}
                </div>
                <div class="profile-current-task-body">
                    <div class="panel-title profile-current-task-title">No active task linked</div>
                    <div class="panel-copy profile-current-task-meta">Suggested next step: reconnect this week.</div>
                </div>
            </div>
        `;
        return;
    }

    const dueLabel = formatTaskDistanceLabel(task);
    const priorityLabel = String(task.priority || 'medium').toUpperCase();
    const watchReason = String(
        context.follow_up_confirmation_reason ||
        context.queue_reason ||
        context.cover_reason ||
        ''
    ).trim();
    target.innerHTML = `
        <div class="panel profile-current-task-card">
            <div class="profile-current-task-head">
                <div class="profile-current-task-heading">
                    <div class="panel-kicker profile-current-task-kicker">Current Task</div>
                    <div class="profile-current-task-state">${escapeHtml(priorityLabel)}</div>
                </div>
                ${actionMarkup}
            </div>
            <div class="profile-current-task-body">
                <div class="panel-title profile-current-task-title">${escapeHtml(task.task_text || 'Untitled task')}</div>
                <div class="panel-copy profile-current-task-meta">Due ${escapeHtml(dueLabel)}${task.status ? ` | ${escapeHtml(String(task.status).replace(/_/g, ' '))}` : ''}</div>
                ${watchReason ? `<div class="profile-current-task-watch">${escapeHtml(watchReason)}</div>` : ''}
            </div>
        </div>
    `;
}

function sanitizePhoneNumber(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const hasPlus = raw.startsWith('+');
    const digits = raw.replace(/\D+/g, '');
    if (!digits) return '';
    return hasPlus ? `+${digits}` : digits;
}

function phoneHref(value) {
    const sanitized = sanitizePhoneNumber(value);
    return sanitized ? `tel:${sanitized}` : '';
}

function whatsappHref(value) {
    const sanitized = sanitizePhoneNumber(value);
    if (!sanitized) return '';
    const digits = sanitized.startsWith('+') ? sanitized.slice(1) : sanitized;
    return digits ? `https://wa.me/${digits}` : '';
}

function mailtoHref(value) {
    const email = String(value || '').trim();
    return email ? `mailto:${encodeURIComponent(email)}` : '';
}

function resolveProfilePhotoSrc(photoUrl) {
    if (!photoUrl) return '';
    const normalizedPhotoUrl = String(photoUrl).replace('/static/uploads/', '/uploads/');
    return `${API_BASE}${normalizedPhotoUrl}`;
}

function actionButtonMarkup({ href = '', title, icon, extraClass = '', disabled = false, target = '', rel = '' }) {
    const classes = ['v1-act-btn'];
    if (extraClass) classes.push(extraClass);
    if (disabled) classes.push('is-disabled');
    const safeHref = href ? escapeHtml(href) : '#';
    const safeTitle = escapeHtml(title || '');
    const targetAttr = target ? ` target="${target}"` : '';
    const relAttr = rel ? ` rel="${rel}"` : '';
    const ariaDisabled = disabled ? ' aria-disabled="true" tabindex="-1"' : '';
    return `<a class="${classes.join(' ')}" href="${safeHref}" title="${safeTitle}"${targetAttr}${relAttr}${ariaDisabled}>${icon}</a>`;
}

function syncMobileProfileTopLayout() {
    const header = document.querySelector('.profile-header');
    const body = document.querySelector('.profile-header-body');
    const bottomStrip = document.querySelector('.header-bottom-strip');
    const taxGrid = document.querySelector('.profile-tax-grid');
    if (!header || !body || !bottomStrip) return;

    const isMobile = window.matchMedia('(max-width: 768px)').matches;
    if (isMobile) {
        if (bottomStrip.parentElement !== header) {
            header.appendChild(bottomStrip);
        }
        bottomStrip.classList.add('is-mobile-flow');
        return;
    }

    if (bottomStrip.parentElement !== body) {
        if (taxGrid && taxGrid.parentElement === body) {
            taxGrid.insertAdjacentElement('afterend', bottomStrip);
        } else {
            body.appendChild(bottomStrip);
        }
    }
    bottomStrip.classList.remove('is-mobile-flow');
}

function formatProfileTitle(person) {
    const rawTitle = String(person?.title_current || '').trim();
    const rawCompany = String(person?.company_name_raw || '').trim();
    const cleanTitle = rawTitle.replace(/\s*\n+\s*/g, ' ').replace(/\s{2,}/g, ' ').trim();
    const cleanCompany = rawCompany.replace(/\s{2,}/g, ' ').trim();

    if (cleanTitle && cleanCompany) {
        if (cleanTitle.toLowerCase().includes(cleanCompany.toLowerCase())) {
            return cleanTitle;
        }
        return `${cleanTitle} @ ${cleanCompany}`;
    }
    return cleanTitle || cleanCompany || 'No title';
}

function formatCategoryDisplay(value) {
    return String(value || '')
        .split(',')
        .map((entry) => String(entry || '').trim())
        .filter(Boolean)
        .map((entry) => {
            const upper = entry.toUpperCase();
            if (upper === 'OBE M') return 'OBE Member';
            if (upper === 'OBE T') return 'OBE Target';
            if (upper === 'TSA') return 'TS Advisory';
            return entry;
        })
        .join(', ');
}

function renderProfileNavigationControls(state) {
    const target = document.getElementById('profile-nav-controls');
    if (!target) return;

    const people = Array.isArray(state?.people) ? state.people : [];
    const index = Number.isInteger(state?.index) ? state.index : -1;
    const prev = index > 0 ? people[index - 1] : null;
    const next = index >= 0 && index < people.length - 1 ? people[index + 1] : null;
    const position = index >= 0 && people.length ? `${index + 1} / ${people.length}` : '';

    target.innerHTML = `
        <button type="button" class="profile-nav-btn" ${prev ? `onclick="navigateProfileByOffset(-1)"` : 'disabled'} aria-label="Last profile">
            <span class="profile-nav-arrow">←</span>
            <span class="profile-nav-text">${prev ? escapeHtml(prev.full_name || 'Last') : 'Last'}</span>
        </button>
        <div class="profile-nav-position">${escapeHtml(position)}</div>
        <button type="button" class="profile-nav-btn" ${next ? `onclick="navigateProfileByOffset(1)"` : 'disabled'} aria-label="Next profile">
            <span class="profile-nav-text">${next ? escapeHtml(next.full_name || 'Next') : 'Next'}</span>
            <span class="profile-nav-arrow">→</span>
        </button>
    `;
}

window.renderProfileNavigationControls = renderProfileNavigationControls;

function renderPerson(person, briefing) {
    // Expose person globally so the task modal can read person_id / full_name
    window.currentPersonData = person
    window._personPersonalData = person.personal_data || {};
    window.currentProfileRecentHistory = Array.isArray(briefing?.recent_history) ? briefing.recent_history : [];

    const universalTitle = document.querySelector('h1.universal-header');
    if (universalTitle) universalTitle.textContent = (person.full_name || '').toUpperCase();

    if (document.getElementById('profile-chat-title')) {
        document.getElementById('profile-chat-title').textContent = `Assistant for ${person.full_name}`;
    }

    const profileNameLabel = escapeHtml(person.full_name || 'Unnamed Contact');
    document.getElementById('profile-name').innerHTML = `${profileNameLabel} <button type="button" class="profile-inline-edit primary" onclick="editProfileHeader()" title="Edit profile">Edit Profile</button> <button type="button" class="profile-inline-edit danger" onclick="confirmDeleteProfile()" title="Delete profile">Delete Profile</button>`;
    document.getElementById('profile-title').textContent = formatProfileTitle(person);
    let employerLink = document.getElementById('profile-employer-link');
    if (!employerLink) {
        employerLink = document.createElement('div');
        employerLink.id = 'profile-employer-link';
        employerLink.style.marginTop = '0.35rem';
        const profileTitleNode = document.getElementById('profile-title');
        if (profileTitleNode && profileTitleNode.parentElement) {
            profileTitleNode.insertAdjacentElement('afterend', employerLink);
        }
    }
    const employerName = String(person.company_name_raw || '').trim();
    if (employerLink) {
        if (employerName) {
            const employerHref = typeof window.companyDirectoryHref === 'function'
                ? window.companyDirectoryHref(employerName)
                : `/companies/${encodeURIComponent(employerName.toLowerCase())}`;
            employerLink.innerHTML = `<a href="${escapeHtml(employerHref)}" style="font-size:0.82rem; color:var(--accent-blue); text-decoration:none;">Employer: ${escapeHtml(employerName)}</a>`;
            employerLink.style.display = '';
        } else {
            employerLink.innerHTML = '';
            employerLink.style.display = 'none';
        }
    }

    // Contact Info Row
    let contactRow = document.getElementById('contact-info-row');
    if (!contactRow) {
        contactRow = document.createElement('div');
        contactRow.id = 'contact-info-row';
        contactRow.className = 'contact-info-row contact-strip';
        const anchorNode = employerLink || document.getElementById('profile-title');
        anchorNode.insertAdjacentElement('afterend', contactRow);
    }

    const primaryEmailHref = mailtoHref(person.email_primary);
    const secondaryEmailHref = mailtoHref(person.email_secondary);
    const primaryPhoneHref = phoneHref(person.phone_primary);
    const secondaryPhoneHref = phoneHref(person.phone_secondary);
    const primaryWhatsappHref = whatsappHref(person.phone_primary);
    const linkedinHref = String(person.linkedin_url || '').trim();

    contactRow.innerHTML = `
                <div class="contact-info-item ${primaryEmailHref ? 'is-actionable' : ''}" ${primaryEmailHref ? `role="link" tabindex="0" onclick="window.location.href='${escapeHtml(primaryEmailHref)}'" onkeydown="if(event.key==='Enter' || event.key===' '){ event.preventDefault(); window.location.href='${escapeHtml(primaryEmailHref)}'; }"` : `onclick="editProfileHeader()"`}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                        <polyline points="22,6 12,13 2,6"></polyline>
                    </svg>
                    <span>${person.email_primary || ''}</span>
                    <span class="edit-info-btn" aria-hidden="true">✎</span>
                </div>
                ${person.email_secondary ? `
                <div class="contact-info-item ${secondaryEmailHref ? 'is-actionable' : ''}" ${secondaryEmailHref ? `role="link" tabindex="0" onclick="window.location.href='${escapeHtml(secondaryEmailHref)}'" onkeydown="if(event.key==='Enter' || event.key===' '){ event.preventDefault(); window.location.href='${escapeHtml(secondaryEmailHref)}'; }"` : `onclick="editProfileHeader()"`}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                        <polyline points="22,6 12,13 2,6"></polyline>
                    </svg>
                    <span>${person.email_secondary}</span>
                    <span class="edit-info-btn" aria-hidden="true">✎</span>
                </div>` : ''}
                <div class="contact-info-item ${primaryPhoneHref ? 'is-actionable' : ''}" ${primaryPhoneHref ? `role="link" tabindex="0" onclick="window.location.href='${escapeHtml(primaryPhoneHref)}'" onkeydown="if(event.key==='Enter' || event.key===' '){ event.preventDefault(); window.location.href='${escapeHtml(primaryPhoneHref)}'; }"` : `onclick="editProfileHeader()"`}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                    </svg>
                    <span>${person.phone_primary || ''}</span>
                    <svg style="margin-left: 6px;" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-green)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 1 1-7.6-11.7 8.38 8.38 0 0 1 3.8.9L21 3z"></path>
                    </svg>
                    ${primaryWhatsappHref ? `<a class="contact-inline-link" href="${escapeHtml(primaryWhatsappHref)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">WhatsApp</a>` : ''}
                    <span class="edit-info-btn" aria-hidden="true">✎</span>
                </div>
                ${person.phone_secondary ? `
                <div class="contact-info-item ${secondaryPhoneHref ? 'is-actionable' : ''}" ${secondaryPhoneHref ? `role="link" tabindex="0" onclick="window.location.href='${escapeHtml(secondaryPhoneHref)}'" onkeydown="if(event.key==='Enter' || event.key===' '){ event.preventDefault(); window.location.href='${escapeHtml(secondaryPhoneHref)}'; }"` : `onclick="editProfileHeader()"`}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                    </svg>
                    <span>${person.phone_secondary}</span>
                    <span class="edit-info-btn" aria-hidden="true">✎</span>
                </div>` : ''}
                ${linkedinHref ? `
                <div class="contact-info-item is-actionable" role="link" tabindex="0"
                    onclick="window.open('${escapeHtml(linkedinHref)}', '_blank', 'noopener')"
                    onkeydown="if(event.key==='Enter' || event.key===' '){ event.preventDefault(); window.open('${escapeHtml(linkedinHref)}', '_blank', 'noopener'); }">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle>
                    </svg>
                    <span>LinkedIn</span>
                    <span class="edit-info-btn" aria-hidden="true">↗</span>
                </div>` : ''}
            `;

    // Initials in photo OR Profile Image
    const photoEl = document.getElementById('profile-photo');
    const photoSrc = resolveProfilePhotoSrc(person.profile_photo_url);
    if (photoSrc) {
        const initials = getInitials(person.full_name);
        photoEl.innerHTML = `
                    <img src="${photoSrc}" 
                         alt="${person.full_name}" 
                         style="width:100%; height:100%; object-fit:cover; border-radius:20px;"
                         onerror="const container=this.parentElement; if(container){container.innerHTML='${initials}'; container.style.background='var(--bg-secondary)';}">`;
        photoEl.style.backgroundImage = 'none';
        photoEl.style.backgroundColor = 'transparent';
        photoEl.style.display = 'flex';
        photoEl.style.alignItems = 'center';
        photoEl.style.justifyContent = 'center';
    } else {
        photoEl.textContent = getInitials(person.full_name);
        photoEl.style.backgroundImage = 'none';
        photoEl.style.backgroundColor = 'var(--bg-secondary)';
        photoEl.innerHTML = getInitials(person.full_name);
    }

    if (window.AntigravityBackground) {
        window.AntigravityBackground.applyBackground({
            page: 'profile',
            profilePhotoUrl: photoSrc
        });
    }


    const agendaHref = (() => {
        const params = new URLSearchParams();
        params.set('person_id', person.person_id || '');
        if (person.full_name) params.set('contact_name', person.full_name);
        if (person.company_name_raw) params.set('employer', person.company_name_raw);
        return `/agenda?${params.toString()}`;
    })();
    const networkLabHref = networkLabProfileHref(person);
    const hasNetworkLabProfile = !!String(person?.person_id || '').trim();
    const openNetworkLabProfileLink = document.getElementById('open-network-lab-profile');
    if (openNetworkLabProfileLink) {
        if (hasNetworkLabProfile) {
            openNetworkLabProfileLink.setAttribute('href', networkLabHref);
            openNetworkLabProfileLink.removeAttribute('aria-disabled');
            openNetworkLabProfileLink.style.pointerEvents = '';
            openNetworkLabProfileLink.style.opacity = '';
        } else {
            openNetworkLabProfileLink.setAttribute('href', '/network-lab');
            openNetworkLabProfileLink.setAttribute('aria-disabled', 'true');
            openNetworkLabProfileLink.style.pointerEvents = 'none';
            openNetworkLabProfileLink.style.opacity = '0.6';
        }
    }

    renderCurrentTaskCard(briefing, agendaHref, person);
    renderHeaderActionPriorityWidget(person, briefing, agendaHref);
    consumePendingProfileAssistantPrompt(person);
    let mobileAttributes = document.getElementById('profile-mobile-attributes');
    if (!mobileAttributes) {
        mobileAttributes = document.createElement('div');
        mobileAttributes.id = 'profile-mobile-attributes';
        const grid = document.querySelector('.profile-command-grid');
        if (grid) {
            grid.appendChild(mobileAttributes);
        }
    }
    if (mobileAttributes) {
        const categoryLabel = formatCategoryDisplay(person.cat);
        const chips = [
            person.env ? `<span class="profile-mobile-attr-chip">${escapeHtml(person.env)}</span>` : '',
            person.disc ? `<span class="profile-mobile-attr-chip">${escapeHtml(person.disc)}</span>` : '',
            categoryLabel ? `<span class="profile-mobile-attr-chip">${escapeHtml(categoryLabel)}</span>` : '',
            person.contact_value ? `<span class="profile-mobile-attr-chip ${String(person.contact_value).toLowerCase() === 'hot' ? 'is-hot' : ''}">${escapeHtml(person.contact_value)}</span>` : ''
        ].filter(Boolean).join('');
        mobileAttributes.innerHTML = `
            <div class="panel profile-mobile-attributes-card">
                <div class="panel-kicker">Attributes</div>
                <div class="profile-mobile-attr-row">${chips || '<span class="profile-mobile-attr-empty">No attributes set</span>'}</div>
            </div>
        `;
    }

    // SIT-REP Pill (V1 Style)
    const nextMeetingDate = person.next_meeting_date || person.next_contact_due_date;
    const nextMeetingTopic = person.next_meeting_topic || 'Meeting / Review';
    const meetingTarget = document.getElementById('meeting-status-display');
    if (nextMeetingDate && meetingTarget) {
        const scheduledDate = new Date(String(nextMeetingDate).replace(' ', 'T'));
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const targetDate = new Date(scheduledDate);
        targetDate.setHours(0, 0, 0, 0);
        const diffDays = isNaN(targetDate.getTime()) ? null : Math.round((targetDate - today) / (1000 * 60 * 60 * 24));
        const statusText = person.next_meeting_date
            ? (diffDays !== null && diffDays < 0 ? 'PAST' : diffDays !== null && diffDays <= 7 ? 'SOON' : 'SCHEDULED')
            : (person.meeting_status === 'overdue' ? 'PAST' : person.meeting_status === 'soon' ? 'SOON' : 'ON TRACK');
        const distanceLabel = diffDays === null
            ? formatDate(nextMeetingDate)
            : diffDays < 0
                ? `${Math.abs(diffDays)}d past`
                : diffDays === 0
                    ? 'Today'
                    : `${diffDays}d out`;
        const statusClass = statusText.toLowerCase().replace(/\s+/g, '-');
        const pillTitle = person.next_meeting_date ? 'Scheduled Microsoft meeting and related agenda' : 'Open related tasks in Agenda';

        meetingTarget.innerHTML = `
                    <div class="meeting-inline-chip ${statusClass}" role="link" tabindex="0" title="${pillTitle}"
                        onclick="window.location.href='${agendaHref}'"
                        onkeydown="if(event.key==='Enter' || event.key===' '){ event.preventDefault(); window.location.href='${agendaHref}'; }"
                        >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line>
                        </svg>
                        <span class="meeting-inline-date">${escapeHtml(distanceLabel)}</span>
                        <span class="meeting-inline-sep">&middot;</span>
                        <span class="meeting-inline-topic">${escapeHtml(nextMeetingTopic)}</span>
                        <span class="meeting-inline-badge">${escapeHtml(statusText === 'SCHEDULED' ? 'BOOKED' : statusText)}</span>
                    </div>
                `;
    } else if (meetingTarget) {
        meetingTarget.innerHTML = '';
    }

    renderRelationshipTemperature(person);

    // Action Cluster (V1 Style)
    const iconActions = document.getElementById('header-icon-actions');
    if (iconActions) {
        iconActions.innerHTML = `
                    ${actionButtonMarkup({
                        href: primaryEmailHref,
                        title: person.email_primary ? 'Email' : 'No Email',
                        disabled: !primaryEmailHref,
                        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>`
                    })}
                    ${actionButtonMarkup({
                        href: primaryPhoneHref,
                        title: person.phone_primary ? 'Call' : 'No Phone',
                        disabled: !primaryPhoneHref,
                        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>`
                    })}
                    ${actionButtonMarkup({
                        href: primaryWhatsappHref,
                        title: person.phone_primary ? 'WhatsApp' : 'No WhatsApp',
                        disabled: !primaryWhatsappHref,
                        target: '_blank',
                        rel: 'noopener noreferrer',
                        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 1 1-7.6-11.7 8.38 8.38 0 0 1 3.8.9L21 3z"></path></svg>`
                    })}
                    <a class="v1-act-btn" href="${escapeHtml(agendaHref)}" title="Agenda Tasks">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2v4"></path><path d="M16 2v4"></path><rect x="3" y="4" width="18" height="18" rx="2"></rect><path d="M3 10h18"></path><path d="M8 14h3"></path><path d="M8 18h6"></path></svg>
                    </a>
                    ${actionButtonMarkup({
                        href: networkLabHref,
                        title: hasNetworkLabProfile ? 'Network Lab Profile' : 'Network Lab',
                        disabled: !hasNetworkLabProfile,
                        icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h6v6H4z"></path><path d="M14 4h6v6h-6z"></path><path d="M4 14h6v6H4z"></path><path d="M14 14h6v6h-6z"></path></svg>`
                    })}
                    <button type="button" class="v1-act-btn primary" onclick="openTaskModal()" title="Add Task">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                    </button>
                    ${person.linkedin_url ? `
                    <a class="v1-act-btn" href="${escapeHtml(person.linkedin_url)}" target="_blank" rel="noopener noreferrer" title="LinkedIn">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle>
                        </svg>
                    </a>` : `
                    <span class="v1-act-btn is-disabled" title="No LinkedIn URL" aria-disabled="true">
                         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle>
                        </svg>
                    </span>`}
                `;
    }
    if (typeof refreshM365HeaderState === 'function') {
        refreshM365HeaderState();
    }

    syncMobileProfileTopLayout();

    renderPersonalIntel(window._personPersonalData);
    if (typeof renderRelationshipLinks === 'function') {
        renderRelationshipLinks(briefing?.relationships || []);
    }
    // Career History
    renderCareerTimeline(Array.isArray(person.employment_history) ? person.employment_history : []);

    // Env Toggles Init
    renderEnvToggles(person.env);

    // Disc Toggles Init
    renderDiscToggles(person.disc || 'OTHR');

    // Cat Toggles Init
    renderCatToggles(person.cat || 'GEN');

    // Status Toggles Init
    renderStatusToggles(person.contact_value);

    // Briefing History & Tasks
    if (briefing && briefing.recent_history && Array.isArray(briefing.recent_history) && briefing.recent_history.length > 0) {
        renderInteractions(briefing.recent_history);
    } else {
        const iTimeline = document.getElementById('interactions-timeline');
        if (iTimeline) iTimeline.innerHTML = '<p style="color: var(--text-secondary);">No interactions recorded</p>';
    }

}

function triggerProfilePhotoUpload() {
    document.getElementById('profile-photo-input')?.click();
}

function openBackgroundSettings() {
    window.location.href = '/settings#sec-visual-theme';
}

async function handleProfilePhotoSelected(event) {
    const file = event?.target?.files?.[0];
    if (!file || !personId) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API_BASE}/api/people/${personId}/media`, {
            method: 'POST',
            body: formData
        });
        const payload = await response.json();
        if (!response.ok || payload.status !== 'success') {
            throw new Error(payload.detail || payload.message || 'Upload failed');
        }
        toast('Profile photo updated', 'success');
        await loadPersonQuiet();
    } catch (err) {
        console.error('Profile photo upload failed', err);
        toast(`Photo upload failed: ${err.message}`, 'error');
    } finally {
        if (event?.target) {
            event.target.value = '';
        }
    }
}


let activeTaxonomy = {};

async function fetchTaxonomy() {
    if (Object.keys(activeTaxonomy).length > 0) return;
    try {
        const res = await fetch(`${API_BASE}/api/taxonomy`);
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data.items || []);
        activeTaxonomy = list.reduce((acc, item) => {
            if (!acc[item.category_type]) acc[item.category_type] = [];
            acc[item.category_type].push(item);
            return acc;
        }, {});
        const relationshipStatuses = activeTaxonomy.contact_value || [];
        if (!relationshipStatuses.some((item) => String(item?.value || item?.label).toLowerCase() === 'frozen')) {
            relationshipStatuses.push({ value: 'Frozen', label: 'Frozen', color: '#94a3b8' });
        }
        activeTaxonomy.contact_value = relationshipStatuses;
        const categories = activeTaxonomy.cat || [];
        if (!categories.some((item) => String(item?.value || item?.label).toLowerCase() === 'tsa' || String(item?.value || item?.label).toLowerCase() === 'ts advisory')) {
            categories.push({ value: 'TSA', label: 'TS Advisory', color: '#e5e7eb' });
        }
        activeTaxonomy.cat = categories;
    } catch (err) {
        console.error("Failed to fetch taxonomy:", err);
        activeTaxonomy = {
            cat: [{ value: 'OBE M', label: 'OBE Member' }, { value: 'OBE T', label: 'OBE Target' }, { value: 'TGT', label: 'Client Target' }, { value: 'EXT', label: 'Existing Client' }, { value: 'HPC', label: 'Candidate' }, { value: 'TSA', label: 'TS Advisory' }, { value: 'GEN', label: 'General' }],
            env: [{ value: 'DEV-G', label: 'Gov Dev' }, { value: 'DEV-S', label: 'Semi-Gov Dev' }, { value: 'DEV-P', label: 'Private Dev' }, { value: 'CONS', label: 'Consultant' }, { value: 'MAIN', label: 'Main Contractor' }, { value: 'SUB', label: 'Sub Contractor' }, { value: 'MGMT', label: 'PMO' }],
            disc: [{ value: 'COMM', label: 'Commercial' }, { value: 'DELV', label: 'Delivery' }, { value: 'DSGN', label: 'Design' }, { value: 'CORP', label: 'Corporate' }, { value: 'SUPP', label: 'Support' }, { value: 'OTHR', label: 'Others' }],
            contact_value: [{ value: 'Hot', label: 'Hot' }, { value: 'Warm', label: 'Warm' }, { value: 'Cold', label: 'Cold' }, { value: 'Frozen', label: 'Frozen' }],
            engagement_status: [{ value: 'Active', label: 'Active' }, { value: 'Passive', label: 'Passive' }, { value: 'Dormant', label: 'Dormant' }]
        };
    }
}

async function setEnv(env) {
    await updatePersonField('env', env);
    isEditingEnv = false;
    loadPersonQuiet();
}

function toggleEnvEdit() {
    isEditingEnv = !isEditingEnv;
    renderEnvToggles(window.currentPersonData?.env);
}

// Removed redundant setEnv definition below

function normalizeTaxonomySelections(currentString, items, aliases = {}) {
    const rawValues = String(currentString || '')
        .split(',')
        .map(v => v.trim())
        .filter(Boolean);

    const normalized = [];
    rawValues.forEach(raw => {
        const lowerRaw = raw.toLowerCase();
        const matched = items.find(item =>
            item.value === raw ||
            item.label === raw ||
            item.value.toLowerCase() === lowerRaw ||
            item.label.toLowerCase() === lowerRaw
        );
        if (matched) {
            normalized.push(matched.value);
            return;
        }
        if (aliases[lowerRaw]) {
            normalized.push(aliases[lowerRaw]);
            return;
        }
        const fuzzy = items.find(item =>
            item.label.toLowerCase().includes(lowerRaw) ||
            lowerRaw.includes(item.label.toLowerCase()) ||
            item.value.toLowerCase().includes(lowerRaw) ||
            lowerRaw.includes(item.value.toLowerCase())
        );
        normalized.push(fuzzy ? fuzzy.value : raw);
    });

    return [...new Set(normalized)];
}

function renderEnvToggles(currentString) {
    const envs = activeTaxonomy['env'] || [];
    const container = document.getElementById('env-toggles');
    if (!container) return;

    const envAliases = { 'developer - governmental': 'Developer - Gov', 'developer - government': 'Developer - Gov', 'developer - gov': 'Developer - Gov', 'governmental': 'Developer - Gov' };
    const selectedArray = normalizeTaxonomySelections(currentString, envs, envAliases);

    if (isEditingEnv) {
        container.innerHTML = envs.map(e => {
            const isActive = selectedArray.includes(e.value);
            return `<button class="chip ${isActive ? 'active' : ''}" 
                            onclick="toggleSelectEnv('${e.value}', '${currentString || ''}')">${e.label}</button>`;
        }).join('');
    } else {
        if (selectedArray.length === 0) {
            container.innerHTML = `<span style="font-size:0.65rem; color:var(--text-muted); padding:2px 0;">None</span>`;
        } else {
            container.innerHTML = selectedArray.map(val => {
                const taxItem = envs.find(e => e.value === val) || envs.find(e => e.label === val);
                return `<div class="chip active">${taxItem ? taxItem.label : val}</div>`;
            }).join('');
        }
    }
}

async function toggleSelectEnv(val, currentString) {
    const envs = activeTaxonomy['env'] || [];
    const envAliases = { 'developer - governmental': 'Developer - Gov', 'developer - government': 'Developer - Gov', 'developer - gov': 'Developer - Gov', 'governmental': 'Developer - Gov' };
    let selectedArray = normalizeTaxonomySelections(currentString, envs, envAliases);
    if (selectedArray.includes(val)) {
        selectedArray = selectedArray.filter(v => v !== val);
    } else {
        selectedArray.push(val);
    }
    const newStr = selectedArray.join(', ');
    await updatePersonField('env', newStr);
    loadPersonQuiet();
}

function toggleDiscEdit() {
    isEditingDisc = !isEditingDisc;
    renderDiscToggles(window.currentPersonData?.disc);
}

function parseDiscSelections(currentString, discs) {
    const discAliases = {
        'other': 'OTHR',
        'others': 'OTHR',
        'pm': 'PM',
        'pmo': 'PM',
        'project management': 'PM',
        'project manager': 'PM'
    };
    const rawValues = String(currentString || '')
        .split(',')
        .map(d => d.trim())
        .filter(Boolean);

    const normalized = [];
    rawValues.forEach(raw => {
        const lowerRaw = raw.toLowerCase();
        const matched = discs.find(d =>
            d.value === raw ||
            d.label === raw ||
            String(d.value || '').toLowerCase() === lowerRaw ||
            String(d.label || '').toLowerCase() === lowerRaw
        );
        if (matched) {
            normalized.push(matched.value);
            return;
        }
        if (discAliases[lowerRaw]) {
            normalized.push(discAliases[lowerRaw]);
            return;
        }
        normalized.push(raw);
    });

    return [...new Set(normalized)];
}

function renderDiscToggles(currentString) {
    const discs = activeTaxonomy['disc'] || [];
    const container = document.getElementById('disc-toggles');
    if (!container) return;

    const defaultDisc = 'OTHR';
    const selectedArray = parseDiscSelections(currentString || defaultDisc, discs);
    const legacySelected = selectedArray.filter(val => !discs.some(d => d.value === val));
    const editingOptions = [
        ...discs,
        ...legacySelected.map(val => ({ value: val, label: val, legacy: true }))
    ];

    if (isEditingDisc) {
        container.innerHTML = editingOptions.map(d => {
            const isActive = selectedArray.includes(d.value);
            return `<button class="chip ${isActive ? 'active' : ''} ${d.legacy ? 'legacy-chip' : ''}" onclick="toggleSelectDisc('${escapeHtml(d.value)}', '${escapeHtml(currentString || defaultDisc)}')">${escapeHtml(d.label)}</button>`;
        }).join('');
    } else {
        container.innerHTML = selectedArray.map(val => {
            const taxItem = discs.find(d => d.value === val) || discs.find(d => d.label === val);
            return `<div class="chip active ${taxItem ? '' : 'legacy-chip'}">${escapeHtml(taxItem ? taxItem.label : val)}</div>`;
        }).join('');
    }
}

async function toggleSelectDisc(val, currentString) {
    const discs = activeTaxonomy['disc'] || [];
    const defaultDisc = 'OTHR';
    let selectedArray = parseDiscSelections(currentString || defaultDisc, discs);
    if (selectedArray.includes(val)) {
        if (selectedArray.length > 1) {
            selectedArray = selectedArray.filter(v => v !== val);
        } else if (val !== defaultDisc && discs.some(d => d.value === defaultDisc)) {
            selectedArray = [defaultDisc];
        } else {
            selectedArray = [];
        }
    } else {
        if (selectedArray.includes(defaultDisc)) {
            selectedArray = selectedArray.filter(v => v !== defaultDisc);
        }
        selectedArray.push(val);
    }
    const validValues = selectedArray.filter(selection =>
        discs.some(d => d.value === selection) || selection === 'PM'
    );
    const newStr = validValues.join(', ');
    await updatePersonField('disc', newStr);
    loadPersonQuiet();
}

function toggleCatEdit() {
    isEditingCat = !isEditingCat;
    loadPersonQuiet();
}

function renderCatToggles(currentCatsString) {
    const taxonomyCats = activeTaxonomy['cat'] || [];
    const cats = taxonomyCats.length > 0 ? taxonomyCats : [
        { value: 'OBE M', label: 'OBE M' },
        { value: 'OBE T', label: 'OBE T' },
        { value: 'EXT', label: 'EXT' },
        { value: 'TGT', label: 'TGT' },
        { value: 'HPC', label: 'HPC' },
        { value: 'TSA', label: 'TS Advisory' },
        { value: 'GEN', label: 'GEN' }
    ];

    const container = document.getElementById('cat-toggles');
    if (!container) return;

    const selectedArray = normalizeTaxonomySelections(
        currentCatsString || 'GEN',
        cats,
        {
            'ts advisory': 'TSA',
            'tsa': 'TSA',
        }
    );
    if (!selectedArray.length) selectedArray.push('GEN');

    if (isEditingCat) {
        container.innerHTML = cats.map(c => {
            const isActive = selectedArray.includes(c.value);
            return `<button class="chip ${isActive ? 'active' : ''}" onclick="toggleSelectCat('${c.value}', '${currentCatsString || 'GEN'}')">${c.label}</button>`;
        }).join('');
    } else {
        container.innerHTML = selectedArray.map(c => {
            const taxItem = cats.find(ct => ct.value === c) || cats.find(ct => ct.label === c);
            return `<div class="chip active">${taxItem ? taxItem.label : c}</div>`;
        }).join('');
    }
}

async function toggleSelectCat(cat, currentString) {
    const taxonomyCats = activeTaxonomy['cat'] || [];
    const cats = taxonomyCats.length > 0 ? taxonomyCats : [
        { value: 'OBE M', label: 'OBE M' },
        { value: 'OBE T', label: 'OBE T' },
        { value: 'EXT', label: 'EXT' },
        { value: 'TGT', label: 'TGT' },
        { value: 'HPC', label: 'HPC' },
        { value: 'TSA', label: 'TS Advisory' },
        { value: 'GEN', label: 'GEN' }
    ];
    let selectedArray = normalizeTaxonomySelections(
        currentString,
        cats,
        {
            'ts advisory': 'TSA',
            'tsa': 'TSA',
        }
    );
    if (!selectedArray.length) selectedArray = ['GEN'];

    if (selectedArray.includes(cat)) {
        // Remove if already selected (toggle off)
        if (selectedArray.length > 1) {
            selectedArray = selectedArray.filter(c => c !== cat);
        } else if (cat !== 'GEN') {
            selectedArray = ['GEN']; // Default back to GEN if everything removed
        }
    } else {
        // Add if not selected (toggle on)
        if (selectedArray.includes('GEN')) {
            selectedArray = selectedArray.filter(c => c !== 'GEN');
        }
        selectedArray.push(cat);
    }

    const newString = selectedArray.join(', ');
    await updatePersonField('cat', newString);
    loadPersonQuiet(); // Refresh to show active states
}



function toggleStatusEdit() {
    isEditingStatus = !isEditingStatus;
    renderStatusToggles(window.currentPersonData?.contact_value);
}

function renderStatusToggles(currentStatus) {
    const statuses = [
        { value: 'Hot', label: 'Hot', class: 'hot' },
        { value: 'Warm', label: 'Warm', class: 'warm' },
        { value: 'Cold', label: 'Cold', class: 'cold' },
        { value: 'Frozen', label: 'Frozen', class: 'frozen' }
    ];
    const container = document.getElementById('status-toggles');
    if (!container) return;

    const labelArea = document.getElementById('label-status');
    if (isEditingStatus) {
        container.innerHTML = statuses.map(s => {
            const isActive = currentStatus === s.value;
            return `<button class="chip ${isActive ? 'active' : ''} ${s.class}" onclick="setStatus('${s.value}')">${isActive ? 'Active: ' : ''}${s.label}</button>`;
        }).join('');
    } else {
        const s = statuses.find(x => x.value === (currentStatus || 'Cold'));
        container.innerHTML = `<div class="chip active ${s?.class || ''}">${currentStatus || 'Cold'}</div>`;
    }
}

async function setStatus(status) {
    await updatePersonField('contact_value', status);
    isEditingStatus = false;
    loadPersonQuiet();
}


function editProfileHeader() {
    const existing = document.getElementById('profile-edit-modal');
    if (existing) { existing.remove(); return; }

    const person = window.currentPersonData || {};
    
    // Split job title and company from rendered state if needed, but person data is better
    const titleVal = person.title_current || '';
    const companyVal = person.company_name_raw || '';
    const nameVal = person.full_name || '';
    const email1 = person.email_primary || '';
    const email2 = person.email_secondary || '';
    const phone1 = person.phone_primary || '';
    const phone2 = person.phone_secondary || '';
    const linkedin = person.linkedin_url || '';

    const modal = document.createElement('div');
    modal.id = 'profile-edit-modal';
    modal.style = `
                position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(255,255,255,0.15);
                backdrop-filter:none; border-radius:16px; padding:2rem;
                z-index:9999; min-width:400px; max-width:600px; width:90%;
                max-height:90vh; overflow-y:auto; box-shadow:0 24px 80px rgba(0,0,0,0.6);
            `;
    
    const fields = [
        { label: 'Full Name', key: 'full_name', val: nameVal },
        { label: 'Job Title', key: 'title_current', val: titleVal },
        { label: 'Company', key: 'company_name_raw', val: companyVal },
        { label: 'Primary Email', key: 'email_primary', val: email1 },
        { label: 'Secondary Email', key: 'email_secondary', val: email2 },
        { label: 'Primary Phone', key: 'phone_primary', val: phone1 },
        { label: 'Secondary Phone', key: 'phone_secondary', val: phone2 },
        { label: 'LinkedIn URL', key: 'linkedin_url', val: linkedin }
    ];

    modal.innerHTML = `
                <div style="font-weight:800; font-size:1rem; color:var(--accent-cyan); margin-bottom:1.25rem; display:flex; align-items:center; gap:8px;">
                    <i class="fas fa-edit"></i> Edit Profile Essentials
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem;">
                    ${fields.map(f => `
                        <div style="margin-bottom:0.75rem; grid-column: ${['full_name', 'linkedin_url'].includes(f.key) ? 'span 2' : 'span 1'};">
                            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:4px;">${f.label}</div>
                            <input id="edit-field-${f.key}" value="${f.val.replace(/"/g, '&quot;')}" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:white; padding:8px 12px; border-radius:8px; font-size:0.85rem; outline:none; box-sizing:border-box;" onfocus="this.style.borderColor='var(--accent-cyan)'" onblur="this.style.borderColor='rgba(255,255,255,0.15)'">
                        </div>`).join('')}
                </div>
                <div style="display:flex; gap:0.75rem; margin-top:1.5rem;">
                    <button onclick="saveProfileHeader()" style="flex:1; background:var(--accent-cyan); color:#0a0a1a; font-weight:800; padding:12px; border:none; border-radius:8px; cursor:pointer; font-size:0.9rem; text-transform:uppercase; letter-spacing:1px;">Save Changes</button>
                    <button onclick="document.getElementById('profile-edit-modal').remove()" style="flex:1; background:rgba(255,255,255,0.08); color:white; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; cursor:pointer; font-size:0.9rem;">Cancel</button>
                </div>
            `;
    document.body.appendChild(modal);
    document.getElementById('edit-field-full_name').focus();
}

async function saveProfileHeader() {
    const payload = {};
    const fields = ['full_name', 'title_current', 'company_name_raw', 'email_primary', 'email_secondary', 'phone_primary', 'phone_secondary', 'linkedin_url'];
    
    fields.forEach(k => {
        const el = document.getElementById(`edit-field-${k}`);
        if (el) {
            const val = el.value.trim();
            // Only update if value is different or to clear field
            if (val !== (window.currentPersonData[k] || '')) {
                payload[k] = val || null;
            }
        }
    });

    if (Object.keys(payload).length === 0) {
        document.getElementById('profile-edit-modal')?.remove();
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        document.getElementById('profile-edit-modal')?.remove();
        if (res.ok) {
            loadPersonQuiet();
            toast('Profile updated', 'success');
        } else {
            toast('Failed to save profile', 'error');
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

async function confirmDeleteProfile() {
    const person = window.currentPersonData || {};
    const targetName = String(person.full_name || 'this profile').trim() || 'this profile';
    const approved = window.confirm(`Delete "${targetName}"? This hides the profile and keeps historical data for audit.`);
    if (!approved) return;

    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'DELETE'
        });
        let payload = {};
        try {
            payload = await res.json();
        } catch (_err) {
            payload = {};
        }
        if (!res.ok || String(payload.status || '').toLowerCase() !== 'success') {
            throw new Error(payload.detail || payload.message || `Delete failed (${res.status})`);
        }
        toast('Profile deleted', 'success');
        window.setTimeout(() => {
            window.location.href = '/';
        }, 350);
    } catch (err) {
        toast(`Delete failed: ${err.message}`, 'error');
    }
}

// -- CAREER TIMELINE EDITING -------------------------------------------






