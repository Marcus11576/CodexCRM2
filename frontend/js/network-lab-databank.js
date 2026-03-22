let networkDatabank = null;
let databankScope = 'pilot';
let activeDatabankDomain = 'market_intel';

function setDatabankStatus(message, tone = '') {
    const target = document.getElementById('network-lab-databank-status');
    if (!target) return;
    target.textContent = message;
    target.className = 'network-lab-status';
    if (tone) target.classList.add(`is-${tone}`);
}

function escDatabank(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderDatabankSummaryCards() {
    const target = document.getElementById('databank-summary-cards');
    const summary = networkDatabank?.summary || {};
    const cards = [
        ['market_intel', 'Market Intel', summary.market_intel_count || 0, 'Cross-contact market signals you can use in search and positioning.'],
        ['market_themes', 'Market Themes', summary.market_theme_count || 0, 'Repeated market patterns emerging across contacts.'],
        ['opportunity_watch', 'Opportunity Watch', summary.opportunity_watch_count || 0, 'Live process and opportunity movement that needs attention.'],
        ['intent_watch', 'Intent Watch', summary.intent_watch_count || 0, 'What contacts appear to want, need, or be driving toward.'],
        ['rapport_memory', 'Rapport Memory', summary.rapport_memory_count || 0, 'Personal and relationship context worth retaining.'],
        ['relationship_trajectory', 'Trajectory', summary.relationship_trajectory_count || 0, 'Whether relationships are warming, steady, reactivating, or under strain.'],
        ['timing_triggers', 'Timing Triggers', summary.timing_trigger_count || 0, 'Deadlines, urgency, and seasonal or near-term timing cues.'],
        ['friction_watch', 'Friction Watch', summary.friction_watch_count || 0, 'Risks, blockers, payment issues, and process drag.'],
        ['influence_map', 'Influence Map', summary.influence_map_count || 0, 'Signals that show where doors open, decisions move, or influence sits.'],
    ];
    target.innerHTML = cards.map(([key, title, count, meta]) => `
        <button type="button" class="network-lab-card ${activeDatabankDomain === key ? 'active' : ''}" onclick="setDatabankDomain('${key}')">
            <h3>${title}</h3>
            <div class="network-lab-count">${count}</div>
            <div class="network-lab-meta">${meta}</div>
        </button>
    `).join('');
}

function setDatabankDomain(key) {
    activeDatabankDomain = key;
    const filter = document.getElementById('databank-domain-filter');
    if (filter) filter.value = key;
    renderDatabankSummaryCards();
    renderDatabankList();
}

function renderDatabankList() {
    const titles = {
        market_intel: ['Market Intel', 'Monitoring the strongest market signals across the selected cohort.'],
        market_themes: ['Market Themes', 'Aggregated market patterns showing up across multiple contacts.'],
        opportunity_watch: ['Opportunity Watch', 'Watching live momentum, process movement, and real opportunity signals.'],
        intent_watch: ['Intent Watch', 'Surfacing what contacts are trying to do, need, or prioritize.'],
        rapport_memory: ['Rapport Memory', 'Surfacing relationship context that helps sustain trust and better engagement.'],
        relationship_trajectory: ['Relationship Trajectory', 'Monitoring whether relationships are warming, steady, reactivating, or under strain.'],
        timing_triggers: ['Timing Triggers', 'Watching explicit timing pressure, deadlines, and event-based triggers.'],
        friction_watch: ['Friction Watch', 'Tracking blockers, hesitation, commercial pressure, and process drag.'],
        influence_map: ['Influence Map', 'Watching where introductions, decision power, and door-opening signals appear.'],
    };
    document.getElementById('databank-section-title').textContent = titles[activeDatabankDomain][0];
    document.getElementById('databank-section-subtitle').textContent = titles[activeDatabankDomain][1];

    const items = networkDatabank?.[activeDatabankDomain] || [];
    const target = document.getElementById('databank-list');
    if (!items.length) {
        target.innerHTML = '<div class="network-contact-card"><div class="network-lab-subtle">No items in this section yet.</div></div>';
        return;
    }
    if (activeDatabankDomain === 'market_themes') {
        target.innerHTML = items.map((item) => `
            <div class="network-contact-card">
                <div class="network-chip-row">
                    <span class="network-chip">Theme</span>
                    <span class="network-chip warn">${escDatabank(item.count)} mentions</span>
                    <span class="network-chip">${escDatabank(item.people_count)} people</span>
                    <span class="network-chip">${escDatabank(item.company_count)} companies</span>
                </div>
                <div style="font-weight:800;">${escDatabank(item.theme || 'No theme')}</div>
                <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${escDatabank((item.evidence_snippets || []).join(' | ') || 'No evidence snippets captured')}</div>
                ${item.full_evidence_text ? `
                    <details class="network-evidence-detail">
                        <summary>View Full Evidence</summary>
                        <div class="network-evidence-body">${escDatabank(item.full_evidence_text).replace(/\n/g, '<br>')}</div>
                    </details>
                ` : ''}
            </div>
        `).join('');
        return;
    }
    target.innerHTML = items.map((item) => `
        <div class="network-contact-card">
            <div class="network-contact-head">
                <div>
                    <div style="font-weight:800;">${escDatabank(item.full_name)}</div>
                    <div class="network-lab-subtle">${escDatabank(item.title_current || 'No title')} @ ${escDatabank(item.company_name_raw || 'Unknown')}</div>
                </div>
                <a class="network-lab-button secondary" href="/network-lab/profile/${encodeURIComponent(item.person_id)}">Open Profile</a>
            </div>
            <div class="network-chip-row">
                <span class="network-chip">${escDatabank(item.domain_label || 'Intel')}</span>
                <span class="network-chip warn">${escDatabank(item.stage || 'Relationship Update')}</span>
                <span class="network-chip">${escDatabank(item.network_tier || 'No tier')}</span>
                <span class="network-chip">${escDatabank(item.relationship_owner || 'No owner')}</span>
                ${item.promoted_memory_status ? `<span class="network-chip">Memory ${escDatabank(item.promoted_memory_status)}</span>` : ''}
                ${item.promoted_market_intel_status ? `<span class="network-chip warn">Market ${escDatabank(item.promoted_market_intel_status)}</span>` : ''}
            </div>
            <div style="font-weight:800;">${escDatabank(item.what_is_happening || 'No interpretation')}</div>
            <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Why it matters:</strong> ${escDatabank(item.why_it_matters || 'No explanation')}</div>
            <div class="network-intelligence-tag-grid">
                ${(item.chips || []).map((value) => `<span class="network-chip">${escDatabank(value)}</span>`).join('')}
            </div>
            <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Recommended action:</strong> ${escDatabank(item.recommended_action || 'No action suggested')}</div>
            <div class="network-lab-subtle" style="margin-top:0.45rem;"><strong>Evidence:</strong> ${escDatabank((item.evidence_snippets || []).join(' | ') || 'No evidence snippets captured')}</div>
            <details class="network-evidence-detail">
                <summary>View Full Evidence</summary>
                <div class="network-evidence-body">${escDatabank(item.full_evidence_text || 'No full evidence available').replace(/\n/g, '<br>')}</div>
            </details>
            <div class="network-lab-actions" style="margin-top:0.8rem;">
                ${(activeDatabankDomain !== 'market_themes') ? `
                    <button class="network-lab-button secondary" type="button" onclick="promoteDatabankMemory('${encodeURIComponent(item.interpretation_id)}', '${escDatabank(resolveMemoryDomain(item.domain_key))}')">Promote Memory</button>
                ` : ''}
                ${(activeDatabankDomain === 'market_intel') ? `
                    <button class="network-lab-button" type="button" onclick="promoteDatabankMarketIntel('${encodeURIComponent(item.interpretation_id)}')">Promote Market Intel</button>
                ` : ''}
            </div>
        </div>
    `).join('');
}

function resolveMemoryDomain(domainKey) {
    if (domainKey === 'market_intel') return 'market';
    if (domainKey === 'opportunity') return 'opportunity';
    if (domainKey === 'rapport') return 'rapport';
    if (domainKey === 'risk') return 'risk';
    if (domainKey === 'influence') return 'influence';
    return 'rapport';
}

async function promoteDatabankMemory(interpretationId, memoryDomain) {
    const domain = resolveMemoryDomain(memoryDomain);
    const res = await fetch(`${API_BASE}/api/network-lab/interpretations/${interpretationId}/promote-memory`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ memory_domain: domain, status: 'approved' }),
        credentials: 'same-origin',
    });
    if (!res.ok) {
        setDatabankStatus('Failed to promote enduring memory.', 'error');
        return;
    }
    setDatabankStatus('Promoted to enduring memory.', 'success');
    await refreshNetworkDatabank();
}

async function promoteDatabankMarketIntel(interpretationId) {
    const res = await fetch(`${API_BASE}/api/network-lab/interpretations/${interpretationId}/promote-market-intel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'approved' }),
        credentials: 'same-origin',
    });
    if (!res.ok) {
        setDatabankStatus('Failed to promote market intel.', 'error');
        return;
    }
    setDatabankStatus('Promoted to market intel.', 'success');
    await refreshNetworkDatabank();
}

function toggleDatabankScope() {
    databankScope = databankScope === 'pilot' ? 'all' : 'pilot';
    const button = document.getElementById('databank-scope-btn');
    if (button) {
        button.textContent = databankScope === 'pilot' ? 'Showing Pilot Cohort' : 'Showing All Contacts';
    }
    refreshNetworkDatabank();
}

async function refreshNetworkDatabank() {
    setDatabankStatus('Loading databank...');
    try {
        const res = await fetch(`${API_BASE}/api/network-lab/databank?scope=${encodeURIComponent(databankScope)}`, { credentials: 'same-origin' });
        if (!res.ok) {
            throw new Error(`Databank failed to load (${res.status}).`);
        }
        networkDatabank = await res.json();
        renderDatabankSummaryCards();
        renderDatabankList();
        setDatabankStatus(`Databank loaded for ${databankScope === 'pilot' ? 'the pilot cohort' : 'all contacts'}. Scanned ${networkDatabank.summary?.items_scanned || 0} interpreted items.`);
    } catch (error) {
        console.error(error);
        setDatabankStatus(error.message || 'Databank failed to load.', 'error');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const filter = document.getElementById('databank-domain-filter');
    if (filter) {
        filter.value = activeDatabankDomain;
        filter.addEventListener('change', () => {
            activeDatabankDomain = filter.value;
            renderDatabankSummaryCards();
            renderDatabankList();
        });
    }
    await refreshNetworkDatabank();
});
