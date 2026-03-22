/**
 * Activities Dashboard - Intelligence Momentum Logic
 * Handles real-time data fetching and rendering for the Pulse and Trends.
 */

document.addEventListener('DOMContentLoaded', () => {
    loadMomentum();
    loadRecentIntel();
    loadCategorySentiment();
    // Refresh every 30 seconds for local live feel
    setInterval(() => {
        loadMomentum();
        loadRecentIntel();
        loadCategorySentiment();
    }, 30000);
});

async function loadMomentum() {
    try {
        const res = await fetch('/api/v2/analytics/momentum');
        const data = await res.json();
        
        // Split data by 1PM
        const now = new Date();
        const isAfternoon = now.getHours() >= 13;
        const period = isAfternoon ? 'afternoon' : 'morning';
        const stats = data?.[period] || data?.summary || { people: 0, interactions: 0, intel: 0 };

        // Update Dial
        document.getElementById('total-momentum').textContent = stats.people + stats.interactions + stats.intel;
        document.getElementById('current-period').textContent = isAfternoon ? 'AFTERNOON' : 'MORNING';
        
        // Progress (0 to 283)
        const total = stats.people + stats.interactions + stats.intel;
        const target = 15; // Mock target for momentum
        const offset = 283 - (Math.min(total / target, 1) * 283);
        document.getElementById('momentum-progress').style.strokeDashoffset = offset;

        // Orbit Stats
        document.querySelector('#stat-people .orbit-val').textContent = stats.people;
        document.querySelector('#stat-interactions .orbit-val').textContent = stats.interactions;
        document.querySelector('#stat-intel .orbit-val').textContent = stats.intel;

    } catch (err) {
        console.error('Error loading momentum:', err);
    }
}

async function loadRecentIntel() {
    const container = document.getElementById('intel-feed');
    if (!container) return;
    try {
        const res = await fetch('/api/v2/analytics/recent-intel');
        const data = await res.json();
        container.innerHTML = '';

        if (data.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted); grid-column: 1/-1; text-align: center;">No intelligence gathered today yet.</p>';
            return;
        }

        container.innerHTML = data.map(intel => {
            const sentiment = intel.sentiment || 0.5;
            const posPct = sentiment * 100;
            const negPct = (1 - sentiment) * 100;
            
            return `
                <div class="intel-card" onclick="window.location.href='/person/${intel.person_id}'" style="cursor: pointer;">
                    <div class="intel-topic">${(intel.topic || 'intel').replace('_', ' ')}</div>
                    <div class="intel-text">"${intel.intel_text}"</div>
                    <div class="intel-meta">
                        <div class="sentiment-bar">
                            <div class="sentiment-pos" style="width: ${posPct}%"></div>
                            <div class="sentiment-neg" style="width: ${negPct}%"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 0.65rem; margin-top: 0.5rem; color: var(--text-muted);">
                            <span>POSITIVE ${Math.round(posPct)}%</span>
                            <span>NEGATIVE ${Math.round(negPct)}%</span>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Failed to load intel feed:', err);
        container.innerHTML = '<p style="color: var(--accent-red); grid-column: 1/-1; text-align: center;">Error loading intelligence.</p>';
    }
}

async function loadCategorySentiment() {
    const trendGrid = document.getElementById('trend-grid');
    if (!trendGrid) return;

    try {
        const res = await fetch('/api/v2/analytics/category-sentiment');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const items = Array.isArray(data) ? data : (data.categories || []);

        if (items.length === 0) {
            trendGrid.innerHTML = '<div class="trend-card" style="color: var(--text-muted);">No category sentiment yet.</div>';
            return;
        }

        trendGrid.innerHTML = items.map(item => {
            const label = item.label || item.category || item.topic || 'General';
            const sentiment = Number(item.sentiment ?? 0.5);
            const confidence = Math.round(Number(item.confidence ?? 0.5) * 100);
            const sentimentPct = Math.round(sentiment * 100);
            return `
                <div class="trend-card">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.75rem;">
                        <div style="font-weight:800; letter-spacing:0.5px;">${label}</div>
                        <div style="font-size:0.75rem; color: var(--accent-cyan);">${confidence}% confidence</div>
                    </div>
                    <div style="height:8px; border-radius:999px; background:rgba(255,255,255,0.06); overflow:hidden; margin-bottom:0.65rem;">
                        <div style="height:100%; width:${sentimentPct}%; background:linear-gradient(90deg, rgba(16,185,129,0.75), rgba(53,232,255,0.9));"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.72rem; color: var(--text-muted);">
                        <span>Sentiment</span>
                        <span>${sentimentPct}% positive</span>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error('Failed to load category sentiment:', err);
        trendGrid.innerHTML = '<div class="trend-card" style="color: var(--accent-red);">Category sentiment is unavailable right now.</div>';
    }
}
