const LAB_API_BASE = window.API_BASE || '';
const PROFILE_ASSISTANT_PROMPT_KEY = 'crm.profile.assistantPrompt.v1';
let networkLabPersonId = null;
let networkLabOwners = [];
let networkLabProfile = null;
let networkStoryThreadSection = 'active';

function isoDateFromNow(daysAhead = 0) {
    const date = new Date();
    date.setDate(date.getDate() + daysAhead);
    return date.toISOString().slice(0, 10);
}

function setProfileStatus(message, tone = '') {
    const target = document.getElementById('network-lab-profile-status');
    if (!target) return;
    target.textContent = message;
    target.className = 'network-lab-status';
    if (tone) target.classList.add(`is-${tone}`);
}

function esc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeReason(reason) {
    if (typeof reason === 'string') {
        return { text: reason, evidence: 'inferred' };
    }
    return {
        text: String(reason?.text || ''),
        evidence: String(reason?.evidence || 'inferred'),
    };
}

function evidenceBadge(reason) {
    const item = normalizeReason(reason);
    const label = item.evidence === 'substantiated' ? 'Substantiated' : 'Inferred';
    return `<span class="network-evidence-badge ${item.evidence === 'substantiated' ? 'is-substantiated' : 'is-inferred'}">${label}</span>`;
}

function topicClass(topicType = '') {
    const value = String(topicType || 'relationship').toLowerCase();
    return `topic-${value}`;
}

function momentumClass(momentum = '') {
    const value = String(momentum || 'steady').toLowerCase();
    if (value.includes('positive') || value.includes('strong')) return 'is-positive';
    if (value.includes('negative') || value.includes('weak') || value.includes('stalled')) return 'is-negative';
    return 'is-steady';
}

function situationStatusClass(status = '') {
    const value = String(status || 'watching').toLowerCase();
    return `status-${value}`;
}

function humanCoverLabel(coverKind = '') {
    const value = String(coverKind || 'none');
    return {
        meeting: 'Booked meeting cover',
        task: 'Dated task cover',
        scheduled_touchpoint: 'Scheduled touchpoint',
        undated_task: 'Undated task only',
        none: 'No cover in place',
    }[value] || value;
}

function suggestOutcomeChannel(context = {}) {
    const coverKind = String(context.cover_kind || '').toLowerCase();
    const taskKind = String(context.primary_open_task_kind || '').toLowerCase();
    if (coverKind === 'meeting') return 'meeting';
    if (taskKind === 'meeting_arrangement') return 'call';
    if (taskKind === 'relationship_follow_up') return 'call';
    return 'note';
}

function focusInteractionCapture() {
    const text = document.getElementById('lab-interaction-text');
    if (!text) return;
    text.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => text.focus(), 250);
}

function openOperatorTools() {
    const details = document.getElementById('lab-operator-tools');
    if (!details) return;
    details.open = true;
}

function spotlightInteractionCapture() {
    const shell = document.getElementById('lab-interaction-capture-shell');
    if (!shell) return;
    shell.classList.remove('is-spotlit');
    void shell.offsetWidth;
    shell.classList.add('is-spotlit');
    shell.scrollIntoView({ behavior: 'smooth', block: 'start' });
    window.setTimeout(() => shell.classList.remove('is-spotlit'), 3200);
}

function prefillFollowUpOutcome() {
    const context = networkLabProfile?.queue_context || {};
    document.getElementById('lab-interaction-channel').value = suggestOutcomeChannel(context);
    document.getElementById('lab-interaction-direction').value = 'outbound';
    document.getElementById('lab-interaction-outcome').value = 'progressed';
    document.getElementById('lab-interaction-meaningful').value = 'true';
    document.getElementById('lab-interaction-response').value = 'true';
    document.getElementById('lab-interaction-follow-up').value = 'true';

    const reason = String(context.follow_up_confirmation_reason || 'Scheduled follow-up was completed.').trim();
    const taskLabel = String(context.primary_open_task_label || '').trim();
    const coverReason = String(context.cover_reason || '').trim();
    const summary = [
        reason,
        taskLabel ? `Task context: ${taskLabel}.` : '',
        coverReason ? `Recorded cover: ${coverReason}.` : '',
        'Outcome:',
        'Next step:',
    ].filter(Boolean).join('\n');
    document.getElementById('lab-interaction-text').value = summary;
    focusInteractionCapture();
    setProfileStatus('Outcome template loaded into Interaction Capture.', 'success');
}

function prefillQuickTask() {
    const context = networkLabProfile?.queue_context || {};
    const person = networkLabProfile?.person || {};
    const input = document.getElementById('lab-follow-through-task-text');
    const due = document.getElementById('lab-follow-through-task-due');
    if (!input || !due) return;
    const base = String(context.primary_open_task_label || '').trim();
    const name = String(person.full_name || 'contact').trim();
    input.value = base
        ? `Follow up on ${base.toLowerCase()} with ${name}`
        : `Follow up with ${name} and lock the next step`;
    due.value = isoDateFromNow(2);
    input.scrollIntoView({ behavior: 'smooth', block: 'center' });
    window.setTimeout(() => input.focus(), 250);
}

function assistantPayloadAttr(payload = {}) {
    try {
        return esc(encodeURIComponent(JSON.stringify(payload)));
    } catch (_error) {
        return '';
    }
}

function formatEvidenceDateLabel(value = '') {
    const text = String(value || '').trim();
    if (!text) return '';
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) {
        return text.slice(0, 10);
    }
    return parsed.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function topicResolutionEvidenceList(item = {}) {
    const evidence = [];
    for (const value of item.evidence || []) {
        if (String(value || '').trim() && !evidence.includes(String(value).trim())) {
            evidence.push(String(value).trim());
        }
    }
    for (const value of item.key_points || []) {
        if (String(value || '').trim() && !evidence.includes(String(value).trim())) {
            evidence.push(String(value).trim());
        }
    }
    for (const entry of item.supporting_entries || []) {
        for (const value of entry.evidence_snippets || []) {
            if (String(value || '').trim() && !evidence.includes(String(value).trim())) {
                evidence.push(String(value).trim());
            }
        }
    }
    return evidence.slice(0, 3);
}

function topicResolutionEvidenceDetails(item = {}) {
    const details = [];
    const pushDetail = (detail = {}) => {
        const preview = String(detail.preview || '').trim();
        if (!preview) return;
        const channel = String(detail.channel || 'Interaction').trim();
        const dateLabel = String(detail.date_label || '').trim();
        const dedupeKey = `${dateLabel}|${channel}|${preview.toLowerCase()}`;
        if (details.some((itemValue) => itemValue._key === dedupeKey)) return;
        details.push({
            date_label: dateLabel,
            channel,
            preview,
            _key: dedupeKey,
        });
    };

    for (const detail of item.evidence_details || []) {
        pushDetail(detail);
    }
    for (const entry of item.supporting_entries || []) {
        const preview = String((entry.evidence_snippets || [])[0] || entry.what_is_happening || '').trim();
        pushDetail({
            date_label: formatEvidenceDateLabel(entry.interaction_at),
            channel: entry.channel || 'Interaction',
            preview,
        });
    }
    return details.slice(0, 3).map(({ _key, ...detail }) => detail);
}

function renderTopicContextDetails(details = [], emptyText = 'No dated source context is attached yet.') {
    const items = Array.isArray(details) ? details.filter(Boolean).slice(0, 3) : [];
    if (!items.length) {
        return `<div class="network-lab-subtle">${esc(emptyText)}</div>`;
    }
    return items.map((detail) => {
        const label = [
            String(detail.channel || '').trim(),
            String(detail.date_label || '').trim(),
        ].filter(Boolean).join(' | ');
        return `
            <div class="network-context-detail">
                ${label ? `<div class="network-context-detail-meta">${esc(label)}</div>` : ''}
                <div class="network-context-detail-body">${esc(String(detail.preview || '').trim())}</div>
            </div>
        `;
    }).join('');
}

function entryContextDetails(entry = {}) {
    const snippets = Array.isArray(entry.evidence_snippets) ? entry.evidence_snippets.filter(Boolean) : [];
    const snippet = snippets.find((value) => String(value || '').trim()) || '';
    const preview = String(snippet || entry.what_is_happening || entry.full_evidence_text || '').trim();
    if (!preview) return [];
    return [{
        channel: entry.channel || 'Interaction',
        date_label: formatEvidenceDateLabel(entry.interaction_at),
        preview,
    }];
}

function clarificationContextDetails(item = {}) {
    const directDetails = Array.isArray(item.evidence_details) ? item.evidence_details.filter(Boolean) : [];
    if (directDetails.length) {
        return directDetails.slice(0, 3);
    }

    const fallback = [];
    for (const thread of item.supporting_threads || []) {
        const threadDetails = Array.isArray(thread.evidence_details) ? thread.evidence_details.filter(Boolean) : [];
        if (threadDetails.length) {
            for (const detail of threadDetails) {
                fallback.push({
                    channel: detail.channel || thread.source_person_name || 'Context',
                    date_label: detail.date_label || thread.window_label || '',
                    preview: detail.preview || '',
                });
            }
        } else {
            for (const preview of thread.evidence || []) {
                if (!String(preview || '').trim()) continue;
                fallback.push({
                    channel: thread.source_person_name || 'Context',
                    date_label: thread.window_label || '',
                    preview: String(preview).trim(),
                });
            }
        }
        if (fallback.length >= 3) break;
    }

    if (!fallback.length) {
        for (const preview of item.evidence || []) {
            if (!String(preview || '').trim()) continue;
            fallback.push({
                channel: (item.source_people || [])[0] || 'Context',
                date_label: '',
                preview: String(preview).trim(),
            });
            if (fallback.length >= 3) break;
        }
    }
    return fallback.slice(0, 3);
}

function scrollToStorylineContext(situationRecordId = '') {
    const value = String(situationRecordId || '').trim();
    if (!value) return;
    const target = document.getElementById(`storyline-situation-${value}`);
    if (!target) {
        setProfileStatus('No matching storyline card was found for this topic yet.', 'warning');
        return;
    }
    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
    target.classList.remove('is-spotlit');
    void target.offsetWidth;
    target.classList.add('is-spotlit');
    window.setTimeout(() => target.classList.remove('is-spotlit'), 2600);
}

function buildTopicResolutionPrompt(context = {}) {
    const personName = String(networkLabProfile?.person?.full_name || 'this contact').trim();
    const title = String(context.title || 'Relationship topic').trim();
    const status = String(context.tracking_status_label || context.status_label || '').trim();
    const stage = String(context.stage || '').trim();
    const whyItMatters = String(context.why_it_matters || '').trim();
    const currentRead = String(context.current_read || '').trim();
    const question = String(context.question || '').trim();
    const evidence = Array.isArray(context.evidence) ? context.evidence.filter(Boolean).slice(0, 2) : [];
    const evidenceDetails = Array.isArray(context.evidence_details) ? context.evidence_details.filter(Boolean).slice(0, 2) : [];
    return [
        `Review this relationship topic for ${personName}: ${title}.`,
        status || stage ? `Current state: ${[status, stage].filter(Boolean).join(' | ')}.` : '',
        currentRead && currentRead !== title ? `Current read: ${currentRead}.` : '',
        whyItMatters ? `Why it matters: ${whyItMatters}.` : '',
        question ? `Clarification needed: ${question}.` : '',
        ...evidenceDetails.map((detail) => {
            const parts = [
                String(detail.channel || '').trim(),
                String(detail.date_label || '').trim(),
                String(detail.preview || '').trim(),
            ].filter(Boolean);
            return parts.length ? `Detailed context: ${parts.join(' | ')}.` : '';
        }),
        evidence.length ? `Evidence: ${evidence.join(' | ')}.` : '',
        'Capture the latest truth, whether it is open, watching, stalled, or closed, and the next step if one remains.',
    ].filter(Boolean).join(' ');
}

function pilotTopicResolutionAllowed() {
    return Boolean(networkLabProfile?.is_pilot_profile);
}

function pilotTopicResolutionNotice() {
    const mode = String(networkLabProfile?.pilot_cohort_mode || 'recommended').trim().toLowerCase();
    if (mode === 'explicit') {
        return 'Topic review is pilot-only right now. This profile is outside the explicit pilot cohort.';
    }
    return 'Topic review is pilot-only right now. This profile is outside the current pilot cohort.';
}

function openTopicResolutionInAssistant(context = {}) {
    if (!pilotTopicResolutionAllowed()) {
        setProfileStatus(pilotTopicResolutionNotice());
        return;
    }
    const assistantContext = {
        type: 'relationship_topic_resolution',
        source: String(context.source || 'network_lab_topic_resolution'),
        situation_record_id: String(context.situation_record_id || '').trim(),
        situation_id: String(context.situation_id || '').trim(),
        title: String(context.title || '').trim(),
        topic_type: String(context.topic_type || '').trim(),
        topic_type_label: String(context.topic_type_label || '').trim(),
        current_read: String(context.current_read || '').trim(),
        why_it_matters: String(context.why_it_matters || '').trim(),
        tracking_status: String(context.tracking_status || context.status || '').trim(),
        tracking_status_label: String(context.tracking_status_label || context.status_label || '').trim(),
        stage: String(context.stage || '').trim(),
        momentum: String(context.momentum || '').trim(),
        recommended_action: String(context.recommended_action || '').trim(),
        resolution_note: String(context.resolution_note || '').trim(),
        question: String(context.question || '').trim(),
        evidence: Array.isArray(context.evidence) ? context.evidence.filter(Boolean).slice(0, 3) : [],
        evidence_details: Array.isArray(context.evidence_details) ? context.evidence_details.filter(Boolean).slice(0, 3) : [],
        source_people: Array.isArray(context.source_people) ? context.source_people.filter(Boolean).slice(0, 3) : [],
        channels: Array.isArray(context.channels) ? context.channels.filter(Boolean).slice(0, 4) : [],
    };
    const prompt = buildTopicResolutionPrompt(assistantContext);
    try {
        window.sessionStorage.setItem(PROFILE_ASSISTANT_PROMPT_KEY, JSON.stringify({
            person_id: networkLabPersonId,
            prompt,
            assistant_context: assistantContext.situation_record_id ? assistantContext : null,
            source: assistantContext.source,
            topic_title: assistantContext.title,
            created_at: new Date().toISOString(),
        }));
    } catch (_error) {
        // ignore storage issues and still navigate
    }
    window.location.href = `/person/${encodeURIComponent(networkLabPersonId)}?from=network-lab-topic#assistant`;
}

function openTopicResolutionInAssistantFromPayload(encodedPayload = '') {
    try {
        const payload = JSON.parse(decodeURIComponent(String(encodedPayload || '')));
        openTopicResolutionInAssistant(payload || {});
    } catch (_error) {
        openTopicResolutionInAssistant({});
    }
}

function topicResolutionActionMarkup(payload = {}, { label = 'Resolve In Assistant', secondary = false } = {}) {
    if (!payload?.situation_record_id) return '';
    if (!pilotTopicResolutionAllowed()) {
        return `<div class="network-lab-subtle">${esc(pilotTopicResolutionNotice())}</div>`;
    }
    const buttonClass = secondary ? 'network-lab-button secondary' : 'network-lab-button';
    return `
        <button
            class="${buttonClass}"
            type="button"
            onclick="openTopicResolutionInAssistantFromPayload('${assistantPayloadAttr(payload)}')"
        >${esc(label)}</button>
    `;
}

function prefillClarificationAnswer(index) {
    const prompts = networkLabProfile?.relationship_topics?.clarification_prompts || [];
    const item = prompts[index];
    if (!item) return;
    openTopicResolutionInAssistant({
        source: 'network_lab_clarification',
        situation_record_id: item.situation_record_id,
        situation_id: item.situation_id,
        title: String(item.title || item.topic_title || item.question || 'Relationship topic').trim(),
        topic_type: item.topic_type,
        topic_type_label: item.topic_type_label,
        current_read: item.current_read,
        why_it_matters: item.why_it_matters,
        status: item.status,
        status_label: item.status_label,
        question: item.question,
        recommended_action: item.recommended_action,
        evidence: item.evidence || [],
        evidence_details: item.evidence_details || [],
        source_people: item.source_people || [],
    });
}

async function createQuickFollowUpTask(event) {
    event.preventDefault();
    const taskText = document.getElementById('lab-follow-through-task-text')?.value.trim();
    const dueDate = document.getElementById('lab-follow-through-task-due')?.value || null;
    if (!taskText) {
        alert('Enter a follow-up task first.');
        return;
    }
    const payload = {
        person_id: networkLabPersonId,
        task_text: taskText,
        due_date: dueDate || null,
        priority: 'high',
    };
    const res = await fetch(`${LAB_API_BASE}/api/tasks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        alert('Failed to create follow-up task.');
        return;
    }
    setProfileStatus('Follow-up task created.', 'success');
    event.target.reset();
    await loadLabProfile();
}

function queryPersonId() {
    const pathParts = window.location.pathname.split('/');
    return pathParts[pathParts.length - 1] || new URLSearchParams(window.location.search).get('person_id');
}

function renderOwnerOptions(elementId, selectedValue = '') {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.innerHTML = networkLabOwners.map((owner) => `
        <option value="${esc(owner.full_name)}" ${String(owner.full_name) === String(selectedValue) ? 'selected' : ''}>${esc(owner.full_name)}</option>
    `).join('');
}

function renderOpportunityCards(targetId, items, idField) {
    const target = document.getElementById(targetId);
    target.innerHTML = (items || []).map((item) => `
        <div class="network-contact-card">
            <div style="font-weight:800;">${esc(item.opportunity_type || 'Opportunity')}</div>
            <div class="network-lab-subtle">${esc(item.stage || 'No stage')} | ${esc(item.status || 'open')}</div>
            <div class="network-chip-row">
                <span class="network-chip">${esc(item.value_band || 'No value band')}</span>
                <span class="network-chip warn">${esc(item.owner || 'No owner')}</span>
                <span class="network-chip">${esc(item.trigger_date || 'No trigger')}</span>
            </div>
            <div class="network-lab-subtle">${esc(item.notes || '')}</div>
            <div class="network-lab-subtle" style="margin-top:0.5rem;">${esc(item[idField] || '')}</div>
        </div>
    `).join('');
}

function renderSignalCards(targetId, items = []) {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!items.length) {
        const emptyMessage = targetId === 'lab-surfaced-intelligence'
            ? 'No surfaced intelligence is ready yet.'
            : 'No draft intelligence is waiting review right now.';
        target.innerHTML = `<div class="network-contact-card"><div class="network-lab-subtle">${esc(emptyMessage)}</div></div>`;
        return;
    }
    target.innerHTML = items.map((item) => `
        <div class="network-contact-card">
            <div class="network-chip-row">
                <span class="network-chip">${esc(item.primary_category || item.category || 'Signal')}</span>
                ${item.business_subtopic_label ? `<span class="network-chip warn">${esc(item.business_subtopic_label)}</span>` : ''}
                ${item.display_channel ? `<span class="network-chip">${esc(item.display_channel)}</span>` : ''}
            </div>
            <div style="font-weight:800;">${esc(item.signal_text || item.text || 'No signal text')}</div>
            <div class="network-lab-subtle" style="margin-top:0.5rem;">${esc(item.supporting_context || item.source_snippet || 'No supporting context')}</div>
        </div>
    `).join('');
}

function renderEvidenceCards(targetId, items = []) {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!items.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No evidence items yet.</div></div>';
        return;
    }
    target.innerHTML = items.map((item) => `
        <div class="network-contact-card">
            <div class="network-chip-row">
                <span class="network-chip">${esc(item.channel || 'Interaction')}</span>
                <span class="network-chip warn">${esc(item.interaction_at || '')}</span>
            </div>
            <div class="network-lab-subtle">${esc(item.summary || item.raw_text || 'No interaction text')}</div>
            <details class="network-evidence-detail">
                <summary>View Full Evidence</summary>
                <div class="network-evidence-body">${esc(item.raw_text || item.summary || 'No full evidence available').replace(/\n/g, '<br>')}</div>
            </details>
        </div>
    `).join('');
}

function renderInterpretedInteractions(items = []) {
    const target = document.getElementById('lab-interpreted-interactions');
    if (!target) return;
    if (!items.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No interpreted interactions yet.</div></div>';
        return;
    }
    target.innerHTML = items.map((item) => `
        <article class="network-timeline-item ${topicClass(item.market_intel_signals?.length ? 'market' : item.opportunity_signals?.length ? 'opportunity' : item.friction_signals?.length ? 'risk' : item.influence_signals?.length ? 'influence' : 'relationship')}">
            <div class="network-timeline-rail">
                <div class="network-timeline-date">${esc((item.interaction_at || '').slice(0, 10) || 'No date')}</div>
                <div class="network-timeline-dot"></div>
            </div>
            <div class="network-timeline-card">
                <div class="network-chip-row">
                    <span class="network-chip">${esc(item.display_channel || item.channel || 'Interaction')}</span>
                    <span class="network-chip">${esc(item.stage || 'Relationship Update')}</span>
                    <span class="network-chip network-momentum-chip ${momentumClass(item.momentum)}">${esc(item.momentum || 'steady')}</span>
                    <span class="network-chip">Confidence ${esc(item.confidence_score || 0)}</span>
                </div>
                <div class="network-storyline-headline">${esc(item.what_is_happening || 'No interpretation yet')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Why it matters:</strong> ${esc(item.why_it_matters || 'No interpretation yet')}</div>
                <div style="margin-top:0.65rem;">
                    <div class="network-story-section-note" style="margin-bottom:0.45rem;">Linked context</div>
                    ${renderTopicContextDetails(entryContextDetails(item), 'No linked source context yet.')}
                </div>
                <div class="network-intelligence-tag-grid">
                    ${(item.opportunity_signals || []).map((value) => `<span class="network-chip topic-opportunity">${esc(value)}</span>`).join('')}
                    ${(item.market_intel_signals || []).map((value) => `<span class="network-chip topic-market">${esc(value)}</span>`).join('')}
                    ${(item.relationship_signals || []).map((value) => `<span class="network-chip topic-relationship">${esc(value)}</span>`).join('')}
                    ${(item.friction_signals || []).map((value) => `<span class="network-chip topic-risk">${esc(value)}</span>`).join('')}
                    ${(item.influence_signals || []).map((value) => `<span class="network-chip topic-influence">${esc(value)}</span>`).join('')}
                </div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Recommended action:</strong> ${esc(item.recommended_action || 'No action suggested')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${esc((item.evidence_snippets || []).join(' | ') || 'No evidence snippets captured')}</div>
                <details class="network-evidence-detail">
                    <summary>View Full Evidence</summary>
                    <div class="network-evidence-body">${esc(item.full_evidence_text || 'No full evidence available').replace(/\n/g, '<br>')}</div>
                </details>
                <div class="network-lab-actions" style="margin-top:0.8rem;">
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretedMemory('${esc(item.interpretation_id)}', 'rapport')">Promote Rapport</button>
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretedMemory('${esc(item.interpretation_id)}', 'opportunity')">Promote Opportunity</button>
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretedMemory('${esc(item.interpretation_id)}', 'risk')">Promote Risk</button>
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretedMemory('${esc(item.interpretation_id)}', 'influence')">Promote Influence</button>
                    <button class="network-lab-button" type="button" onclick="promoteMarketIntel('${esc(item.interpretation_id)}')">Promote Market Intel</button>
                </div>
            </div>
        </article>
    `).join('');
}

function renderPromotedCards(targetId, items = [], accentClass = '') {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!items.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No promoted items yet.</div></div>';
        return;
    }
    target.innerHTML = items.map((item) => `
        <div class="network-contact-card">
            <div class="network-chip-row">
                <span class="network-chip ${accentClass}">${esc(item.memory_domain || item.topic || 'Promoted')}</span>
                <span class="network-chip warn">${esc(item.status || 'draft')}</span>
                <span class="network-chip">Confidence ${esc(item.confidence_score || 0)}</span>
            </div>
            <div style="font-weight:800;">${esc(item.memory_text || item.signal_text || 'No promoted text')}</div>
            <div class="network-lab-subtle" style="margin-top:0.45rem;">Importance ${esc(item.importance_score || 0)} | Updated ${esc(item.updated_at || '')}</div>
        </div>
    `).join('');
}

function renderSituationSupportingEntries(entries = []) {
    if (!entries.length) {
        return '<div class="network-lab-subtle">No supporting interactions were captured for this situation.</div>';
    }
    return entries.map((entry) => `
        <div class="network-situation-entry">
            <div class="network-situation-entry-meta">
                <span>${esc((entry.interaction_at || '').slice(0, 10) || 'No date')}</span>
                <span>${esc(entry.channel || 'Interaction')}</span>
                <span>${esc(entry.stage || 'Relationship Update')}</span>
            </div>
            <div class="network-situation-entry-headline">${esc(entry.what_is_happening || 'No interpretation yet')}</div>
            <div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Why it matters:</strong> ${esc(entry.why_it_matters || 'No explanation')}</div>
            <div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Evidence:</strong> ${esc((entry.evidence_snippets || []).join(' | ') || 'No evidence snippets captured')}</div>
            <div style="margin-top:0.65rem;">
                <div class="network-story-section-note" style="margin-bottom:0.45rem;">Linked context</div>
                ${renderTopicContextDetails(entryContextDetails(entry), 'No linked source context yet.')}
            </div>
            <details class="network-evidence-detail">
                <summary>View Full Evidence</summary>
                <div class="network-evidence-body">${esc(entry.full_evidence_text || 'No full evidence available').replace(/\n/g, '<br>')}</div>
            </details>
        </div>
    `).join('');
}

function renderStorylineGroups(groups = []) {
    const target = document.getElementById('lab-storyline-groups');
    if (!target) return;
    if (!groups.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No storyline has been built yet.</div></div>';
        return;
    }
    target.innerHTML = groups.map((group) => `
        <article class="network-timeline-item ${topicClass(group.topic_type)}" id="${group.situation_record_id ? `storyline-situation-${esc(group.situation_record_id)}` : ''}">
            <div class="network-timeline-rail">
                <div class="network-timeline-date">${esc(group.window_label || '')}</div>
                <div class="network-timeline-dot"></div>
            </div>
            <div class="network-timeline-card network-storyline-card ${topicClass(group.topic_type)}">
                <div class="network-inline-row network-storyline-top">
                    <div class="network-chip-row">
                        <span class="network-chip ${topicClass(group.topic_type)}">${esc(group.topic_type_label || 'Relationship')}</span>
                        <span class="network-chip network-storyline-id">${esc(group.situation_id || 'No ID')}</span>
                        <span class="network-chip network-situation-status ${situationStatusClass(group.tracking_status)}">${esc(group.tracking_status_label || 'Watching')}</span>
                        <span class="network-chip">${esc(group.stage || 'Relationship Update')}</span>
                        <span class="network-chip network-momentum-chip ${momentumClass(group.momentum)}">${esc(group.momentum || 'steady')}</span>
                    </div>
                    <div class="network-lab-subtle">${esc((group.channels || []).join(', ') || 'unknown')}</div>
                </div>
                <div class="network-storyline-headline">${esc(group.headline || group.topic || 'No storyline headline')}</div>
                <div class="network-lab-subtle network-storyline-timeline">${esc(group.timeline_summary || '')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Why it matters:</strong> ${esc(group.why_it_matters || 'No explanation')}</div>
                <div class="network-intelligence-tag-grid">
                    ${(group.key_points || []).map((value) => `<span class="network-chip ${topicClass(group.topic_type)}">${esc(value)}</span>`).join('')}
                </div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Entries:</strong> ${esc(group.entry_count || 0)}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Recommended action:</strong> ${esc(group.recommended_action || 'No action suggested')}</div>
                <div style="margin-top:0.75rem;">
                    <div class="network-story-section-note" style="margin-bottom:0.45rem;">Linked context</div>
                    ${renderTopicContextDetails(topicResolutionEvidenceDetails(group), 'No linked source context yet.')}
                </div>
                ${group.recent_events?.length ? `<div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Recent state change:</strong> ${esc(group.recent_events[0].summary || 'Tracked update')}</div>` : ''}
                ${group.situation_record_id ? `
                    <div class="network-lab-actions" style="margin-top:0.8rem;">
                        ${topicResolutionActionMarkup({
                            source: 'network_lab_storyline_group',
                            situation_record_id: group.situation_record_id,
                            situation_id: group.situation_id,
                            title: group.headline || group.topic || 'Relationship topic',
                            topic_type: group.topic_type,
                            topic_type_label: group.topic_type_label,
                            current_read: group.headline || group.topic || '',
                            why_it_matters: group.why_it_matters || '',
                            tracking_status: group.tracking_status,
                            tracking_status_label: group.tracking_status_label,
                            stage: group.stage,
                            momentum: group.momentum,
                            recommended_action: group.recommended_action || '',
                            resolution_note: group.resolution_note || '',
                            evidence: topicResolutionEvidenceList(group),
                            evidence_details: topicResolutionEvidenceDetails(group),
                            channels: group.channels || [],
                        })}
                    </div>
                ` : ''}
                <details class="network-story-situation-detail">
                    <summary>Show supporting interactions (${esc(group.entry_count || 0)})</summary>
                    <div class="network-story-section-note">These interpreted interactions are the evidence trail that built this situation.</div>
                    <div class="network-situation-entry-list">
                        ${renderSituationSupportingEntries(group.supporting_entries || [])}
                    </div>
                </details>
            </div>
        </article>
    `).join('');
}

function renderPrepList(targetId, items = [], emptyMessage) {
    const target = document.getElementById(targetId);
    if (!target) return;
    const values = (items || []).filter(Boolean);
    if (!values.length) {
        target.innerHTML = `<li>${esc(emptyMessage)}</li>`;
        return;
    }
    target.innerHTML = values.map((item) => `<li>${esc(item)}</li>`).join('');
}

function storyThreadSectionMeta(sectionKey = '') {
    const key = String(sectionKey || '').toLowerCase();
    return {
        family: { label: 'Family', className: 'section-family' },
        interests_life: { label: 'Interests & Life', className: 'section-interests' },
        active: { label: 'Active', className: 'section-active' },
        market_business: { label: 'Market & Business', className: 'section-market' },
        track_record: { label: 'Track Record', className: 'section-track' },
    }[key] || { label: 'Story', className: 'section-generic' };
}

function setStoryThreadSection(sectionKey) {
    networkStoryThreadSection = String(sectionKey || 'active');
    renderRelationshipStoryThread(networkLabProfile?.story_thread || {});
}

function renderRelationshipStoryThread(storyThread = {}) {
    const masterTarget = document.getElementById('lab-story-thread-master');
    const sectionTarget = document.getElementById('lab-story-thread-sections');
    const detailTarget = document.getElementById('lab-story-thread-detail');
    if (!masterTarget || !sectionTarget || !detailTarget) return;

    const masterThread = Array.isArray(storyThread.master_thread) ? storyThread.master_thread.filter(Boolean) : [];
    const sections = Array.isArray(storyThread.sections) ? storyThread.sections.filter(Boolean) : [];
    const availableSections = sections.filter((section) => Array.isArray(section.threads) && section.threads.length);
    const validSectionKeys = new Set(availableSections.map((section) => String(section.key || '')));
    if (!validSectionKeys.has(networkStoryThreadSection)) {
        networkStoryThreadSection = validSectionKeys.has('active')
            ? 'active'
            : (availableSections[0]?.key || 'family');
    }

    if (!masterThread.length) {
        masterTarget.innerHTML = '<div class="network-lab-subtle">No master story thread is ready yet.</div>';
    } else {
        masterTarget.innerHTML = `
            <div class="network-story-thread-list">
                ${masterThread.map((entry) => {
                    const meta = storyThreadSectionMeta(entry.section_key);
                    return `
                        <article class="network-story-thread-entry ${meta.className}">
                            <div class="network-story-thread-entry-head">
                                <span class="network-story-thread-pill ${meta.className}">${esc(meta.label)}</span>
                                ${entry.date_label ? `<span class="network-chip">${esc(entry.date_label)}</span>` : ''}
                                ${entry.channel ? `<span class="network-chip">${esc(entry.channel)}</span>` : ''}
                            </div>
                            <div class="network-story-thread-entry-text">${esc(entry.text || 'Story point')}</div>
                        </article>
                    `;
                }).join('')}
            </div>
        `;
    }

    sectionTarget.innerHTML = `
        <div class="network-story-thread-button-row">
            ${sections.map((section) => {
                const meta = storyThreadSectionMeta(section.key);
                const threadCount = Array.isArray(section.threads) ? section.threads.length : 0;
                const isActive = String(section.key || '') === networkStoryThreadSection;
                return `
                    <button
                        type="button"
                        class="network-story-thread-button ${meta.className} ${isActive ? 'is-active' : ''}"
                        onclick="setStoryThreadSection('${esc(section.key || '')}')"
                    >
                        ${esc(meta.label)} ${threadCount ? `<span class="network-story-thread-button-count">${esc(threadCount)}</span>` : ''}
                    </button>
                `;
            }).join('')}
        </div>
    `;

    const activeSection = sections.find((section) => String(section.key || '') === networkStoryThreadSection) || sections[0];
    const activeMeta = storyThreadSectionMeta(activeSection?.key);
    const threads = Array.isArray(activeSection?.threads) ? activeSection.threads.filter(Boolean) : [];
    if (!threads.length) {
        detailTarget.innerHTML = `<div class="network-lab-subtle">No ${esc(activeMeta.label.toLowerCase())} threads are ready yet.</div>`;
        return;
    }
    detailTarget.innerHTML = `
        <div class="network-story-thread-detail-head">
            <div class="network-story-thread-pill ${activeMeta.className}">${esc(activeMeta.label)}</div>
            <div class="network-lab-subtle">Open the threads below for the deeper story inside this lane.</div>
        </div>
        <div class="network-story-thread-detail-grid">
            ${threads.map((thread) => `
                <article class="network-topic-ledger-item">
                    <div class="network-storyline-headline">${esc(thread.title || activeMeta.label)}</div>
                    ${thread.date_window ? `<div class="network-lab-subtle" style="margin-top:0.35rem;">${esc(thread.date_window)}</div>` : ''}
                    <ul class="network-prep-list network-story-thread-points">
                        ${(thread.points || []).map((point) => `<li>${esc(point)}</li>`).join('')}
                    </ul>
                    ${(thread.evidence || []).length ? `<div class="network-lab-subtle network-story-thread-evidence"><strong>Evidence:</strong> ${esc((thread.evidence || []).join(' | '))}</div>` : ''}
                </article>
            `).join('')}
        </div>
    `;
}

function renderRelationshipStory(story = {}) {
    const summary = document.getElementById('lab-relationship-story-summary');
    if (summary) {
        summary.textContent = story.summary || 'No retained relationship story is ready yet.';
    }

    const renderStorySection = (targetId, section = {}, emptyMessage) => {
        const target = document.getElementById(targetId);
        if (!target) return;
        const items = Array.isArray(section.items) ? section.items.filter(Boolean) : [];
        const groups = Array.isArray(section.groups) ? section.groups.filter(Boolean) : [];
        const renderStoryItems = (storyItems = []) => `
            <ul class="network-prep-list network-story-bullet-list">
                ${storyItems.map((item) => {
                    const detailBits = [
                        item.title && item.title !== item.summary ? item.title : '',
                        item.status_label || '',
                        item.last_updated_label || '',
                    ].filter(Boolean);
                    const supportingPoints = Array.isArray(item.supporting_points) ? item.supporting_points.filter(Boolean) : [];
                    return `
                        <li class="network-story-bullet-item">
                            <div class="network-story-bullet-main">${esc(item.summary || item.title || 'Story point')}</div>
                            ${detailBits.length ? `<div class="network-lab-subtle network-story-bullet-meta">${esc(detailBits.join(' · '))}</div>` : ''}
                            ${supportingPoints.length ? `
                                <div class="network-lab-subtle network-story-bullet-meta"><strong>More context:</strong></div>
                                <ul class="network-story-bullet-subpoints">
                                    ${supportingPoints.map((point) => `<li>${esc(point)}</li>`).join('')}
                                </ul>
                            ` : ''}
                            ${item.why_it_matters ? `<div class="network-lab-subtle network-story-bullet-meta"><strong>Why it matters:</strong> ${esc(item.why_it_matters)}</div>` : ''}
                            ${item.next_move ? `<div class="network-lab-subtle network-story-bullet-meta"><strong>Next move:</strong> ${esc(item.next_move)}</div>` : ''}
                            ${item.resolution_note ? `<div class="network-lab-subtle network-story-bullet-meta"><strong>Resolution note:</strong> ${esc(item.resolution_note)}</div>` : ''}
                            ${item.evidence_anchor ? `<div class="network-lab-subtle network-story-bullet-meta"><strong>Evidence:</strong> ${esc(item.evidence_anchor)}</div>` : ''}
                        </li>
                    `;
                }).join('')}
            </ul>
        `;
        if (!items.length && !groups.length) {
            target.innerHTML = `<div class="network-lab-subtle">${esc(section.summary || emptyMessage)}</div>`;
            return;
        }
        if (groups.length) {
            target.innerHTML = `
                <div class="network-lab-subtle" style="margin-bottom:0.65rem;">${esc(section.summary || '')}</div>
                ${groups.map((group) => {
                    const groupItems = Array.isArray(group.items) ? group.items.filter(Boolean) : [];
                    return `
                        <div style="margin-bottom:1rem;">
                            <div class="network-storyline-headline" style="font-size:0.95rem; margin-bottom:0.45rem;">${esc(group.label || 'Personal')}</div>
                            <div class="network-lab-subtle" style="margin-bottom:0.5rem;">${esc(group.summary || '')}</div>
                            ${groupItems.length ? renderStoryItems(groupItems) : `<div class="network-lab-subtle">${esc(group.summary || 'No retained continuity yet.')}</div>`}
                        </div>
                    `;
                }).join('')}
            `;
            return;
        }
        target.innerHTML = `
            <div class="network-lab-subtle" style="margin-bottom:0.65rem;">${esc(section.summary || '')}</div>
            ${renderStoryItems(items)}
        `;
    };

    renderStorySection(
        'lab-relationship-story-personal',
        story.sections?.personal || {},
        'No personal continuity has been retained yet.'
    );
    renderStorySection(
        'lab-relationship-story-active',
        story.sections?.active || {},
        'No active threads are currently open.'
    );
    renderStorySection(
        'lab-relationship-story-market',
        story.sections?.market_business || {},
        'No market or business perspective is currently retained.'
    );
    renderStorySection(
        'lab-relationship-story-track',
        story.sections?.track_record || {},
        'No track record outcomes are currently retained.'
    );

    renderPrepList(
        'lab-relationship-story-next',
        story.next_recommended_moves || [],
        'No next move has been derived yet.'
    );
    renderPrepList(
        'lab-relationship-story-open',
        (story.open_questions || []).map((item) => {
            const title = String(item.title || '').trim();
            const question = String(item.question || '').trim();
            if (title && question) return `${title}: ${question}`;
            return question || title;
        }),
        'No open story questions remain.'
    );

    const evidence = document.getElementById('lab-relationship-story-evidence');
    if (evidence) {
        const items = Array.isArray(story.evidence_trail) ? story.evidence_trail.filter(Boolean) : [];
        if (!items.length) {
            evidence.innerHTML = '<div class="network-lab-subtle">No evidence anchors are ready yet.</div>';
        } else {
            evidence.innerHTML = `
                <ul class="network-prep-list network-story-bullet-list">
                    ${items.map((item) => `
                        <li class="network-story-bullet-item">
                            <div class="network-story-bullet-main">${esc(item.preview || 'No evidence preview')}</div>
                            <div class="network-lab-subtle network-story-bullet-meta">${esc([item.related_topic || 'Relationship evidence', item.channel || 'Interaction', item.date_label || ''].filter(Boolean).join(' · '))}</div>
                        </li>
                    `).join('')}
                </ul>
            `;
        }
    }
}

function renderTopicLedgerItems(targetId, items = [], emptyMessage) {
    const target = document.getElementById(targetId);
    if (!target) return;
    if (!items.length) {
        target.innerHTML = `<div class="network-lab-subtle">${esc(emptyMessage)}</div>`;
        return;
    }
    target.innerHTML = items.map((item) => `
        <article class="network-topic-ledger-item ${topicClass(item.topic_type)}">
            <div class="network-chip-row">
                <span class="network-chip ${topicClass(item.topic_type)}">${esc(item.topic_type_label || 'Relationship')}</span>
                <span class="network-chip network-situation-status ${situationStatusClass(item.status)}">${esc(item.status_label || 'Open')}</span>
                <span class="network-chip">${esc(item.last_touch_label || '')}</span>
            </div>
            <div class="network-storyline-headline">${esc(item.title || 'Relationship topic')}</div>
            ${item.source_people?.length ? `<div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Source:</strong> ${esc(item.source_people.join(', '))}</div>` : ''}
            ${item.current_read && item.current_read !== item.title ? `<div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Current read:</strong> ${esc(item.current_read)}</div>` : ''}
            ${item.evidence?.length ? `<div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Evidence:</strong> ${esc(item.evidence.join(' | '))}</div>` : ''}
            ${item.situation_record_id ? `
                <div class="network-lab-actions" style="margin-top:0.8rem;">
                    ${topicResolutionActionMarkup({
                        source: 'network_lab_topic_ledger',
                        situation_record_id: item.situation_record_id,
                        situation_id: item.situation_id,
                        title: item.title || 'Relationship topic',
                        topic_type: item.topic_type,
                        topic_type_label: item.topic_type_label,
                        current_read: item.current_read || '',
                        why_it_matters: item.why_it_matters || '',
                        tracking_status: item.tracking_status || item.status,
                        tracking_status_label: item.tracking_status_label || item.status_label,
                        stage: item.stage,
                        momentum: item.momentum,
                        recommended_action: item.recommended_action || '',
                        resolution_note: item.resolution_note || '',
                        evidence: item.evidence || [],
                        evidence_details: item.evidence_details || [],
                        source_people: item.source_people || [],
                        channels: item.channels || [],
                    }, { label: 'Resolve In Assistant', secondary: true })}
                </div>
            ` : ''}
        </article>
    `).join('');
}

function renderClarificationPrompts(items = []) {
    const target = document.getElementById('lab-clarification-prompts');
    if (!target) return;
    if (!items.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No clarification questions are currently blocking the relationship picture.</div></div>';
        return;
    }
    target.innerHTML = items.map((item, index) => `
        <article class="network-contact-card network-clarification-card">
            <div class="network-chip-row">
                <span class="network-chip warn">${esc(item.status_label || 'Open')}</span>
                <span class="network-chip">Importance ${esc(item.importance_score || 0)}</span>
            </div>
            <div class="network-storyline-headline">${esc(item.question || 'Clarification needed')}</div>
            <div class="network-lab-subtle" style="margin-top:0.45rem;">${esc(item.context || '')}</div>
            <div class="network-clarification-context">
                <div class="network-clarification-context-label">Linked Context</div>
                ${renderTopicContextDetails(clarificationContextDetails(item), 'No linked source context is attached yet.')}
            </div>
            <div class="network-clarification-actions">
                ${pilotTopicResolutionAllowed() ? `
                    <div class="network-inline-row">
                        <button class="network-lab-button" type="button" onclick="prefillClarificationAnswer(${index})">Answer In Assistant</button>
                        ${item.situation_record_id ? `<button class="network-lab-button secondary" type="button" onclick="scrollToStorylineContext('${esc(item.situation_record_id)}')">Open Storyline Context</button>` : ''}
                    </div>
                    <div class="network-lab-subtle">This opens the main profile assistant with this exact topic and its linked context preloaded.</div>
                ` : `
                    <div class="network-lab-subtle">${esc(pilotTopicResolutionNotice())}</div>
                    ${item.situation_record_id ? `<button class="network-lab-button secondary" type="button" onclick="scrollToStorylineContext('${esc(item.situation_record_id)}')">Open Storyline Context</button>` : ''}
                `}
            </div>
        </article>
    `).join('');
}

function renderRelationshipTopics(model = {}) {
    renderTopicLedgerItems(
        'lab-topic-personal',
        model.personal_continuity || [],
        'No personal continuity points are surfaced yet.'
    );
    renderTopicLedgerItems(
        'lab-topic-active',
        model.active_topics || [],
        'No active topics are currently open.'
    );
    renderTopicLedgerItems(
        'lab-topic-market',
        model.market_business_view || [],
        'No market or business themes are currently retained.'
    );
    renderTopicLedgerItems(
        'lab-topic-track-record',
        model.track_record || [],
        'No recent track-record items are being carried yet.'
    );
    renderClarificationPrompts(model.clarification_prompts || []);
}

function renderConversationPrep(prep = {}) {
    const summary = document.getElementById('lab-prep-summary');
    const coverage = document.getElementById('lab-prep-coverage');
    const liveThreads = document.getElementById('lab-prep-live-threads');
    const recentShifts = document.getElementById('lab-prep-recent-shifts');
    if (!summary || !coverage || !liveThreads || !recentShifts) return;

    summary.textContent = prep.summary || 'No briefing-grade conversation prep is ready yet.';
    coverage.innerHTML = `
        <span class="network-chip">${esc(prep.relevant_interaction_count || 0)} relevant interactions</span>
        <span class="network-chip">${esc(prep.interpreted_count || 0)} interpreted items</span>
        <span class="network-chip topic-opportunity">${esc(prep.live_thread_count || 0)} live threads</span>
        <span class="network-chip warn">${esc(prep.open_person_opportunity_count || 0)} person opps</span>
        <span class="network-chip">${esc(prep.open_company_opportunity_count || 0)} company opps</span>
    `;

    renderPrepList('lab-prep-context', prep.relationship_context || [], 'No relationship context is ready yet.');
    renderPrepList('lab-prep-topics', prep.topics_to_cover || [], 'No conversation topics are ready yet.');
    renderPrepList('lab-prep-follow-up', prep.follow_up_to_lock || [], 'No explicit follow-up action has been derived yet.');

    if (!(prep.live_threads || []).length) {
        liveThreads.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No live threads are ready yet.</div></div>';
    } else {
        liveThreads.innerHTML = (prep.live_threads || []).map((thread) => `
            <article class="network-contact-card network-prep-thread-card ${topicClass(thread.topic_type)}">
                <div class="network-chip-row">
                    <span class="network-chip ${topicClass(thread.topic_type)}">${esc(thread.topic_type_label || 'Relationship')}</span>
                    <span class="network-chip network-situation-status ${situationStatusClass(thread.tracking_status)}">${esc(thread.tracking_status_label || 'Watching')}</span>
                    <span class="network-chip">${esc(thread.stage || 'Relationship Update')}</span>
                    <span class="network-chip network-momentum-chip ${momentumClass(thread.momentum)}">${esc(thread.momentum || 'steady')}</span>
                    <span class="network-chip">${esc(thread.last_touch_label || '')}</span>
                </div>
                <div class="network-storyline-headline">${esc(thread.headline || 'Live thread')}</div>
                ${thread.current_read && thread.current_read !== thread.headline ? `<div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Current read:</strong> ${esc(thread.current_read)}</div>` : ''}
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Why it matters:</strong> ${esc(thread.why_it_matters || 'No explanation')}</div>
                ${(thread.key_points || []).length ? `<div class="network-intelligence-tag-grid">${(thread.key_points || []).map((value) => `<span class="network-chip ${topicClass(thread.topic_type)}">${esc(value)}</span>`).join('')}</div>` : ''}
                ${(thread.evidence || []).length ? `<div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${esc((thread.evidence || []).join(' | '))}</div>` : ''}
                ${thread.recommended_action ? `<div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Next action:</strong> ${esc(thread.recommended_action)}</div>` : ''}
            </article>
        `).join('');
    }

    if (!(prep.recent_shifts || []).length) {
        recentShifts.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No recent shifts are ready yet.</div></div>';
    } else {
        recentShifts.innerHTML = (prep.recent_shifts || []).map((item) => `
            <article class="network-contact-card network-prep-shift-card">
                <div class="network-chip-row">
                    <span class="network-chip">${esc(item.channel || 'Interaction')}</span>
                    <span class="network-chip">${esc(item.interaction_label || '')}</span>
                </div>
                <div class="network-storyline-headline">${esc(item.summary || item.evidence || 'Recent shift')}</div>
                ${item.detail ? `<div class="network-lab-subtle" style="margin-top:0.45rem;">${esc(item.detail)}</div>` : ''}
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${esc(item.evidence || 'No evidence')}</div>
            </article>
        `).join('');
    }
}

function renderFollowThroughWatch(context = {}) {
    const target = document.getElementById('lab-follow-through-watch');
    if (!target) return;

    const hasConfirmation = Boolean(context.follow_up_confirmation_needed);
    const hasTaskPressure = Boolean(context.has_task_pressure);
    const coverStrength = Number(context.cover_strength || 0);
    const coverKind = humanCoverLabel(context.cover_kind);
    const coverReason = String(context.cover_reason || 'No scheduled follow-up cover is recorded.');
    const taskLabel = String(context.primary_open_task_label || '').trim();
    const taskIntent = String(context.primary_open_task_kind || '').trim();
    const confirmationReason = String(context.follow_up_confirmation_reason || '').trim();
    const confirmationPrompt = String(context.follow_up_confirmation_prompt || '').trim();

    const toneClass = hasConfirmation ? 'is-alert' : coverStrength >= 60 ? 'is-covered' : 'is-watch';
    const title = hasConfirmation
        ? 'Follow-Through Confirmation Needed'
        : coverStrength >= 60
            ? 'Follow-Through Cover Looks Strong'
            : 'Follow-Through Watch';
    const summary = hasConfirmation
        ? confirmationReason || 'A scheduled follow-up has passed without a recorded outcome.'
        : coverReason;

    target.innerHTML = `
        <div class="network-prep-watch-card ${toneClass}">
            <div class="network-prep-watch-head">
                <div>
                    <div class="network-lab-kicker">Follow-Through Watch</div>
                    <h4>${esc(title)}</h4>
                    <div class="network-prep-summary-text">${esc(summary)}</div>
                </div>
                <div class="network-chip-row">
                    <span class="network-chip ${hasConfirmation ? 'alert' : ''}">${esc(coverKind)}</span>
                    ${taskIntent ? `<span class="network-chip warn">${esc(String(taskIntent).replace(/_/g, ' '))}</span>` : ''}
                    ${hasTaskPressure ? '<span class="network-chip alert">Task pressure</span>' : ''}
                    ${context.has_future_cover ? '<span class="network-chip">Cover active</span>' : '<span class="network-chip alert">No reliable cover</span>'}
                </div>
            </div>
            <div class="network-prep-watch-grid">
                <div class="network-prep-watch-detail">
                    <strong>What the score is reacting to</strong>
                    <ul class="network-prep-list">
                        <li>${esc(coverReason)}</li>
                        ${taskLabel ? `<li>Current task context: ${esc(taskLabel)}</li>` : ''}
                        ${confirmationPrompt ? `<li>${esc(confirmationPrompt)}</li>` : ''}
                    </ul>
                </div>
                <div class="network-prep-watch-actions">
                    <strong>Resolve it now</strong>
                    <div class="network-lab-actions network-lab-actions-stack">
                        <button class="network-lab-button" type="button" onclick="prefillFollowUpOutcome()">Log Outcome Now</button>
                        <button class="network-lab-button secondary" type="button" onclick="prefillQuickTask()">Prepare Next-Step Task</button>
                    </div>
                    <form class="network-prep-task-form" onsubmit="createQuickFollowUpTask(event)">
                        <label>Next-Step Task
                            <input id="lab-follow-through-task-text" type="text" placeholder="Create a dated next-step task">
                        </label>
                        <label>Due Date
                            <input id="lab-follow-through-task-due" type="date" value="${esc(isoDateFromNow(2))}">
                        </label>
                        <button class="network-lab-button secondary" type="submit">Create Follow-Up Task</button>
                    </form>
                </div>
            </div>
        </div>
    `;
}

function renderRelatedTeamContext(context = {}, companyName = '') {
    const heading = document.getElementById('lab-related-team-heading');
    const summary = document.getElementById('lab-related-team-summary');
    const threadsTarget = document.getElementById('lab-related-team-threads');
    if (!summary || !threadsTarget) return;

    if (heading) {
        heading.textContent = companyName ? `Across ${companyName}` : 'Related Team Context';
    }
    summary.textContent = context.summary || 'No related team context is available yet.';

    if (!(context.threads || []).length) {
        threadsTarget.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No separately attributed company-team threads are visible yet.</div></div>';
        return;
    }

    threadsTarget.innerHTML = (context.threads || []).map((thread) => `
        <article class="network-contact-card network-team-thread-card ${topicClass(thread.topic_type)}">
            <div class="network-inline-row">
                <div>
                    <div style="font-weight:800;">${esc(thread.full_name || 'Related contact')}</div>
                    <div class="network-lab-subtle">${esc(thread.title_current || '')}</div>
                </div>
                <a class="network-lab-button secondary network-inline-link" href="${esc(thread.profile_path || '#')}">Open profile</a>
            </div>
            <div class="network-chip-row">
                <span class="network-chip ${topicClass(thread.topic_type)}">${esc(thread.topic_type_label || 'Relationship')}</span>
                <span class="network-chip network-situation-status ${situationStatusClass(thread.tracking_status)}">${esc(thread.tracking_status_label || 'Watching')}</span>
                <span class="network-chip">${esc(thread.stage || 'Relationship Update')}</span>
                <span class="network-chip network-momentum-chip ${momentumClass(thread.momentum)}">${esc(thread.momentum || 'steady')}</span>
            </div>
            <div class="network-lab-subtle">${esc(thread.attribution || '')}</div>
            <div class="network-storyline-headline" style="margin-top:0.45rem;">${esc(thread.headline || 'Related team thread')}</div>
            ${thread.current_read && thread.current_read !== thread.headline ? `<div class="network-lab-subtle" style="margin-top:0.35rem;"><strong>Current read:</strong> ${esc(thread.current_read)}</div>` : ''}
            <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Why it matters:</strong> ${esc(thread.why_it_matters || 'No explanation')}</div>
            ${(thread.key_points || []).length ? `<div class="network-intelligence-tag-grid">${(thread.key_points || []).map((value) => `<span class="network-chip ${topicClass(thread.topic_type)}">${esc(value)}</span>`).join('')}</div>` : ''}
            ${(thread.evidence || []).length ? `<div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${esc((thread.evidence || []).join(' | '))}</div>` : ''}
            <div class="network-lab-subtle" style="margin-top:0.45rem;">${esc(thread.window_label || '')}</div>
        </article>
    `).join('');
}

function renderScoreBreakdown(context = {}) {
    const scoreSummary = document.getElementById('lab-score-summary');
    const scoreGrid = document.getElementById('lab-score-grid');
    const scoreBand = document.getElementById('lab-score-band');
    const componentReasons = context.score_component_reasons || {};
    const summaryReasons = context.score_reason_summary || [];

    if (scoreBand) {
        scoreBand.textContent = context.score_band ? `${context.score_band} score` : 'score';
    }

    scoreSummary.innerHTML = (summaryReasons.length ? summaryReasons : ['No score summary is available yet.'])
        .map((item) => {
            const reason = normalizeReason(item);
            return `<li>${evidenceBadge(reason)} <span>${esc(reason.text)}</span></li>`;
        })
        .join('');

    const components = [
        ['Coverage Health', 'coverage_health'],
        ['Strategic Value', 'strategic_value'],
        ['Opportunity Readiness', 'opportunity_readiness'],
        ['Relationship Strength', 'relationship_strength'],
        ['Confidence', 'confidence'],
    ];

    scoreGrid.innerHTML = components.map(([label, key]) => {
        const reasons = (componentReasons[key] || []).map(normalizeReason);
        return `
            <div class="network-score-card">
                <strong>${label}</strong>
                <div class="network-score-value">${esc(context[key] ?? 0)}</div>
                <div class="network-lab-subtle">${
                    reasons.length
                        ? reasons.map((reason) => `${evidenceBadge(reason)} ${esc(reason.text)}`).join('<br>')
                        : 'No detail available'
                }</div>
            </div>
        `;
    }).join('');
}

function renderProfile() {
    const person = networkLabProfile.person;
    const context = networkLabProfile.queue_context || {};
    document.getElementById('lab-profile-name').textContent = person.full_name || 'Unknown contact';
    const pilotMeta = pilotTopicResolutionAllowed()
        ? `Pilot cohort | ${String(networkLabProfile.pilot_cohort_mode || 'recommended')}`
        : `Outside pilot | ${String(networkLabProfile.pilot_cohort_mode || 'recommended')}`;
    document.getElementById('lab-profile-meta').textContent = `${person.title_current || 'No title'} @ ${person.company_name_raw || 'Unknown company'} | ${pilotMeta}`;
    document.getElementById('lab-score').textContent = String(context.network_health_score || 0);
    renderScoreBreakdown(context);

    document.getElementById('lab-chip-row').innerHTML = `
        <span class="network-chip">${esc(context.effective_network_tier_label || person.network_tier || 'No tier')}</span>
        <span class="network-chip warn">${esc(person.maintenance_mode || 'No mode')}</span>
        <span class="network-chip">${esc(person.account_priority || 'No account priority')}</span>
        <span class="network-chip ${context.has_future_cover ? '' : 'alert'}">${context.has_future_cover ? humanCoverLabel(context.cover_kind) : 'No next step'}</span>
        ${context.primary_open_task_label ? `<span class="network-chip">${esc(context.primary_open_task_label)}</span>` : ''}
        ${context.follow_up_confirmation_needed ? '<span class="network-chip alert">Confirmation needed</span>' : ''}
    `;

    document.getElementById('lab-why-list').innerHTML = `
        <li>${esc(context.queue_reason || 'Not currently surfaced')}</li>
        <li>${esc(context.open_opportunity_count || 0)} open person-level opportunities</li>
        <li>Coverage health ${esc(context.coverage_health || 0)}</li>
        <li>Opportunity readiness ${esc(context.opportunity_readiness || 0)}</li>
        ${context.cover_reason ? `<li>${esc(context.cover_reason)}</li>` : ''}
    `;
    document.getElementById('lab-tier-trace').innerHTML = (context.tier_reason_trace || [person.tier_rationale || 'No tier trace yet'])
        .map((item) => {
            const reason = normalizeReason(item);
            return `<li>${evidenceBadge(reason)} <span>${esc(reason.text)}</span></li>`;
        })
        .join('');

    document.getElementById('person-network-tier').value = person.network_tier || (context.effective_network_tier || 'T3');
    document.getElementById('person-maintenance-mode').value = person.maintenance_mode || 'maintain';
    renderOwnerOptions('person-owner', person.relationship_owner || (networkLabOwners[0]?.full_name || ''));
    document.getElementById('person-decision-role').value = person.decision_role || 'decision_maker';
    document.getElementById('person-influence-scope').value = person.influence_scope || 'both';
    document.getElementById('person-account-priority').value = person.account_priority || 'Warm';
    document.getElementById('person-tier-rationale').value = person.tier_rationale || '';

    renderOwnerOptions('person-opportunity-owner', person.relationship_owner || (networkLabOwners[0]?.full_name || ''));
    renderOwnerOptions('company-opportunity-owner', person.relationship_owner || (networkLabOwners[0]?.full_name || ''));
    document.getElementById('company-opportunity-company-name').value = person.company_name_raw || '';

    renderOpportunityCards('person-opportunity-list', networkLabProfile.person_opportunities, 'opportunity_id');
    renderOpportunityCards('company-opportunity-list', networkLabProfile.company_opportunities, 'company_opportunity_id');
    renderConversationPrep(networkLabProfile.conversation_prep || {});
    renderRelationshipStoryThread(networkLabProfile.story_thread || {});
    renderRelationshipStory(networkLabProfile.relationship_story || {});
    renderRelationshipTopics(networkLabProfile.relationship_topics || {});
    renderFollowThroughWatch(context);
    renderRelatedTeamContext(networkLabProfile.related_team_context || {}, person.company_name_raw || '');
    const storylineSummary = document.getElementById('lab-storyline-summary');
    const currentStateSummary = document.getElementById('lab-current-state-summary');
    const marketIntelSummary = document.getElementById('lab-market-intel-summary');
    const rapportSummary = document.getElementById('lab-rapport-summary');
    const happeningSummary = document.getElementById('lab-what-is-happening-summary');
    const whySummary = document.getElementById('lab-why-it-matters-summary');
    if (storylineSummary) storylineSummary.textContent = networkLabProfile.storyline_summary || 'No storyline is available yet.';
    if (currentStateSummary) currentStateSummary.textContent = networkLabProfile.current_state_summary || 'No current state has been derived yet.';
    renderStorylineGroups(networkLabProfile.storyline_groups || []);
    if (happeningSummary) happeningSummary.textContent = networkLabProfile.what_is_happening_summary || 'No interpreted interaction summary is available yet.';
    if (whySummary) whySummary.textContent = networkLabProfile.why_it_matters_summary || 'No interpreted interaction summary is available yet.';
    if (marketIntelSummary) marketIntelSummary.textContent = networkLabProfile.market_intel_summary || 'No market intelligence has been extracted yet.';
    if (rapportSummary) rapportSummary.textContent = networkLabProfile.rapport_summary || 'No rapport intelligence has been extracted yet.';
    renderInterpretedInteractions(networkLabProfile.interpreted_interactions || []);
    renderSignalCards('lab-surfaced-intelligence', networkLabProfile.surfaced_intelligence || []);
    renderSignalCards('lab-draft-intelligence', networkLabProfile.draft_intelligence || []);
    renderPromotedCards('lab-enduring-memory', networkLabProfile.enduring_memory || []);
    renderPromotedCards('lab-promoted-market-intel', networkLabProfile.promoted_market_intel || [], 'warn');
    renderEvidenceCards('lab-recent-evidence', networkLabProfile.recent_evidence || []);
}

async function loadLabProfile() {
    setProfileStatus('Loading profile...');
    try {
        const [ownersRes, profileRes] = await Promise.all([
            fetch(`${LAB_API_BASE}/api/network-lab/owners`, { credentials: 'same-origin' }),
            fetch(`${LAB_API_BASE}/api/network-lab/profile/${encodeURIComponent(networkLabPersonId)}`, { credentials: 'same-origin' }),
        ]);
        if (!ownersRes.ok || !profileRes.ok) {
            throw new Error(`Profile data failed to load (owners ${ownersRes.status}, profile ${profileRes.status})`);
        }
        networkLabOwners = (await ownersRes.json()).owners || [];
        networkLabProfile = await profileRes.json();
        renderProfile();
        setProfileStatus('Profile loaded.');
    } catch (error) {
        console.error(error);
        setProfileStatus(error.message || 'Profile failed to load.', 'error');
    }
}

async function saveNetworkControls(event) {
    event.preventDefault();
    const payload = {
        network_tier: document.getElementById('person-network-tier').value,
        maintenance_mode: document.getElementById('person-maintenance-mode').value,
        relationship_owner: document.getElementById('person-owner').value,
        decision_role: document.getElementById('person-decision-role').value,
        influence_scope: document.getElementById('person-influence-scope').value,
        account_priority: document.getElementById('person-account-priority').value,
        tier_rationale: document.getElementById('person-tier-rationale').value.trim(),
        last_health_refresh_at: new Date().toISOString(),
    };
    const res = await fetch(`${LAB_API_BASE}/api/people/${encodeURIComponent(networkLabPersonId)}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        alert('Failed to save network controls.');
        return;
    }
    await loadLabProfile();
}

async function createPersonOpportunity(event) {
    event.preventDefault();
    const payload = {
        opportunity_type: document.getElementById('person-opportunity-type').value.trim(),
        stage: document.getElementById('person-opportunity-stage').value.trim(),
        value_band: document.getElementById('person-opportunity-value-band').value.trim(),
        trigger_date: document.getElementById('person-opportunity-trigger-date').value,
        owner: document.getElementById('person-opportunity-owner').value,
        status: document.getElementById('person-opportunity-status').value.trim(),
        notes: document.getElementById('person-opportunity-notes').value.trim(),
        account_name: networkLabProfile.person.company_name_raw || '',
    };
    const res = await fetch(`${LAB_API_BASE}/api/people/${encodeURIComponent(networkLabPersonId)}/opportunities`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        alert('Failed to create person opportunity.');
        return;
    }
    event.target.reset();
    document.getElementById('company-opportunity-company-name').value = networkLabProfile.person.company_name_raw || '';
    await loadLabProfile();
}

async function createCompanyOpportunity(event) {
    event.preventDefault();
    const payload = {
        company_name_raw: document.getElementById('company-opportunity-company-name').value.trim(),
        opportunity_type: document.getElementById('company-opportunity-type').value.trim(),
        stage: document.getElementById('company-opportunity-stage').value.trim(),
        value_band: document.getElementById('company-opportunity-value-band').value.trim(),
        trigger_date: document.getElementById('company-opportunity-trigger-date').value,
        owner: document.getElementById('company-opportunity-owner').value,
        status: document.getElementById('company-opportunity-status').value.trim(),
        notes: document.getElementById('company-opportunity-notes').value.trim(),
    };
    const res = await fetch(`${LAB_API_BASE}/api/network-lab/company-opportunities`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        alert('Failed to create company opportunity.');
        return;
    }
    event.target.reset();
    document.getElementById('company-opportunity-company-name').value = networkLabProfile.person.company_name_raw || '';
    await loadLabProfile();
}

async function logLabInteraction(event) {
    event.preventDefault();
    const payload = {
        person_id: networkLabPersonId,
        channel: document.getElementById('lab-interaction-channel').value,
        raw_text: document.getElementById('lab-interaction-text').value.trim(),
        direction: document.getElementById('lab-interaction-direction').value,
        meaningful_flag: document.getElementById('lab-interaction-meaningful').value === 'true',
        outcome_type: document.getElementById('lab-interaction-outcome').value,
        response_flag: document.getElementById('lab-interaction-response').value === 'true',
        follow_up_committed_flag: document.getElementById('lab-interaction-follow-up').value === 'true',
    };
    const res = await fetch(`${LAB_API_BASE}/api/interactions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        alert('Failed to log interaction.');
        return;
    }
    event.target.reset();
    await loadLabProfile();
}

async function promoteInterpretedMemory(interpretationId, memoryDomain) {
    const res = await fetch(`${LAB_API_BASE}/api/network-lab/interpretations/${encodeURIComponent(interpretationId)}/promote-memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_domain: memoryDomain, status: 'approved' }),
    });
    if (!res.ok) {
        alert('Failed to promote enduring memory.');
        return;
    }
    await loadLabProfile();
}

async function promoteMarketIntel(interpretationId) {
    const res = await fetch(`${LAB_API_BASE}/api/network-lab/interpretations/${encodeURIComponent(interpretationId)}/promote-market-intel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'approved' }),
    });
    if (!res.ok) {
        alert('Failed to promote market intel.');
        return;
    }
    await loadLabProfile();
}

document.addEventListener('DOMContentLoaded', async () => {
    networkLabPersonId = queryPersonId();
    if (!networkLabPersonId) {
        document.getElementById('lab-profile-name').textContent = 'No person selected';
        return;
    }
    await loadLabProfile();
});
