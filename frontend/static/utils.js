/**
 * Antigravity CRM — Shared JS Utilities
 * API client, toast notifications, auth helpers.
 * Import this in every page.
 */

// ── API Base URL ──────────────────────────────────────────────
window.API_BASE = '';  // Same origin — FastAPI serves both API and frontend
var API_BASE = window.API_BASE;

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
    isLoggedIn: () => true,
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
    return true;
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
function channelLabel(ch) {
    const map = {
        note: 'Note', whatsapp: 'WhatsApp', email: 'Email', call: 'Call',
        meeting: 'Meeting', audio: 'Audio', screenshot: 'Screenshot',
        upload: 'Upload', chat: 'AI Chat', system_audit: 'Audit'
    };
    return map[ch] || ch;
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
                <a href="/?view=pipeline" class="nav-icon-link ${activePage === 'pipeline' ? 'active' : ''}" title="Pipeline">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M22 12h-4l-3 9L9 3l-3 9H2"></path></svg>
                </a>
                <a href="/analytics" class="nav-icon-link ${activePage === 'analytics' ? 'active' : ''}" title="Analytics">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><line x1="18" y1="20" x2="18" y2="10"></line><line x1="12" y1="20" x2="12" y2="4"></line><line x1="6" y1="20" x2="6" y2="14"></line></svg>
                </a>
                <a href="/events" class="nav-icon-link ${activePage === 'events' ? 'active' : ''}" title="Events">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="5" width="18" height="16" rx="2"></rect><path d="M16 3v4"></path><path d="M8 3v4"></path><path d="M3 11h18"></path><path d="M8 15h3"></path><path d="M13 15h3"></path></svg>
                </a>
                <a href="/settings" class="nav-icon-link ${activePage === 'settings' ? 'active' : ''}" title="Settings">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>
                </a>
            </nav>

            <div class="top-nav-right">
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
    
    // Initialize Search Logic
    initUniversalSearch();
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



