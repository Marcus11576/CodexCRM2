// Profile signals, personal intelligence, and employment timeline

async function fetchintelligence() {
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}/intelligence`);
        if (!res.ok) throw new Error('Failed to fetch intelligence');
        const data = await res.json();
        window.currentIntelligenceData = data;
        window.dispatchEvent(new CustomEvent('ag:intelligence-updated', { detail: data }));

        renderBusinessCard('db-business-interests', data.business_focus, 'business_interests');
        renderBusinessCard('db-business-market-pulse', data.business_focus, 'market_pulse');
        renderBusinessCard('db-business-leadership-view', data.business_focus, 'leadership_view');
        renderBusinessCard('db-business-commercial-position', data.business_focus, 'commercial_position');
        renderBusinessCard('db-business-operational-pressure', data.business_focus, 'operational_pressure');
        renderTopic('db-recruitment', data.recruitment_talent, 'recruitment-talent');
        renderTopic('db-personal', data.family_personal, 'family-personal');
        renderTopic('db-obe', data.obe_focus, 'obe-focus');
    } catch (err) {
        console.error(err);
    }
}

// hook up review button after page load
window.addEventListener('DOMContentLoaded', () => {
    ensureCareerTimelineObserver();
    const btn = document.getElementById('review-signals-btn');
    if (btn) btn.addEventListener('click', reviewSignals);
});

const SIGNAL_CATEGORY_OPTIONS = [
    { value: 'business_focus', label: 'Business Focus' },
    { value: 'recruitment_talent', label: 'Recruitment & Talent' },
    { value: 'family_personal', label: 'Family & Personal' },
    { value: 'obe_focus', label: 'OBE Focus' },
];

const BUSINESS_SUBTOPIC_OPTIONS = [
    { value: 'business_interests', label: 'Business Interests' },
    { value: 'market_pulse', label: 'Market Pulse' },
    { value: 'leadership_view', label: 'Leadership View' },
    { value: 'commercial_position', label: 'Commercial Position' },
    { value: 'operational_pressure', label: 'Operational Pressure' },
];
window.BUSINESS_SUBTOPIC_OPTIONS = BUSINESS_SUBTOPIC_OPTIONS;

let currentSignalReview = null;
let currentSignalReviewDialog = null;

function signalCategoryLabel(category) {
    return SIGNAL_CATEGORY_OPTIONS.find((item) => item.value === category)?.label
        || String(category || 'Uncategorised').replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
}

function getSignalById(signalId) {
    const targetId = String(signalId);
    return [
        ...(currentSignalReview?.signals || []),
        ...listAllIntelligenceSignals(),
    ].find((signal) => String(signal.signal_ref || signal.id || signal.intel_id) === targetId);
}

function listAllIntelligenceSignals() {
    const data = window.currentIntelligenceData || {};
    return [
        ...(data.business_focus || []),
        ...(data.recruitment_talent || []),
        ...(data.family_personal || []),
        ...(data.obe_focus || []),
    ];
}

function signalStatusLabel(signal) {
    const status = String(signal.review_state || signal.status || 'pending_review').replace(/_/g, ' ');
    return status.replace(/\b\w/g, (char) => char.toUpperCase());
}

function businessSubtopicLabel(value) {
    return BUSINESS_SUBTOPIC_OPTIONS.find((item) => item.value === value)?.label || '';
}

function normalizeSignalText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function splitSignalSentences(value) {
    return normalizeSignalText(value)
        .split(/(?<=[.!?])\s+/)
        .map((sentence) => sentence.trim())
        .filter(Boolean);
}

function isGenericSignalSentence(sentence) {
    const normalized = normalizeSignalText(sentence).toLowerCase();
    return [
        'the conversation centered on',
        'the discussion centered on',
        'the discussion focused on',
        'with an emphasis on',
        'highlighted the need for',
        'highlighted the importance of',
        'their approach to project management',
        'in their approach to project management',
    ].some((fragment) => normalized.includes(fragment));
}

function signalDisplayText(signal) {
    const sentences = splitSignalSentences(signal?.text || '');
    const filtered = sentences.filter((sentence) => !isGenericSignalSentence(sentence));
    const preferred = filtered.length ? filtered : sentences;
    return preferred.slice(0, 2).join(' ').trim() || normalizeSignalText(signal?.text || '');
}

function evidenceDisplayText(signal) {
    const raw = normalizeSignalText(signal?.supporting_context || signal?.snippet || '');
    if (!raw) return '';
    if (raw.length <= 320) return raw;
    const trimmed = raw.slice(0, 317).replace(/\s+\S*$/, '');
    return `${trimmed}...`;
}

function businessSubtopicGroups(nuggets) {
    return BUSINESS_SUBTOPIC_OPTIONS.map((option) => ({
        key: option.value,
        label: option.label,
        items: (nuggets || []).filter((item) => item.business_subtopic === option.value),
    }));
}

function renderSignalCard(n, cssClass) {
    const sourceMeta = channelMetaForItem(n);
    const sourceName = sourceMeta.label;
    const icon = {
        note: 'Note',
        whatsapp: 'WA',
        email: 'Email',
        call: 'Call',
        meeting: 'Meet',
        screenshot: 'Screen',
        audio: 'Audio',
        upload: 'Upload',
        document: 'Doc',
        chat: 'Chat'
    }[sourceMeta.key] || 'Note';
    const statusLabel = signalStatusLabel(n);
    const sourceLabel = signalSourceLabel(n);
    const signalText = signalDisplayText(n);
    const contextText = evidenceDisplayText(n);
    const showContext = contextText && contextText !== normalizeSignalText(signalText);
    const signalId = n.signal_ref || n.id || n.intel_id || '';
    return `
        <article class="nugget-item ${cssClass} ${cssClass === 'business-focus' ? 'business-focus-card' : ''}">
            <div class="signal-card-topline">
                <span class="signal-card-date">${formatDate(n.date)}</span>
                <div class="signal-card-tools">
                    <span class="signal-card-source" title="Source: ${sourceName}">${icon}</span>
                    ${signalId ? `<button type="button" class="signal-card-edit-btn" onclick="editSignalFromCard('${escapeHtml(signalId)}')" title="Edit this intelligence point">Edit</button>` : ''}
                    ${signalId ? `<button type="button" class="signal-card-remove-btn" onclick="removeSignalFromCard('${escapeHtml(signalId)}')" title="Remove this intelligence point">Remove</button>` : ''}
                </div>
            </div>
            ${n.business_subtopic_label && cssClass !== 'business-focus' ? `<div class="signal-inline-subtopic">${escapeHtml(n.business_subtopic_label)}</div>` : ''}
            <div class="nugget-text"><strong>Signal:</strong> ${escapeHtml(signalText)}</div>
            <div class="signal-meta-row">
                <span>${escapeHtml(sourceLabel)}</span>
                <span>${escapeHtml(statusLabel)}</span>
                <span>Confidence ${escapeHtml(String(n.confidence ?? 'n/a'))}</span>
                <span>${n.influences_brief ? 'In brief' : 'Not in brief'}</span>
            </div>
            ${showContext ? `<div class="signal-evidence-row"><strong>Evidence:</strong> ${escapeHtml(contextText)}</div>` : ''}
        </article>
    `;
}

function signalSourceLabel(signal) {
    const channelLabel = channelMetaForItem(signal).label;
    if (signal.source_kind === 'legacy_intelligence') {
        return `${channelLabel} · Legacy intel`;
    }
    return `${channelLabel} · AI signal`;
}

async function updateSignalRecord(signalId, payload, successMessage) {
    const response = await fetch(`${API_BASE}/api/ai/signals/${encodeURIComponent(signalId)}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!response.ok) {
        throw new Error('Unable to update signal');
    }
    await fetchintelligence();
    if (currentSignalReviewDialog) {
        await reviewSignals();
    }
    if (successMessage) {
        toast(successMessage, 'success');
    }
    return response.json();
}

async function reviewSignals() {
    try {
        const res = await fetch(`${API_BASE}/api/intelligence/assistant/${personId}/review`, { method: 'POST' });
        if (!res.ok) throw new Error('Review failed');
        const data = await res.json();
        showReviewModal(data);
    } catch (e) {
        toast(`Error reviewing signals: ${e.message}`, 'error');
        console.error(e);
    }
}

function showReviewModal(data) {
    currentSignalReview = data;
    if (currentSignalReviewDialog) {
        currentSignalReviewDialog.close();
    }

    const content = document.createElement('div');
    content.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:0.75rem; margin-bottom:1rem; flex-wrap:wrap;">
            <div class="ag-dialog-description" style="margin:0;">Review extracted signals, correct them, and keep the brief grounded in what should matter.</div>
            <button type="button" class="ag-inline-btn" data-add-signal data-tone="promote">+ Add Signal</button>
        </div>
        <div class="ag-review-list">
            ${(data.signals || []).map((signal) => `
                <article class="ag-review-card" data-review-signal="${signal.signal_ref || signal.id || signal.intel_id}">
                    <div class="ag-review-top">
                        <div style="display:flex; gap:0.5rem; align-items:center; flex-wrap:wrap;">
                            <span class="ag-review-chip">${escapeHtml(signalCategoryLabel(signal.category))}</span>
                            ${signal.business_subtopic_label ? `<span class="ag-review-subtopic-chip">${escapeHtml(signal.business_subtopic_label)}</span>` : ''}
                        </div>
                        <span class="ag-dialog-description" style="margin:0;">${escapeHtml(signalStatusLabel(signal))}</span>
                    </div>
                    <div class="ag-review-text"><strong>Signal:</strong> ${escapeHtml(signal.text || '')}</div>
                    <div class="ag-dialog-description" style="margin:0.45rem 0 0;">${escapeHtml(signalSourceLabel(signal))} · Confidence ${escapeHtml(String(signal.confidence ?? 'n/a'))} · ${signal.influences_brief ? 'In brief' : 'Not in brief'}</div>
                    <div class="ag-review-snippet"><strong>Evidence:</strong> ${escapeHtml(signal.supporting_context || signal.snippet || 'No source snippet saved for this item yet.')}</div>
                    <div class="ag-review-actions">
                        <button type="button" class="ag-inline-btn" data-signal-action="approve" data-signal-id="${signal.signal_ref || signal.id || signal.intel_id}" data-tone="approve">Approve</button>
                        <button type="button" class="ag-inline-btn" data-signal-action="reject" data-signal-id="${signal.signal_ref || signal.id || signal.intel_id}" data-tone="reject">Reject</button>
                        <button type="button" class="ag-inline-btn" data-signal-action="edit" data-signal-id="${signal.signal_ref || signal.id || signal.intel_id}" data-tone="secondary">Edit</button>
                        <button type="button" class="ag-inline-btn" data-signal-action="remove" data-signal-id="${signal.signal_ref || signal.id || signal.intel_id}" data-tone="reject">Remove</button>
                        <button type="button" class="ag-inline-btn" data-signal-action="promote" data-signal-id="${signal.signal_ref || signal.id || signal.intel_id}" data-tone="promote">Promote</button>
                        <button type="button" class="ag-inline-btn" data-signal-action="demote" data-signal-id="${signal.signal_ref || signal.id || signal.intel_id}">Demote</button>
                    </div>
                </article>
            `).join('') || '<div class="ag-picker-empty">No signals found for review.</div>'}
        </div>
        <div style="margin-top:1.1rem;">
            <div class="ag-dialog-title" style="font-size:0.92rem;">Brief Preview</div>
            <pre class="ag-brief-preview">${escapeHtml(JSON.stringify(data.brief, null, 2))}</pre>
        </div>
    `;

    content.querySelector('[data-add-signal]')?.addEventListener('click', () => addSignal());
    content.querySelectorAll('[data-signal-action]').forEach((button) => {
        button.addEventListener('click', async () => {
            const signalId = button.dataset.signalId;
            const action = button.dataset.signalAction;
            if (action === 'approve') await approveSignal(signalId);
            if (action === 'reject') await rejectSignal(signalId);
            if (action === 'edit') editSignal(signalId);
            if (action === 'remove') await removeSignalFromCard(signalId);
            if (action === 'promote') await promoteSignal(signalId);
            if (action === 'demote') await demoteSignal(signalId);
        });
    });

    const dialog = openAgDialog({
        title: 'Signal Review',
        width: '920px',
        content,
        actions: [
            {
                label: 'Close',
                variant: 'ghost',
                onClick: () => true,
            },
        ],
        onClose: () => {
            if (currentSignalReviewDialog === dialog) {
                currentSignalReviewDialog = null;
            }
        },
    });
    currentSignalReviewDialog = dialog;
}

async function approveSignal(id) {
    await updateSignalRecord(id, { action: 'approve' }, 'Signal approved');
}

async function rejectSignal(id) {
    await updateSignalRecord(id, { action: 'reject' }, 'Signal rejected');
}

async function promoteSignal(id) {
    await updateSignalRecord(id, { action: 'promote' }, 'Signal promoted');
}

async function demoteSignal(id) {
    await updateSignalRecord(id, { action: 'demote' }, 'Signal demoted');
}

async function removeSignal(id) {
    await updateSignalRecord(id, { status: 'archived' }, 'Signal removed from intelligence');
}

async function removeSignalFromCard(id) {
    const signal = getSignalById(id);
    const label = signal ? signalDisplayText(signal) : 'this intelligence point';
    const confirmed = window.confirm(`Remove this intelligence point?\n\n${label}`);
    if (!confirmed) return;
    await removeSignal(id);
}

function openSignalEditorModal(signal = null, defaults = {}) {
    const isEditing = !!signal;
    const selectedCategory = signal?.category || defaults.category || 'business_focus';
    const selectedSubtopic = signal?.business_subtopic || defaults.business_subtopic || '';
    const content = document.createElement('div');
    content.innerHTML = `
        <div class="ag-form-grid">
            <label class="ag-form-field ag-form-field-full">
                <span class="ag-form-field-label">Primary Category</span>
                <select id="signal-editor-category" class="ag-select">
                    ${SIGNAL_CATEGORY_OPTIONS.map((option) => `
                        <option value="${option.value}" ${option.value === selectedCategory ? 'selected' : ''}>${option.label}</option>
                    `).join('')}
                </select>
            </label>
            <label class="ag-form-field ag-form-field-full" id="signal-editor-subtopic-wrap" style="${selectedCategory === 'business_focus' ? '' : 'display:none;'}">
                <span class="ag-form-field-label">Business Subtopic</span>
                <select id="signal-editor-subtopic" class="ag-select">
                    <option value="">Select a business subtopic</option>
                    ${BUSINESS_SUBTOPIC_OPTIONS.map((option) => `
                        <option value="${option.value}" ${option.value === selectedSubtopic ? 'selected' : ''}>${option.label}</option>
                    `).join('')}
                </select>
            </label>
            <label class="ag-form-field ag-form-field-full">
                <span class="ag-form-field-label">Signal Text</span>
                <textarea id="signal-editor-text" class="ag-textarea" rows="6" placeholder="Add the exact intelligence point you want in the profile trail.">${escapeHtml(signal?.text || '')}</textarea>
            </label>
        </div>
    `;

    const categorySelect = content.querySelector('#signal-editor-category');
    const subtopicWrap = content.querySelector('#signal-editor-subtopic-wrap');
    categorySelect?.addEventListener('change', () => {
        if (!subtopicWrap) return;
        subtopicWrap.style.display = categorySelect.value === 'business_focus' ? '' : 'none';
    });

    openAgDialog({
        title: isEditing ? 'Edit Signal' : 'Add Manual Signal',
        width: '620px',
        content,
        actions: [
            {
                label: 'Cancel',
                variant: 'ghost',
                onClick: () => true,
            },
            {
                label: isEditing ? 'Save Signal' : 'Create Signal',
                variant: 'primary',
                onClick: async ({ close }) => {
                    const category = document.getElementById('signal-editor-category')?.value;
                    const businessSubtopic = document.getElementById('signal-editor-subtopic')?.value || null;
                    const text = document.getElementById('signal-editor-text')?.value.trim();
                    if (!category || !text) {
                        toast('Category and signal text are required', 'warning');
                        return false;
                    }

                    if (isEditing) {
                        await updateSignalRecord(signal.signal_ref || signal.id || signal.intel_id, {
                            text,
                            category,
                            business_subtopic: category === 'business_focus' ? businessSubtopic : null,
                        }, 'Signal updated');
                    } else {
                        const response = await fetch(`${API_BASE}/api/ai/signals`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                person_id: personId,
                                category,
                                business_subtopic: category === 'business_focus' ? businessSubtopic : null,
                                content: text,
                                source_snippet: text,
                                confidence: 3,
                                manual: true
                            }),
                        });
                        if (!response.ok) {
                            throw new Error('Unable to create signal');
                        }
                        toast('Signal added', 'success');
                    }

                    close(true);
                    if (!isEditing) {
                        await fetchintelligence();
                        await reviewSignals();
                    }
                    return true;
                },
                closeOnClick: false,
            },
        ],
    });
}

function editSignal(id) {
    const signal = getSignalById(id);
    if (!signal) return;
    openSignalEditorModal(signal);
}

function addSignal() {
    openSignalEditorModal();
}

function editSignalFromCard(id) {
    editSignal(id);
}

function addSignalForCategory(category, businessSubtopic = '') {
    openSignalEditorModal(null, {
        category,
        business_subtopic: businessSubtopic || '',
    });
}


function renderTopic(elementId, nuggets, cssClass) {
    const container = document.getElementById(elementId);
    if (!container) return;

    if (!nuggets || nuggets.length === 0) {
        const category = cssClass === 'recruitment-talent'
            ? 'recruitment_talent'
            : cssClass === 'family-personal'
                ? 'family_personal'
                : 'obe_focus';
        container.innerHTML = `
            <div class="business-subtopic-empty">Nothing specific recorded yet.</div>
            <button type="button" class="signal-empty-add-btn" onclick="addSignalForCategory('${category}')">Add intelligence</button>
        `;
        return;
    }

    const grouped = [{ key: cssClass, label: '', items: nuggets }];

    container.innerHTML = grouped.map((group) => {
        const groupOpen = group.label
            ? `<section class="signal-subtopic-group"><div class="signal-subtopic-header">${escapeHtml(group.label)}</div>`
            : '<section class="signal-subtopic-group signal-subtopic-group--plain">';
        return groupOpen + group.items.map((n) => renderSignalCard(n, cssClass)).join('') + '</section>';
    }).join('');
}

function renderBusinessCard(elementId, nuggets, subtopicKey) {
    const container = document.getElementById(elementId);
    if (!container) return;
    const items = (nuggets || []).filter((item) => item.business_subtopic === subtopicKey);
    container.innerHTML = items.length
        ? items.map((item) => renderSignalCard(item, 'business-focus')).join('')
        : `
            <div class="business-subtopic-empty">Nothing specific recorded yet.</div>
            <button type="button" class="signal-empty-add-btn" onclick="addSignalForCategory('business_focus', '${subtopicKey}')">Add intelligence</button>
        `;
}

// -- WORLD-CLASS 6-SECTION BRIEFING RENDERER ---------------------------

function renderPersonalIntel(pd) {
    const el = document.getElementById('personal-intel-display');
    if (!el) return;
    if (!pd || Object.keys(pd).length === 0) {
        el.innerHTML = `<p style="color:var(--text-muted); font-size:0.82rem;">No personal intelligence recorded yet. Click Edit to add details.</p>`;
        return;
    }
    const rows = [];
    if (pd.partner) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">Partner</span><div style="color:white; font-size:0.85rem; margin-top:2px;">${pd.partner}</div></div>`);
    if (pd.kids && pd.kids.length) {
        const kidsHtml = pd.kids.map(k =>
            `${k.name}${k.age ? ` (${k.age})` : ''}${k.school ? `, ${k.school}` : ''}${k.interests?.length ? ` loves ${k.interests.join(', ')}` : ''}`
        ).join('<br>');
        rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">Kids</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${kidsHtml}</div></div>`);
    }
    if (pd.hobbies?.length) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">Hobbies</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.hobbies.join(', ')}</div></div>`);
    if (pd.sports_teams?.length) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">Supports</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.sports_teams.join(', ')}</div></div>`);
    if (pd.university) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">University</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.university}</div></div>`);
    if (pd.hometown) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">From</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.hometown}</div></div>`);
    if (pd.personality) rows.push(`<div style="grid-column:span 2;"><span style="color:#f472b6; font-size:0.7rem;">Personality</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px; font-style:italic;">${pd.personality}</div></div>`);
    if (pd.upcoming_events?.length) rows.push(`<div style="grid-column:span 2;"><span style="color:#f472b6; font-size:0.7rem;">Upcoming</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.upcoming_events.join(' | ')}</div></div>`);
    el.innerHTML = `<div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem;">${rows.join('')}</div>`;
}

function openPersonalDataEditor() {
    const existing = document.getElementById('personal-data-modal');
    if (existing) { existing.remove(); return; }
    const pd = window._personPersonalData || {};
    const kidsArr = pd.kids || [];

    const modal = document.createElement('div');
    modal.id = 'personal-data-modal';
    modal.style = `position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(244,114,182,0.2);
                backdrop-filter:none; border-radius:16px; padding:2rem;
                z-index:9999; width:90%; max-width:560px; max-height:85vh; overflow-y:auto;
                box-shadow:0 24px 80px rgba(0,0,0,0.6);`;

    modal.innerHTML = `
                <div style="font-weight:800; font-size:1rem; color:#f472b6; margin-bottom:1.25rem;">Personal Intelligence</div>
                ${[
            ['Partner', 'partner', pd.partner || ''],
            ['University', 'university', pd.university || ''],
            ['Hometown / From', 'hometown', pd.hometown || ''],
            ['Hobbies (comma separated)', 'hobbies', (pd.hobbies || []).join(', ')],
            ['Sports Teams (comma separated)', 'sports_teams', (pd.sports_teams || []).join(', ')],
            ['Personality / Communication Style', 'personality', pd.personality || ''],
            ['Upcoming Personal Events (comma separated)', 'upcoming_events', (pd.upcoming_events || []).join(', ')],
        ].map(([lbl, key, val]) => `
                    <div style="margin-bottom:0.75rem;">
                        <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">${lbl}</div>
                        <input id="pd-${key}" value="${val.replace(/"/g, '&quot;')}" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:7px 12px; border-radius:8px; font-size:0.85rem; outline:none; box-sizing:border-box;">
                    </div>`).join('')}
                <div style="margin-bottom:0.75rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <div style="font-size:0.7rem; color:var(--text-muted);">Kids</div>
                        <button onclick="addKidRow()" style="font-size:0.7rem; padding:2px 8px; background:rgba(244,114,182,0.12); border:1px solid rgba(244,114,182,0.3); color:#f472b6; border-radius:4px; cursor:pointer;">+ Add Kid</button>
                    </div>
                    <div id="kids-table">
                        ${kidsArr.map((k, i) => `
                        <div class="kid-row" style="display:grid; grid-template-columns:1fr 60px 1fr 1fr auto; gap:6px; margin-bottom:6px; align-items:center;">
                            <input placeholder="Name" value="${k.name || ''}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <input placeholder="Age" value="${k.age || ''}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <input placeholder="School" value="${k.school || ''}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <input placeholder="Interests (comma)" value="${(k.interests || []).join(', ')}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <button onclick="this.closest('.kid-row').remove()" style="background:none; border:none; color:rgba(255,80,80,0.6); cursor:pointer; font-size:1rem;">Remove</button>
                        </div>`).join('')}
                    </div>
                </div>
                <div style="display:flex; gap:0.75rem; margin-top:1rem;">
                    <button onclick="savePersonalData()" style="flex:1; background:#f472b6; color:#0a0a1a; font-weight:800; padding:10px; border:none; border-radius:8px; cursor:pointer;">Save</button>
                    <button onclick="document.getElementById('personal-data-modal').remove()" style="flex:1; background:rgba(255,255,255,0.08); color:white; padding:10px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; cursor:pointer;">Cancel</button>
                </div>
            `;
    document.body.appendChild(modal);
}

function addKidRow() {
    const table = document.getElementById('kids-table');
    const row = document.createElement('div');
    row.className = 'kid-row';
    row.style = 'display:grid; grid-template-columns:1fr 60px 1fr 1fr auto; gap:6px; margin-bottom:6px; align-items:center;';
    row.innerHTML = `
                <input placeholder="Name" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <input placeholder="Age" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <input placeholder="School" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <input placeholder="Interests (comma)" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <button onclick="this.closest('.kid-row').remove()" style="background:none; border:none; color:rgba(255,80,80,0.6); cursor:pointer; font-size:1rem;">Remove</button>
            `;
    table.appendChild(row);
}

async function savePersonalData() {
    const g = id => document.getElementById(id)?.value.trim() || '';
    const splitComma = v => v ? v.split(',').map(x => x.trim()).filter(Boolean) : [];

    const kids = Array.from(document.querySelectorAll('.kid-row')).map(row => {
        const inputs = row.querySelectorAll('input');
        return {
            name: inputs[0]?.value.trim() || '',
            age: inputs[1]?.value.trim() || '',
            school: inputs[2]?.value.trim() || '',
            interests: splitComma(inputs[3]?.value || '')
        };
    }).filter(k => k.name);

    const pd = {
        partner: g('pd-partner') || undefined,
        university: g('pd-university') || undefined,
        hometown: g('pd-hometown') || undefined,
        hobbies: splitComma(g('pd-hobbies')),
        sports_teams: splitComma(g('pd-sports_teams')),
        personality: g('pd-personality') || undefined,
        upcoming_events: splitComma(g('pd-upcoming_events')),
        kids: kids.length ? kids : undefined
    };
    // Clean undefined
    Object.keys(pd).forEach(k => (pd[k] === undefined || (Array.isArray(pd[k]) && !pd[k].length)) && delete pd[k]);

    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ personal_data: pd })
        });
        document.getElementById('personal-data-modal')?.remove();
        if (res.ok) {
            window._personPersonalData = pd;
            renderPersonalIntel(pd);
            toast('Personal intelligence updated', 'success');
        } else {
            toast('Save failed', 'error');
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

// -- EDIT PROFILE HEADER MODAL -----------------------------------------

let currentEmploymentHistory = [];

function calcDuration(start, end) {
    if (!start || start === '?') return '';
    try {
        const [sy, sm = '01'] = start.split('-');
        const endDate = (end && end !== 'Present') ? end : null;
        const [ey, em = '01'] = endDate ? endDate.split('-') : [new Date().getFullYear(), String(new Date().getMonth() + 1).padStart(2, '0')];
        const months = (parseInt(ey) - parseInt(sy)) * 12 + (parseInt(em) - parseInt(sm));
        if (months < 0) return '';
        const y = Math.floor(months / 12), m = months % 12;
        return y > 0 && m > 0 ? `${y}y ${m}m` : y > 0 ? `${y}y` : `${m}m`;
    } catch { return ''; }
}

function careerDisplayValue(...values) {
    for (const value of values) {
        const text = String(value || '').trim();
        if (text) return text;
    }
    return '';
}

function careerDurationBadge(start, end) {
    const raw = calcDuration(start, end);
    if (!raw) return '';
    const yearMatch = raw.match(/(\d+)y/);
    const monthMatch = raw.match(/(\d+)m/);
    const years = yearMatch ? parseInt(yearMatch[1], 10) : 0;
    const months = monthMatch ? parseInt(monthMatch[1], 10) : 0;
    if (years > 0) {
        return `${years}y${months > 0 ? '+' : ''}`;
    }
    return months > 0 ? `${months}m` : raw;
}

function normalizeCareerRole(role) {
    const title = careerDisplayValue(
        role?.title,
        role?.role,
        role?.position,
        role?.job_title
    ) || 'Untitled role';
    const company = careerDisplayValue(
        role?.company,
        role?.employer,
        role?.company_name,
        role?.employer_name,
        role?.organization,
        role?.organisation,
        role?.institution
    ) || 'Employer not listed';
    const location = careerDisplayValue(role?.location, role?.city, role?.region);
    const start = careerDisplayValue(role?.start_date, role?.from_date, role?.start);
    const end = careerDisplayValue(role?.end_date, role?.to_date, role?.end);
    return { title, company, location, start, end };
}

function buildCareerTimelineMarkup(roles) {
    if (roles && roles.length > 0) {
        const staggerPattern = [0, 22, 44, 66];
        return `
                <div class="employment-grid employment-grid-shell">
                    <div class="employment-grid-header">
                        <span>Employer</span>
                        <span>Role</span>
                        <span>Dates</span>
                        <span>Duration</span>
                        <span>Location</span>
                        <span></span>
                    </div>
                    ${roles.map((role, idx) => {
            const normalized = normalizeCareerRole(role);
            const isCurrent = !normalized.end;
            const dur = careerDurationBadge(normalized.start, normalized.end || 'Present');
            const dateStr = normalized.start
                ? `${normalized.start}${normalized.end ? ' to ' + normalized.end : ' to now'}`
                : 'Not set';
            const stagger = staggerPattern[idx % staggerPattern.length];
            return `
                        <article class="career-row-card${isCurrent ? ' is-current' : ''}" id="career-row-${idx}" style="--career-stagger:${stagger}px;">
                            <div class="career-row-employer">${escapeHtml(normalized.company)}</div>
                            <div class="career-row-role">
                                <div class="career-row-role-title">${escapeHtml(normalized.title)}</div>
                                ${normalized.location ? `<div class="career-row-role-mobile-meta">${escapeHtml(normalized.location)}</div>` : ''}
                            </div>
                            <div class="career-row-dates">${escapeHtml(dateStr)}</div>
                            <div class="career-row-duration">${dur ? `Duration ${escapeHtml(dur)}` : 'Duration n/a'}</div>
                            <div class="career-row-location">${escapeHtml(normalized.location || 'Location not listed')}</div>
                            <div class="career-row-actions">
                                <button onclick="editRole(${idx})" title="Edit" class="career-row-btn">Edit</button>
                                <button onclick="deleteRole(${idx})" title="Delete" class="career-row-btn career-row-btn-danger">Remove</button>
                            </div>
                        </article>`;
        }).join('')}
                </div>`;
    }
    return `<p style="color:var(--text-muted); font-size:0.85rem;">No career history yet. Click Add Role to start building the timeline.</p>`;
}

function renderCareerTimeline(roles) {
    currentEmploymentHistory = roles || [];
    const timelineEl = document.getElementById('employment-timeline');
    if (!timelineEl) return;
    timelineEl.innerHTML = buildCareerTimelineMarkup(currentEmploymentHistory);
}

function normalizeCareerCellText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function isLegacyIconLabel(text) {
    const normalized = normalizeCareerCellText(text).toLowerCase();
    return ['in', 'ln', 'li'].includes(normalized);
}

function looksLikeCareerDate(text) {
    return /\b\d{4}(?:[./-]\d{1,2})?\s*(?:-|to)\s*(?:\d{4}(?:[./-]\d{1,2})?|now|present)\b/i.test(text);
}

function looksLikeCareerDuration(text) {
    return /^duration\b/i.test(normalizeCareerCellText(text));
}

function looksLikeCareerLocation(text) {
    const normalized = normalizeCareerCellText(text);
    return normalized.includes(',') || /\b(?:uae|ksa|saudi arabia|qatar|malaysia|ireland|united kingdom|australia|dubai|abu dhabi|riyadh|doha|jeddah|kuwait)\b/i.test(normalized);
}

function collectLegacyCareerCells(rowEl) {
    const directCells = Array.from(rowEl.children || [])
        .map((child) => normalizeCareerCellText(child.innerText || child.textContent || ''))
        .filter(Boolean)
        .filter((text) => !isLegacyIconLabel(text));

    if (directCells.length >= 4) {
        return directCells;
    }

    const leafCells = Array.from(rowEl.querySelectorAll('*'))
        .filter((el) => el.children.length === 0)
        .map((el) => normalizeCareerCellText(el.innerText || el.textContent || ''))
        .filter(Boolean)
        .filter((text) => !isLegacyIconLabel(text));

    return leafCells.filter((text, index) => leafCells.indexOf(text) === index);
}

function parseLegacyCareerRow(rowEl) {
    const cells = collectLegacyCareerCells(rowEl);
    if (!cells.length) return null;

    const date = cells.find(looksLikeCareerDate) || '';
    const durationCell = cells.find(looksLikeCareerDuration) || '';
    const location = [...cells].reverse().find((text) => looksLikeCareerLocation(text) && text !== durationCell) || '';

    const filtered = cells.filter((text) => text !== date && text !== durationCell && text !== location);
    const company = filtered[0] || '';
    const title = filtered.slice(1).join(' ').trim() || filtered[0] || '';

    const [start = '', end = ''] = date
        ? date.split(/\s*(?:-|to)\s*/i).map((part) => part.trim())
        : ['', ''];

    if (!company && !title && !date && !durationCell && !location) return null;
    return normalizeCareerRole({
        company,
        title,
        start_date: start,
        end_date: /^(now|present)$/i.test(end) ? '' : end,
        location,
    });
}

function findLegacyCareerRows(root) {
    const directRows = Array.from(root.children || []).filter((el) => /\bDuration\b|\b\d{4}/i.test(el.innerText || ''));
    if (directRows.length >= 2) return directRows;

    for (const child of Array.from(root.children || [])) {
        const nestedRows = Array.from(child.children || []).filter((el) => /\bDuration\b|\b\d{4}/i.test(el.innerText || ''));
        if (nestedRows.length >= 2) return nestedRows;
    }
    return [];
}

function normalizeLegacyCareerTimeline() {
    const timelineEl = document.getElementById('employment-timeline');
    if (!timelineEl || timelineEl.querySelector('.career-row-card')) return;

    const legacyRows = findLegacyCareerRows(timelineEl);
    if (legacyRows.length < 2) return;

    const roles = legacyRows
        .map(parseLegacyCareerRow)
        .filter((role) => role && (role.company || role.title || role.start || role.location));

    if (roles.length < 2) return;
    timelineEl.innerHTML = buildCareerTimelineMarkup(roles);
}

let careerTimelineObserverReady = false;

function ensureCareerTimelineObserver() {
    if (careerTimelineObserverReady) return;
    const timelineEl = document.getElementById('employment-timeline');
    if (!timelineEl) return;

    const observer = new MutationObserver(() => {
        window.requestAnimationFrame(() => normalizeLegacyCareerTimeline());
    });
    observer.observe(timelineEl, { childList: true, subtree: true });
    careerTimelineObserverReady = true;
    normalizeLegacyCareerTimeline();
}

function openRoleModal(idx) {
    const existing = document.getElementById('role-edit-modal');
    if (existing) existing.remove();

    const isNew = idx === -1;
    const role = isNew ? {} : currentEmploymentHistory[idx];
    const modal = document.createElement('div');
    modal.id = 'role-edit-modal';
    modal.style = `
                position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(255,255,255,0.15);
                backdrop-filter:none; border-radius:16px; padding:2rem;
                z-index:9999; min-width:340px; max-width:540px; width:90%;
                box-shadow:0 24px 80px rgba(0,0,0,0.6);
            `;
    modal.innerHTML = `
                <div style="font-weight:800; font-size:1rem; color:var(--accent-cyan); margin-bottom:1.25rem;">${isNew ? 'Add Role' : 'Edit Role'}</div>
                ${[
            ['Job Title', 'title', role.title || ''],
            ['Company', 'company', role.company || ''],
            ['Start Date (YYYY-MM)', 'start_date', role.start_date || ''],
            ['End Date (YYYY-MM, blank = Present)', 'end_date', role.end_date || ''],
            ['Location', 'location', role.location || ''],
        ].map(([lbl, key, val]) => `
                    <div style="margin-bottom:0.75rem;">
                        <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">${lbl}</div>
                        <input id="role-${key}" value="${val}" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:white; padding:7px 12px; border-radius:8px; font-size:0.85rem; outline:none; box-sizing:border-box;">
                    </div>`).join('')}
                <div style="margin-bottom:1rem;">
                    <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">Description</div>
                    <textarea id="role-description" rows="3" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:white; padding:7px 12px; border-radius:8px; font-size:0.85rem; outline:none; resize:vertical; box-sizing:border-box;">${role.description || ''}</textarea>
                </div>
                <div style="display:flex; gap:0.75rem;">
                    <button onclick="saveRole(${idx})" style="flex:1; background:var(--accent-cyan); color:#0a0a1a; font-weight:800; padding:10px; border:none; border-radius:8px; cursor:pointer;">Save</button>
                    <button onclick="document.getElementById('role-edit-modal').remove()" style="flex:1; background:rgba(255,255,255,0.08); color:white; padding:10px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; cursor:pointer;">Cancel</button>
                </div>
            `;
    document.body.appendChild(modal);
}

function addRole() { openRoleModal(-1); }
function editRole(idx) { openRoleModal(idx); }

async function saveRole(idx) {
    const newRole = {
        title: document.getElementById('role-title').value.trim() || null,
        company: document.getElementById('role-company').value.trim() || null,
        start_date: document.getElementById('role-start_date').value.trim() || null,
        end_date: document.getElementById('role-end_date').value.trim() || null,
        location: document.getElementById('role-location').value.trim() || null,
        description: document.getElementById('role-description').value.trim() || null,
    };
    // Remove nulls
    Object.keys(newRole).forEach(k => newRole[k] === null && delete newRole[k]);

    const updated = [...currentEmploymentHistory];
    if (idx === -1) {
        updated.unshift(newRole); // Add at top
    } else {
        updated[idx] = newRole;
    }

    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employment_history: updated })
        });
        document.getElementById('role-edit-modal')?.remove();
        if (res.ok) {
            currentEmploymentHistory = updated;
            renderCareerTimeline(updated);
            toast('Career role saved', 'success');
        } else {
            toast('Failed to save role', 'error');
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}

async function deleteRole(idx) {
    const confirmed = await showConfirmDialog({
        title: 'Delete role?',
        message: 'This removes the role from the employment history timeline.',
        confirmLabel: 'Delete Role',
    });
    if (!confirmed) return;
    const updated = currentEmploymentHistory.filter((_, i) => i !== idx);
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employment_history: updated })
        });
        if (res.ok) {
            currentEmploymentHistory = updated;
            renderCareerTimeline(updated);
            toast('Role removed', 'success');
        } else {
            toast('Failed to delete role', 'error');
        }
    } catch (e) {
        toast(`Error: ${e.message}`, 'error');
    }
}


// Scroll Logic - Robust "Scroll Everything" Approach

