var API_BASE = window.API_BASE || '';
let currentStatusFilter = null; // for traffic light click
let activeMeetingStatuses = new Set(); // Multi-select Meeting Filter
let selectedCats = new Set(['all']); // Multi-select
let selectedEnvs = new Set(); // Multi-select Env Filter
let selectedDiscs = new Set(); // Multi-select Disc Filter
let selectedStatuses = new Set(); // Multi-select Status Filter
let isPipelineMode = false;
let pipelineDays = 30;

// Get initials from name
function getInitials(name) {
    if (!name) return '?';
    const parts = name.split(' ');
    if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name[0].toUpperCase();
}

// Cat badge mapping
function getCatBadge(catStr) {
    if (!catStr) return '<span class="badge">GEN</span>';

    return catStr.split(',').map(cat => {
        cat = cat.trim();
        return `<span class="badge">${cat}</span>`;
    }).join(' ');
}

// Format date
function formatDate(dateStr) {
    if (!dateStr) return 'Not set';
    const date = new Date(dateStr);
    const now = new Date();
    const diffDays = Math.ceil((date - now) / (1000 * 60 * 60 * 24));

    if (diffDays < 0) {
        return `${Math.abs(diffDays)}d past`;
    } else if (diffDays === 0) {
        return 'Today';
    } else if (diffDays === 1) {
        return 'Tomorrow';
    } else {
        return `${diffDays}d`;
    }
}

// Render contact card
function renderContact(contact, listId) {
    const card = document.createElement('div');
    const statusClass = contact.meeting_status || 'not_scheduled';
    card.className = `contact-card status-${statusClass}`;
    card.onclick = () => viewPerson(contact.person_id);

    // Avatar logic
    let avatarHtml = '';
    if (contact.profile_photo_url) {
        const proxiedUrl = `${API_BASE}/api/proxy/image?url=${encodeURIComponent(contact.profile_photo_url)}`;
        const initials = getInitials(contact.full_name);
        avatarHtml = `
                    <div class="contact-avatar">
                        <img src="${proxiedUrl}" 
                             loading="lazy" 
                             alt="${contact.full_name}" 
                             style="width:100%; height:100%; object-fit:cover; border-radius:50%;"
                             onerror="this.parentElement.innerHTML='${initials}'; this.parentElement.style.background='var(--bg-secondary)';">
                    </div>`;
    } else {
        avatarHtml = `<div class="contact-avatar">${getInitials(contact.full_name)}</div>`;
    }

    card.innerHTML = `
                    <div class="contact-header">
                        ${avatarHtml}
                        <div class="contact-info">
                            <div class="contact-name">${contact.full_name}</div>
                            <div class="contact-title">${contact.title_current || 'No title'} @ ${contact.company_name_raw || 'Unknown'}</div>
                        </div>
                    </div>
                        <div class="contact-meta">
                        <div class="meta-group">
                            ${getCatBadge(contact.cat)}
                            ${contact.env && contact.env !== 'None' ? `<span class="badge" style="border-color:var(--accent-cyan); color:var(--accent-cyan);">${contact.env}</span>` : ''}
                            ${contact.disc && contact.disc !== 'None' ? `<span class="badge" style="border-color:var(--accent-cyan); color:var(--accent-cyan);">${contact.disc}</span>` : ''}
                        </div>
                        <div class="meta-group" style="margin-left: auto; display: flex; gap: 0.5rem; align-items: center;">
                            ${contact.phone_primary ? `
                                <div class="mini-action" onclick="event.stopPropagation(); window.location.href='tel:${contact.phone_primary}'">📞</div>
                                <div class="mini-action whatsapp" onclick="event.stopPropagation(); window.location.href='whatsapp://send?phone=${contact.phone_primary.replace(/\D/g, '')}'">💬</div>
                            ` : ''}
                            <span style="font-weight:700; margin-left: 0.5rem;">📅 ${formatDate(contact.next_contact_due_date)}</span>
                        </div>
                    </div>
                    `;

    document.getElementById(listId).appendChild(card);
}

// Helper to filter lists based on UI state
const filterList = (list) => {
    let filtered = list || [];

    // 1. Cat Filter (Multi-select)
    if (!selectedCats.has('all')) {
        filtered = filtered.filter(c => {
            const personCats = (c.cat || '').split(',').map(x => x.trim());
            // Show if ANY of person's categories are in selectedCats
            return personCats.some(cat => selectedCats.has(cat));
        });
    }

    // 2. Env Filter (Multi-select)
    if (!selectedEnvs.has('all') && selectedEnvs.size > 0) {
        filtered = filtered.filter(c => {
            const personEnv = (c.env || '').trim().toLowerCase(); // Normalize DB value
            // Check if any selected env matches (normalized)
            for (let env of selectedEnvs) {
                if (env.trim().toLowerCase() === personEnv) return true;
            }
            return false;
        });
    }

    // 3. Disc Filter (Multi-select)
    if (!selectedDiscs.has('all') && selectedDiscs.size > 0) {
        filtered = filtered.filter(c => {
            const personDisc = (c.disc || '').trim();
            return selectedDiscs.has(personDisc);
        });
    }

    // 4. Status Filter (Multi-select)
    if (selectedStatuses.size > 0) {
        filtered = filtered.filter(c => {
            return selectedStatuses.has(c.contact_value);
        });
    }

    return filtered;
};

// Load dashboard data
async function loadDashboard() {
    try {
        // Load meeting feed
        const feedRes = await fetch(`${API_BASE}/api/dashboard/meeting-feed`);
        const feed = await feedRes.json();

        // Hide loading
        document.getElementById('loading-state').style.display = 'none';

        // --- Filter Logic ---

        const overdue = filterList(feed.overdue);
        const notScheduled = filterList(feed.not_scheduled || []);
        const soon = filterList(feed.soon);
        const onTrack = filterList(feed.on_track);

        // Update Stats to reflect 'Filtered' counts
        const oCount = document.getElementById('stat-overdue');
        const sCount = document.getElementById('stat-soon');
        const otCount = document.getElementById('stat-ontrack');
        const nsCount = document.getElementById('stat-not-scheduled');
        
        if (oCount) oCount.textContent = feed.overdue.length;
        if (sCount) sCount.textContent = feed.soon.length;
        if (otCount) otCount.textContent = feed.on_track.length;
        if (nsCount) nsCount.textContent = (feed.not_scheduled || []).length;

        // Update Stat Card Active States
        document.querySelectorAll('.stat-card').forEach(card => {
            const type = card.className.split('status-')[1]?.split(' ')[0];
            // Normalize overdue vs past for mapping
            const cleanType = type === 'past' ? 'overdue' : type;
            if (activeMeetingStatuses.has(cleanType)) {
                card.classList.add('active');
            } else {
                card.classList.remove('active');
            }
        });

        // --- Render ---
        const hasContacts = overdue.length + notScheduled.length + soon.length + onTrack.length > 0;

        // Clear lists first (important for re-render)
        document.getElementById('overdue-list').innerHTML = '';
        document.getElementById('not-scheduled-list').innerHTML = '';
        document.getElementById('soon-list').innerHTML = '';
        document.getElementById('ontrack-list').innerHTML = '';

        // Only hide/show these sections if NOT in pipeline mode
        if (!isPipelineMode) {
            document.getElementById('overdue-section').style.display = 'none';
            document.getElementById('not-scheduled-section').style.display = 'none';
            document.getElementById('soon-section').style.display = 'none';
            document.getElementById('ontrack-section').style.display = 'none';
            document.getElementById('empty-state').style.display = 'none';

            if (!hasContacts) {
                document.getElementById('empty-state').style.display = 'block';
                return;
            }

            // Show sections logic
            const shouldShow = (type) => {
                if (activeMeetingStatuses.size === 0) return true; // Show all by default
                return activeMeetingStatuses.has(type);
            };

            if (shouldShow('overdue') && overdue.length > 0) {
                document.getElementById('overdue-section').style.display = 'block';
                document.getElementById('overdue-count').textContent = overdue.length;
                overdue.forEach(c => renderContact(c, 'overdue-list'));
            }

            if (shouldShow('not_scheduled') && notScheduled.length > 0) {
                document.getElementById('not-scheduled-section').style.display = 'block';
                document.getElementById('not-scheduled-count').textContent = notScheduled.length;
                notScheduled.forEach(c => renderContact(c, 'not-scheduled-list'));
            }

            if (shouldShow('soon') && soon.length > 0) {
                document.getElementById('soon-section').style.display = 'block';
                document.getElementById('soon-count').textContent = soon.length;
                soon.forEach(c => renderContact(c, 'soon-list'));
            }

            if (shouldShow('on_track') && onTrack.length > 0) {
                document.getElementById('ontrack-section').style.display = 'block';
                document.getElementById('ontrack-count').textContent = onTrack.length;
                onTrack.forEach(c => renderContact(c, 'ontrack-list'));
            }
        }

    } catch (error) {
        console.error('Dashboard load error:', error);
        if (!isPipelineMode) {
            document.getElementById('loading-state').innerHTML = `
                        <p style="color: var(--accent-red);">Failed to load dashboard</p>
                        <p style="font-size: 0.85rem; margin-top: 0.5rem;">Make sure the server is running</p>
                    `;
        }
    }
}

// Toggle Cat (Multi-select)
function toggleCat(cat) {
    const chips = document.querySelectorAll('#cat-filters .filter-chip');
    const catMap = {
        'OBE Member': 'OBE M',
        'OBE Target': 'OBE T',
        'Client Target': 'TGT',
        'Target Client': 'TGT',
        'Existing Client': 'EXT',
        'Candidate': 'HPC',
        'High Performing Candidate': 'HPC',
        'General': 'GEN',
        'General Contact': 'GEN'
    };

    const dbValue = catMap[cat] || cat;

    if (cat === 'all') {
        selectedCats.clear();
        selectedCats.add('all');
    } else {
        if (selectedCats.has('all')) {
            selectedCats.delete('all');
        }

        if (selectedCats.has(dbValue)) {
            selectedCats.delete(dbValue);
        } else {
            selectedCats.add(dbValue);
        }

        if (selectedCats.size === 0) {
            selectedCats.add('all');
        }
    }

    // Update UI
    chips.forEach(chip => {
        const text = chip.textContent;
        let isActive = false;
        if (text === 'All') {
            isActive = selectedCats.has('all');
        } else {
            const mapped = catMap[text] || text;
            isActive = selectedCats.has(mapped);
        }

        if (isActive) chip.classList.add('active');
        else chip.classList.remove('active');
    });

    loadDashboard();
}

// Toggle Env (Multi-select)
function toggleEnv(env) {
    const envMap = {
        'Gov Dev': 'Developer - Gov',
        'Semi-Gov Dev': 'Developer - Semi-Gov',
        'Private Dev': 'Developer - Private',
        'Consultant': 'Consultant',
        'Main Contractor': 'Main Contractor',
        'Sub Contractor': 'Sub Contractor',
        'PMO': 'Management Consultant'
    };

    if (env === 'all') {
        selectedEnvs.clear();
        selectedEnvs.add('all');
    } else if (env === 'DevMaster') {
        // Multi-select Dev values
        const devValues = ['Developer - Gov', 'Developer - Semi-Gov', 'Developer - Private'];
        const allSelected = devValues.every(v => selectedEnvs.has(v));

        if (selectedEnvs.has('all')) selectedEnvs.delete('all');

        if (allSelected) {
            devValues.forEach(v => selectedEnvs.delete(v));
        } else {
            devValues.forEach(v => selectedEnvs.add(v));
        }
        if (selectedEnvs.size === 0) selectedEnvs.add('all');
    } else {
        const dbValue = envMap[env] || env;

        if (selectedEnvs.has('all')) selectedEnvs.delete('all');

        if (selectedEnvs.has(dbValue)) {
            selectedEnvs.delete(dbValue);
        } else {
            selectedEnvs.add(dbValue);
        }
        if (selectedEnvs.size === 0) selectedEnvs.add('all');
    }

    // Update UI
    const chips = document.querySelectorAll('#env-filters .filter-chip');
    chips.forEach(chip => {
        const text = chip.textContent;
        if (text === 'Dev') {
            const devValues = ['Developer - Gov', 'Developer - Semi-Gov', 'Developer - Private'];
            const allSelected = devValues.every(v => selectedEnvs.has(v));
            if (allSelected) chip.classList.add('active');
            else chip.classList.remove('active');
        } else if (text === 'All') {
            if (selectedEnvs.has('all')) chip.classList.add('active');
            else chip.classList.remove('active');
        } else {
            const dbValue = envMap[text] || text;
            if (selectedEnvs.has(dbValue)) {
                chip.classList.add('active');
            } else {
                chip.classList.remove('active');
            }
        }
    });

    loadDashboard();
}

// Toggle Disc (Multi-select)
function toggleDisc(disc) {
    const discMap = {
        'Commercial': 'Commercial',
        'Delivery': 'Delivery',
        'Design': 'Design',
        'Corporate': 'Corporate',
        'Support': 'Support Services',
        'Others': 'Other'
    };

    if (disc === 'all') {
        selectedDiscs.clear();
        selectedDiscs.add('all');
    } else {
        const dbValue = discMap[disc] || disc;
        if (selectedDiscs.has('all')) selectedDiscs.delete('all');

        if (selectedDiscs.has(dbValue)) {
            selectedDiscs.delete(dbValue);
        } else {
            selectedDiscs.add(dbValue);
        }
        if (selectedDiscs.size === 0) selectedDiscs.add('all');
    }

    // Update UI
    const chips = document.querySelectorAll('#disc-filters .filter-chip');
    chips.forEach(chip => {
        const text = chip.textContent;
        if (text === 'All') {
            if (selectedDiscs.has('all')) chip.classList.add('active');
            else chip.classList.remove('active');
            return;
        }

        const dbValue = discMap[text] || text;
        if (selectedDiscs.has(dbValue)) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });

    loadDashboard();
}

// Toggle Status (Multi-select)
function toggleStatus(status) {
    if (status === null) {
        selectedStatuses.clear();
    } else {
        if (selectedStatuses.has(status)) {
            selectedStatuses.delete(status);
        } else {
            selectedStatuses.add(status);
        }
    }

    // Update UI
    const chips = document.querySelectorAll('#status-filters .filter-chip');
    chips.forEach(chip => {
        const title = chip.title;

        // Handle "All" button (no title or title='All')
        if (!title || title === 'All') {
            if (selectedStatuses.size === 0) {
                chip.classList.add('active');
                chip.style.opacity = '1';
            } else {
                chip.classList.remove('active');
                chip.style.opacity = '0.6';
            }
            return;
        }

        if (selectedStatuses.has(title)) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });

    loadDashboard();
}

// Filter by status (Multi-select)
function filterByStatus(status) {
    if (activeMeetingStatuses.has(status)) {
        activeMeetingStatuses.delete(status);
    } else {
        activeMeetingStatuses.add(status);
    }

    loadDashboard();
}

// View person details
function viewPerson(personId) {
    window.location.href = `/person/${personId}?from=dashboard`;
}

// Brief me
function briefMe(personId) {
    alert(`Briefing feature coming soon for person: ${personId}`);
    // TODO: Implement briefing modal
}

// Quick capture
async function quickCapture() {
    const modal = document.getElementById('quick-capture-modal');
    const dataList = document.getElementById('person-list');

    modal.style.display = 'flex';
    document.getElementById('qc-person-input').focus();

    // Load people for datalist if empty
    if (dataList.children.length === 0) {
        try {
            const res = await fetch(`${API_BASE}/api/people`);
            const data = await res.json();
            const people = data.people || [];

            people.forEach(p => {
                const option = document.createElement('option');
                option.value = p.full_name;
                option.dataset.id = p.person_id;
                option.label = p.company_name_raw || '';
                dataList.appendChild(option);
            });

            // Store people map for lookup on save
            window.peopleMap = people.reduce((acc, p) => {
                acc[p.full_name] = p.person_id;
                return acc;
            }, {});

        } catch (err) {
            console.error('Failed to load people for quick capture', err);
        }
    }
}

function closeQuickCapture() {
    document.getElementById('quick-capture-modal').style.display = 'none';
    document.getElementById('qc-note-input').value = '';
    document.getElementById('qc-person-input').value = '';
}

async function saveQuickCapture() {
    const nameInput = document.getElementById('qc-person-input');
    const noteInput = document.getElementById('qc-note-input');
    const modal = document.getElementById('quick-capture-modal');

    const name = nameInput.value;
    const note = noteInput.value;

    if (!note) {
        alert('Please enter a note');
        return;
    }

    // Find person ID
    const personId = window.peopleMap ? window.peopleMap[name] : null;

    if (!personId) {
        alert('Please select a valid person from the list');
        return;
    }

    const saveBtn = modal.querySelector('.btn-primary');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/interactions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                person_id: personId,
                text: note,
                channel: 'quick_capture'
            })
        });

        if (res.ok) {
            closeQuickCapture();
            // Refresh feed if needed
            loadDashboard();
            alert('Note saved!');
        } else {
            alert('Failed to save note');
        }
    } catch (err) {
        console.error(err);
        alert('Error saving note');
    } finally {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

// --- Dashboard Search ---
function performDashboardSearch() {
    const searchInput = document.getElementById('dashboard-search');
    const query = searchInput.value.trim().toLowerCase();

    // Get all contact cards
    const cards = document.querySelectorAll('.contact-card');

    if (!query) {
        // Show all cards if search is empty
        cards.forEach(card => card.style.display = '');
        return;
    }

    // Filter cards based on search query
    cards.forEach(card => {
        const name = card.querySelector('.contact-name')?.textContent.toLowerCase() || '';
        const title = card.querySelector('.contact-title')?.textContent.toLowerCase() || '';

        if (name.includes(query) || title.includes(query)) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
}

// --- Pipeline Variables ---
isPipelineMode = false;
pipelineDays = 30; // Default to 1 month


// --- Navigation Logic ---
function toggleDashboardView() {
    // Check for pipeline view in URL
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get('view') === 'pipeline') {
        isPipelineMode = true;
        document.getElementById('pill-network')?.classList.add('active');
        document.getElementById('pill-dashboard')?.classList.remove('active');
    }

    if (isPipelineMode) {
        showPipeline(pipelineDays);
    } else {
        loadDashboard();
    }
}

async function showPipeline(days, updateHistory = true) {
    isPipelineMode = true;
    pipelineDays = days;

    // UI Switching
    document.getElementById('pipeline-filters').style.display = 'flex';
    document.getElementById('cat-filters').style.display = 'flex';
    document.getElementById('env-filters').style.display = 'flex';
    document.getElementById('disc-filters').style.display = 'flex';
    document.getElementById('status-filters').style.display = 'none';
    const statsGrid = document.querySelector('.stats-grid');
    if (statsGrid) statsGrid.style.display = 'none';

    // Update floating pill active state
    const pillDash = document.getElementById('pill-dashboard');
    const pillNet = document.getElementById('pill-network');
    if (pillDash && pillNet) {
        pillDash.classList.remove('active');
        pillNet.classList.add('active');
    }

    // Hide Feed Sections
    const feedSections = ['overdue-section', 'not-scheduled-section', 'soon-section', 'ontrack-section'];
    feedSections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    // Update Active Chip
    const timeframeMap = { 0: 'Today', 3: '3 Days', 7: '7 Days', 14: '14 Days', 30: '1 Month', 90: '3 Months' };
    document.querySelectorAll('#pipeline-filters .filter-chip').forEach(chip => {
        if (chip.textContent === timeframeMap[days]) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });

    // Update History
    if (updateHistory) {
        const url = new URL(window.location);
        url.searchParams.set('view', 'pipeline');
        url.searchParams.set('days', days);
        history.pushState({ view: 'pipeline', days: days }, '', url);
    }

    await loadPipelineData();
}

function showMeetingFeed(updateHistory = true) {
    isPipelineMode = false;

    document.getElementById('pipeline-filters').style.display = 'none';
    document.getElementById('cat-filters').style.display = 'flex';
    document.getElementById('env-filters').style.display = 'flex';
    document.getElementById('status-filters').style.display = 'flex';
    const statsGrid = document.querySelector('.stats-grid');
    if (statsGrid) statsGrid.style.display = 'grid';

    // Update floating pill active state
    const pillDash = document.getElementById('pill-dashboard');
    const pillNet = document.getElementById('pill-network');
    if (pillDash && pillNet) {
        pillDash.classList.add('active');
        pillNet.classList.remove('active');
    }

    // Hide Pipeline Sections
    const pipeSections = ['pipeline-section', 'gaps-section'];
    pipeSections.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });

    // Update History
    if (updateHistory) {
        const url = new URL(window.location);
        url.searchParams.delete('view');
        url.searchParams.delete('days');
        history.pushState({ view: 'dashboard' }, '', url);
    }

    loadDashboard();
}

async function loadPipelineData() {
    const loading = document.getElementById('loading-state');
    if (loading) loading.style.display = 'block';
    const emptyState = document.getElementById('empty-state');
    if (emptyState) emptyState.style.display = 'none';

    try {
        const res = await fetch(`${API_BASE}/api/dashboard/task-pipeline?days=${pipelineDays}`);
        if (!res.ok) throw new Error(`Server returned ${res.status}`);
        const data = await res.json();

        const pipelineList = document.getElementById('pipeline-list');
        const gapsList = document.getElementById('gaps-list');
        if (pipelineList) pipelineList.innerHTML = '';
        if (gapsList) gapsList.innerHTML = '';

        // Apply Dashboard Filters
        const pipeline = filterList(data.pipeline);
        const action_gaps = filterList(data.action_gaps);

        // Render Pipeline
        if (pipeline && pipeline.length > 0) {
            const pipeSection = document.getElementById('pipeline-section');
            if (pipeSection) pipeSection.style.display = 'block';

            const targetDate = new Date();
            targetDate.setDate(targetDate.getDate() + (data.days_view || pipelineDays));
            const pipeCount = document.getElementById('pipeline-count');
            if (pipeCount) {
                pipeCount.textContent = `${pipeline.length} (due by ${targetDate.toLocaleDateString()})`;
            }

            pipeline.forEach(c => {
                const card = document.createElement('div');
                card.className = 'contact-card status-on_track';
                card.onclick = () => viewPerson(c.person_id);

                let avatarHtml = '';
                if (c.profile_photo_url) {
                    const proxiedUrl = `${API_BASE}/api/proxy/image?url=${encodeURIComponent(c.profile_photo_url)}`;
                    const initials = getInitials(c.full_name);
                    avatarHtml = `
                        <div class="contact-avatar">
                            <img src="${proxiedUrl}" loading="lazy" alt="${c.full_name}" 
                                 style="width:100%; height:100%; object-fit:cover; border-radius:50%;"
                                 onerror="this.parentElement.innerHTML='${initials}'; this.parentElement.style.background='var(--bg-secondary)';">
                        </div>`;
                } else {
                    avatarHtml = `<div class="contact-avatar">${getInitials(c.full_name)}</div>`;
                }

                const displayDate = c.due_date ? new Date(c.due_date).toLocaleDateString() : 'No date';

                card.innerHTML = `
                    <div class="contact-header" style="display: flex; align-items: center;">
                        ${avatarHtml}
                        <div style="flex:1;">
                            <div class="contact-name" style="font-weight:700;">${c.full_name}</div>
                            <span class="category-badge" style="font-size: 0.6rem; background:var(--accent-blue); color:white; padding:2px 6px; border-radius:4px;">TASK DUE</span>
                        </div>
                    </div>
                    <div style="font-size: 0.95rem; font-weight: 700; color: var(--text-primary); margin: 0.5rem 0 0.5rem 0;">
                        📝 ${c.task_text || 'No task text'}
                    </div>
                    <div class="contact-meta" style="margin-left: 0;">
                        <span title="Due Date">📅 ${displayDate}</span>
                        <span title="Company">🏢 ${c.company_name_raw || 'No Company'}</span>
                    </div>
                `;
                if (pipelineList) pipelineList.appendChild(card);
            });
        } else {
            const pipeSection = document.getElementById('pipeline-section');
            if (pipeSection) pipeSection.style.display = 'none';
        }

        // Render Gaps
        if (action_gaps && action_gaps.length > 0) {
            const gapsSection = document.getElementById('gaps-section');
            if (gapsSection) gapsSection.style.display = 'block';
            const gapsCount = document.getElementById('gaps-count');
            if (gapsCount) gapsCount.textContent = action_gaps.length;

            action_gaps.forEach(c => {
                const card = document.createElement('div');
                card.className = 'contact-card status-overdue';
                card.onclick = () => viewPerson(c.person_id);

                let avatarHtml = '';
                if (c.profile_photo_url) {
                    const proxiedUrl = `${API_BASE}/api/proxy/image?url=${encodeURIComponent(c.profile_photo_url)}`;
                    const initials = getInitials(c.full_name);
                    avatarHtml = `
                        <div class="contact-avatar">
                            <img src="${proxiedUrl}" loading="lazy" alt="${c.full_name}" 
                                 style="width:100%; height:100%; object-fit:cover; border-radius:50%;"
                                 onerror="this.parentElement.innerHTML='${initials}'; this.parentElement.style.background='var(--bg-secondary)';">
                        </div>`;
                } else {
                    avatarHtml = `<div class="contact-avatar">${getInitials(c.full_name)}</div>`;
                }

                card.innerHTML = `
                    <div class="contact-header" style="display: flex; align-items: center;">
                        ${avatarHtml}
                        <div style="flex:1;">
                            <div class="contact-name">${c.full_name}</div>
                            <span class="category-badge badge-obe-target" style="background: var(--accent-red); font-size: 0.6rem; color:white; padding:2px 6px; border-radius:4px;">ACTION GAP</span>
                        </div>
                    </div>
                    <div style="font-size: 0.85rem; color: var(--text-secondary); margin: 0.5rem 0 0.5rem 64px;">
                        High-priority contact with no tasks scheduled in the next 3 months.
                    </div>
                    <div class="contact-meta" style="margin-left: 64px;">
                        <span>🏷️ ${c.cat || 'Member'}</span>
                    </div>
                `;
                if (gapsList) gapsList.appendChild(card);
            });
        } else {
            const gapsSection = document.getElementById('gaps-section');
            if (gapsSection) gapsSection.style.display = 'none';
        }

        if (emptyState) {
            const isEmpty = (!data.pipeline || data.pipeline.length === 0) && (!data.action_gaps || data.action_gaps.length === 0);
            emptyState.style.display = isEmpty ? 'block' : 'none';
            if (isEmpty) emptyState.querySelector('p').textContent = 'No upcoming tasks or action gaps found';
        }

    } catch (err) {
        console.error('Pipeline load error:', err);
        if (loading) loading.innerHTML = `<p style="color:var(--accent-red);">Error loading pipeline: ${err.message}</p>`;
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

// Handle browser Back button
window.onpopstate = function (event) {
    if (event.state && event.state.view === 'pipeline') {
        showPipeline(event.state.days || 30, false);
    } else {
        showMeetingFeed(false);
    }
};

// Load on page ready
function initDashboardFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const view = params.get('view');
    const days = parseInt(params.get('days')) || 30;

    if (view === 'pipeline') {
        showPipeline(days, false);
    } else {
        const status = params.get('status');
        if (status) currentExclusiveStatus = status;
        loadDashboard();
    }
}

function renderEventDashboardWidget(summary) {
    const widget = document.getElementById('event-dashboard-widget');
    const stats = document.getElementById('event-dashboard-stats');
    const cards = document.getElementById('event-dashboard-cards');
    if (!widget || !stats || !cards) return;

    const upcomingEvents = summary.upcoming_events || [];
    if (!upcomingEvents.length) {
        widget.style.display = 'none';
        return;
    }

    widget.style.display = 'block';
    stats.textContent = `${summary.upcoming_event_count || 0} upcoming events � ${summary.upcoming_linked_people || 0} linked people`;
    cards.innerHTML = upcomingEvents.map((eventItem) => `
        <a class="event-dashboard-card" href="/events/${eventItem.event_id}">
            <div class="event-dashboard-card-top">
                <strong>${eventItem.event_name}</strong>
                <span>${formatDate(eventItem.event_date)}</span>
            </div>
            <div class="event-dashboard-meta">${eventItem.location || 'Location TBD'}</div>
            <div class="event-dashboard-meta">${eventItem.linked_people_count || 0} linked � ${eventItem.confirmed_count || 0} confirmed � ${eventItem.registered_count || 0} registered</div>
        </a>
    `).join('');
}

async function loadEventDashboardWidget() {
    try {
        const summary = await get('/api/events/dashboard/summary');
        renderEventDashboardWidget(summary);
    } catch (error) {
        console.error('Event widget load error:', error);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    renderUniversalLayout('dashboard', 'RELATIONSHIP INTELLIGENCE');
    initDashboardFromUrl();
    loadEventDashboardWidget();
});


// --- Twin Chat Logic ---
let twinHistory = [];

function openTwinChat() {
    document.getElementById('twin-chat-modal').style.display = 'flex';
    document.getElementById('twin-input').focus();
    // Hide Sparkle FAB
    const fab = document.querySelector('.twin-fab');
    if (fab) fab.style.display = 'none';
}

function closeTwinChat() {
    document.getElementById('twin-chat-modal').style.display = 'none';
    // Show Sparkle FAB
    const fab = document.querySelector('.twin-fab');
    if (fab) fab.style.display = 'flex';
}

async function sendTwinMessage() {
    const input = document.getElementById('twin-input');
    const historyDiv = document.getElementById('twin-history');
    const message = input.value.trim();

    if (!message) return;

    // Add User Message
    appendMessage('user', message);
    input.value = '';

    // Calls API
    try {
        // Show thinking
        const loadingId = 'loading-' + Date.now();
        historyDiv.innerHTML += `<div id="${loadingId}" class="assistant-message" style="font-style:italic;">Thinking...</div>`;
        historyDiv.scrollTop = historyDiv.scrollHeight;

        const res = await fetch(`${API_BASE}/api/intelligence/twin/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message, history: twinHistory })
        });

        const data = await res.json();
        document.getElementById(loadingId).remove();

        // Add Twin Reply
        if (data.reply) {
            appendMessage('twin', data.reply);
        }

        // Handle Hybrid Data (Rich Results)
        if (data.data && Array.isArray(data.data)) {
            renderSearchResults(data.data);
        }

        // Handle Pending Action
        if (data.pending_action) {
            if (data.pending_action.type === 'search') {
                // Auto-execute search for better UX
                appendMessage('twin', 'Search in progress...');
                executeTwinAction(data.pending_action);
            } else {
                renderActionCard(data.pending_action);
            }
        }

        // Update History
        twinHistory.push({ role: 'user', content: message });

        let assistantContent = data.reply || '';
        if (data.data && Array.isArray(data.data) && data.data.length > 0) {
            // Inject context for follow-up questions
            const contextList = data.data.map(p => `${p.full_name} (${p.company_name_raw})`).join(', ');
            assistantContent += `\n\n[System Context: The user observes these profiles: ${contextList}]`;
        }

        if (assistantContent) {
            twinHistory.push({ role: 'assistant', content: assistantContent });
        }

    } catch (err) {
        console.error(err);
        document.getElementById(loadingId)?.remove();
        appendMessage('twin', `Error: ${err.message}`);
    }
}

function appendMessage(role, text) {
    const historyDiv = document.getElementById('twin-history');
    const div = document.createElement('div');
    // Map roles to new CSS classes
    const className = role === 'user' ? 'user-message' : 'assistant-message';
    div.className = className;
    // Allow HTML for rich content
    div.innerHTML = text;
    historyDiv.appendChild(div);
    historyDiv.scrollTop = historyDiv.scrollHeight;
}

// Store actions in memory to avoid quote escaping issues
let actionCache = {};

function renderActionCard(action) {
    const historyDiv = document.getElementById('twin-history');
    const div = document.createElement('div');
    const actionId = 'action-' + Date.now();
    actionCache[actionId] = action;

    div.className = 'chat-message twin';
    div.innerHTML = `
            <div class="action-card">
                <h4>Confirm Action</h4>
                <p><strong>Type:</strong> ${action.type}</p>
                <p><strong>Details:</strong> <pre style="font-size:0.8rem; overflow-x:auto;">${JSON.stringify(action.params, null, 2)}</pre></p>
                <div style="margin-top:0.5rem; display:flex; gap:0.5rem;">
                    <button class="btn btn-primary" onclick="executeTwinAction(actionCache['${actionId}'])">Confirm</button>
                    <button class="btn btn-secondary" onclick="this.parentElement.parentElement.parentElement.remove()">Cancel</button>
                </div>
            </div>
        `;
    historyDiv.appendChild(div);
    historyDiv.scrollTop = historyDiv.scrollHeight;
}


async function executeTwinAction(action) {
    try {
        const res = await fetch(`${API_BASE}/api/intelligence/twin/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action_type: action.type, params: action.params })
        });
        const result = await res.json();

        if (result.status === 'success') {
            // appendMessage('twin', `Done! ${result.message || 'Action completed.'}`); // Too verbose
            if (result.data) {
                // Render rich results instead of JSON
                if (Array.isArray(result.data)) {
                    renderSearchResults(result.data);
                } else {
                    appendMessage('twin', JSON.stringify(result.data, null, 2));
                }
            } else {
                appendMessage('twin', `Done: ${result.message || 'Done'}`);
            }
        } else {
            appendMessage('twin', `Failed: ${result.message}`);
        }
    } catch (err) {
        appendMessage('twin', `Error: ${err.message}`);
    }
}



function renderSearchResults(results) {
    if (!results || results.length === 0) {
        appendMessage('twin', 'No results found.');
        return;
    }

    const historyDiv = document.getElementById('twin-history');
    const container = document.createElement('div');
    container.className = 'chat-message twin';
    container.style.background = 'transparent';
    container.style.border = 'none';
    container.style.padding = '0';

    // Export to CSV function
    const exportId = 'export-' + Date.now();
    const exportCSV = () => {
        const headers = ['Name', 'Title', 'Company', 'Category', 'Environment'];
        const rows = results.map(p => [
            p.full_name || '',
            p.title_current || '',
            p.company_name_raw || '',
            p.cat || '',
            p.env || ''
        ]);
        const csvContent = [headers, ...rows]
            .map(row => row.map(v => `"${String(v).replace(/"/g, '""')}"`).join(','))
            .join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `crm_export_${new Date().toISOString().slice(0, 10)}.csv`;
        link.click();
        URL.revokeObjectURL(url);
    };

    let html = `<div style="display:flex; flex-direction:column; gap:0.5rem; width:100%;">`;
    html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.25rem;">
                <span style="color:var(--text-muted); font-size:0.7rem; text-transform:uppercase; letter-spacing:1px;">${results.length} results</span>
                <button id="${exportId}" style="background:rgba(53,232,255,0.1); border:1px solid var(--accent-cyan); color:var(--accent-cyan); padding:4px 10px; border-radius:6px; font-size:0.7rem; font-weight:700; cursor:pointer;">Export CSV</button>
            </div>`;

    results.forEach(p => {
        html += `
                <div onclick="window.location.href='/person/${p.person_id}'" style="
                    background: var(--bg-card); 
                    border: 1px solid var(--glass-border); 
                    padding: 0.75rem; 
                    border-radius: 8px; 
                    cursor: pointer;
                    transition: transform 0.2s;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                " onmouseover="this.style.borderColor='var(--accent-blue)'" onmouseout="this.style.borderColor='var(--glass-border)'">
                    <div>
                        <div style="font-weight:700; color:var(--text-primary);">${p.full_name}</div>
                        <div style="font-size:0.8rem; color:var(--text-secondary);">${p.title_current || 'No Title'} @ ${p.company_name_raw || 'Unknown'}</div>
                        <div style="font-size:0.7rem; color:var(--accent-cyan); margin-top:2px;">${p.cat || ''}</div>
                    </div>
                    <div style="color:var(--accent-blue);">View</div>
                </div>`;
    });

    html += `</div>`;
    container.innerHTML = html;
    historyDiv.appendChild(container);
    historyDiv.scrollTop = historyDiv.scrollHeight;

    // Bind the export button after DOM insertion
    document.getElementById(exportId)?.addEventListener('click', exportCSV);
}


// --- Audio Logic (Server-Side Whisper) ---
let mediaRecorder;
let audioChunks = [];

async function startDictation() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        alert("Audio recording not supported in this browser.");
        return;
    }

    const btn = document.querySelector('button[onclick="startDictation()"]');
    const input = document.getElementById('twin-input');

    if (mediaRecorder && mediaRecorder.state === 'recording') {
        // Stop recording
        mediaRecorder.stop();
        btn.textContent = '⏳'; // Processing
        btn.style.background = '';
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        // Explicitly request opus codec for OpenAI Whisper compatibility
        const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? { mimeType: 'audio/webm;codecs=opus' }
            : undefined;

        mediaRecorder = new MediaRecorder(stream, options);
        audioChunks = [];

        mediaRecorder.ondataavailable = (event) => {
            audioChunks.push(event.data);
        };

        mediaRecorder.onstop = async () => {
            const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
            if (audioBlob.size > 0) {
                await processAudio(audioBlob);
            } else {
                console.warn("Audio recording was empty.");
                input.placeholder = "Recording failed (empty).";
            }
            btn.textContent = '🎤';
            stream.getTracks().forEach(track => track.stop());
        };

        mediaRecorder.start(200); // 200ms timeslice for better reliability
        btn.textContent = '🔴'; // Recording indicator
        btn.style.background = 'var(--accent-red)';
        input.placeholder = "Recording... Click mic to stop.";

    } catch (err) {
        console.error(err);
        alert("Could not access microphone.");
    }
}

async function pollTranscriptionJob(jobId) {
    for (let attempt = 0; attempt < 120; attempt++) {
        const res = await fetch(`${API_BASE}/api/ai/jobs/${jobId}`);
        if (!res.ok) throw new Error("Unable to read transcription job");
        const job = await res.json();
        if (job.status === "completed") return job.result || {};
        if (job.status === "failed") throw new Error(job.error_text || "Transcription failed");
        await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    throw new Error("Transcription timed out");
}

async function processAudio(blob) {
    const input = document.getElementById('twin-input');
    const formData = new FormData();
    formData.append('file', blob, 'recording.webm');

    try {
        input.value = 'Queued for transcription...';
        const res = await fetch(`${API_BASE}/api/intelligence/transcribe`, {
            method: 'POST',
            body: formData
        });
        const data = await res.json();
        if (!data.job_id) throw new Error('No transcription job returned');
        const result = await pollTranscriptionJob(data.job_id);

        if (result.text) {
            input.value = result.text;
        } else {
            input.value = '';
            input.placeholder = 'Transcription returned no text.';
        }
    } catch (err) {
        console.error(err);
        input.value = '';
        input.placeholder = 'Error transcribing.';
    }
}
// --- Twin Audio Recording ---
let twinMediaRecorder;
let twinAudioChunks = [];

async function recordTwinAudio() {
    const micBtn = document.getElementById('twin-mic-btn');

    if (twinMediaRecorder && twinMediaRecorder.state === 'recording') {
        twinMediaRecorder.stop();
        return;
    }

    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });

        // Explicitly request opus codec for OpenAI Whisper compatibility
        const options = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? { mimeType: 'audio/webm;codecs=opus' }
            : undefined;

        twinMediaRecorder = new MediaRecorder(stream, options);
        twinAudioChunks = [];

        twinMediaRecorder.ondataavailable = (e) => {
            twinAudioChunks.push(e.data);
        };

        twinMediaRecorder.onstop = async () => {
            const audioBlob = new Blob(twinAudioChunks, { type: twinMediaRecorder.mimeType || 'audio/webm' });

            if (audioBlob.size === 0) {
                console.warn("Twin audio recording was empty.");
                micBtn.textContent = '🎤';
                return;
            }

            const formData = new FormData();
            formData.append('file', audioBlob, 'twin-voice.webm');

            micBtn.textContent = '⏳';
            micBtn.classList.remove('recording');

            try {
                const res = await fetch(`${API_BASE}/api/intelligence/transcribe`, {
                    method: 'POST',
                    body: formData
                });

                const data = await res.json();
                if (!data.job_id) throw new Error('No transcription job returned');
                const result = await pollTranscriptionJob(data.job_id);

                if (result.text) {
                    const input = document.getElementById('twin-input');
                    input.value = result.text;
                    input.focus();
                }
            } catch (err) {
                console.error('Transcription failed:', err);
                alert('Transcription failed');
            } finally {
                micBtn.textContent = '🎤';
            }

            stream.getTracks().forEach(track => track.stop());
        };

        twinMediaRecorder.start(200);
        micBtn.classList.add('recording');
        micBtn.textContent = '⏹';

    } catch (err) {
        console.error('Mic error:', err);
        alert('Microphone access denied');
    }
}
