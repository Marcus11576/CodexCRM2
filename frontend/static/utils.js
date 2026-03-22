/**
 * Antigravity CRM — Shared JS Utilities
 * API client, toast notifications, auth helpers.
 * Import this in every page.
 */

// ── API Base URL ──────────────────────────────────────────────
window.API_BASE = '';  // Same origin — FastAPI serves both API and frontend
var API_BASE = window.API_BASE;
window.__m365NavPoller = null;
window.__backupNavStatus = null;

// ── Session Management ─────────────────────────────────────────
/**
 * Note: Session tokens are now handled via HttpOnly cookies.
 * This frontend object only manages UI-level user metadata.
 */
const auth = {
    getUser: () => { try { return JSON.parse(localStorage.getItem('ag_user') || 'null'); } catch { return null; } },
    setUser: (u) => localStorage.setItem('ag_user', JSON.stringify(u)),
    clear: async () => { 
        localStorage.removeItem('ag_user');
        // Clear server-side session
        try { await fetch('/api/auth/logout', { method: 'POST' }); } catch(e) {}
    },
    isLoggedIn: () => !!auth.getUser(),
};

// ── API Client ────────────────────────────────────────────────
async function api(method, path, body = null, isFormData = false) {
    const headers = {};
    // Authorization is now handled automatically by the browser via cookies
    if (!isFormData && body) headers['Content-Type'] = 'application/json';

    const opts = { method, headers };
    if (body) opts.body = isFormData ? body : JSON.stringify(body);

    const response = await fetch(`${API_BASE}${path}`, opts);

    if (response.status === 401) {
        const err = await response.json().catch(() => ({ error: response.statusText }));
        throw new Error(err.message || err.detail || err.error || 'Unauthorized');
    }

    if (!response.ok) {
        const err = await response.json().catch(() => ({ error: response.statusText }));
        // Sanitized error response handling
        const msg = err.message || err.detail || err.error || `HTTP ${response.status}`;
        if (err.reference) console.error(`Error Reference: ${err.reference}`);
        throw new Error(msg);
    }

    if (response.status === 204) return null;
    return response.json();
}

const get = (path) => api('GET', path);
const post = (path, body) => api('POST', path, body);
const put = (path, body) => api('PUT', path, body);
const patch = (path, body) => api('PATCH', path, body);
const del = (path) => api('DELETE', path);

// ── Toast Notifications ───────────────────────────────────────
function ensureToastContainer() {
    let c = document.getElementById('toast-container');
    if (!c) {
        c = document.createElement('div');
        c.id = 'toast-container';
        document.body.appendChild(c);
    }
    return c;
}

function toast(message, type = 'info', duration = 3500) {
    const icons = { success: '✓', error: '✕', info: 'ℹ', warning: '⚠' };
    const container = ensureToastContainer();
    const el = document.createElement('div');
    el.className = `toast toast-${type}`;
    el.innerHTML = `<span style="font-size:16px;font-weight:700">${icons[type]}</span><span>${message}</span>`;
    container.appendChild(el);
    setTimeout(() => {
        el.classList.add('hiding');
        el.addEventListener('animationend', () => el.remove(), { once: true });
    }, duration);
}

// ── Require Auth ──────────────────────────────────────────────
function requireAuth() {
    return !!auth.getUser();
}

// ── Taxonomy Cache ────────────────────────────────────────────
let _taxonomyCache = null;
async function getTaxonomy() {
    if (_taxonomyCache) return _taxonomyCache;
    _taxonomyCache = await get('/api/taxonomy');
    return _taxonomyCache;
}
function getTaxonomyByType(type, all = []) {
    return all.filter(t => t.category_type === type && t.is_active);
}

// ── Avatar Helper ─────────────────────────────────────────────
function avatarHtml(person, size = 'md') {
    const initials = (person.full_name || '??').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
    const sizeMap = { sm: 36, md: 52, lg: 80, xl: 120 };
    const px = sizeMap[size] || 52;
    const fontSize = px * 0.36;

    if (person.profile_photo_url) {
        return `<img src="${person.profile_photo_url}" class="avatar avatar-${size}"
               style="width:${px}px;height:${px}px"
               onerror="this.replaceWith(avatarPlaceholder('${initials}',${px},${fontSize}))"
               alt="${person.full_name}">`;
    }
    return `<div class="avatar-placeholder avatar-${size}"
              style="width:${px}px;height:${px}px;font-size:${fontSize}px">
            ${initials}
          </div>`;
}

function avatarPlaceholder(initials, px, fontSize) {
    const el = document.createElement('div');
    el.className = 'avatar-placeholder';
    el.style.cssText = `width:${px}px;height:${px}px;font-size:${fontSize}px`;
    el.textContent = initials;
    return el;
}

function ensureM365NavModal() {
    let modal = document.getElementById('m365-nav-modal');
    if (modal) return modal;

    modal = document.createElement('div');
    modal.id = 'm365-nav-modal';
    modal.className = 'm365-nav-modal';
    modal.innerHTML = `
        <div class="m365-nav-modal-card">
            <button type="button" class="m365-nav-modal-close" aria-label="Close Microsoft 365 dialog" onclick="window.closeM365NavModal()">&times;</button>
            <div class="m365-nav-modal-badge">Microsoft 365</div>
            <h3 class="m365-nav-modal-title">Connect Microsoft</h3>
            <p class="m365-nav-modal-copy">Open the Microsoft device login page, enter the code below, and approve mail and calendar access.</p>
            <a id="m365-nav-auth-url" href="https://microsoft.com/devicelogin" target="_blank" rel="noopener noreferrer" class="m365-nav-modal-link">https://microsoft.com/devicelogin</a>
            <div id="m365-nav-auth-code" class="m365-nav-modal-code">...</div>
            <p id="m365-nav-auth-status-text" class="m365-nav-modal-status">Waiting for Microsoft approval...</p>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}

window.closeM365NavModal = function closeM365NavModal() {
    const modal = document.getElementById('m365-nav-modal');
    if (modal) modal.classList.remove('active');
    if (window.__m365NavPoller) {
        clearInterval(window.__m365NavPoller);
        window.__m365NavPoller = null;
    }
};

function setM365NavState(active, message) {
    const title = active ? 'M365 Active' : 'M365 Inactive';
    const statusBtn = document.getElementById('m365-nav-status-btn');
    const syncBtn = document.getElementById('m365-nav-sync-btn');

    if (statusBtn) {
        statusBtn.classList.remove('m365-status-active', 'm365-status-inactive');
        statusBtn.classList.add(active ? 'm365-status-active' : 'm365-status-inactive');
        statusBtn.title = title;
        statusBtn.setAttribute('aria-label', title);
        const label = statusBtn.querySelector('.m365-nav-status-label');
        if (label) label.textContent = title;
    }

    if (syncBtn) {
        syncBtn.disabled = !active;
        syncBtn.classList.toggle('is-disabled', !active);
        syncBtn.title = active ? 'Refresh mail and calendar across CRM contacts' : 'Connect Microsoft first';
        syncBtn.setAttribute('aria-label', syncBtn.title);
    }

    if (message && typeof toast === 'function') {
        toast(message, active ? 'success' : 'info');
    }
}

function formatBackupNavLabel(data) {
    if (!data || !data.exists || !data.last_backup_at) return 'Backup unavailable';
    return `Backup ${relativeTime(data.last_backup_at)}`;
}

function setBackupNavState(data) {
    window.__backupNavStatus = data || null;
    const badge = document.getElementById('backup-nav-status');
    if (!badge) return;

    const label = formatBackupNavLabel(data);
    const title = data?.exists && data?.last_backup_at
        ? `Last backup ${formatDate(data.last_backup_at)}${data.label ? ` (${data.label})` : ''}`
        : 'No backup found yet';

    badge.textContent = label;
    badge.title = title;
    badge.setAttribute('aria-label', title);
    badge.classList.toggle('is-missing', !data?.exists);
}

window.setGlobalM365NavState = function setGlobalM365NavState(status, meta = {}) {
    const active = status === 'authenticated';
    setM365NavState(active, meta.toastMessage || '');
};

async function fetchM365NavStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/m365/auth/status`);
        const data = await res.json().catch(() => ({}));
        const active = res.ok && data.status === 'authenticated';
        setM365NavState(active);
        if (data && data.backup) {
            setBackupNavState(data.backup);
        } else if (!window.__backupNavStatus || !window.__backupNavStatus.exists) {
            fetchBackupNavStatus();
        }
        return data;
    } catch (err) {
        setM365NavState(false);
        if (!window.__backupNavStatus || !window.__backupNavStatus.exists) {
            fetchBackupNavStatus();
        }
        return { status: 'error', message: err.message };
    }
}

async function fetchBackupNavStatus() {
    try {
        const res = await fetch(`${API_BASE}/api/health/backups/status`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.message || `Backup status failed (${res.status})`);
        setBackupNavState(data);
        return data;
    } catch (_err) {
        if (!window.__backupNavStatus || !window.__backupNavStatus.exists) {
            setBackupNavState({ exists: false });
        }
        return window.__backupNavStatus || { exists: false };
    }
}

window.handleM365NavStatusAction = async function handleM365NavStatusAction() {
    const status = await fetchM365NavStatus();
    if (status.status === 'authenticated') {
        toast('Microsoft 365 is connected. Use Sync Now to refresh mail and calendar.', 'success');
        return;
    }
    await window.startGlobalM365Auth();
};

window.handleM365NavSyncAction = async function handleM365NavSyncAction() {
    const status = await fetchM365NavStatus();
    if (status.status !== 'authenticated') {
        toast('Connect Microsoft 365 first, then run Sync Now.', 'info');
        await window.startGlobalM365Auth();
        return;
    }

    const syncBtn = document.getElementById('m365-nav-sync-btn');
    const original = syncBtn ? syncBtn.innerHTML : '';
    if (syncBtn) {
        syncBtn.disabled = true;
        syncBtn.innerHTML = '<span class="m365-sync-dot"></span><span>Syncing…</span>';
    }

    try {
        const res = await fetch(`${API_BASE}/api/m365/sync/full`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok || data.status !== 'success') {
            throw new Error(data.message || `Sync failed (${res.status})`);
        }
        const mailbox = data.summary?.mailbox || {};
        const calendar = data.summary?.calendar || {};
        const newEmails = mailbox.new_emails || 0;
        const newMeetings = calendar.new_meetings || 0;
        const refreshedEmails = mailbox.matched_messages || 0;
        const refreshedMeetings = calendar.synced_meetings || 0;
        const message = (newEmails || newMeetings)
            ? `Synced ${newEmails} new emails and ${newMeetings} new meetings.`
            : `Sync complete. Refreshed ${refreshedEmails} email matches and ${refreshedMeetings} meetings.`;
        toast(message, 'success');
        setM365NavState(true);
        if (typeof window.loadPerson === 'function') {
            window.loadPerson();
        }
    } catch (err) {
        toast(err.message || 'M365 sync failed', 'error');
    } finally {
        if (syncBtn) {
            syncBtn.disabled = false;
            syncBtn.innerHTML = original;
        }
    }
};

window.startGlobalM365Auth = async function startGlobalM365Auth() {
    ensureM365NavModal();
    const modal = document.getElementById('m365-nav-modal');
    const link = document.getElementById('m365-nav-auth-url');
    const code = document.getElementById('m365-nav-auth-code');
    const statusText = document.getElementById('m365-nav-auth-status-text');

    try {
        const res = await fetch(`${API_BASE}/api/m365/auth/start`, { method: 'POST' });
        const data = await res.json();

        if (data.status === 'authenticated') {
            setM365NavState(true, 'Microsoft 365 is already connected.');
            if (modal) modal.classList.remove('active');
            return;
        }

        if (data.status !== 'pending') {
            throw new Error(data.message || 'Could not start Microsoft 365 login.');
        }

        if (link) {
            link.href = data.verification_uri;
            link.textContent = data.verification_uri;
        }
        if (code) code.textContent = data.user_code || '...';
        if (statusText) statusText.textContent = 'Waiting for Microsoft approval...';
        modal.classList.add('active');

        if (window.__m365NavPoller) clearInterval(window.__m365NavPoller);
        window.__m365NavPoller = setInterval(async () => {
            try {
                const pollRes = await fetch(`${API_BASE}/api/m365/auth/status`);
                const pollData = await pollRes.json();
                if (pollData.status === 'authenticated') {
                    clearInterval(window.__m365NavPoller);
                    window.__m365NavPoller = null;
                    modal.classList.remove('active');
                    setM365NavState(true, 'Microsoft 365 connected.');
                } else if (pollData.status === 'error') {
                    clearInterval(window.__m365NavPoller);
                    window.__m365NavPoller = null;
                    if (statusText) statusText.textContent = pollData.message || 'Microsoft login failed.';
                    toast(pollData.message || 'Microsoft login failed.', 'error');
                }
            } catch (err) {
                clearInterval(window.__m365NavPoller);
                window.__m365NavPoller = null;
                if (statusText) statusText.textContent = err.message || 'Microsoft login failed.';
                toast(err.message || 'Microsoft login failed.', 'error');
            }
        }, 3000);
    } catch (err) {
        if (statusText) statusText.textContent = err.message || 'Microsoft login failed.';
        if (modal) modal.classList.add('active');
        toast(err.message || 'Microsoft login failed.', 'error');
    }
};

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ── Category Badge Colour ─────────────────────────────────────
function catBadgeClass(cat) {
    const map = {
        'OBE M': 'badge-blue',
        'OBE T': 'badge-violet',
        'TGT': 'badge-amber',
        'EXT': 'badge-emerald',
        'HPC': 'badge-violet',
        'GEN': 'badge-gray',
    };
    return map[cat] || 'badge-white';
}

// ── Meeting Status ────────────────────────────────────────────
function meetingStatusHtml(status, dueDate) {
    const map = {
        overdue: { label: 'Overdue', class: 'badge-rose', dot: '#f43f5e' },
        soon: { label: 'Due Soon', class: 'badge-amber', dot: '#f59e0b' },
        on_track: { label: 'On Track', class: 'badge-emerald', dot: '#10b981' },
    };
    const s = map[status];
    if (!s) return '';
    const dateStr = dueDate ? ` · ${new Date(dueDate).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}` : '';
    return `<span class="badge ${s.class}">
    <span style="width:6px;height:6px;border-radius:50%;background:${s.dot};display:inline-block;margin-right:4px"></span>
    ${s.label}${dateStr}
  </span>`;
}

// ── Relative Time ─────────────────────────────────────────────
function relativeTime(dateStr) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: days > 365 ? 'numeric' : undefined });
}

// ── Format Date ───────────────────────────────────────────────
function formatDate(dateStr, opts = {}) {
    if (!dateStr) return '';
    const d = new Date(dateStr);
    const defaults = { day: 'numeric', month: 'short', year: 'numeric' };
    return d.toLocaleDateString('en-GB', { ...defaults, ...opts });
}

// ── Channel Label ─────────────────────────────────────────────
function normalizeChannelKey(ch) {
    const raw = (ch || '').toString().trim().toLowerCase();
    if (!raw) return 'note';
    if (raw === 'email') return 'email';
    if (raw === 'whatsapp') return 'whatsapp';
    if (['call', 'mobile', 'phone'].includes(raw)) return 'call';
    if (['meeting', 'face to face', 'teams'].includes(raw)) return 'meeting';
    if (['note', 'manual', 'manual_input', 'quick_capture'].includes(raw)) return 'note';
    if (['audio', 'voice', 'voice_note'].includes(raw)) return 'audio';
    if (['screenshot', 'image', 'photo'].includes(raw)) return 'screenshot';
    if (['upload', 'document', 'file', 'imported'].includes(raw)) return 'upload';
    if (raw === 'chat') return 'chat';
    if (raw === 'system_audit') return 'system_audit';
    return raw.replace(/\s+/g, '_');
}

function channelDisplayMeta(ch) {
    const key = normalizeChannelKey(ch);
    const map = {
        note: { label: 'Manual Note', icon: 'fas fa-pen', tone: 'note' },
        whatsapp: { label: 'WhatsApp', icon: 'fab fa-whatsapp', tone: 'whatsapp' },
        email: { label: 'Email', icon: 'fas fa-envelope', tone: 'email' },
        call: { label: 'Phone Call', icon: 'fas fa-phone', tone: 'call' },
        meeting: { label: 'Meeting', icon: 'fas fa-user-group', tone: 'meeting' },
        audio: { label: 'Voice Note', icon: 'fas fa-microphone-lines', tone: 'audio' },
        screenshot: { label: 'Image', icon: 'fas fa-image', tone: 'screenshot' },
        upload: { label: 'File', icon: 'fas fa-file-lines', tone: 'upload' },
        chat: { label: 'AI Chat', icon: 'fas fa-comments', tone: 'chat' },
        system_audit: { label: 'System Audit', icon: 'fas fa-shield-halved', tone: 'audit' },
    };
    const fallbackLabel = key
        .split('_')
        .map(part => part ? part.charAt(0).toUpperCase() + part.slice(1) : '')
        .join(' ')
        .trim() || 'Interaction';
    const meta = map[key] || { label: fallbackLabel, icon: 'fas fa-message', tone: 'default' };
    return { key, ...meta };
}

function channelMetaForItem(itemOrChannel) {
    if (typeof itemOrChannel === 'string' || itemOrChannel == null) {
        return channelDisplayMeta(itemOrChannel);
    }
    return channelDisplayMeta(itemOrChannel.display_channel || itemOrChannel.channel);
}

function channelLabel(ch) {
    return channelMetaForItem(ch).label;
}

function normalizeRelationshipKey(value) {
    const raw = (value || '').toString().trim().toLowerCase();
    if (!raw) return 'mentioned';
    if (['colleague', 'coworker', 'co-worker', 'same_company'].includes(raw)) return 'colleague';
    if (['org_peer', 'same_company_only', 'orgpeer'].includes(raw)) return 'org_peer';
    if (['referral', 'referrer', 'introduced'].includes(raw)) return 'referral';
    if (['friend', 'personal_friend'].includes(raw)) return 'friend';
    if (['mentioned', 'mention', 'linked'].includes(raw)) return 'mentioned';
    return raw.replace(/\s+/g, '_');
}

function relationshipDisplayMeta(value) {
    const key = normalizeRelationshipKey(value);
    const map = {
        colleague: { label: 'Colleague', icon: 'fas fa-building-user', tone: 'colleague' },
        org_peer: { label: 'Org Peer', icon: 'fas fa-diagram-project', tone: 'org-peer' },
        referral: { label: 'Referral', icon: 'fas fa-share-nodes', tone: 'referral' },
        friend: { label: 'Friend', icon: 'fas fa-user-group', tone: 'friend' },
        mentioned: { label: 'Mentioned', icon: 'fas fa-comment-dots', tone: 'mentioned' },
    };
    return map[key] || { label: 'Linked', icon: 'fas fa-link', tone: 'default' };
}

// ── Debounce ──────────────────────────────────────────────────
function debounce(fn, ms = 300) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn(...args), ms);
    };
}

// ── URL Params ────────────────────────────────────────────────
function getParam(name) {
    return new URLSearchParams(window.location.search).get(name);
}

// ── Navigation ────────────────────────────────────────────────
const VIEWPORT_PREVIEW_STORAGE_KEY = 'crm.viewport.preview.v1';
const VIEWPORT_PREVIEW_MIN_WIDTH = 1025;
const VIEWPORT_PREVIEW_QUERY_PARAM = 'vpPreview';
const VIEWPORT_PRESET = {
    desktop: { label: 'Desktop', width: '' },
    tablet: { label: 'Tablet', width: '1024px' },
    mobile: { label: 'Mobile', width: '430px' },
};

function normalizeViewportPreview(mode) {
    const key = (mode || '').toString().trim().toLowerCase();
    if (Object.prototype.hasOwnProperty.call(VIEWPORT_PRESET, key)) return key;
    return 'desktop';
}

function readViewportPreview() {
    try {
        return normalizeViewportPreview(localStorage.getItem(VIEWPORT_PREVIEW_STORAGE_KEY));
    } catch (_err) {
        return 'desktop';
    }
}

function persistViewportPreview(mode) {
    try {
        localStorage.setItem(VIEWPORT_PREVIEW_STORAGE_KEY, normalizeViewportPreview(mode));
    } catch (_err) {
        // Ignore storage failures and keep preview local to the session.
    }
}

function updateViewportPreviewButtons(mode) {
    const normalized = normalizeViewportPreview(mode);
    document.querySelectorAll('.viewport-preview-btn').forEach((btn) => {
        const isActive = btn.dataset.viewportPreview === normalized;
        btn.classList.toggle('active', isActive);
        btn.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
}

function canUseViewportPreview() {
    return window.innerWidth >= VIEWPORT_PREVIEW_MIN_WIDTH;
}

function getUrlViewportPreviewMode() {
    try {
        const params = new URLSearchParams(window.location.search);
        return normalizeViewportPreview(params.get(VIEWPORT_PREVIEW_QUERY_PARAM));
    } catch (_err) {
        return 'desktop';
    }
}

function clearViewportPreview() {
    const html = document.documentElement;
    html.dataset.viewportPreview = 'desktop';
    html.classList.remove('viewport-preview-active');
    html.style.removeProperty('--preview-shell-width');
    updateViewportPreviewButtons('desktop');
}

function syncViewportPreviewControls() {
    const toggle = document.querySelector('.viewport-preview-toggle');
    const supported = canUseViewportPreview();
    const urlMode = getUrlViewportPreviewMode();
    if (toggle) {
        toggle.classList.toggle('is-hidden', !supported);
    }
    clearViewportPreview();
    if (!supported) {
        clearViewportPreview();
        persistViewportPreview('desktop');
        return;
    }
    updateViewportPreviewButtons(urlMode === 'desktop' ? 'desktop' : urlMode);
}

function launchViewportPreviewWindow(mode) {
    const normalized = normalizeViewportPreview(mode);
    const preset = VIEWPORT_PRESET[normalized];
    const width = parseInt((preset && preset.width) ? preset.width : '1280', 10);
    const height = Math.max(window.outerHeight || 900, 900);
    const url = new URL(window.location.href);
    url.searchParams.set(VIEWPORT_PREVIEW_QUERY_PARAM, normalized);
    const features = `popup=yes,width=${width},height=${height},resizable=yes,scrollbars=yes`;

    let previewWindow = null;
    try {
        previewWindow = window.open(url.toString(), `ag-viewport-${normalized}`, features);
    } catch (_err) {
        previewWindow = null;
    }

    if (previewWindow && !previewWindow.closed) {
        previewWindow.focus();
        if (typeof toast === 'function') {
            toast(`${VIEWPORT_PRESET[normalized].label} preview opened in a dedicated window.`, 'info', 2400);
        }
        return true;
    }

    if (typeof toast === 'function') {
        toast('Popup blocked. Allow popups to use viewport preview windows.', 'warning', 3000);
    }
    return false;
}

function enforceViewportPreviewWindowSize() {
    const urlMode = getUrlViewportPreviewMode();
    if (urlMode === 'desktop') return;
    const preset = VIEWPORT_PRESET[urlMode];
    const targetInnerWidth = parseInt((preset && preset.width) ? preset.width : '', 10);
    if (!Number.isFinite(targetInnerWidth) || targetInnerWidth <= 0) return;

    const chromeWidth = Math.max(0, (window.outerWidth || targetInnerWidth) - window.innerWidth);
    const targetOuterWidth = targetInnerWidth + chromeWidth;
    const targetOuterHeight = Math.max(window.outerHeight || 900, 900);

    try {
        if (Math.abs(window.innerWidth - targetInnerWidth) > 24) {
            window.resizeTo(targetOuterWidth, targetOuterHeight);
        }
    } catch (_err) {
        // Ignore resize failures (browser policy, platform limits).
    }
}

window.setViewportPreview = function setViewportPreview(mode) {
    if (!canUseViewportPreview()) {
        syncViewportPreviewControls();
        return;
    }
    const normalized = normalizeViewportPreview(mode);
    if (normalized === 'desktop') {
        const currentUrlMode = getUrlViewportPreviewMode();
        if (currentUrlMode !== 'desktop') {
            const url = new URL(window.location.href);
            url.searchParams.delete(VIEWPORT_PREVIEW_QUERY_PARAM);
            window.location.href = url.toString();
            return;
        }
        persistViewportPreview('desktop');
        clearViewportPreview();
        updateViewportPreviewButtons('desktop');
        return;
    }
    persistViewportPreview('desktop');
    clearViewportPreview();
    updateViewportPreviewButtons('desktop');
    launchViewportPreviewWindow(normalized);
};

function initViewportPreviewControls() {
    enforceViewportPreviewWindowSize();
    syncViewportPreviewControls();
    if (!window.__viewportPreviewResizeBound) {
        window.__viewportPreviewResizeBound = true;
        window.addEventListener('resize', debounce(() => {
            enforceViewportPreviewWindowSize();
            syncViewportPreviewControls();
        }, 120));
    }
}

function setActiveNav(page) {
    document.querySelectorAll('.nav-link').forEach(el => {
        el.classList.toggle('active', el.dataset.page === page);
    });
}

/**
 * Renders the universal top navigation bar.
 * @param {string} activePage - The ID of the active page for nav highlighting.
 * @param {string} title - The title for the header.
 */
function renderUniversalLayout(activePage, title) {
    const navHtml = `
        <header class="universal-top-nav">
            <div class="top-nav-left">
                <h1 class="universal-header">${title}</h1>
            </div>

            <nav class="top-nav-center">
                <button class="nav-icon-link back-button" onclick="handleUniversalBack()" title="Go Back">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M19 12H5M12 5l-7 7 7 7"/></svg>
                </button>
                <a href="/" class="nav-icon-link ${activePage === 'dashboard' ? 'active' : ''}" title="Dashboard">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                </a>
                <a href="/agenda" class="nav-icon-link ${activePage === 'agenda' ? 'active' : ''}" title="Agenda">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>
                </a>
                <a href="/analytics" class="nav-icon-link ${activePage === 'analytics' ? 'active' : ''}" title="Analytics">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
                </a>
                <a href="/events" class="nav-icon-link ${activePage === 'events' ? 'active' : ''}" title="Events">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="5" width="18" height="16" rx="2"></rect><path d="M16 3v4"></path><path d="M8 3v4"></path><path d="M3 11h18"></path><path d="M8 15h3"></path><path d="M13 15h3"></path></svg>
                </a>
                <a href="/network-lab" class="nav-icon-link ${activePage === 'network-lab' ? 'active' : ''}" title="Network Lab">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                        <circle cx="6" cy="12" r="2"></circle>
                        <circle cx="18" cy="6" r="2"></circle>
                        <circle cx="18" cy="18" r="2"></circle>
                        <path d="M8 12h6"></path>
                        <path d="M16.5 7.5l-4.5 3"></path>
                        <path d="M16.5 16.5l-4.5-3"></path>
                    </svg>
                </a>
                <a href="/settings" class="nav-icon-link ${activePage === 'settings' ? 'active' : ''}" title="Settings">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                </a>
            </nav>

            <div class="top-nav-right">
                <div class="viewport-preview-toggle" role="group" aria-label="Viewport preview">
                    <button type="button" class="viewport-preview-btn" data-viewport-preview="desktop" aria-pressed="false" onclick="window.setViewportPreview('desktop')">Desktop</button>
                    <button type="button" class="viewport-preview-btn" data-viewport-preview="tablet" aria-pressed="false" onclick="window.setViewportPreview('tablet')">Tablet</button>
                    <button type="button" class="viewport-preview-btn" data-viewport-preview="mobile" aria-pressed="false" onclick="window.setViewportPreview('mobile')">Mobile</button>
                </div>
                <button type="button" id="m365-nav-status-btn" class="m365-nav-status m365-status-btn m365-status-inactive" title="M365 Inactive" aria-label="M365 Inactive" onclick="window.handleM365NavStatusAction()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M3 7l9 6 9-6"></path></svg>
                    <span class="m365-nav-status-label">M365 Inactive</span>
                </button>
                <button type="button" id="m365-nav-sync-btn" class="m365-nav-sync-btn" title="Connect Microsoft first" aria-label="Connect Microsoft first" onclick="window.handleM365NavSyncAction()" disabled>
                    <span class="m365-sync-dot"></span>
                    <span>Sync Now</span>
                </button>
                <div id="backup-nav-status" class="backup-nav-status" title="Checking backup status..." aria-live="polite">Checking backup...</div>
                <div class="nav-search-container">
                    <div class="nav-search-input-wrapper">
                        <span class="nav-search-icon">🔍</span>
                        <input type="text" id="nav-search-input" class="nav-search-input" placeholder="Search profiles..." autocomplete="off">
                    </div>
                    <div id="nav-search-results" class="nav-search-results"></div>
                </div>
            </div>
        </header>
    `;

    const existingNav = document.querySelector('.universal-top-nav') || document.querySelector('.universal-sidebar');
    if (existingNav) existingNav.remove();
    const existingHeader = document.querySelector('.universal-header-container');
    if (existingHeader) existingHeader.remove();

    document.body.insertAdjacentHTML('afterbegin', navHtml);
    ensureM365NavModal();
    
    // Initialize Search Logic
    initUniversalSearch();
    initViewportPreviewControls();
    fetchM365NavStatus();
}

/**
 * Universal Search Logic
 */
function initUniversalSearch() {
    const input = document.getElementById('nav-search-input');
    const results = document.getElementById('nav-search-results');
    if (!input || !results) return;

    const debouncedSearch = debounce(async (q) => {
        if (!q.trim()) {
            results.classList.remove('active');
            return;
        }

        try {
            const data = await get(`/api/people?q=${encodeURIComponent(q)}&limit=5`);
            renderSearchPreviews(data.people || []);
        } catch (err) {
            console.error('Search failed:', err);
        }
    }, 250);

    input.addEventListener('input', (e) => debouncedSearch(e.target.value));

    // Close results on blur
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !results.contains(e.target)) {
            results.classList.remove('active');
        }
    });

    // Re-open if input focused and has value
    input.addEventListener('focus', () => {
        if (input.value.trim() && results.children.length > 0) {
            results.classList.add('active');
        }
    });
}

function renderSearchPreviews(people) {
    const results = document.getElementById('nav-search-results');
    if (!results) return;

    if (people.length === 0) {
        results.innerHTML = '<div class="search-no-results">No contacts found</div>';
    } else {
        results.innerHTML = people.map(p => `
            <div class="search-result-item" onclick="window.location.href='/person/${p.person_id}'">
                ${avatarHtml(p, 'sm')}
                <div class="search-result-info">
                    <div class="search-result-name">${p.full_name}</div>
                    <div class="search-result-meta">${p.title_current || ''} ${p.company_name_raw ? '@ ' + p.company_name_raw : ''}</div>
                </div>
            </div>
        `).join('');
    }
    results.classList.add('active');
}

/**
 * Universal Back behavior.
 */
window.handleUniversalBack = function() {
    if (window.history.length > 1) {
        window.history.back();
    } else {
        window.location.href = '/';
    }
};

let agDialogDepth = 0;

function updateAgDialogBodyState() {
    document.body.classList.toggle('ag-dialog-open', agDialogDepth > 0);
}

function openAgDialog(options = {}) {
    const {
        title = '',
        description = '',
        content = '',
        actions = [],
        width = '560px',
        className = '',
        closeOnBackdrop = true,
        showCloseButton = true,
        onClose = null,
    } = options;

    const overlay = document.createElement('div');
    overlay.className = 'ag-dialog-overlay';

    const card = document.createElement('div');
    card.className = `ag-dialog-card ${className}`.trim();
    if (width) {
        card.style.maxWidth = width;
    }

    const header = document.createElement('div');
    header.className = 'ag-dialog-header';

    const headerCopy = document.createElement('div');
    headerCopy.className = 'ag-dialog-copy';
    headerCopy.innerHTML = `
        ${title ? `<div class="ag-dialog-title">${escapeHtml(title)}</div>` : ''}
        ${description ? `<p class="ag-dialog-description">${escapeHtml(description)}</p>` : ''}
    `;
    header.appendChild(headerCopy);

    const body = document.createElement('div');
    body.className = 'ag-dialog-body';
    if (typeof content === 'string') {
        body.innerHTML = content;
    } else if (content instanceof Node) {
        body.appendChild(content);
    }

    const actionsEl = document.createElement('div');
    actionsEl.className = 'ag-dialog-actions';

    let closed = false;
    let removed = false;
    let resolveAfterClose = null;

    function close(result = null) {
        if (closed) return;
        closed = true;
        document.removeEventListener('keydown', handleKeydown);
        overlay.classList.remove('is-open');
        agDialogDepth = Math.max(0, agDialogDepth - 1);
        updateAgDialogBodyState();
        const remove = () => {
            if (removed) return;
            removed = true;
            overlay.remove();
            if (typeof onClose === 'function') {
                onClose(result);
            }
            if (typeof resolveAfterClose === 'function') {
                resolveAfterClose(result);
            }
        };
        card.addEventListener('transitionend', remove, { once: true });
        window.setTimeout(remove, 220);
    }

    function handleKeydown(event) {
        if (event.key === 'Escape') {
            close(false);
        }
    }

    if (showCloseButton) {
        const closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'ag-dialog-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.setAttribute('aria-label', 'Close dialog');
        closeBtn.addEventListener('click', () => close(false));
        header.appendChild(closeBtn);
    }

    actions.forEach((action) => {
        const button = document.createElement('button');
        button.type = action.type || 'button';
        button.className = `ag-dialog-btn ag-dialog-btn-${action.variant || 'ghost'}`;
        button.textContent = action.label || 'Continue';
        if (action.disabled) button.disabled = true;
        button.addEventListener('click', async () => {
            if (button.disabled) return;
            button.disabled = true;
            try {
                const response = action.onClick ? await action.onClick({ overlay, card, body, actionsEl, close, button }) : undefined;
                if (response === false) {
                    button.disabled = !!action.disabled;
                    return;
                }
                if (action.closeOnClick !== false) {
                    close(response);
                    return;
                }
            } catch (error) {
                console.error(error);
                toast(error.message || 'Something went wrong', 'error');
            } finally {
                button.disabled = !!action.disabled;
            }
        });
        actionsEl.appendChild(button);
    });

    card.appendChild(header);
    card.appendChild(body);
    if (actions.length) {
        card.appendChild(actionsEl);
    }
    overlay.appendChild(card);

    overlay.addEventListener('click', (event) => {
        if (closeOnBackdrop && event.target === overlay) {
            close(false);
        }
    });

    document.body.appendChild(overlay);
    agDialogDepth += 1;
    updateAgDialogBodyState();
    document.addEventListener('keydown', handleKeydown);
    requestAnimationFrame(() => overlay.classList.add('is-open'));

    const firstFocusable = card.querySelector('input, textarea, select, button');
    if (firstFocusable) {
        requestAnimationFrame(() => firstFocusable.focus());
    }

    return {
        overlay,
        card,
        body,
        actionsEl,
        close,
        waitForClose() {
            return new Promise((resolve) => {
                resolveAfterClose = resolve;
            });
        },
    };
}

function showConfirmDialog(options = {}) {
    return new Promise((resolve) => {
        const {
            title = 'Please confirm',
            message = '',
            confirmLabel = 'Confirm',
            cancelLabel = 'Cancel',
            confirmVariant = 'danger',
        } = options;

        let settled = false;
        const settle = (value) => {
            if (settled) return;
            settled = true;
            resolve(value);
        };

        openAgDialog({
            title,
            description: message,
            width: '460px',
            onClose: (result) => settle(!!result),
            actions: [
                {
                    label: cancelLabel,
                    variant: 'ghost',
                    onClick: ({ close }) => {
                        close(false);
                        return false;
                    },
                    closeOnClick: false,
                },
                {
                    label: confirmLabel,
                    variant: confirmVariant,
                    onClick: ({ close }) => {
                        close(true);
                        return false;
                    },
                    closeOnClick: false,
                },
            ],
        });
    });
}

function downloadFile(url, filename = '') {
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.rel = 'noopener';
    if (filename) {
        anchor.download = filename;
    }
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
}

function normalizeSearchText(value) {
    return String(value ?? '')
        .toLowerCase()
        .replace(/\s+/g, ' ')
        .trim();
}

function microphoneSupportStatus() {
    const secureContext = window.isSecureContext || ['localhost', '127.0.0.1'].includes(window.location.hostname);
    const mediaDevicesAvailable = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    const mediaRecorderAvailable = typeof window.MediaRecorder !== 'undefined';
    const supported = secureContext && mediaDevicesAvailable && mediaRecorderAvailable;
    let reason = '';

    if (!secureContext) {
        reason = 'Microphone access requires HTTPS in production.';
    } else if (!mediaDevicesAvailable) {
        reason = 'This browser does not expose microphone capture.';
    } else if (!mediaRecorderAvailable) {
        reason = 'This browser cannot record audio directly.';
    }

    return {
        supported,
        secureContext,
        mediaDevicesAvailable,
        mediaRecorderAvailable,
        reason,
    };
}

window.microphoneSupportStatus = microphoneSupportStatus;

window.applyMicrophoneAvailability = function applyMicrophoneAvailability(target, options = {}) {
    const element = typeof target === 'string' ? document.getElementById(target) : target;
    if (!element) return microphoneSupportStatus();

    const status = microphoneSupportStatus();
    const {
        supportedLabel = null,
        unsupportedLabel = null,
        showToast = false,
    } = options;

    if (!status.supported) {
        element.disabled = true;
        element.classList.add('is-disabled');
        element.setAttribute('aria-disabled', 'true');
        element.title = status.reason || 'Microphone unavailable';
        if (unsupportedLabel !== null) {
            if ('value' in element) element.value = unsupportedLabel;
            else element.textContent = unsupportedLabel;
        }
        if (showToast && typeof toast === 'function') {
            toast(status.reason || 'Microphone unavailable', 'warning');
        }
    } else {
        element.disabled = false;
        element.classList.remove('is-disabled');
        element.removeAttribute('aria-disabled');
        if (supportedLabel !== null) {
            if ('value' in element) element.value = supportedLabel;
            else element.textContent = supportedLabel;
        }
    }

    return status;
};

function rankSearchMatches(items, query, getSearchFields, limit = 8) {
    const normalizedQuery = normalizeSearchText(query);
    const terms = normalizedQuery ? normalizedQuery.split(' ').filter(Boolean) : [];

    return (items || [])
        .map((item) => {
            const fields = (getSearchFields(item) || [])
                .map((value) => normalizeSearchText(value))
                .filter(Boolean);
            if (!fields.length) return null;
            if (!normalizedQuery) return { item, score: 1 };
            if (fields.some((field) => field === normalizedQuery)) return { item, score: 5 };
            if (fields.some((field) => field.startsWith(normalizedQuery))) return { item, score: 4 };
            if (terms.length && terms.every((term) => fields.some((field) => field.includes(term)))) return { item, score: 3 };
            if (fields.some((field) => field.includes(normalizedQuery))) return { item, score: 2 };
            return null;
        })
        .filter(Boolean)
        .sort((a, b) => b.score - a.score)
        .slice(0, limit)
        .map((entry) => entry.item);
}
