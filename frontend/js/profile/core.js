// Profile core state, loaders, and shared update helpers
var API_BASE = window.API_BASE || '';
let personId = null;
let isEditingEnv = false;
let isEditingDisc = false;
let isEditingStatus = false;
let isEditingCat = false;
let isAdvisoryState = false;
const PROFILE_NAV_STORAGE_KEY = 'crm.profile.nav.v1';
let profileNavigationState = { people: [], index: -1 };
let profileSwipeBound = false;

function getPersonIdFromUrl() {
    const urlParams = new URLSearchParams(window.location.search);
    const idParam = urlParams.get('id');
    if (idParam) return idParam;

    const path = window.location.pathname;
    const match = path.match(/\/(?:people|person)\/([^\/]+)/);
    return match ? match[1] : null;
}

function readProfileNavigationContext() {
    try {
        const raw = window.sessionStorage.getItem(PROFILE_NAV_STORAGE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (_error) {
        return null;
    }
}

function writeProfileNavigationContext(context) {
    try {
        window.sessionStorage.setItem(PROFILE_NAV_STORAGE_KEY, JSON.stringify(context));
    } catch (error) {
        console.error('Failed to save profile navigation context', error);
    }
}

async function fetchProfileNavigationContext() {
    const response = await fetch(`${API_BASE}/api/people?limit=500`, {
        headers: { 'Accept': 'application/json' }
    });
    if (!response.ok) {
        throw new Error('Failed to load profile navigation');
    }
    const payload = await response.json();
    const people = Array.isArray(payload.people) ? payload.people : [];
    const context = {
        source: 'global',
        updatedAt: Date.now(),
        people: people.map((person) => ({
            person_id: person.person_id,
            full_name: person.full_name || 'Unknown Contact',
            title_current: person.title_current || '',
            company_name_raw: person.company_name_raw || '',
        })),
    };
    writeProfileNavigationContext(context);
    return context;
}

async function ensureProfileNavigationContext(currentId) {
    let context = readProfileNavigationContext();
    const people = Array.isArray(context?.people) ? context.people : [];
    const hasCurrent = people.some((person) => String(person.person_id) === String(currentId));

    if (!context || !people.length || (!hasCurrent && context.source === 'dashboard')) {
        context = await fetchProfileNavigationContext();
    }

    const resolvedPeople = Array.isArray(context?.people) ? context.people : [];
    const index = resolvedPeople.findIndex((person) => String(person.person_id) === String(currentId));
    profileNavigationState = { people: resolvedPeople, index };
    if (typeof window.renderProfileNavigationControls === 'function') {
        window.renderProfileNavigationControls(profileNavigationState);
    }
    return profileNavigationState;
}

function getProfileNavigationTarget(offset) {
    const { people, index } = profileNavigationState;
    if (!Array.isArray(people) || index < 0) return null;
    const targetIndex = index + offset;
    if (targetIndex < 0 || targetIndex >= people.length) return null;
    return people[targetIndex];
}

function navigateProfileTo(person) {
    if (!person?.person_id) return;
    const hash = window.location.hash || '';
    window.location.href = `/person/${person.person_id}?from=profile-nav${hash}`;
}

function navigateProfileByOffset(offset) {
    const target = getProfileNavigationTarget(offset);
    if (!target) return;
    navigateProfileTo(target);
}

function shouldIgnoreSwipeTarget(target) {
    if (!target || !(target instanceof Element)) return false;
    if (target.closest('a, button, input, textarea, select, label, [role="button"], [contenteditable="true"]')) {
        return true;
    }
    let current = target;
    while (current && current !== document.body) {
        const style = window.getComputedStyle(current);
        const canScrollX = /(auto|scroll)/.test(style.overflowX) && current.scrollWidth > current.clientWidth + 4;
        if (canScrollX) return true;
        current = current.parentElement;
    }
    return false;
}

function bindProfileSwipeNavigation() {
    if (profileSwipeBound) return;
    profileSwipeBound = true;

    let startX = 0;
    let startY = 0;
    let tracking = false;

    document.addEventListener('touchstart', (event) => {
        if (!window.matchMedia('(max-width: 768px)').matches) return;
        if (!event.touches || event.touches.length !== 1) return;
        if (shouldIgnoreSwipeTarget(event.target)) return;
        startX = event.touches[0].clientX;
        startY = event.touches[0].clientY;
        tracking = true;
    }, { passive: true });

    document.addEventListener('touchend', (event) => {
        if (!tracking || !window.matchMedia('(max-width: 768px)').matches) return;
        tracking = false;
        if (!event.changedTouches || event.changedTouches.length !== 1) return;
        const deltaX = event.changedTouches[0].clientX - startX;
        const deltaY = event.changedTouches[0].clientY - startY;
        if (Math.abs(deltaX) < 72) return;
        if (Math.abs(deltaY) > Math.abs(deltaX) * 0.7) return;
        if (deltaX < 0) {
            navigateProfileByOffset(1);
        } else {
            navigateProfileByOffset(-1);
        }
    }, { passive: true });
}

window.navigateProfileByOffset = navigateProfileByOffset;

function getCategoryBadgeClass(cat) {
    if (!cat) return 'gen';
    const map = {
        'OBE M': 'obe-m',
        'OBE T': 'obe-t',
        'TGT': 'tgt',
        'EXT': 'ext',
        'HPC': 'hpc',
        'TSA': 'tsa',
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
}

function toggleAdvisoryCheckbox(el) {
    const isAdvisory = !!(el && el.checked);
    setAdvisory(isAdvisory);
    if (personId) {
        updatePersonField('is_ts_advisory_candidate', isAdvisory ? 1 : 0);
    }
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
            open_loops: personData.tasks || [],
            relationships: personData.relationships || []
        });
        await ensureProfileNavigationContext(personId);
        if (typeof window.initProfileSectionChrome === 'function') {
            window.initProfileSectionChrome();
        }
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
                open_loops: data.tasks || [],
                relationships: data.relationships || []
            });
            await ensureProfileNavigationContext(personId);
            if (typeof window.initProfileSectionChrome === 'function') {
                window.initProfileSectionChrome();
            }
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

document.addEventListener('DOMContentLoaded', () => {
    bindProfileSwipeNavigation();
});

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
        toast(`Error updating profile: ${err.message}`, 'error');
        return false;
    }
}

