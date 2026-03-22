/**
 * Antigravity CRM - Network Intelligence Pulse
 * Handles date slider, Chart.js visualizations, and category-based filtering.
 */

var API_BASE = window.API_BASE || '';
let effortChart = null;
let profileDonut = null;
let dateSlider = null;
let activeCategory = null;
let activeVizMode = 'profiles';

const CHANNELS = ['meeting', 'call', 'whatsapp', 'email'];
const CHANNEL_COLORS = {
    meeting: '#8b5cf6',
    call: '#3b82f6',
    whatsapp: '#22c55e',
    email: '#f59e0b'
};

let startDate = new Date();
startDate.setDate(startDate.getDate() - 30);
let endDate = new Date();
let activePreset = '1m';

async function boot() {
    initCharts();
    initSlider();
    setupEventListeners();
    await applyPresetRange(activePreset, true);
}

function initCharts() {
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

function initSlider() {
    const slider = document.getElementById('date-slider');
    const minDate = new Date();
    minDate.setMonth(minDate.getMonth() - 3);

    dateSlider = noUiSlider.create(slider, {
        start: [startDate.getTime(), endDate.getTime()],
        connect: true,
        range: {
            min: minDate.getTime(),
            max: new Date().getTime()
        },
        step: 24 * 60 * 60 * 1000,
        format: wNumb({ decimals: 0 })
    });

    dateSlider.on('update', values => {
        const d1 = new Date(parseInt(values[0], 10));
        const d2 = new Date(parseInt(values[1], 10));
        document.getElementById('slider-start').textContent = d1.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
        document.getElementById('slider-end').textContent = d2.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
        document.getElementById('currentDateRangeStr').textContent = `${d1.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })} - ${d2.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })}`;
    });

    dateSlider.on('change', async values => {
        startDate = new Date(parseInt(values[0], 10));
        endDate = new Date(parseInt(values[1], 10));
        activePreset = null;
        syncPresetButtons();
        updatePeriodLabel();
        await loadData();
    });
}

function applyPresetRange(preset, shouldLoad) {
    const now = new Date();
    const start = new Date(now);

    if (preset === '1d') start.setDate(now.getDate() - 1);
    else if (preset === '2d') start.setDate(now.getDate() - 2);
    else if (preset === '1w') start.setDate(now.getDate() - 7);
    else if (preset === '3m') start.setMonth(now.getMonth() - 3);
    else start.setMonth(now.getMonth() - 1);

    startDate = start;
    endDate = now;
    activePreset = preset;
    syncPresetButtons();
    updatePeriodLabel();
    if (dateSlider) {
        dateSlider.set([startDate.getTime(), endDate.getTime()]);
    }
    return shouldLoad ? loadData() : Promise.resolve();
}

function updatePeriodLabel() {
    let label = 'Custom Range';
    if (activePreset === '1d') label = 'Last 24 Hours';
    else if (activePreset === '2d') label = 'Last 2 Days';
    else if (activePreset === '1w') label = 'Last 7 Days';
    else if (activePreset === '1m') label = 'Last 30 Days';
    else if (activePreset === '3m') label = 'Last 3 Months';
    const period = document.getElementById('periodLabel');
    if (period) period.textContent = label;
}

function syncPresetButtons() {
    document.querySelectorAll('[data-range]').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.range === activePreset);
    });
}

async function loadData() {
    const startStr = startDate.toISOString().split('T')[0];
    const endStr = endDate.toISOString().split('T')[0];
    const catQuery = activeCategory ? `&cat=${encodeURIComponent(activeCategory)}` : '';

    try {
        const requests = [
            fetch(`${API_BASE}/api/analytics/effort-stats?start_date=${startStr}&end_date=${endStr}${catQuery}`),
            fetch(`${API_BASE}/api/analytics/profile-growth-stats?start_date=${startStr}&end_date=${endStr}`),
        ];
        if (activeVizMode === 'temperature') {
            requests.push(fetch(`${API_BASE}/api/dashboard/meeting-feed`));
        }

        const [effortRes, profileRes, temperatureRes] = await Promise.all(requests);

        const effortData = await effortRes.json();
        const profileData = await profileRes.json();
        updateEffortUI(effortData);
        if (activeVizMode === 'temperature' && temperatureRes) {
            updateTemperatureUI(await temperatureRes.json());
        } else {
            updateProfileUI(profileData);
        }
    } catch (err) {
        console.error('Data load error:', err);
    }
}

function formatTrend(current, previous) {
    if (!previous && !current) {
        return { text: '0%', className: 'stat-change' };
    }
    if (!previous && current > 0) {
        return { text: 'New', className: 'stat-change up' };
    }
    const change = Math.round(((current - previous) / previous) * 100);
    if (change === 0) {
        return { text: '0%', className: 'stat-change' };
    }
    return {
        text: `${change > 0 ? '+' : ''}${change}%`,
        className: `stat-change ${change > 0 ? 'up' : 'down'}`
    };
}

function updateEffortUI(data) {
    CHANNELS.forEach(ch => {
        const count = data.totals[ch] || 0;
        document.getElementById(`count-${ch}`).textContent = count.toLocaleString();
        const trend = document.getElementById(`change-${ch}`);
        const previous = data.comparison_totals ? (data.comparison_totals[ch] || 0) : 0;
        const trendMeta = formatTrend(count, previous);
        trend.textContent = trendMeta.text;
        trend.className = trendMeta.className;
    });

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

function updateProfileUI(data) {
    const note = document.getElementById('temperatureVizNote');
    const slider = document.getElementById('date-slider-container');
    const label = document.getElementById('totalProfilesLabel');
    if (note) note.hidden = true;
    if (slider) slider.hidden = false;
    if (label) label.innerHTML = 'Manual<br>Profiles';
    const title = document.getElementById('profileBreakdownTitle');
    if (title) title.textContent = 'Manual Profile Growth';

    const stats = [...data.stats].sort((a, b) => b.count - a.count);
    const total = data.total_profiles ?? stats.reduce((acc, s) => acc + s.count, 0);
    document.getElementById('totalProfiles').textContent = total.toLocaleString();
    const subtitle = document.getElementById('profileBreakdownSubtitle');
    if (subtitle) {
        const excluded = data.excluded_profiles || 0;
        subtitle.textContent = excluded > 0
            ? 'Profiles personally added in the selected period. Bulk imports and test records are excluded.'
            : 'Profiles personally added in the selected period';
    }

    profileDonut.data.labels = stats.map(s => s.label || s.cat);
    profileDonut.data.datasets[0].data = stats.map(s => s.count);
    profileDonut.data.datasets[0].backgroundColor = stats.map(s => s.color || '#666');
    profileDonut.update();

    const legend = document.getElementById('profileLegend');
    if (stats.length === 0) {
        legend.innerHTML = `
            <div class="legend-item active">
                <div class="legend-label">No manual profile additions in this period</div>
            </div>
        `;
        return;
    }

    legend.innerHTML = stats.map(s => {
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

function updateTemperatureUI(feed) {
    const note = document.getElementById('temperatureVizNote');
    const slider = document.getElementById('date-slider-container');
    const label = document.getElementById('totalProfilesLabel');
    const title = document.getElementById('profileBreakdownTitle');
    const subtitle = document.getElementById('profileBreakdownSubtitle');
    if (note) note.hidden = false;
    if (slider) slider.hidden = true;
    if (label) label.innerHTML = 'Live<br>Network';
    if (title) title.textContent = 'Relationship Temperature';
    if (subtitle) subtitle.textContent = 'Live distribution across cadence pressure, cover, and freeze-aware status handling';

    const contacts = [
        ...(feed?.overdue || []),
        ...(feed?.not_scheduled || []),
        ...(feed?.soon || []),
        ...(feed?.on_track || []),
    ];
    const totals = { critical: 0, needs_attention: 0, due_soon: 0, on_track: 0, frozen: 0 };
    contacts.forEach((contact) => {
        const state = window.RelationshipTemperature.getTemperature(contact).stateKey;
        totals[state] += 1;
    });

    const ordered = [
        { key: 'critical', label: 'Critical', color: '#ef4444' },
        { key: 'needs_attention', label: 'Needs Attention', color: '#f97316' },
        { key: 'due_soon', label: 'Due Soon', color: '#f59e0b' },
        { key: 'on_track', label: 'On Track', color: '#38bdf8' },
        { key: 'frozen', label: 'Frozen', color: '#94a3b8' },
    ].filter((item) => totals[item.key] > 0);

    const total = contacts.length;
    document.getElementById('totalProfiles').textContent = total.toLocaleString();
    profileDonut.data.labels = ordered.map((item) => item.label);
    profileDonut.data.datasets[0].data = ordered.map((item) => totals[item.key]);
    profileDonut.data.datasets[0].backgroundColor = ordered.map((item) => item.color);
    profileDonut.update();

    const legend = document.getElementById('profileLegend');
    legend.innerHTML = ordered.map((item) => {
        const pct = total > 0 ? Math.round((totals[item.key] / total) * 100) : 0;
        return `
            <div class="legend-item">
                <div class="legend-dot" style="background: ${item.color}"></div>
                <div class="legend-label">${item.label}</div>
                <div class="legend-pct">${pct}%</div>
            </div>
        `;
    }).join('') + `
        <div class="legend-item active" style="margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 12px;">
            <div class="legend-dot" style="background: transparent; border: 1px dashed #666"></div>
            <div class="legend-label">${window.RelationshipTemperature.buildLegend()}</div>
        </div>
    `;
}

window.filterByCategory = async function(cat) {
    activeCategory = cat;
    await loadData();
};

function setupEventListeners() {
    document.querySelectorAll('.segment-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (btn.dataset.vizMode) {
                activeVizMode = btn.dataset.vizMode;
                document.querySelectorAll('[data-viz-mode]').forEach((toggle) => {
                    toggle.classList.toggle('active', toggle.dataset.vizMode === activeVizMode);
                });
                await loadData();
                return;
            }
            await applyPresetRange(btn.dataset.range, true);
        });
    });
}

document.addEventListener('DOMContentLoaded', boot);
