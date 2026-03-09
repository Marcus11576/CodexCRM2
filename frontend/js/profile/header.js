// Profile header rendering, taxonomy controls, and header editor

function renderPerson(person, briefing) {
    // Expose person globally so the task modal can read person_id / full_name
    window.currentPersonData = person
    window._personPersonalData = person.personal_data || {};

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

    renderPersonalIntel(window._personPersonalData);

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


let activeTaxonomy = {};

async function fetchTaxonomy() {
    if (Object.keys(activeTaxonomy).length > 0) return;
    try {
        const res = await fetch(`${API_BASE}/api/taxonomy`);
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
    loadPersonQuiet();
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
    loadPersonQuiet();
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
    loadPersonQuiet();
}

let isEditingCat = false;
function toggleCatEdit() {
    isEditingCat = !isEditingCat;
    loadPersonQuiet();
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
    loadPersonQuiet(); // Refresh to show active states
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
    loadPersonQuiet();
}


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
        if (res.ok) { loadPersonQuiet(); } else { alert('Failed to save'); }
    } catch (e) { alert('Error: ' + e.message); }
}

// -- CAREER TIMELINE EDITING -------------------------------------------


