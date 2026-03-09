// Profile core state, loaders, and shared update helpers
var API_BASE = window.API_BASE || '';
let personId = null;
let isEditingEnv = false;
let isEditingDisc = false;
let isEditingStatus = false;
let isEditingCat = false;
let isAdvisoryState = false;

function getPersonIdFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    const idParam = urlParams.get('id');
    if (idParam) return idParam;

    const path = window.location.pathname;
    const match = path.match(/\/(?:people|person)\/([^\/]+)/);
    return match ? match[1] : null;
}

function getCategoryBadgeClass(cat) {
    if (!cat) return 'gen';
    const map = {
        'OBE M': 'obe-m',
        'OBE T': 'obe-t',
        'TGT': 'tgt',
        'EXT': 'ext',
        'HPC': 'hpc',
        'GEN': 'gen'
    };
    return map[cat.toUpperCase()] || 'gen';
}

function formatDateTime(dateStr) {
    if (!dateStr) return 'Not set';
    try {
        const isoStr = dateStr.replace(' ', 'T');
        const date = new Date(isoStr);
        if (isNaN(date.getTime())) return dateStr;
        return date.toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        });
    } catch (e) {
        return dateStr;
    }
}

function formatDate(dateStr) {
    if (!dateStr) return 'Not set';
    try {
        const isoStr = dateStr.replace(' ', 'T');
        const date = new Date(isoStr);
        if (isNaN(date.getTime())) return dateStr;

        const now = new Date();
        now.setHours(0, 0, 0, 0);
        const target = new Date(date);
        target.setHours(0, 0, 0, 0);

        const diffTime = target - now;
        const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

        if (diffDays < 0) return `${Math.abs(diffDays)}d past`;
        if (diffDays === 0) return 'Today';
        if (diffDays === 1) return 'Tomorrow';
        if (diffDays > 1 && diffDays < 7) return `${diffDays}d`;
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch (e) {
        return dateStr;
    }
}

function setAdvisory(isAdvisory) {
    isAdvisoryState = !!isAdvisory;
    const checkbox = document.getElementById('advisory-checkbox');
    if (checkbox) checkbox.checked = !!isAdvisory;

    if (personId) {
        updatePersonField('is_ts_advisory_candidate', isAdvisory ? 1 : 0);
    }
}

function toggleAdvisoryCheckbox(el) {
    setAdvisory(el.checked);
}

async function logAiFeedback(targetType, eventType, details = {}) {
    const currentId = getPersonIdFromUrl();
    if (!currentId) return;

    let targetId = currentId;
    if (targetType === 'brief') {
        targetId = window.currentBriefId || currentId;
    }

    try {
        const response = await fetch('/api/ai/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_type: targetType,
                target_id: targetId,
                event_type: eventType,
                details: {
                    timestamp: new Date().toISOString(),
                    source: 'profile_ui',
                    ...details
                }
            })
        });

        if (response.ok) {
            const payload = await response.json();
            toast(`Feedback recorded: ${payload.event_type || eventType}`, 'success');
        }
    } catch (err) {
        console.error('Feedback error:', err);
    }
}
function getInitials(name) {
    if (!name) return '?';
    return name.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);
}

async function loadPerson() {
    personId = getPersonIdFromUrl();

    if (!personId) {
        document.getElementById('loading').innerHTML = '<p style="color: var(--accent-red);">Invalid person ID</p>';
        return;
    }

    try {
        const personRes = await fetch(`${API_BASE}/api/people/${personId}`, {
            headers: { 'Accept': 'application/json' }
        });
        const personData = await personRes.json();

        if (personData.status === 'error') {
            throw new Error(personData.message || 'API error loading profile');
        }
        if (!personData || !personData.person) {
            throw new Error('Person data not found in response');
        }

        if (Object.keys(activeTaxonomy).length === 0) {
            await fetchTaxonomy();
        }

        renderPerson(personData.person, {
            recent_history: personData.history || [],
            open_loops: personData.tasks || []
        });
        if (typeof loadProfileEvents === 'function') {
            loadProfileEvents();
        }

        document.getElementById('loading').style.display = 'none';
        document.getElementById('content').style.display = 'block';

        if (window.AntigravityPlugins) {
            window.AntigravityPlugins.mountAll('content', personData.person);
        }

        if (!window.hasLoadedBriefing) {
            window.hasLoadedBriefing = true;
            loadBriefing();
            loadPropensityData();
        }
    } catch (error) {
        console.error('Error loading person:', error);
        document.getElementById('loading').innerHTML = `
            <p style="color: var(--accent-red);">Failed to load profile</p>
            <p style="font-size: 0.85rem; margin-top: 0.5rem;">${error.message}</p>
        `;
    }
}

async function loadPersonQuiet() {
    if (!personId) return;
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            headers: { 'Accept': 'application/json' }
        });
        const data = await res.json();
        if (data.person) {
            renderPerson(data.person, {
                recent_history: data.history || [],
                open_loops: data.tasks || []
            });
            if (typeof loadProfileEvents === 'function') {
                loadProfileEvents();
            }
            if (window.AntigravityPlugins) {
                window.AntigravityPlugins.mountAll('content', data.person);
            }
        }
    } catch (e) {
        console.error('Quiet load failed:', e);
    }
}

async function updateAdvisory() {
    const isAdvisory = document.getElementById('advisory-checkbox').checked;
    await updatePersonField('is_ts_advisory_candidate', isAdvisory);
}

async function updateCat() {
    const cat = document.getElementById('cat-value').value;
    await updatePersonField('cat', cat);
}

async function updateFamily(text) {
    await updatePersonField('key_personal_notes', text);
}

async function updatePersonField(field, value) {
    try {
        const payload = {};
        payload[field] = value;
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            const errorText = await res.text();
            let errorMessage = 'Failed to update';
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage += ': ' + (errorJson.detail || errorText);
            } catch (e) {
                errorMessage += ': ' + errorText;
            }
            throw new Error(errorMessage);
        }
        return true;
    } catch (err) {
        console.error(err);
        alert('Error updating profile: ' + err.message);
        return false;
    }
}

