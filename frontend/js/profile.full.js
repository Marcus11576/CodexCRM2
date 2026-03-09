var API_BASE = window.API_BASE || '';
let personId = null;
let isEditingEnv = false;
let isEditingDisc = false;
let isEditingStatus = false;

// Get person ID from URL
function getPersonIdFromUrl() {
    // Priority 1: Query parameter ?id=...
    const urlParams = new URLSearchParams(window.location.search);
    const idParam = urlParams.get('id');
    if (idParam) return idParam;

    // Priority 2: Path match /people/ID or /person/ID
    const path = window.location.pathname;
    const match = path.match(/\/(?:people|person)\/([^\/]+)/);
    return match ? match[1] : null;
}

// Category badge
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

// Format date and time
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

        if (diffDays < 0) {
            return `${Math.abs(diffDays)}d past`;
        } else if (diffDays === 0) {
            return 'Today';
        } else if (diffDays === 1) {
            return 'Tomorrow';
        } else if (diffDays > 1 && diffDays < 7) {
            return `${diffDays}d`;
        } else {
            return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        }
    } catch (e) {
        return dateStr;
    }
}

// TS Advisory Logic
let isAdvisoryState = false;
function setAdvisory(isAdvisory) {
    isAdvisoryState = isAdvisory;
    const checkbox = document.getElementById('advisory-checkbox');
    if (checkbox) {
        checkbox.checked = isAdvisory;
    }

    if (personId) {
        updatePersonField('is_ts_advisory_candidate', isAdvisory ? 1 : 0);
    }
}

function toggleAdvisoryCheckbox(el) {
    setAdvisory(el.checked);
}

// AI Pipeline Feedback Logic
async function logAiFeedback(targetType, eventType) {
    console.log(`AI Feedback: ${targetType} - ${eventType}`);
    const personId = getPersonIdFromUrl();
    if (!personId) return;

    try {
        const response = await fetch('/api/ai/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                target_type: targetType,
                target_id: personId, // For now, linking to Person ID as target_id for briefs
                event_type: eventType,
                details: { timestamp: new Date().toISOString() }
            })
        });

        if (response.ok) {
            showToast(`Feedback recorded: ${eventType}`, 'success');
        } else {
            console.error('Feedback failed:', await response.text());
        }
    } catch (err) {
        console.error('Feedback error:', err);
    }
}

// updatePersonField moved to consolidated location below

// Get initials
function getInitials(name) {
    if (!name) return '?';
    return name.split(' ').map(n => n[0]).join('').toUpperCase().substring(0, 2);
}

// Load person data
async function loadPerson() {
    personId = getPersonIdFromUrl();

    if (!personId) {
        document.getElementById('loading').innerHTML = '<p style="color: var(--accent-red);">Invalid person ID</p>';
        return;
    }

    try {
        // Load person details FIRST and FAST
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
        // Render person data and history immediately
        renderPerson(personData.person, { recent_history: personData.history });

        // Show content, hide global loading
        document.getElementById('loading').style.display = 'none';
        document.getElementById('content').style.display = 'block';

        // --- PLATINUM PLUGIN MOUNT ---
        if (window.AntigravityPlugins) {
            window.AntigravityPlugins.mountAll('content', personData.person);
        }

        // Now load briefing in background only once per page load, unless refreshed
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
            renderPerson(data.person, { recent_history: data.history });
            // Re-mount plugins without reset
            if (window.AntigravityPlugins) {
                window.AntigravityPlugins.mountAll('content', data.person);
            }
        }
    } catch (e) {
        console.error('Quiet load failed:', e);
    }
}

async function loadBriefing() {
    const briefingContent = document.getElementById('briefing-content');
    briefingContent.innerHTML = `
                <div style="display:flex; align-items:center; gap:10px; color:var(--text-secondary); font-size:0.9rem;">
                    <div class="spinner" style="width:20px; height:20px; border-width:2px; margin:0;"></div>
                    <span>AI Assistant is preparing your briefing...</span>
                </div>
            `;

    try {
        const briefingRes = await fetch(`${API_BASE}/api/intelligence/brief/${personId}`, {
            headers: { 'Accept': 'application/json' }
        });
        const data = await briefingRes.json();

        // data.briefing contains the AI response
        window._briefingCached = data.cached || false;
        renderBriefing(data.briefing);
    } catch (err) {
        console.error('Briefing load failed:', err);
        briefingContent.innerHTML = '<p style="color:var(--text-secondary);">Briefing currently unavailable.</p>';
    }
}
async function forceRefreshBriefing() {
    const btn = document.getElementById('btn-brief-regen') || document.getElementById('regen-btn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Regenerating...';
        btn.style.opacity = '0.5';
    }

    document.getElementById('briefing-content').innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; color:var(--text-secondary); font-size:0.9rem;">
            <div class="spinner" style="width:20px; height:20px; border-width:2px; margin:0;"></div>
            <span>Regenerating strategic context...</span>
        </div>`;

    try {
        const res = await fetch(`${API_BASE}/api/intelligence/brief/${personId}`, { method: 'POST' });
        if (!res.ok) throw new Error('Regen failed');
        const data = await res.json();
        window._briefingCached = false;
        renderBriefing(data.briefing);
    } catch (err) {
        console.error('Brief regen failed:', err);
        alert("Briefing regeneration failed.");
        document.getElementById('briefing-content').innerHTML = '<p style="color:var(--text-secondary);">Briefing currently unavailable.</p>';
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '?? Regenerate';
            btn.style.opacity = '1';
        }
    }
}


// Render person data
function renderPerson(person, briefing) {
    // Expose person globally so the task modal can read person_id / full_name
    window.currentPersonData = person;

    const universalTitle = document.querySelector('h1.universal-header');
    if (universalTitle) universalTitle.textContent = (person.full_name || '').toUpperCase();

    if (document.getElementById('profile-chat-title')) {
        document.getElementById('profile-chat-title').textContent = `Assistant for ${person.full_name}`;
    }

    // Status Icon logic - Minimalist Pointers
    let statusIcon = '';
    if (person.contact_value === 'Hot') {
        statusIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="var(--accent-red)" style="margin-left:8px; vertical-align:middle; filter: drop-shadow(0 0 4px var(--accent-red));">
                    <circle cx="12" cy="12" r="8"></circle>
                </svg>`;
    } else if (person.contact_value === 'Warm') {
        statusIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="var(--accent-orange)" style="margin-left:8px; vertical-align:middle; filter: drop-shadow(0 0 4px var(--accent-orange));">
                    <circle cx="12" cy="12" r="8"></circle>
                </svg>`;
    } else if (person.contact_value === 'Cold') {
        statusIcon = `<svg width="14" height="14" viewBox="0 0 24 24" fill="var(--accent-blue)" style="margin-left:8px; vertical-align:middle; opacity: 0.6;">
                    <circle cx="12" cy="12" r="8"></circle>
                </svg>`;
    }

    document.getElementById('profile-name').innerHTML = person.full_name + statusIcon + ` <span onclick="editProfileHeader()" title="Edit name, title, company" style="cursor:pointer; font-size:0.85rem; opacity:0.5; margin-left:8px; vertical-align:middle;">?</span>`;
    document.getElementById('profile-title').innerHTML =
        `${person.title_current || 'No title'} @ ${person.company_name_raw || 'Unknown'} <span onclick="editProfileHeader()" title="Edit" style="cursor:pointer; opacity:0.5; font-size:0.8rem;">?</span>`;

    // Contact Info Row
    let contactRow = document.getElementById('contact-info-row');
    if (!contactRow) {
        contactRow = document.createElement('div');
        contactRow.id = 'contact-info-row';
        contactRow.className = 'contact-info-row';
        document.getElementById('profile-title').insertAdjacentElement('afterend', contactRow);
    }

    contactRow.innerHTML = `
                <div class="contact-info-item" onclick="editProfileHeader()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                        <polyline points="22,6 12,13 2,6"></polyline>
                    </svg>
                    <span>${person.email_primary || ''}</span>
                    <span class="edit-info-btn">?</span>
                </div>
                ${person.email_secondary ? `
                <div class="contact-info-item" onclick="editProfileHeader()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
                        <polyline points="22,6 12,13 2,6"></polyline>
                    </svg>
                    <span>${person.email_secondary}</span>
                    <span class="edit-info-btn">?</span>
                </div>` : ''}
                <div class="contact-info-item" onclick="editProfileHeader()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                    </svg>
                    <span>${person.phone_primary || ''}</span>
                    <svg style="margin-left: 6px;" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent-green)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 1 1-7.6-11.7 8.38 8.38 0 0 1 3.8.9L21 3z"></path>
                    </svg>
                    <span class="edit-info-btn">?</span>
                </div>
                ${person.phone_secondary ? `
                <div class="contact-info-item" onclick="editProfileHeader()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path>
                    </svg>
                    <span>${person.phone_secondary}</span>
                    <span class="edit-info-btn">?</span>
                </div>` : ''}
            `;

    // Initials in photo OR Profile Image
    const photoEl = document.getElementById('profile-photo');
    if (person.profile_photo_url) {
        const photoSrc = `${API_BASE}${person.profile_photo_url}`;
        const initials = getInitials(person.full_name);
        photoEl.innerHTML = `
                    <img src="${photoSrc}" 
                         alt="${person.full_name}" 
                         style="width:100%; height:100%; object-fit:cover; border-radius:17px;"
                         onerror="this.parentElement.innerHTML='${initials}'; this.parentElement.style.background='var(--bg-secondary)';">`;
        photoEl.style.backgroundImage = 'none';
        photoEl.style.backgroundColor = 'transparent';
        photoEl.style.display = 'flex';
        photoEl.style.alignItems = 'center';
        photoEl.style.justifyContent = 'center';
    } else {
        photoEl.textContent = getInitials(person.full_name);
        photoEl.style.backgroundImage = 'none';
        photoEl.style.backgroundColor = 'var(--bg-secondary)';
        photoEl.innerHTML = getInitials(person.full_name);
    }


    // SIT-REP Pill (V1 Style)
    const meetingTarget = document.getElementById('meeting-status-display');
    if (person.next_contact_due_date && meetingTarget) {
        const statusText = person.meeting_status === 'overdue' ? 'PAST' :
            person.meeting_status === 'soon' ? 'SOON' : 'ON TRACK';

        meetingTarget.innerHTML = `
                    <div class="meet-pill">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line>
                        </svg>
                        <span>${formatDate(person.next_contact_due_date)}</span>
                        <span style="opacity: 0.2">·</span>
                        <span class="meet-topic">${person.next_meeting_topic || 'Meeting / Review'}</span>
                        ${statusText === 'PAST' ? `<span style="font-size:0.55rem; padding:1px 6px; border-radius:100px; background:rgba(239,68,68,0.15); border:1px solid rgba(239,68,68,0.4); color:#f87171; margin-left:0.2rem;">PAST</span>` : ''}
                    </div>
                `;
    } else if (meetingTarget) {
        meetingTarget.innerHTML = '';
    }

    // Action Cluster (V1 Style)
    const iconActions = document.getElementById('header-icon-actions');
    if (iconActions) {
        iconActions.innerHTML = `
                    <div class="v1-act-btn" onclick="window.location.href='mailto:${person.email_primary || ''}'" title="Email">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline></svg>
                    </div>
                    <div class="v1-act-btn" onclick="window.location.href='tel:${person.phone_primary || ''}'" title="Call">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                    </div>
                    <div class="v1-act-btn" onclick="const p='${(person.phone_primary || '').replace(/\D/g, '')}'; window.location.href='whatsapp://send?phone='+p" title="WhatsApp">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 1 1-7.6-11.7 8.38 8.38 0 0 1 3.8.9L21 3z"></path></svg>
                    </div>
                    <div class="v1-act-btn primary" onclick="openTaskModal()" title="Add Task">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
                    </div>
                    ${person.linkedin_url ? `
                    <div class="v1-act-btn" onclick="window.open('${person.linkedin_url}', '_blank')" title="LinkedIn">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle>
                        </svg>
                    </div>` : `
                    <div class="v1-act-btn" style="opacity:0.3; cursor:default;" title="No LinkedIn URL">
                         <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"></path><rect x="2" y="9" width="4" height="12"></rect><circle cx="4" cy="4" r="2"></circle>
                        </svg>
                    </div>`}
                `;
    }

    // Intelligence Databank Fetch
    fetchintelligence();

    // Intelligence & Context Overrides
    const persContext = document.getElementById('pers-context-text');
    if (persContext) {
        persContext.setAttribute('contenteditable', 'true');
        persContext.textContent = person.key_personal_notes || '';
        persContext.onblur = () => {
            const v = persContext.innerText.trim();
            if (v !== (person.key_personal_notes || '')) updatePersonField('key_personal_notes', v);
        };
    }

    const profEl = document.getElementById('prof-context-text');
    if (profEl) {
        profEl.setAttribute('contenteditable', 'true');
        profEl.textContent = person.key_professional_notes || '';
        profEl.onblur = () => {
            const v = profEl.innerText.trim();
            if (v !== (person.key_professional_notes || '')) updatePersonField('key_professional_notes', v);
        };
    }

    // Career History
    renderCareerTimeline(Array.isArray(person.employment_history) ? person.employment_history : []);

    // Env Toggles Init
    renderEnvToggles(person.env);
    setAdvisory(person.is_ts_advisory_candidate ? true : false);

    // Disc Toggles Init
    renderDiscToggles(person.disc || 'OTHR');

    // Cat Toggles Init
    renderCatToggles(person.cat || 'GEN');

    // Status Toggles Init
    renderStatusToggles(person.contact_value);

    // Briefing History & Tasks
    if (briefing && briefing.recent_history && Array.isArray(briefing.recent_history) && briefing.recent_history.length > 0) {
        renderInteractions(briefing.recent_history);
    } else {
        const iTimeline = document.getElementById('interactions-timeline');
        if (iTimeline) iTimeline.innerHTML = '<p style="color: var(--text-secondary);">No interactions recorded</p>';
    }

    if (briefing && briefing.open_loops && Array.isArray(briefing.open_loops) && briefing.open_loops.length > 0) {
        const tSection = document.getElementById('tasks-section');
        if (tSection) tSection.style.display = 'block';
        renderTasks(briefing.open_loops);
    }
}

async function fetchintelligence() {
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}/intelligence`);
        if (!res.ok) throw new Error('Failed to fetch intelligence');
        const data = await res.json();

        renderTopic('db-business', data.business_focus, 'business-focus');
        renderTopic('db-recruitment', data.recruitment_talent, 'recruitment-talent');
        renderTopic('db-personal', data.family_personal, 'family-personal');
        renderTopic('db-obe', data.obe_focus, 'obe-focus');
    } catch (err) {
        console.error(err);
    }
}

function renderTopic(elementId, nuggets, cssClass) {
    const container = document.getElementById(elementId);
    if (!container) return;

    if (!nuggets || nuggets.length === 0) {
        container.innerHTML = `<div style="color:var(--text-muted); font-size:0.75rem; padding:1rem; opacity:0.5;">No data points captured.</div>`;
        return;
    }

    const icons = {
        'whatsapp': '??', 'email': '??', 'call': '??', 'meeting': '??',
        'screenshot': '???', 'audio': '??', 'upload': '??', 'document': '??', 'note': '??'
    };

    container.innerHTML = nuggets.map(n => {
        const icon = icons[n.channel] || '??';
        const sourceName = n.channel ? (n.channel.charAt(0).toUpperCase() + n.channel.slice(1)) : 'Note';
        return `
                <div class="nugget-item ${cssClass}">
                    <div class="nugget-date" style="display:flex; justify-content:space-between; align-items:center;">
                        <span>${formatDate(n.date)}</span>
                        <span title="Source: ${sourceName}" style="opacity:0.7; font-size:0.85rem;">${icon}</span>
                    </div>
                    <div class="nugget-text">${n.text}</div>
                </div>
            `;
    }).join('');
}

// -- WORLD-CLASS 6-SECTION BRIEFING RENDERER ---------------------------
let currentBriefData = null;  // Stores latest brief for audio generation

function briefSection(content, title, iconClass, color, isFullWidth = false) {
    let displayContent = content;
    if (!content || content === 'No specific data recorded.' || content === 'Not available.') {
        displayContent = `<span style="opacity:0.4; font-style:italic; font-size:0.8rem;">Nothing specific recorded yet.</span>`;
    }

    let html = '';
    if (Array.isArray(displayContent)) {
        html = `<ul style="margin:0; padding-left:0; list-style:none;">` +
            displayContent.map(b => `<li style="position:relative; padding-left:1.25rem; margin-bottom:0.5rem; color:#fff; font-size:0.875rem; line-height:1.6; opacity:0.9;">
                        <span style="position:absolute; left:0; color:${color}; font-weight:bold;">&rsaquo;</span> ${b}
                    </li>`).join('') +
            `</ul>`;
    } else {
        html = `<p style="color:#fff; font-size:0.92rem; line-height:1.6; margin:0; font-weight:500; opacity:0.95;">${displayContent}</p>`;
    }

    return `
            <div style="grid-column: ${isFullWidth ? 'span 2' : 'span 1'}; 
                        padding: 1.25rem; 
                        background: rgba(255,255,255,0.03); 
                        border: 1px solid rgba(255,255,255,0.1); 
                        border-top: 2px solid ${color};
                        border-radius: 12px;
                        transition: transform 0.2s ease;">
                <div style="font-size:0.65rem; text-transform:uppercase; letter-spacing:1.8px; color:${color}; font-weight:800; margin-bottom:1rem; display:flex; align-items:center; gap:0.5rem;">
                    <i class="${iconClass}" style="font-size:0.9rem;"></i> ${title}
                </div>
                ${html}
            </div>`;
}

function renderBriefing(briefing) {
    const container = document.getElementById('briefing-content');
    if (!container) return;

    if (!briefing) {
        container.innerHTML = `<div style="padding:1rem; opacity:0.6; font-size:0.85rem;">No briefing generated yet.</div>`;
        return;
    }

    // --- REFRESH BUTTON & STATUS ---
    const isCached = window._briefingCached === true;
    const refreshHTML = `
                <div style="display:flex; justify-content:flex-end; gap:8px; margin-bottom:1rem; align-items:center;">
                    ${isCached ? '<span style="font-size:0.65rem; color:var(--accent-blue); opacity:0.7; font-weight:700; text-transform:uppercase; letter-spacing:1px;">?? Cached (Token Optimized)</span>' : '<span style="font-size:0.65rem; color:var(--accent-cyan); opacity:0.7; font-weight:700; text-transform:uppercase; letter-spacing:1px;">? Fresh Generation</span>'}
                </div>
            `;

    // Store for other functions
    currentBriefData = briefing;

    const labelRecruitment = briefing.label_recruitment || 'Recruitment & Talent';
    const labelObe = briefing.label_obe || 'OBE Focus';

    // Header colors for the new topics
    container.innerHTML = refreshHTML + `
                <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1.25rem;">
                    ${briefSection(briefing.business_focus, 'Business Focus', 'fas fa-chart-line', '#3b82f6')}
                    ${briefSection(briefing.recruitment_talent, labelRecruitment, 'fas fa-users-cog', '#fbbf24')}
                    ${briefSection(briefing.personal_rapport, 'Personal Rapport', 'fas fa-heart', '#f472b6')}
                    ${briefSection(briefing.obe_focus, labelObe, 'fas fa-star', '#a78bfa')}
                    ${briefSection(briefing.strategic_hypotheses, 'Strategic Hypotheses', 'fas fa-brain', '#a78bfa', true)}
                </div>
                <div style="margin-top: 1.5rem; text-align: center; display: flex; flex-direction: column; align-items: center; gap: 0.75rem;">
                    <div style="font-size:0.6rem; color:rgba(255,255,255,0.3); text-transform:uppercase; letter-spacing:1px;">
                        Platinum Standard Strategic Brief &middot; v5.0 SIT-REP
                    </div>
                </div>
            `;

    // Set voice from briefing metadata if available
    if (briefing.voice) {
        const vSelect = document.getElementById('select-brief-voice');
        if (vSelect) vSelect.value = briefing.voice;
    }

    // Store the audio script for the Listen button
    window.currentBriefAudioScript = briefing.audio_script || "";
}


function buildBriefAudioScript(b) {
    if (b && b.audio_script && b.audio_script !== "Not available.") {
        return b.audio_script;
    }

    if (!b) return "No briefing available.";
    const sections = [];
    if (b.personal_rapport) sections.push(`Personal Rapport: ${b.personal_rapport}`);
    if (b.business_focus) sections.push(`Business Focus: ${b.business_focus}`);
    if (b.recruitment_talent) sections.push(`Recruitment and Talent: ${b.recruitment_talent}`);
    if (b.obe_focus) sections.push(`OBE Focus: ${b.obe_focus}`);
    if (b.strategic_hypotheses) sections.push(`Strategic Hypotheses: ${b.strategic_hypotheses}`);
    return sections.join('\n\n');
}

async function generateBriefAudio() {
    if (!currentBriefData) {
        alert('Generate the brief first with ?? Regenerate');
        return;
    }
    const btn = document.getElementById('btn-brief-listen');
    btn.textContent = '? Recording...';
    btn.disabled = true;
    try {
        const script = buildBriefAudioScript(currentBriefData);
        const voice = document.getElementById('select-brief-voice')?.value || 'shimmer';
        const res = await fetch(`${API_BASE}/api/intelligence/tts/${personId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: script, voice: voice })
        });
        const data = await res.json();
        if (data.audio_url) {
            const player = document.getElementById('brief-audio-player');
            player.src = data.audio_url;
            player.style.display = 'block';
            player.play();
            btn.textContent = '? Playing';
            player.onended = () => { btn.textContent = '?? Listen'; btn.disabled = false; };
        } else {
            alert('Audio generation failed: ' + (data.detail || 'Unknown error'));
            btn.textContent = '?? Listen';
            btn.disabled = false;
        }
    } catch (e) {
        alert('Error: ' + e.message);
        btn.textContent = '?? Listen';
        btn.disabled = false;
    }
}



// Render interactions timeline
function renderInteractions(interactions) {
    const html = interactions.slice(0, 5).map(interaction => `
                <div class="timeline-item">
                    <div class="timeline-icon">??</div>
                    <div class="timeline-content" id="interaction-${interaction.interaction_id}">
                        <div class="timeline-date">${formatDateTime(interaction.created_at || interaction.interaction_at)}</div>
                        <div class="timeline-text" id="text-${interaction.interaction_id}">${interaction.summary || interaction.raw_text || 'No details'}</div>
                        <div style="margin-top:0.5rem; display:flex; gap:0.5rem;">
                            <button onclick="editInteraction('${interaction.interaction_id}')" style="font-size:0.75rem; padding:2px 8px; background:rgba(255,255,255,0.1); border:none; border-radius:4px; color:var(--text-primary); cursor:pointer;">Edit</button>
                            <button onclick="deleteInteraction('${interaction.interaction_id}')" style="font-size:0.75rem; padding:2px 8px; background:rgba(255,0,0,0.1); border:none; border-radius:4px; color:var(--accent-red); cursor:pointer;">Delete</button>
                        </div>
                    </div>
                </div>
            `).join('');

    document.getElementById('interactions-timeline').innerHTML = html || '<p style="color: var(--text-secondary);">No interactions recorded</p>';
}

// Render tasks
function renderTasks(tasks) {
    const html = tasks.map(task => `
                <div class="context-item" style="display:flex; justify-content:space-between; align-items:center;">
                    <div style="flex:1;">
                        <div class="context-label">Due: ${task.due_date}</div>
                        <div class="context-text">${task.task_text}</div>
                    </div>
                    <button onclick="deleteTask('${task.task_id}')" 
                            style="font-size:1.2rem; padding:4px 8px; background:rgba(255,0,0,0.1); border:none; border-radius:4px; color:var(--accent-red); cursor:pointer; margin-left:1rem;"
                            title="Delete task">???</button>
                </div>
            `).join('');

    document.getElementById('tasks-list').innerHTML = html;
}

// Scroll to briefing
function scrollToBriefing() {
    document.getElementById('briefing-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Executive Log File Handling
let selectedLogFiles = [];

function handleLogFileSelect(input) {
    if (!input.files || input.files.length === 0) return;

    const container = document.getElementById('selected-files-container');

    for (const file of input.files) {
        selectedLogFiles.push(file);

        const chip = document.createElement('div');
        chip.style = `
            background: rgba(53,232,255,0.1);
            border: 1px solid rgba(53,232,255,0.3);
            border-radius: 6px;
            padding: 4px 10px;
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.75rem;
            color: var(--accent-cyan);
        `;
        chip.innerHTML = `
            <i class="fas fa-file-alt"></i>
            <span style="max-width:120px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${file.name}</span>
            <i class="fas fa-times" style="cursor:pointer; opacity:0.6;" onclick="removeLogFile(this, ${selectedLogFiles.length - 1})"></i>
        `;
        container.appendChild(chip);
    }
    input.value = ''; // clear for next pick
}

function removeLogFile(el, index) {
    selectedLogFiles.splice(index, 1);
    el.parentElement.remove();
}

// Submit Interaction
async function submitInteraction() {
    const input = document.getElementById('interaction-input');
    const status = document.getElementById('log-status');
    const btn = document.getElementById('btn-submit-interaction');
    const fileContainer = document.getElementById('selected-files-container');

    if (!input) return;
    const text = input.value.trim();

    if (!text && selectedLogFiles.length === 0) {
        input.focus();
        return;
    }

    btn.disabled = true;
    const originalBtnHtml = btn.innerHTML;
    btn.innerHTML = 'Processing... <i class="fas fa-spinner fa-spin"></i>';
    if (status) status.textContent = 'AI is extracting intelligence...';

    try {
        // 1. Upload Files First
        for (const file of selectedLogFiles) {
            const formData = new FormData();
            formData.append('file', file);

            const fileRes = await fetch(`${API_BASE}/api/interactions/upload/${personId}`, {
                method: 'POST',
                body: formData
            });
            if (!fileRes.ok) console.warn(`Failed to upload ${file.name}`);
        }

        // 2. Submit Text if present
        if (text) {
            const res = await fetch(`${API_BASE}/api/interactions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    person_id: personId,
                    raw_text: text,
                    channel: 'note',
                    process_with_ai: true
                })
            });
            if (!res.ok) throw new Error('Failed to save interaction text');
        }

        // Success Cleanup
        input.value = '';
        selectedLogFiles = [];
        if (fileContainer) fileContainer.innerHTML = '';

        if (status) {
            status.textContent = '? Intelligence logged and processed.';
            status.style.color = 'var(--accent-cyan)';
        }

        // Surgical UI Update - Only load the parts that changed
        await loadPersonQuiet();
        loadBriefing();
        loadPropensityData();

        setTimeout(() => { if (status) status.textContent = ''; }, 5000);
    } catch (err) {
        console.error(err);
        if (status) {
            status.textContent = '? Error logging intelligence.';
            status.style.color = 'var(--accent-red)';
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
    }
}

// Edit Interaction
function editInteraction(id) {
    const textDiv = document.getElementById(`text-${id}`);
    const currentText = textDiv.innerText;
    textDiv.innerHTML = `
                <textarea id="edit-${id}" style="width:100%; height:60px; background:rgba(0,0,0,0.2); border:1px solid var(--glass-border); color:var(--text-primary); padding:0.5rem; border-radius:4px;">${currentText}</textarea>
                <div style="margin-top:0.5rem;">
                    <button onclick="saveInteraction('${id}')" class="action-btn primary" style="font-size:0.8rem; padding:4px 8px;">Save</button>
                    <button onclick="loadPerson()" class="action-btn" style="font-size:0.8rem; padding:4px 8px;">Cancel</button>
                </div>
            `;
}

// Save Edited Interaction
async function saveInteraction(id) {
    const newText = document.getElementById(`edit-${id}`).value;
    try {
        const res = await fetch(`${API_BASE}/api/interactions/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: newText })
        });
        if (res.ok) {
            loadPerson(); // Reload to show updates
        } else {
            alert('Failed to update interaction');
        }
    } catch (err) {
        console.error(err);
        alert('Error updating interaction');
    }
}

// Delete Interaction
async function deleteInteraction(id) {
    if (!confirm('Are you sure you want to delete this interaction?')) return;
    try {
        const res = await fetch(`${API_BASE}/api/interactions/${id}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            loadPerson(); // Reload to show updates
        } else {
            alert('Failed to delete interaction');
        }
    } catch (err) {
        console.error(err);
        alert('Error deleting interaction');
    }
}

async function loadPropensityData() {
    try {
        const res = await fetch(`${API_BASE}/api/analytics/propensity/${personId}`);
        if (!res.ok) return;
        const data = await res.json();

        const healthScore = document.getElementById('health-score');
        const healthBar = document.getElementById('health-bar');
        const velocityScore = document.getElementById('velocity-score');
        const nextAction = document.getElementById('next-action');

        if (healthScore) healthScore.innerText = `${data.health || 0}%`;
        if (healthBar) healthBar.style.width = `${data.health || 0}%`;
        if (velocityScore) velocityScore.innerText = data.recent_hits_14d || 0;
        if (nextAction) nextAction.innerText = `AI Recommended: ${data.next_best_action}`;

    } catch (err) {
        console.error('Failed to load propensity:', err);
    }
}

// --- Update Functions for Dropdowns ---

let activeTaxonomy = {};

async function fetchTaxonomy() {
    if (Object.keys(activeTaxonomy).length > 0) return;
    try {
        const res = await fetch(`${API_BASE}/api/config/taxonomy`);
        const data = await res.json();
        const list = Array.isArray(data) ? data : (data.items || []);
        activeTaxonomy = list.reduce((acc, item) => {
            if (!acc[item.category_type]) acc[item.category_type] = [];
            acc[item.category_type].push(item);
            return acc;
        }, {});
    } catch (err) {
        console.error("Failed to fetch taxonomy:", err);
        activeTaxonomy = {
            cat: [{ value: 'OBE M', label: 'OBE Member' }, { value: 'OBE T', label: 'OBE Target' }, { value: 'TGT', label: 'Client Target' }, { value: 'EXT', label: 'Existing Client' }, { value: 'HPC', label: 'Candidate' }, { value: 'GEN', label: 'General' }],
            env: [{ value: 'DEV-G', label: 'Gov Dev' }, { value: 'DEV-S', label: 'Semi-Gov Dev' }, { value: 'DEV-P', label: 'Private Dev' }, { value: 'CONS', label: 'Consultant' }, { value: 'MAIN', label: 'Main Contractor' }, { value: 'SUB', label: 'Sub Contractor' }, { value: 'MGMT', label: 'PMO' }],
            disc: [{ value: 'COMM', label: 'Commercial' }, { value: 'DELV', label: 'Delivery' }, { value: 'DSGN', label: 'Design' }, { value: 'CORP', label: 'Corporate' }, { value: 'SUPP', label: 'Support' }, { value: 'OTHR', label: 'Others' }],
            contact_value: [{ value: 'Hot', label: 'Hot' }, { value: 'Warm', label: 'Warm' }, { value: 'Cold', label: 'Cold' }],
            engagement_status: [{ value: 'Active', label: 'Active' }, { value: 'Passive', label: 'Passive' }, { value: 'Dormant', label: 'Dormant' }]
        };
    }
}

async function setEnv(env) {
    await updatePersonField('env', env);
    isEditingEnv = false;
    loadPerson();
}

function toggleEnvEdit() {
    isEditingEnv = !isEditingEnv;
    renderEnvToggles(window.currentPersonData?.env);
}

// Removed redundant setEnv definition below


function renderEnvToggles(currentString) {
    const envs = activeTaxonomy['env'] || [];
    const container = document.getElementById('env-toggles');
    if (!container) return;

    const selectedArray = (currentString || '').split(',').map(e => e.trim()).filter(Boolean);

    if (isEditingEnv) {
        container.innerHTML = envs.map(e => {
            const isActive = selectedArray.includes(e.value);
            return `<button class="chip ${isActive ? 'active' : ''}" 
                            onclick="toggleSelectEnv('${e.value}', '${currentString || ''}')">${e.label}</button>`;
        }).join('');
    } else {
        if (selectedArray.length === 0) {
            container.innerHTML = `<span style="font-size:0.65rem; color:var(--text-muted); padding:2px 0;">None</span>`;
        } else {
            container.innerHTML = selectedArray.map(val => {
                const taxItem = envs.find(e => e.value === val) || envs.find(e => e.label === val);
                return `<div class="chip active">${taxItem ? taxItem.label : val}</div>`;
            }).join('');
        }
    }
}

async function toggleSelectEnv(val, currentString) {
    let selectedArray = (currentString || '').split(',').map(e => e.trim()).filter(Boolean);
    if (selectedArray.includes(val)) {
        selectedArray = selectedArray.filter(v => v !== val);
    } else {
        selectedArray.push(val);
    }
    const newStr = selectedArray.join(', ');
    await updatePersonField('env', newStr);
    loadPerson();
}

function toggleDiscEdit() {
    isEditingDisc = !isEditingDisc;
    renderDiscToggles(window.currentPersonData?.disc);
}

function renderDiscToggles(currentString) {
    const discs = activeTaxonomy['disc'] || [];
    const container = document.getElementById('disc-toggles');
    if (!container) return;

    const defaultDisc = 'Other';
    const selectedArray = (currentString || defaultDisc).split(',').map(d => d.trim()).filter(Boolean);

    if (isEditingDisc) {
        container.innerHTML = discs.map(d => {
            const isActive = selectedArray.includes(d.value);
            return `<button class="chip ${isActive ? 'active' : ''}" onclick="toggleSelectDisc('${d.value}', '${currentString || defaultDisc}')">${d.label}</button>`;
        }).join('');
    } else {
        container.innerHTML = selectedArray.map(val => {
            const taxItem = discs.find(d => d.value === val) || discs.find(d => d.label === val);
            return `<div class="chip active">${taxItem ? taxItem.label : val}</div>`;
        }).join('');
    }
}

async function toggleSelectDisc(val, currentString) {
    // Use 'Other' as the default if nothing is selected, matching DB value
    const defaultDisc = 'Other';
    let selectedArray = (currentString || defaultDisc).split(',').map(d => d.trim()).filter(Boolean);
    if (selectedArray.includes(val)) {
        if (selectedArray.length > 1) {
            selectedArray = selectedArray.filter(v => v !== val);
        } else if (val !== defaultDisc) {
            selectedArray = [defaultDisc];
        }
    } else {
        if (selectedArray.includes(defaultDisc)) {
            selectedArray = selectedArray.filter(v => v !== defaultDisc);
        }
        selectedArray.push(val);
    }
    const newStr = selectedArray.join(', ');
    await updatePersonField('disc', newStr);
    loadPerson();
}

let isEditingCat = false;
function toggleCatEdit() {
    isEditingCat = !isEditingCat;
    loadPerson();
}

function renderCatToggles(currentCatsString) {
    const taxonomyCats = activeTaxonomy['cat'] || [];
    const cats = taxonomyCats.length > 0 ? taxonomyCats : [
        { value: 'OBE M', label: 'OBE M' },
        { value: 'OBE T', label: 'OBE T' },
        { value: 'EXT', label: 'EXT' },
        { value: 'TGT', label: 'TGT' },
        { value: 'HPC', label: 'HPC' },
        { value: 'GEN', label: 'GEN' }
    ];

    const container = document.getElementById('cat-toggles');
    if (!container) return;

    const selectedArray = (currentCatsString || 'GEN').split(',').map(c => c.trim());

    if (isEditingCat) {
        container.innerHTML = cats.map(c => {
            const isActive = selectedArray.includes(c.value);
            return `<button class="chip ${isActive ? 'active' : ''}" onclick="toggleSelectCat('${c.value}', '${currentCatsString || 'GEN'}')">${c.label}</button>`;
        }).join('');
    } else {
        container.innerHTML = selectedArray.map(c => {
            const taxItem = cats.find(ct => ct.value === c) || cats.find(ct => ct.label === c);
            return `<div class="chip active">${taxItem ? taxItem.label : c}</div>`;
        }).join('');
    }
}

async function toggleSelectCat(cat, currentString) {
    let selectedArray = currentString.split(',').map(c => c.trim());

    if (selectedArray.includes(cat)) {
        // Remove if already selected (toggle off)
        if (selectedArray.length > 1) {
            selectedArray = selectedArray.filter(c => c !== cat);
        } else if (cat !== 'GEN') {
            selectedArray = ['GEN']; // Default back to GEN if everything removed
        }
    } else {
        // Add if not selected (toggle on)
        if (selectedArray.includes('GEN')) {
            selectedArray = selectedArray.filter(c => c !== 'GEN');
        }
        selectedArray.push(cat);
    }

    const newString = selectedArray.join(', ');
    await updatePersonField('cat', newString);
    loadPerson(); // Refresh to show active states
}



function toggleStatusEdit() {
    isEditingStatus = !isEditingStatus;
    renderStatusToggles(window.currentPersonData?.contact_value);
}

function renderStatusToggles(currentStatus) {
    const statuses = [
        { value: 'Hot', label: 'Hot', class: 'hot' },
        { value: 'Warm', label: 'Warm', class: 'warm' },
        { value: 'Cold', label: 'Cold', class: '' }
    ];
    const container = document.getElementById('status-toggles');
    if (!container) return;

    const labelArea = document.getElementById('label-status');
    if (isEditingStatus) {
        container.innerHTML = statuses.map(s => {
            const isActive = currentStatus === s.value;
            return `<button class="chip ${isActive ? 'active' : ''} ${s.class}" onclick="setStatus('${s.value}')">${isActive ? '? ' : ''}${s.label}</button>`;
        }).join('');
    } else {
        const s = statuses.find(x => x.value === (currentStatus || 'Cold'));
        container.innerHTML = `<div class="chip active ${s?.class || ''}">? ${currentStatus || 'Cold'}</div>`;
    }
}

async function setStatus(status) {
    await updatePersonField('contact_value', status);
    isEditingStatus = false;
    loadPerson();
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
        if (res.ok) {
            console.log(`Updated ${field}`);
            // Removed forced regenerateBrief() to prevent unnecessary AI calls
        } else {
            const errorText = await res.text();
            let errorMessage = 'Failed to update';
            try {
                const errorJson = JSON.parse(errorText);
                errorMessage += ': ' + (errorJson.detail || errorText);
            } catch (e) {
                errorMessage += ': ' + errorText;
            }
            alert(errorMessage);
        }
    } catch (err) {
        console.error(err);
        alert('Error updating profile: ' + err.message);
    }
}


// --- Drag & Drop for Files ---
function initDragDrop() {
    const dropZone = document.getElementById('drop-zone');
    if (!dropZone) return; // Safety check

    const body = document.body;

    ['dragenter', 'dragover'].forEach(eventName => {
        body.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            const card = document.querySelector('.person-card');
            if (card) {
                card.style.outline = '3px dashed var(--accent-cyan)';
                card.style.outlineOffset = '4px';
                card.style.borderRadius = '24px';
            }
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        body.addEventListener(eventName, (e) => {
            e.preventDefault();
            e.stopPropagation();
            const card = document.querySelector('.person-card');
            if (card) {
                card.style.outline = '';
            }
        });
    });

    body.addEventListener('drop', async (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) {
            await uploadFiles(files);
        }
    });
}

async function uploadFiles(files) {
    for (let file of files) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            // Show processing message
            const processingMsg = document.createElement('div');
            processingMsg.style = 'position:fixed; top:20px; right:20px; background:var(--bg-card); border:1px solid var(--accent-blue); padding:1rem; border-radius:8px; z-index:200; max-width:300px;';
            processingMsg.innerHTML = `<div style="color:var(--text-primary);"><strong>Processing ${file.name}...</strong><br><small style="color:var(--text-secondary);">Extracting and analyzing content</small></div>`;
            document.body.appendChild(processingMsg);

            const res = await fetch(`${API_BASE}/api/people/${personId}/media`, {
                method: 'POST',
                body: formData
            });

            document.body.removeChild(processingMsg);

            if (res.ok) {
                const result = await res.json();

                // Show enrichment result if available
                if (result.enrichment) {
                    const enrichmentMsg = document.createElement('div');
                    enrichmentMsg.style = 'position:fixed; top:20px; right:20px; background:var(--bg-card); border:1px solid var(--accent-green); padding:1rem 1.5rem; border-radius:8px; z-index:200; max-width:400px;';
                    enrichmentMsg.innerHTML = `
                                <div style="color:var(--text-primary);">
                                    <strong>? Profile Enriched</strong>
                                    <button onclick="this.parentElement.parentElement.remove()" style="float:right; background:none; border:none; color:var(--text-secondary); cursor:pointer; font-size:1.2rem;">&times;</button>
                                    <div style="margin-top:0.5rem; font-size:0.9rem; color:var(--text-secondary); line-height:1.4;">${result.enrichment}</div>
                                </div>
                            `;
                    document.body.appendChild(enrichmentMsg);
                    setTimeout(() => enrichmentMsg.remove(), 10000);
                } else {
                    alert(`Uploaded ${file.name}`);
                }

                loadPerson(); // Refresh
            } else {
                alert(`Failed to upload ${file.name}`);
            }
        } catch (err) {
            console.error(err);
            alert(`Error uploading ${file.name}`);
        }
    }
}

// Delete task
async function deleteTask(taskId) {
    if (!confirm('Are you sure you want to delete this task?')) {
        return;
    }

    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            loadPerson(); // Refresh to show updated tasks and status
        } else {
            const error = await response.json();
            alert(`Error deleting task: ${error.detail || 'Unknown error'}`);
        }
    } catch (err) {
        console.error(err);
        alert('Error deleting task');
    }
}

// Edit Contact Info - Deprecated in favor of unified Edit Profile modal
// async function editContactInfo(field, currentVal) { ... }

// -- PERSONAL INTELLIGENCE DISPLAY & EDITOR ---------------------------
function renderPersonalIntel(pd) {
    const el = document.getElementById('personal-intel-display');
    if (!el) return;
    if (!pd || Object.keys(pd).length === 0) {
        el.innerHTML = `<p style="color:var(--text-muted); font-size:0.82rem;">No personal intelligence recorded yet. Click ? Edit to add details.</p>`;
        return;
    }
    const rows = [];
    if (pd.partner) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? Partner</span><div style="color:white; font-size:0.85rem; margin-top:2px;">${pd.partner}</div></div>`);
    if (pd.kids && pd.kids.length) {
        const kidsHtml = pd.kids.map(k =>
            `${k.name}${k.age ? ` (${k.age})` : ''}${k.school ? `, ${k.school}` : ''}${k.interests?.length ? ` — loves ${k.interests.join(', ')}` : ''}`
        ).join('<br>');
        rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">???????? Kids</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${kidsHtml}</div></div>`);
    }
    if (pd.hobbies?.length) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? Hobbies</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.hobbies.join(', ')}</div></div>`);
    if (pd.sports_teams?.length) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">? Supports</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.sports_teams.join(', ')}</div></div>`);
    if (pd.university) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? University</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.university}</div></div>`);
    if (pd.hometown) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? From</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.hometown}</div></div>`);
    if (pd.personality) rows.push(`<div style="grid-column:span 2;"><span style="color:#f472b6; font-size:0.7rem;">?? Personality</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px; font-style:italic;">${pd.personality}</div></div>`);
    if (pd.upcoming_events?.length) rows.push(`<div style="grid-column:span 2;"><span style="color:#f472b6; font-size:0.7rem;">?? Upcoming</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.upcoming_events.join(' • ')}</div></div>`);
    el.innerHTML = `<div style="display:grid; grid-template-columns:1fr 1fr; gap:0.75rem;">${rows.join('')}</div>`;
}

function openPersonalDataEditor() {
    const existing = document.getElementById('personal-data-modal');
    if (existing) { existing.remove(); return; }
    const pd = window._personPersonalData || {};
    const kidsArr = pd.kids || [];

    const modal = document.createElement('div');
    modal.id = 'personal-data-modal';
    modal.style = `position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(244,114,182,0.2);
                backdrop-filter:none; border-radius:16px; padding:2rem;
                z-index:9999; width:90%; max-width:560px; max-height:85vh; overflow-y:auto;
                box-shadow:0 24px 80px rgba(0,0,0,0.6);`;

    modal.innerHTML = `
                <div style="font-weight:800; font-size:1rem; color:#f472b6; margin-bottom:1.25rem;">?? Personal Intelligence</div>
                ${[
            ['Partner', 'partner', pd.partner || ''],
            ['University', 'university', pd.university || ''],
            ['Hometown / From', 'hometown', pd.hometown || ''],
            ['Hobbies (comma separated)', 'hobbies', (pd.hobbies || []).join(', ')],
            ['Sports Teams (comma separated)', 'sports_teams', (pd.sports_teams || []).join(', ')],
            ['Personality / Communication Style', 'personality', pd.personality || ''],
            ['Upcoming Personal Events (comma separated)', 'upcoming_events', (pd.upcoming_events || []).join(', ')],
        ].map(([lbl, key, val]) => `
                    <div style="margin-bottom:0.75rem;">
                        <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">${lbl}</div>
                        <input id="pd-${key}" value="${val.replace(/"/g, '&quot;')}" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:7px 12px; border-radius:8px; font-size:0.85rem; outline:none; box-sizing:border-box;">
                    </div>`).join('')}
                <div style="margin-bottom:0.75rem;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                        <div style="font-size:0.7rem; color:var(--text-muted);">Kids</div>
                        <button onclick="addKidRow()" style="font-size:0.7rem; padding:2px 8px; background:rgba(244,114,182,0.12); border:1px solid rgba(244,114,182,0.3); color:#f472b6; border-radius:4px; cursor:pointer;">+ Add Kid</button>
                    </div>
                    <div id="kids-table">
                        ${kidsArr.map((k, i) => `
                        <div class="kid-row" style="display:grid; grid-template-columns:1fr 60px 1fr 1fr auto; gap:6px; margin-bottom:6px; align-items:center;">
                            <input placeholder="Name" value="${k.name || ''}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <input placeholder="Age" value="${k.age || ''}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <input placeholder="School" value="${k.school || ''}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <input placeholder="Interests (comma)" value="${(k.interests || []).join(', ')}" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                            <button onclick="this.closest('.kid-row').remove()" style="background:none; border:none; color:rgba(255,80,80,0.6); cursor:pointer; font-size:1rem;">?</button>
                        </div>`).join('')}
                    </div>
                </div>
                <div style="display:flex; gap:0.75rem; margin-top:1rem;">
                    <button onclick="savePersonalData()" style="flex:1; background:#f472b6; color:#0a0a1a; font-weight:800; padding:10px; border:none; border-radius:8px; cursor:pointer;">?? Save</button>
                    <button onclick="document.getElementById('personal-data-modal').remove()" style="flex:1; background:rgba(255,255,255,0.08); color:white; padding:10px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; cursor:pointer;">Cancel</button>
                </div>
            `;
    document.body.appendChild(modal);
}

function addKidRow() {
    const table = document.getElementById('kids-table');
    const row = document.createElement('div');
    row.className = 'kid-row';
    row.style = 'display:grid; grid-template-columns:1fr 60px 1fr 1fr auto; gap:6px; margin-bottom:6px; align-items:center;';
    row.innerHTML = `
                <input placeholder="Name" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <input placeholder="Age" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <input placeholder="School" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <input placeholder="Interests (comma)" style="background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.1); color:white; padding:5px 8px; border-radius:6px; font-size:0.8rem; outline:none;">
                <button onclick="this.closest('.kid-row').remove()" style="background:none; border:none; color:rgba(255,80,80,0.6); cursor:pointer; font-size:1rem;">?</button>
            `;
    table.appendChild(row);
}

async function savePersonalData() {
    const g = id => document.getElementById(id)?.value.trim() || '';
    const splitComma = v => v ? v.split(',').map(x => x.trim()).filter(Boolean) : [];

    const kids = Array.from(document.querySelectorAll('.kid-row')).map(row => {
        const inputs = row.querySelectorAll('input');
        return {
            name: inputs[0]?.value.trim() || '',
            age: inputs[1]?.value.trim() || '',
            school: inputs[2]?.value.trim() || '',
            interests: splitComma(inputs[3]?.value || '')
        };
    }).filter(k => k.name);

    const pd = {
        partner: g('pd-partner') || undefined,
        university: g('pd-university') || undefined,
        hometown: g('pd-hometown') || undefined,
        hobbies: splitComma(g('pd-hobbies')),
        sports_teams: splitComma(g('pd-sports_teams')),
        personality: g('pd-personality') || undefined,
        upcoming_events: splitComma(g('pd-upcoming_events')),
        kids: kids.length ? kids : undefined
    };
    // Clean undefined
    Object.keys(pd).forEach(k => (pd[k] === undefined || (Array.isArray(pd[k]) && !pd[k].length)) && delete pd[k]);

    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ personal_data: pd })
        });
        document.getElementById('personal-data-modal')?.remove();
        if (res.ok) {
            window._personPersonalData = pd;
            renderPersonalIntel(pd);
        } else { alert('Save failed'); }
    } catch (e) { alert('Error: ' + e.message); }
}

// -- EDIT PROFILE HEADER MODAL -----------------------------------------
function editProfileHeader() {
    const existing = document.getElementById('profile-edit-modal');
    if (existing) { existing.remove(); return; }

    const person = window.currentPersonData || {};
    
    // Split job title and company from rendered state if needed, but person data is better
    const titleVal = person.title_current || '';
    const companyVal = person.company_name_raw || '';
    const nameVal = person.full_name || '';
    const email1 = person.email_primary || '';
    const email2 = person.email_secondary || '';
    const phone1 = person.phone_primary || '';
    const phone2 = person.phone_secondary || '';
    const linkedin = person.linkedin_url || '';

    const modal = document.createElement('div');
    modal.id = 'profile-edit-modal';
    modal.style = `
                position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(255,255,255,0.15);
                backdrop-filter:none; border-radius:16px; padding:2rem;
                z-index:9999; min-width:400px; max-width:600px; width:90%;
                max-height:90vh; overflow-y:auto; box-shadow:0 24px 80px rgba(0,0,0,0.6);
            `;
    
    const fields = [
        { label: 'Full Name', key: 'full_name', val: nameVal },
        { label: 'Job Title', key: 'title_current', val: titleVal },
        { label: 'Company', key: 'company_name_raw', val: companyVal },
        { label: 'Primary Email', key: 'email_primary', val: email1 },
        { label: 'Secondary Email', key: 'email_secondary', val: email2 },
        { label: 'Primary Phone', key: 'phone_primary', val: phone1 },
        { label: 'Secondary Phone', key: 'phone_secondary', val: phone2 },
        { label: 'LinkedIn URL', key: 'linkedin_url', val: linkedin }
    ];

    modal.innerHTML = `
                <div style="font-weight:800; font-size:1rem; color:var(--accent-cyan); margin-bottom:1.25rem; display:flex; align-items:center; gap:8px;">
                    <i class="fas fa-edit"></i> Edit Profile Essentials
                </div>
                <div style="display:grid; grid-template-columns: 1fr 1fr; gap:1rem;">
                    ${fields.map(f => `
                        <div style="margin-bottom:0.75rem; grid-column: ${['full_name', 'linkedin_url'].includes(f.key) ? 'span 2' : 'span 1'};">
                            <div style="font-size:0.65rem; color:var(--text-muted); text-transform:uppercase; letter-spacing:1px; margin-bottom:4px;">${f.label}</div>
                            <input id="edit-field-${f.key}" value="${f.val.replace(/"/g, '&quot;')}" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:white; padding:8px 12px; border-radius:8px; font-size:0.85rem; outline:none; box-sizing:border-box;" onfocus="this.style.borderColor='var(--accent-cyan)'" onblur="this.style.borderColor='rgba(255,255,255,0.15)'">
                        </div>`).join('')}
                </div>
                <div style="display:flex; gap:0.75rem; margin-top:1.5rem;">
                    <button onclick="saveProfileHeader()" style="flex:1; background:var(--accent-cyan); color:#0a0a1a; font-weight:800; padding:12px; border:none; border-radius:8px; cursor:pointer; font-size:0.9rem; text-transform:uppercase; letter-spacing:1px;">Save Changes</button>
                    <button onclick="document.getElementById('profile-edit-modal').remove()" style="flex:1; background:rgba(255,255,255,0.08); color:white; padding:12px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; cursor:pointer; font-size:0.9rem;">Cancel</button>
                </div>
            `;
    document.body.appendChild(modal);
    document.getElementById('edit-field-full_name').focus();
}

async function saveProfileHeader() {
    const payload = {};
    const fields = ['full_name', 'title_current', 'company_name_raw', 'email_primary', 'email_secondary', 'phone_primary', 'phone_secondary', 'linkedin_url'];
    
    fields.forEach(k => {
        const el = document.getElementById(`edit-field-${k}`);
        if (el) {
            const val = el.value.trim();
            // Only update if value is different or to clear field
            if (val !== (window.currentPersonData[k] || '')) {
                payload[k] = val || null;
            }
        }
    });

    if (Object.keys(payload).length === 0) {
        document.getElementById('profile-edit-modal')?.remove();
        return;
    }
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        document.getElementById('profile-edit-modal')?.remove();
        if (res.ok) { loadPerson(); } else { alert('Failed to save'); }
    } catch (e) { alert('Error: ' + e.message); }
}

// -- CAREER TIMELINE EDITING -------------------------------------------
let currentEmploymentHistory = [];

function calcDuration(start, end) {
    if (!start || start === '?') return '';
    try {
        const [sy, sm = '01'] = start.split('-');
        const endDate = (end && end !== 'Present') ? end : null;
        const [ey, em = '01'] = endDate ? endDate.split('-') : [new Date().getFullYear(), String(new Date().getMonth() + 1).padStart(2, '0')];
        const months = (parseInt(ey) - parseInt(sy)) * 12 + (parseInt(em) - parseInt(sm));
        if (months < 0) return '';
        const y = Math.floor(months / 12), m = months % 12;
        return y > 0 && m > 0 ? `${y}y ${m}m` : y > 0 ? `${y}y` : `${m}m`;
    } catch { return ''; }
}

function renderCareerTimeline(roles) {
    currentEmploymentHistory = roles || [];
    const timelineEl = document.getElementById('employment-timeline');
    if (!timelineEl) return;

    if (roles && roles.length > 0) {
        timelineEl.innerHTML = `
                <div style="display:grid; grid-template-columns: 1fr 1fr auto auto auto; gap:0; border:1px solid rgba(255,255,255,0.07); border-radius:10px; overflow:hidden;">
                    <div style="display:contents; font-size:0.65rem; text-transform:uppercase; letter-spacing:1px; color:var(--text-muted); font-weight:700;">
                        <div style="padding:6px 10px; background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.07);">Role</div>
                        <div style="padding:6px 10px; background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.07);">Employer</div>
                        <div style="padding:6px 10px; background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.07);">Dates</div>
                        <div style="padding:6px 10px; background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.07);">Dur.</div>
                        <div style="padding:6px 10px; background:rgba(255,255,255,0.04); border-bottom:1px solid rgba(255,255,255,0.07);"></div>
                    </div>
                    ${roles.map((role, idx) => {
            const start = role.start_date || '';
            const end = role.end_date || '';
            const isCurrent = !role.end_date;
            const dur = calcDuration(start, end || 'Present');
            const dateStr = start ? `${start}${end ? ' – ' + end : ' – now'}` : '—';
            const loc = role.location || '';
            const rowBg = isCurrent ? 'rgba(53,232,255,0.04)' : (idx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)');
            return `
                        <div style="display:contents;" class="career-row" id="career-row-${idx}">
                            <div style="padding:7px 10px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); color:${isCurrent ? 'var(--accent-cyan)' : 'white'}; font-size:0.8rem; font-weight:${isCurrent ? '700' : '500'}; line-height:1.3;">${role.title || '—'}${loc ? `<div style="font-size:0.7rem; color:var(--text-muted); font-weight:400; margin-top:1px;">?? ${loc}</div>` : ''}</div>
                            <div style="padding:7px 10px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); color:var(--text-secondary); font-size:0.8rem; line-height:1.3;">${role.company || '—'}</div>
                            <div style="padding:7px 10px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); color:var(--text-muted); font-size:0.75rem; white-space:nowrap;">${dateStr}</div>
                            <div style="padding:7px 10px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); color:var(--text-muted); font-size:0.75rem; white-space:nowrap;">${dur}</div>
                            <div style="padding:7px 8px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); display:flex; gap:4px; align-items:start;">
                                <button onclick="editRole(${idx})" title="Edit" style="background:none; border:1px solid rgba(255,255,255,0.1); color:var(--text-muted); padding:2px 6px; border-radius:4px; cursor:pointer; font-size:0.65rem;">?</button>
                                <button onclick="deleteRole(${idx})" title="Delete" style="background:none; border:none; color:rgba(255,80,80,0.5); padding:2px 4px; border-radius:4px; cursor:pointer; font-size:0.7rem;">?</button>
                            </div>
                        </div>`;
        }).join('')}
                </div>`;
    } else {
        timelineEl.innerHTML = `<p style="color:var(--text-muted); font-size:0.85rem;">No career history yet — click + Add Role.</p>`;
    }
}

function openRoleModal(idx) {
    const existing = document.getElementById('role-edit-modal');
    if (existing) existing.remove();

    const isNew = idx === -1;
    const role = isNew ? {} : currentEmploymentHistory[idx];
    const modal = document.createElement('div');
    modal.id = 'role-edit-modal';
    modal.style = `
                position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(255,255,255,0.15);
                backdrop-filter:none; border-radius:16px; padding:2rem;
                z-index:9999; min-width:340px; max-width:540px; width:90%;
                box-shadow:0 24px 80px rgba(0,0,0,0.6);
            `;
    modal.innerHTML = `
                <div style="font-weight:800; font-size:1rem; color:var(--accent-cyan); margin-bottom:1.25rem;">${isNew ? '+ Add Role' : '? Edit Role'}</div>
                ${[
            ['Job Title', 'title', role.title || ''],
            ['Company', 'company', role.company || ''],
            ['Start Date (YYYY-MM)', 'start_date', role.start_date || ''],
            ['End Date (YYYY-MM, blank = Present)', 'end_date', role.end_date || ''],
            ['Location', 'location', role.location || ''],
        ].map(([lbl, key, val]) => `
                    <div style="margin-bottom:0.75rem;">
                        <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">${lbl}</div>
                        <input id="role-${key}" value="${val}" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:white; padding:7px 12px; border-radius:8px; font-size:0.85rem; outline:none; box-sizing:border-box;">
                    </div>`).join('')}
                <div style="margin-bottom:1rem;">
                    <div style="font-size:0.7rem; color:var(--text-muted); margin-bottom:4px;">Description</div>
                    <textarea id="role-description" rows="3" style="width:100%; background:rgba(255,255,255,0.07); border:1px solid rgba(255,255,255,0.15); color:white; padding:7px 12px; border-radius:8px; font-size:0.85rem; outline:none; resize:vertical; box-sizing:border-box;">${role.description || ''}</textarea>
                </div>
                <div style="display:flex; gap:0.75rem;">
                    <button onclick="saveRole(${idx})" style="flex:1; background:var(--accent-cyan); color:#0a0a1a; font-weight:800; padding:10px; border:none; border-radius:8px; cursor:pointer;">Save</button>
                    <button onclick="document.getElementById('role-edit-modal').remove()" style="flex:1; background:rgba(255,255,255,0.08); color:white; padding:10px; border:1px solid rgba(255,255,255,0.1); border-radius:8px; cursor:pointer;">Cancel</button>
                </div>
            `;
    document.body.appendChild(modal);
}

function addRole() { openRoleModal(-1); }
function editRole(idx) { openRoleModal(idx); }

async function saveRole(idx) {
    const newRole = {
        title: document.getElementById('role-title').value.trim() || null,
        company: document.getElementById('role-company').value.trim() || null,
        start_date: document.getElementById('role-start_date').value.trim() || null,
        end_date: document.getElementById('role-end_date').value.trim() || null,
        location: document.getElementById('role-location').value.trim() || null,
        description: document.getElementById('role-description').value.trim() || null,
    };
    // Remove nulls
    Object.keys(newRole).forEach(k => newRole[k] === null && delete newRole[k]);

    const updated = [...currentEmploymentHistory];
    if (idx === -1) {
        updated.unshift(newRole); // Add at top
    } else {
        updated[idx] = newRole;
    }

    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employment_history: updated })
        });
        document.getElementById('role-edit-modal')?.remove();
        if (res.ok) {
            currentEmploymentHistory = updated;
            renderCareerTimeline(updated);
        } else { alert('Failed to save role'); }
    } catch (e) { alert('Error: ' + e.message); }
}

async function deleteRole(idx) {
    if (!confirm('Delete this role?')) return;
    const updated = currentEmploymentHistory.filter((_, i) => i !== idx);
    try {
        const res = await fetch(`${API_BASE}/api/people/${personId}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ employment_history: updated })
        });
        if (res.ok) {
            currentEmploymentHistory = updated;
            renderCareerTimeline(updated);
        } else { alert('Failed to delete role'); }
    } catch (e) { alert('Error: ' + e.message); }
}


// Scroll Logic - Robust "Scroll Everything" Approach
function scrollToTop() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
    document.documentElement.scrollTo({ top: 0, behavior: 'smooth' });
    document.body.scrollTo({ top: 0, behavior: 'smooth' });

    const container = document.querySelector('.container');
    if (container) container.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateScrollBtn() {
    const btn = document.getElementById('scroll-top-btn');
    if (!btn) return;

    // Check both window and potential container scrolling
    const container = document.querySelector('.container');
    const windowScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
    const containerScroll = container ? container.scrollTop : 0;
    const scrollPos = Math.max(windowScroll, containerScroll);

    if (scrollPos > 300) {
        btn.style.display = "flex";
    } else {
        btn.style.display = "none";
    }
}

document.addEventListener('DOMContentLoaded', () => {
    loadPerson();
    initDragDrop();

    // Inject back button if navigated from another page
    const fromParam = new URLSearchParams(window.location.search).get('from');
    if (fromParam) {
        const backMap = {
            agenda: { label: '? Back to Agenda', href: '/agenda' },
            dashboard: { label: '? Dashboard', href: '/' },
            settings: { label: '? Settings', href: '/settings' }
        };
        const back = backMap[fromParam];
        if (back) {
            const btn = document.createElement('a');
            btn.href = back.href;
            btn.textContent = back.label;
            btn.style.cssText = 'position:fixed;top:12px;left:12px;z-index:9999;background:rgba(0,0,0,0.6);backdrop-filter:none;color:#fff;padding:6px 14px;border-radius:20px;font-size:0.75rem;font-weight:700;text-decoration:none;border:1px solid rgba(255,255,255,0.15);transition:background 0.2s;';
            btn.onmouseover = () => btn.style.background = 'rgba(0,71,255,0.5)';
            btn.onmouseout = () => btn.style.background = 'rgba(0,0,0,0.6)';
            document.body.appendChild(btn);
        }
    }


    // Initial check
    updateScrollBtn();

    const container = document.querySelector('.container');
    if (container) {
        container.addEventListener('scroll', updateScrollBtn, { passive: true });
    }
    window.addEventListener('scroll', updateScrollBtn, { passive: true });

    // Re-bind to container if it ever gets replaced or re-added
    const observer = new MutationObserver(() => {
        const c = document.querySelector('.container');
        if (c) c.addEventListener('scroll', updateScrollBtn, { passive: true });
        updateScrollBtn();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Global click listener to close inline edit toggles when clicking outside
    document.addEventListener('click', (e) => {
        if (!isEditingEnv && !isEditingCat && !isEditingDisc && !isEditingStatus) return;

        // If the click is inside any control group (the edit area itself), don't close
        if (e.target.closest('.tag-group')) return;

        // Close all and re-render their respective UI
        isEditingEnv = false;
        isEditingCat = false;
        isEditingDisc = false;
        isEditingStatus = false;

        fetchTaxonomy().then(() => {
            const p = window.currentPersonData;
            if (p) {
                renderEnvToggles(p.env);
                renderDiscToggles(p.disc);
                renderCatToggles(p.cat);
                renderStatusToggles(p.contact_value);
            }
        });
    });
});
