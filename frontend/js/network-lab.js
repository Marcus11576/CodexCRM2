let networkWorkspace = null;
let networkOwners = [];
let activeQueueKey = 'act_now';
let selectedPeople = new Set();
let activeReviewKey = 'missing_tier';
let pilotOnly = true;
let networkSearchTerm = '';
let reviewWorkspaceCollapsed = false;

function setStatus(message, tone = '') {
    const target = document.getElementById('network-lab-status');
    if (!target) return;
    target.textContent = message;
    target.className = 'network-lab-status';
    if (tone) target.classList.add(`is-${tone}`);
}

function escapeLab(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function normalizeLabReason(reason) {
    if (typeof reason === 'string') {
        return { text: reason, evidence: 'inferred' };
    }
    return {
        text: String(reason?.text || ''),
        evidence: String(reason?.evidence || 'inferred'),
    };
}

function selectedIds() {
    return Array.from(selectedPeople);
}

function renderOwnerSelect(elementId, allowBlank = true) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const options = [];
    if (allowBlank) options.push('<option value="">Leave unchanged</option>');
    options.push(...networkOwners.map((owner) => `<option value="${escapeLab(owner.full_name)}">${escapeLab(owner.full_name)}</option>`));
    el.innerHTML = options.join('');
}

function renderQueueCards() {
    const target = document.getElementById('queue-cards');
    const queues = [
        ['act_now', 'Act Now', networkWorkspace.summary.act_now_count, 'Urgent coverage or opportunity pressure'],
        ['maintain', 'Maintain', networkWorkspace.summary.maintain_count, 'Strategic relationships in active upkeep'],
        ['preserve', 'Preserve', networkWorkspace.summary.preserve_count, 'Keep-warm network value'],
        ['monitor', 'Monitor', networkWorkspace.summary.monitor_count, 'Trigger-led visibility without noise'],
    ];
    target.innerHTML = queues.map(([key, title, count, meta]) => `
        <button type="button" class="network-lab-card ${activeQueueKey === key ? 'active' : ''}" onclick="setActiveQueue('${key}')">
            <h3>${title}</h3>
            <div class="network-lab-count">${count}</div>
            <div class="network-lab-meta">${meta}</div>
        </button>
    `).join('');
}

function filteredItems(items) {
    const allItems = items || [];
    const pilotIds = new Set((networkWorkspace && networkWorkspace.pilot_cohort_ids) || []);
    const pilotFiltered = pilotOnly
        ? allItems.filter((item) => pilotIds.has(item.person_id))
        : allItems;
    if (!networkSearchTerm) return pilotFiltered;
    const query = networkSearchTerm.toLowerCase();
    return pilotFiltered.filter((item) => {
        const haystack = [
            item.full_name,
            item.title_current,
            item.company_name_raw,
            item.queue_reason,
            item.relationship_owner,
            item.effective_network_tier_label,
            item.maintenance_mode,
        ]
            .map((value) => String(value || '').toLowerCase())
            .join(' ');
        return haystack.includes(query);
    });
}

function renderQueueList() {
    const target = document.getElementById('queue-list');
    const title = document.getElementById('active-queue-title');
    const queueTitles = {
        act_now: 'Act Now',
        maintain: 'Maintain',
        preserve: 'Preserve',
        monitor: 'Monitor',
    };
    title.textContent = queueTitles[activeQueueKey];
    const items = filteredItems(networkWorkspace[activeQueueKey] || []);
    target.innerHTML = items.map((item) => {
        const isSelected = selectedPeople.has(item.person_id);
        const chips = [
            `<span class="network-chip">${escapeLab(item.effective_network_tier_label || 'Unscored')}</span>`,
            `<span class="network-chip warn">${escapeLab(item.maintenance_mode || 'No mode')}</span>`,
            `<span class="network-chip">${escapeLab(item.relationship_owner || 'No owner')}</span>`,
            item.has_future_cover ? '<span class="network-chip">Covered</span>' : '<span class="network-chip alert">No next step</span>',
        ].join('');
        return `
            <div class="network-contact-card ${selectedPeople.has(item.person_id) ? 'is-selected' : ''}">
                <div class="network-contact-head">
                    <div>
                        <div style="font-weight:800;">${escapeLab(item.full_name)}</div>
                        <div class="network-lab-subtle">${escapeLab(item.title_current || 'No title')} @ ${escapeLab(item.company_name_raw || 'Unknown')}</div>
                    </div>
                    <button type="button" class="network-select-button ${isSelected ? 'is-selected' : ''}" onclick="toggleSelectedPerson('${item.person_id}')">
                        ${isSelected ? 'Selected for Bulk Actions' : 'Select for Bulk Actions'}
                    </button>
                </div>
                <div class="network-chip-row">${chips}</div>
                <div class="network-inline-row">
                    <div class="network-score-badge" title="${escapeLab((item.score_reason_summary || []).map((reason) => normalizeLabReason(reason).text).join(' | '))}">
                        <span>${item.network_health_score}</span><span>${escapeLab((item.score_band || 'Score').toLowerCase())}</span>
                    </div>
                    <a class="network-lab-button secondary" href="/person/${encodeURIComponent(item.person_id)}">Open Profile</a>
                </div>
                <div style="margin-top:0.8rem;"><strong>${escapeLab(item.queue_reason || 'No queue reason')}</strong></div>
                <div class="network-lab-subtle" style="margin-top:0.4rem;">Recency ${item.recency_days ?? 'n/a'}d | Open opportunities ${item.open_opportunity_count || 0}</div>
                <div class="network-lab-subtle" style="margin-top:0.35rem;">${
                    escapeLab(normalizeLabReason((item.score_reason_summary || [])[0] || { text: 'Open profile to inspect score rationale', evidence: 'inferred' }).text)
                }</div>
            </div>
        `;
    }).join('');
}

function renderReviewTable() {
    const body = document.getElementById('review-table-body');
    const rows = filteredItems(networkWorkspace.review?.[activeReviewKey] || []);
    body.innerHTML = rows.map((item) => `
        <tr>
            <td><input type="checkbox" ${selectedPeople.has(item.person_id) ? 'checked' : ''} onchange="toggleSelectedPerson('${item.person_id}')"></td>
            <td>
                <strong>${escapeLab(item.full_name)}</strong><br>
                <span class="network-lab-subtle">${escapeLab(item.company_name_raw || 'Unknown')}</span>
            </td>
            <td>${escapeLab(item.queue_reason || '')}</td>
            <td>${item.network_health_score}</td>
            <td>${escapeLab(item.queue_reason || '')}</td>
            <td>${escapeLab((item.tier_reason_trace || []).join(' | '))}</td>
        </tr>
    `).join('');
}

function syncReviewWorkspaceVisibility() {
    const body = document.getElementById('review-workspace-body');
    const button = document.getElementById('review-workspace-toggle-btn');
    if (!body || !button) return;
    body.style.display = reviewWorkspaceCollapsed ? 'none' : '';
    button.textContent = reviewWorkspaceCollapsed ? 'Expand' : 'Collapse';
}

function toggleReviewWorkspace() {
    reviewWorkspaceCollapsed = !reviewWorkspaceCollapsed;
    syncReviewWorkspaceVisibility();
}

function updateSelectedCount() {
    const target = document.getElementById('selected-count');
    if (target) target.textContent = String(selectedPeople.size);
}

function renderPilotSummary() {
    const target = document.getElementById('pilot-cohort-summary');
    const button = document.getElementById('pilot-toggle-btn');
    const lockButton = document.getElementById('pilot-lock-btn');
    const clearButton = document.getElementById('pilot-clear-btn');
    if (target) {
        const summary = networkWorkspace.pilot_cohort_summary || {};
        target.textContent = summary.message || 'Pilot cohort is loading.';
    }
    if (button) {
        button.textContent = pilotOnly ? 'Showing Pilot Cohort' : 'Showing All Contacts';
    }
    if (lockButton) {
        lockButton.textContent = 'Lock Selected as Pilot';
    }
    if (clearButton) {
        const mode = String(networkWorkspace?.pilot_cohort_mode || 'recommended');
        clearButton.disabled = mode !== 'explicit';
        clearButton.textContent = mode === 'explicit' ? 'Return to Recommended Pilot' : 'Using Recommended Pilot';
    }
}

function setActiveQueue(queueKey) {
    activeQueueKey = queueKey;
    renderQueueCards();
    renderQueueList();
}

function toggleSelectedPerson(personId) {
    if (selectedPeople.has(personId)) selectedPeople.delete(personId);
    else selectedPeople.add(personId);
    updateSelectedCount();
    renderQueueList();
    renderReviewTable();
}

function togglePilotView() {
    pilotOnly = !pilotOnly;
    renderPilotSummary();
    renderQueueList();
    renderReviewTable();
}

function selectPilotCohort() {
    if (!networkWorkspace) {
        setStatus('Workspace has not loaded yet. Refresh the page or sign in again.', 'error');
        return;
    }
    selectedPeople = new Set(networkWorkspace.pilot_cohort_ids || []);
    updateSelectedCount();
    renderQueueList();
    renderReviewTable();
    setStatus(`Selected ${selectedPeople.size} pilot contacts.`, 'success');
}

async function setSelectedAsPilotCohort() {
    const personIds = selectedIds();
    if (!personIds.length) {
        setStatus('Select the contacts that should define the pilot cohort first.', 'error');
        return;
    }
    const res = await fetch(`${API_BASE}/api/network-lab/pilot-cohort`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ person_ids: personIds }),
    });
    if (!res.ok) {
        const detail = await res.text();
        setStatus(`Failed to set the pilot cohort. ${detail}`, 'error');
        return;
    }
    const data = await res.json();
    setStatus(`Locked ${data.assigned_count || personIds.length} contacts as the explicit pilot cohort.`, 'success');
    await refreshNetworkLab();
}

async function clearExplicitPilotCohort() {
    const res = await fetch(`${API_BASE}/api/network-lab/pilot-cohort`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ person_ids: [] }),
    });
    if (!res.ok) {
        const detail = await res.text();
        setStatus(`Failed to clear the explicit pilot cohort. ${detail}`, 'error');
        return;
    }
    await res.json();
    setStatus('Explicit pilot cohort cleared. The workspace is back on the recommended pilot set.', 'success');
    await refreshNetworkLab();
}

function visibleQueuePersonIds() {
    return filteredItems(networkWorkspace[activeQueueKey] || []).map((item) => item.person_id);
}

function selectVisibleContacts() {
    if (!networkWorkspace) {
        setStatus('Workspace has not loaded yet. Refresh the page or sign in again.', 'error');
        return;
    }
    for (const personId of visibleQueuePersonIds()) {
        selectedPeople.add(personId);
    }
    updateSelectedCount();
    renderQueueList();
    renderReviewTable();
    setStatus(`Selected ${selectedPeople.size} visible contacts.`, 'success');
}

function clearSelectedContacts() {
    selectedPeople.clear();
    updateSelectedCount();
    renderQueueList();
    renderReviewTable();
    setStatus('Selection cleared.', 'success');
}

async function applyQuickBulkAction() {
    const personIds = selectedIds();
    if (!personIds.length) {
        setStatus('Select at least one contact first. Use Select Pilot Cohort, Select Visible, or a card button.', 'error');
        return;
    }
    const payload = {
        person_ids: personIds,
        network_tier: document.getElementById('bulk-network-tier').value || null,
        maintenance_mode: document.getElementById('bulk-maintenance-mode').value || null,
        relationship_owner: document.getElementById('bulk-owner').value || null,
        account_priority: document.getElementById('bulk-account-priority').value || null,
        create_task_text: document.getElementById('bulk-task-text').value.trim() || null,
        create_task_due_date: document.getElementById('bulk-task-due-date').value || null,
    };
    const res = await fetch(`${API_BASE}/api/network-lab/bulk-update`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const detail = await res.text();
        setStatus(`Bulk update failed. ${detail}`, 'error');
        return;
    }
    selectedPeople.clear();
    setStatus(`Bulk update applied to ${personIds.length} contacts.`, 'success');
    await refreshNetworkLab();
}

async function refreshNetworkLab() {
    setStatus('Loading workspace...');
    try {
        const [workspaceRes, ownersRes] = await Promise.all([
            fetch(`${API_BASE}/api/network-lab/workspace`, { credentials: 'same-origin' }),
            fetch(`${API_BASE}/api/network-lab/owners`, { credentials: 'same-origin' }),
        ]);
        if (!workspaceRes.ok || !ownersRes.ok) {
            const statusBits = [`workspace ${workspaceRes.status}`, `owners ${ownersRes.status}`];
            throw new Error(`Network Lab data failed to load (${statusBits.join(', ')}).`);
        }
        networkWorkspace = await workspaceRes.json();
        networkOwners = (await ownersRes.json()).owners || [];
        renderOwnerSelect('bulk-owner');
        renderPilotSummary();
        renderQueueCards();
        renderQueueList();
        renderReviewTable();
        updateSelectedCount();
        setStatus(`Workspace loaded. Pilot cohort has ${networkWorkspace.pilot_cohort_summary?.recommended_size || 0} suggested contacts.`);
    } catch (error) {
        console.error(error);
        networkWorkspace = null;
        networkOwners = [];
        setStatus(error.message || 'Network Lab failed to load. Refresh the page or sign in again.', 'error');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const reviewFilter = document.getElementById('review-filter');
    reviewFilter.addEventListener('change', () => {
        activeReviewKey = reviewFilter.value;
        renderReviewTable();
    });
    const searchInput = document.getElementById('network-search-input');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            networkSearchTerm = searchInput.value.trim();
            renderQueueList();
            renderReviewTable();
        });
    }
    syncReviewWorkspaceVisibility();
    await refreshNetworkLab();
});
