let networkReviewQueue = null;
let reviewScope = 'pilot';
let activeReviewDomain = 'interpreted_drafts';

function setReviewStatusMessage(message, tone = '') {
    const target = document.getElementById('network-lab-review-status');
    if (!target) return;
    target.textContent = message;
    target.className = 'network-lab-status';
    if (tone) target.classList.add(`is-${tone}`);
}

function escReview(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderReviewSummaryCards() {
    const summary = networkReviewQueue?.summary || {};
    const target = document.getElementById('review-summary-cards');
    const cards = [
        ['interpreted_drafts', 'Draft Interpretations', summary.interpreted_draft_count || 0, 'Draft intelligence waiting for operator review and promotion.'],
        ['enduring_memory', 'Enduring Memory', summary.enduring_pending_count || 0, 'Promoted memory that still needs an explicit operator decision.'],
        ['market_intel', 'Market Intel', summary.market_pending_count || 0, 'Promoted market signals waiting for approval or rejection.'],
        ['market_themes', 'Market Themes', summary.theme_count || 0, 'Cross-contact market clusters emerging from the approved and pending signal set.'],
    ];
    target.innerHTML = cards.map(([key, title, count, meta]) => `
        <button type="button" class="network-lab-card ${activeReviewDomain === key ? 'active' : ''}" onclick="setReviewDomain('${key}')">
            <h3>${title}</h3>
            <div class="network-lab-count">${count}</div>
            <div class="network-lab-meta">${meta}</div>
        </button>
    `).join('');
}

function setReviewDomain(key) {
    activeReviewDomain = key;
    const filter = document.getElementById('review-domain-filter');
    if (filter) filter.value = key;
    renderReviewSummaryCards();
    renderReviewList();
}

function renderReviewList() {
    const titles = {
        interpreted_drafts: ['Draft Interpretations', 'Review interpreted intelligence first, then promote only what deserves enduring memory or market intel status.'],
        enduring_memory: ['Enduring Memory', 'Review relationship, opportunity, market, influence, and risk memory before it becomes trusted memory.'],
        market_intel: ['Market Intel', 'Review promoted market signals and keep the databank grounded and useful.'],
        market_themes: ['Market Themes', 'Monitor how promoted market signals cluster across people and companies.'],
    };
    document.getElementById('review-section-title').textContent = titles[activeReviewDomain][0];
    document.getElementById('review-section-subtitle').textContent = titles[activeReviewDomain][1];

    const target = document.getElementById('review-list');
    const items = networkReviewQueue?.[activeReviewDomain] || [];
    if (!items.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No review items in this section right now.</div></div>';
        return;
    }

    if (activeReviewDomain === 'market_themes') {
        target.innerHTML = items.map((item) => `
            <div class="network-contact-card">
                <div class="network-chip-row">
                    <span class="network-chip">Theme</span>
                    <span class="network-chip warn">${escReview(item.count)} signals</span>
                    <span class="network-chip">${escReview(item.people_count)} people</span>
                    <span class="network-chip">${escReview(item.company_count)} companies</span>
                    <span class="network-chip">${escReview(item.draft_count)} pending</span>
                    <span class="network-chip">${escReview(item.approved_count)} approved</span>
                </div>
                <div style="font-weight:800;">${escReview(item.theme || 'No theme')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${escReview((item.evidence_snippets || []).join(' | ') || 'No evidence snippets captured')}</div>
            </div>
        `).join('');
        return;
    }

    if (activeReviewDomain === 'interpreted_drafts') {
        target.innerHTML = items.map((item) => `
            <div class="network-contact-card">
                <div class="network-contact-head">
                    <div>
                        <div style="font-weight:800;">${escReview(item.full_name || 'Unknown contact')}</div>
                        <div class="network-lab-subtle">${escReview(item.title_current || 'No title')} @ ${escReview(item.company_name_raw || 'Unknown')}</div>
                    </div>
                    ${item.person_id ? `<a class="network-lab-button secondary" href="/network-lab/profile/${encodeURIComponent(item.person_id)}">Open Profile</a>` : ''}
                </div>
                <div class="network-chip-row">
                    <span class="network-chip">${escReview(item.stage || 'Relationship Update')}</span>
                    <span class="network-chip warn">${escReview(item.source_channel || 'unknown')}</span>
                    <span class="network-chip">${escReview(item.network_tier || 'No tier')}</span>
                    <span class="network-chip">${escReview(item.relationship_owner || 'No owner')}</span>
                    <span class="network-chip">Confidence ${escReview(item.confidence_score || 0)}</span>
                    ${item.promoted_market_intel_status ? `<span class="network-chip">Market ${escReview(item.promoted_market_intel_status)}</span>` : ''}
                </div>
                <div style="font-weight:800;">${escReview(item.what_is_happening || 'No interpretation')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Why it matters:</strong> ${escReview(item.why_it_matters || 'No explanation')}</div>
                <div class="network-intelligence-tag-grid">
                    ${(item.opportunity_signals || []).slice(0, 2).map((value) => `<span class="network-chip">${escReview(value)}</span>`).join('')}
                    ${(item.market_intel_signals || []).slice(0, 2).map((value) => `<span class="network-chip warn">${escReview(value)}</span>`).join('')}
                    ${(item.relationship_signals || []).slice(0, 2).map((value) => `<span class="network-chip">${escReview(value)}</span>`).join('')}
                    ${(item.intent_signals || []).slice(0, 2).map((value) => `<span class="network-chip">${escReview(value)}</span>`).join('')}
                </div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence snippets:</strong> ${escReview((item.evidence_snippets || []).join(' | ') || 'No snippets captured')}</div>
                <details class="network-evidence-detail">
                    <summary>View Full Evidence</summary>
                    <div class="network-evidence-body">${escReview(item.full_evidence_text || 'No full evidence available').replace(/\n/g, '<br>')}</div>
                </details>
                <div class="network-lab-actions" style="margin-top:0.8rem;">
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretationMemory('${encodeURIComponent(item.interpretation_id)}', 'rapport')">Promote Rapport Memory</button>
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretationMemory('${encodeURIComponent(item.interpretation_id)}', 'opportunity')">Promote Opportunity Memory</button>
                    <button class="network-lab-button secondary" type="button" onclick="promoteInterpretationMemory('${encodeURIComponent(item.interpretation_id)}', 'market')">Promote Market Memory</button>
                    <button class="network-lab-button" type="button" onclick="promoteInterpretationMarketIntel('${encodeURIComponent(item.interpretation_id)}')">Promote Market Intel</button>
                </div>
            </div>
        `).join('');
        return;
    }

    target.innerHTML = items.map((item) => {
        const id = activeReviewDomain === 'enduring_memory' ? item.memory_id : item.market_intel_id;
        const actionType = activeReviewDomain === 'enduring_memory' ? 'memory' : 'market';
        const primaryText = activeReviewDomain === 'enduring_memory' ? item.memory_text : item.signal_text;
        const subtitle = `${item.title_current || 'No title'} @ ${item.company_name_raw || 'Unknown'}`;
        const metaChip = activeReviewDomain === 'enduring_memory'
            ? `${item.memory_domain || 'memory'}`
            : `${item.topic || 'market intel'}`;
        return `
            <div class="network-contact-card">
                <div class="network-contact-head">
                    <div>
                        <div style="font-weight:800;">${escReview(item.full_name || 'Unknown contact')}</div>
                        <div class="network-lab-subtle">${escReview(subtitle)}</div>
                    </div>
                    ${item.person_id ? `<a class="network-lab-button secondary" href="/network-lab/profile/${encodeURIComponent(item.person_id)}">Open Profile</a>` : ''}
                </div>
                <div class="network-chip-row">
                    <span class="network-chip">${escReview(metaChip)}</span>
                    <span class="network-chip warn">${escReview(item.status || 'draft')}</span>
                    <span class="network-chip">${escReview(item.network_tier || 'No tier')}</span>
                    <span class="network-chip">${escReview(item.relationship_owner || 'No owner')}</span>
                    <span class="network-chip">Confidence ${escReview(item.confidence_score || 0)}</span>
                </div>
                <div style="font-weight:800;">${escReview(primaryText || 'No text')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${escReview((item.evidence_snippets || []).join(' | ') || 'No evidence snippets captured')}</div>
                <details class="network-evidence-detail">
                    <summary>View Full Evidence</summary>
                    <div class="network-evidence-body">${escReview(item.full_evidence_text || 'No full evidence available').replace(/\n/g, '<br>')}</div>
                </details>
                <div class="network-lab-actions" style="margin-top:0.8rem;">
                    <button class="network-lab-button" type="button" onclick="updateReviewStatus('${actionType}', '${encodeURIComponent(id)}', 'approved')">Approve</button>
                    <button class="network-lab-button secondary" type="button" onclick="updateReviewStatus('${actionType}', '${encodeURIComponent(id)}', 'draft')">Return to Draft</button>
                    <button class="network-lab-button secondary" type="button" onclick="updateReviewStatus('${actionType}', '${encodeURIComponent(id)}', 'rejected')">Reject</button>
                    <button class="network-lab-button secondary" type="button" onclick="updateReviewStatus('${actionType}', '${encodeURIComponent(id)}', 'archived')">Archive</button>
                </div>
            </div>
        `;
    }).join('');
}

async function promoteInterpretationMemory(interpretationId, memoryDomain) {
    const response = await fetch(`${API_BASE}/api/network-lab/interpretations/${interpretationId}/promote-memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_domain: memoryDomain, status: 'draft' }),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        setReviewStatusMessage('Failed to promote interpretation into memory review.', 'error');
        return;
    }
    setReviewStatusMessage('Interpretation promoted into memory review.', 'success');
    await refreshReviewQueue();
}

async function promoteInterpretationMarketIntel(interpretationId) {
    const response = await fetch(`${API_BASE}/api/network-lab/interpretations/${interpretationId}/promote-market-intel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'draft' }),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        setReviewStatusMessage('Failed to promote interpretation into market-intel review.', 'error');
        return;
    }
    setReviewStatusMessage('Interpretation promoted into market-intel review.', 'success');
    await refreshReviewQueue();
}

async function updateReviewStatus(type, itemId, status) {
    const path = type === 'memory'
        ? `${API_BASE}/api/network-lab/memory/${itemId}/status`
        : `${API_BASE}/api/network-lab/market-intel/${itemId}/status`;
    const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status }),
        credentials: 'same-origin',
    });
    if (!response.ok) {
        setReviewStatusMessage('Failed to update review status.', 'error');
        return;
    }
    setReviewStatusMessage(`Updated item to ${status}.`, 'success');
    await refreshReviewQueue();
}

function toggleReviewScope() {
    reviewScope = reviewScope === 'pilot' ? 'all' : 'pilot';
    const button = document.getElementById('review-scope-btn');
    if (button) {
        button.textContent = reviewScope === 'pilot' ? 'Showing Pilot Cohort' : 'Showing All Contacts';
    }
    refreshReviewQueue();
}

async function refreshReviewQueue() {
    setReviewStatusMessage('Loading review queue...');
    try {
        const response = await fetch(`${API_BASE}/api/network-lab/review-queue?scope=${encodeURIComponent(reviewScope)}`, {
            credentials: 'same-origin',
        });
        if (!response.ok) {
            throw new Error(`Review queue failed to load (${response.status}).`);
        }
        networkReviewQueue = await response.json();
        renderReviewSummaryCards();
        renderReviewList();
        setReviewStatusMessage(`Review queue loaded for ${reviewScope === 'pilot' ? 'the pilot cohort' : 'all contacts'}. Old correspondence beyond 4 years is excluded.`);
    } catch (error) {
        console.error(error);
        setReviewStatusMessage(error.message || 'Review queue failed to load.', 'error');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const filter = document.getElementById('review-domain-filter');
    if (filter) {
        filter.value = activeReviewDomain;
        filter.addEventListener('change', () => {
            activeReviewDomain = filter.value;
            renderReviewSummaryCards();
            renderReviewList();
        });
    }
    await refreshReviewQueue();
});
