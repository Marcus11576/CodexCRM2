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
        const stats = data[period];

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
    try {
        const res = await fetch('/api/v2/analytics/recent-intel');
        const data = await res.json();
        const container = document.getElementById('intel-feed');
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
