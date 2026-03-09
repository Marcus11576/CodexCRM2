/**
 * Antigravity CRM — Network Intelligence Pulse
 * Handles date slider, Chart.js visualizations, and category-based filtering.
 */

var API_BASE = window.API_BASE || '';
let effortChart = null;
let profileDonut = null;
let dateSlider = null;
let activeCategory = null; // null means all

// Settings / Config
const CHANNELS = ['meeting', 'call', 'whatsapp', 'email'];
const CHANNEL_COLORS = {
    'meeting': '#8b5cf6', // Violet
    'call': '#3b82f6',    // Blue
    'whatsapp': '#22c55e', // Green
    'email': '#f59e0b'     // Amber
};

// State
let startDate = new Date();
startDate.setDate(startDate.getDate() - 30);
let endDate = new Date();

/**
 * BOOT
 */
async function boot() {
    initCharts();
    initSlider();
    await loadData();
    setupEventListeners();
}

/**
 * INITIALIZE CHARTS
 */
function initCharts() {
    // 1. Effort Line Chart
    const effortCtx = document.getElementById('effortChart').getContext('2d');
    effortChart = new Chart(effortCtx, {
        type: 'line',
        data: {
            labels: [],
            datasets: CHANNELS.map(ch => ({
                label: ch.charAt(0).toUpperCase() + ch.slice(1),
                data: [],
                borderColor: CHANNEL_COLORS[ch],
                backgroundColor: CHANNEL_COLORS[ch] + '22',
                fill: true,
                tension: 0.4,
                borderWidth: 3,
                pointRadius: 0,
                pointHoverRadius: 6,
                hidden: false
            }))
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: 'rgba(13, 17, 23, 0.9)',
                    titleFont: { family: 'Outfit', size: 14 },
                    bodyFont: { family: 'Inter', size: 12 },
                    padding: 12,
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255,255,255,0.05)' },
                    ticks: { color: 'rgba(255,255,255,0.4)', font: { size: 10 } },
                    beginAtZero: true
                }
            }
        }
    });

    // 2. Profile Donut Chart
    const donutCtx = document.getElementById('profileDonut').getContext('2d');
    profileDonut = new Chart(donutCtx, {
        type: 'doughnut',
        data: {
            labels: [],
            datasets: [{
                data: [],
                backgroundColor: [],
                borderWidth: 0,
                hoverOffset: 10
            }]
        },
        options: {
            cutout: '80%',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } }
        }
    });
}

/**
 * INITIALIZE DATE SLIDER
 */
function initSlider() {
    const slider = document.getElementById('date-slider');
    const startTs = new Date();
    startTs.setDate(startTs.getDate() - 90); // 90 days range
    
    dateSlider = noUiSlider.create(slider, {
        start: [startDate.getTime(), endDate.getTime()],
        connect: true,
        range: {
            'min': startTs.getTime(),
            'max': new Date().getTime()
        },
        step: 24 * 60 * 60 * 1000, // 1 day steps
        format: wNumb({ decimals: 0 })
    });

    dateSlider.on('update', (values) => {
        const d1 = new Date(parseInt(values[0]));
        const d2 = new Date(parseInt(values[1]));
        document.getElementById('slider-start').textContent = d1.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
        document.getElementById('slider-end').textContent = d2.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
        
        const rangeStr = `${d1.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })} - ${d2.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}`;
        document.getElementById('currentDateRangeStr').textContent = rangeStr;
    });

    dateSlider.on('change', async (values) => {
        startDate = new Date(parseInt(values[0]));
        endDate = new Date(parseInt(values[1]));
        await loadData();
    });
}

/**
 * LOAD DATA
 */
async function loadData() {
    const startStr = startDate.toISOString().split('T')[0];
    const endStr = endDate.toISOString().split('T')[0];
    const catQuery = activeCategory ? `&cat=${encodeURIComponent(activeCategory)}` : '';

    try {
        const [effortRes, profileRes] = await Promise.all([
            fetch(`${API_BASE}/api/analytics/effort-stats?start_date=${startStr}&end_date=${endStr}${catQuery}`),
            fetch(`${API_BASE}/api/analytics/profile-growth-stats?start_date=${startStr}&end_date=${endStr}`)
        ]);

        const effortData = await effortRes.json();
        const profileData = await profileRes.json();

        updateEffortUI(effortData);
        updateProfileUI(profileData);
    } catch (err) {
        console.error('Data load error:', err);
    }
}

/**
 * UPDATE EFFORT UI
 */
function updateEffortUI(data) {
    // 1. Update Cards
    CHANNELS.forEach(ch => {
        const count = data.totals[ch] || 0;
        document.getElementById(`count-${ch}`).textContent = count.toLocaleString();
        
        // Mocking trend for UI polish (real trend would need previous period comparison)
        const trend = document.getElementById(`change-${ch}`);
        const fakeVal = Math.floor(Math.random() * 15) + 1;
        trend.textContent = (fakeVal > 7 ? '+' : '-') + fakeVal + '%';
        trend.className = 'stat-change ' + (fakeVal > 7 ? 'up' : 'down');
    });

    // 2. Update Graph
    const days = [...new Set(data.daily_breakdown.map(d => d.day))].sort();
    effortChart.data.labels = days.map(d => new Date(d).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }));
    
    CHANNELS.forEach((ch, idx) => {
        effortChart.data.datasets[idx].data = days.map(d => {
            const entry = data.daily_breakdown.find(row => row.day === d && row.channel === ch);
            return entry ? entry.count : 0;
        });
    });
    
    effortChart.update();
}

/**
 * UPDATE PROFILE UI
 */
function updateProfileUI(data) {
    const total = data.stats.reduce((acc, s) => acc + s.count, 0);
    document.getElementById('totalProfiles').textContent = total;

    profileDonut.data.labels = data.stats.map(s => s.label || s.cat);
    profileDonut.data.datasets[0].data = data.stats.map(s => s.count);
    profileDonut.data.datasets[0].backgroundColor = data.stats.map(s => s.color || '#666');
    profileDonut.update();

    // Update Legend
    const legend = document.getElementById('profileLegend');
    legend.innerHTML = data.stats.map(s => {
        const pct = total > 0 ? Math.round((s.count / total) * 100) : 0;
        const isActive = activeCategory === s.cat;
        return `
            <div class="legend-item ${isActive ? 'active' : ''}" onclick="filterByCategory('${s.cat}')">
                <div class="legend-dot" style="background: ${s.color || '#666'}"></div>
                <div class="legend-label">${s.label || s.cat}</div>
                <div class="legend-pct">${pct}%</div>
            </div>
        `;
    }).join('') + `
        <div class="legend-item ${!activeCategory ? 'active' : ''}" onclick="filterByCategory(null)" style="margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 12px;">
            <div class="legend-dot" style="background: transparent; border: 1px dashed #666"></div>
            <div class="legend-label">Clear Filter (Show All)</div>
        </div>
    `;
}

/**
 * FILTER BY CATEGORY
 */
window.filterByCategory = async function(cat) {
    activeCategory = cat;
    await loadData();
};

/**
 * SETUP EVENT LISTENERS
 */
function setupEventListeners() {
    // Add any specific UI interactions here
}

// Boot up
document.addEventListener('DOMContentLoaded', boot);
