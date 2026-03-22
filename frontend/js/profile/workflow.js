// Tasks, events, scrolling, and page bootstrap
let profileEventStatuses = ['Target', 'Invited', 'Confirmed', 'Registered'];
let profileEventPickerVisible = false;
let profileEventDirectory = [];

function renderTasks(tasks) {
    const html = tasks.map(task => `
        <div class="context-item" style="display:flex; justify-content:space-between; align-items:center;">
            <div style="flex:1;">
                <div class="context-label">Due: ${task.due_date || 'Not set'}</div>
                <div class="context-text">${task.task_text}</div>
            </div>
            <button onclick="deleteTask('${task.task_id}')"
                    style="font-size:1.2rem; padding:4px 8px; background:rgba(255,0,0,0.1); border:none; border-radius:4px; color:var(--accent-red); cursor:pointer; margin-left:1rem;"
                    title="Delete task">x</button>
        </div>
    `).join('');

    document.getElementById('tasks-list').innerHTML = html;
}

async function deleteTask(taskId) {
    const confirmed = await showConfirmDialog({
        title: 'Delete task?',
        message: 'This will remove the task from the profile timeline.',
        confirmLabel: 'Delete Task',
    });
    if (!confirmed) return;

    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        if (response.ok) {
            await loadPersonQuiet();
            toast('Task deleted', 'success');
        } else {
            const error = await response.json();
            toast(`Error deleting task: ${error.detail || 'Unknown error'}`, 'error');
        }
    } catch (err) {
        console.error(err);
        toast('Error deleting task', 'error');
    }
}

function profileEventStatusOptions(selectedStatus) {
    return profileEventStatuses.map((status) => `<option value="${status}" ${status === selectedStatus ? 'selected' : ''}>${status}</option>`).join('');
}

function profileEventDisplayLabel(eventItem) {
    return `${eventItem.event_name}${eventItem.location ? ` - ${eventItem.location}` : ''}${eventItem.event_date ? ` - ${eventItem.event_date}` : ''}`;
}

function resolveProfileEventSelection(directory) {
    const input = document.getElementById('profile-event-search');
    if (!input) return null;
    const selectedId = input.dataset.selectedEventId;
    if (selectedId && (directory || []).some((eventItem) => String(eventItem.event_id) === String(selectedId))) {
        return selectedId;
    }
    const rawValue = input.value.trim();
    if (!rawValue) return null;

    const normalized = rawValue.toLowerCase();
    const match = (directory || []).find((eventItem) => profileEventDisplayLabel(eventItem).toLowerCase() === normalized)
        || (directory || []).find((eventItem) => (eventItem.event_name || '').toLowerCase() === normalized)
        || (directory || []).find((eventItem) => profileEventDisplayLabel(eventItem).toLowerCase().includes(normalized));
    return match ? match.event_id : null;
}

function hideProfileEventResults() {
    const results = document.getElementById('profile-event-results');
    if (!results) return;
    results.hidden = true;
    results.innerHTML = '';
}

function selectProfileEventResult(eventItem) {
    const input = document.getElementById('profile-event-search');
    if (!input || !eventItem) return;
    input.value = profileEventDisplayLabel(eventItem);
    input.dataset.selectedEventId = eventItem.event_id;
    hideProfileEventResults();
}

function renderProfileEventResults(query = '') {
    const results = document.getElementById('profile-event-results');
    const input = document.getElementById('profile-event-search');
    if (!results || !input || !profileEventPickerVisible) {
        hideProfileEventResults();
        return;
    }

    const matches = rankSearchMatches(
        profileEventDirectory,
        query,
        (eventItem) => [eventItem.event_name, eventItem.location, eventItem.event_date, ...(eventItem.topics || [])],
        8
    );

    if (!matches.length) {
        results.hidden = false;
        results.innerHTML = '<div class="ag-picker-empty">No matching events found.</div>';
        return;
    }

    results.hidden = false;
    results.innerHTML = matches.map((eventItem) => `
        <button type="button" class="ag-picker-option ${String(input.dataset.selectedEventId || '') === String(eventItem.event_id) ? 'is-selected' : ''}" data-profile-event-result="${eventItem.event_id}">
            <div class="ag-picker-title">${eventItem.event_name}</div>
            <div class="ag-picker-meta">${eventItem.location || 'Location TBD'}${eventItem.event_date ? ` · ${eventItem.event_date}` : ''}</div>
        </button>
    `).join('');

    results.querySelectorAll('[data-profile-event-result]').forEach((button) => {
        button.addEventListener('mousedown', (event) => event.preventDefault());
        button.addEventListener('click', () => {
            const eventItem = profileEventDirectory.find((candidate) => String(candidate.event_id) === String(button.dataset.profileEventResult));
            selectProfileEventResult(eventItem);
        });
    });
}

function bindProfileEventPicker(eventSearch, addButton, linkButton, statusSelect, controls) {
    if (!eventSearch || !addButton || !linkButton || !statusSelect || !controls || eventSearch.dataset.bound === 'true') {
        return;
    }

    eventSearch.dataset.bound = 'true';

    eventSearch.addEventListener('input', () => {
        eventSearch.dataset.selectedEventId = '';
        profileEventPickerVisible = true;
        controls.style.display = 'grid';
        renderProfileEventResults(eventSearch.value);
        addButton.textContent = 'Hide Event Picker';
    });

    eventSearch.addEventListener('focus', () => {
        if (!profileEventDirectory.length) return;
        profileEventPickerVisible = true;
        controls.style.display = 'grid';
        renderProfileEventResults(eventSearch.value);
        addButton.textContent = 'Hide Event Picker';
    });

    eventSearch.addEventListener('blur', () => {
        window.setTimeout(() => {
            if (document.activeElement !== eventSearch) {
                hideProfileEventResults();
            }
        }, 120);
    });

    addButton.addEventListener('click', () => {
        if (!profileEventDirectory.length) return;
        profileEventPickerVisible = !profileEventPickerVisible;
        controls.style.display = profileEventPickerVisible ? 'grid' : 'none';
        if (profileEventPickerVisible) {
            addButton.textContent = 'Hide Event Picker';
            renderProfileEventResults(eventSearch.value);
            eventSearch.focus();
        } else {
            addButton.textContent = 'Add To Event';
            hideProfileEventResults();
        }
    });

    linkButton.addEventListener('click', async () => {
        const eventId = resolveProfileEventSelection(profileEventDirectory);
        if (!eventId) {
            toast('Choose a valid event to link', 'warning');
            eventSearch.focus();
            return;
        }
        await post(`/api/events/people/${personId}/links`, { event_id: eventId, status: statusSelect.value });
        toast('Event linked to profile', 'success');
        profileEventPickerVisible = false;
        eventSearch.value = '';
        eventSearch.dataset.selectedEventId = '';
        hideProfileEventResults();
        await loadProfileEvents();
    });
}

async function loadProfileEvents() {
    if (!personId) return;
    try {
        const [linked, directory] = await Promise.all([
            get(`/api/events/people/${personId}/links`),
            get('/api/events'),
        ]);
        profileEventStatuses = linked.statuses || profileEventStatuses;
        renderProfileEvents(linked.events || [], directory.events || []);
    } catch (error) {
        console.error('Profile events load failed:', error);
    }
}

function renderProfileEvents(events, directory) {
    const list = document.getElementById('profile-events-list');
    const controls = document.getElementById('profile-events-controls');
    const eventSearch = document.getElementById('profile-event-search');
    const statusSelect = document.getElementById('profile-event-status-select');
    const addButton = document.getElementById('profile-add-event-btn');
    const linkButton = document.getElementById('profile-link-event-btn');

    if (!list || !controls || !eventSearch || !statusSelect || !addButton || !linkButton) return;

    renderUniversalLayout('profile', (window.currentPersonData?.full_name || 'PROFILE').toUpperCase());

    statusSelect.innerHTML = profileEventStatusOptions(profileEventStatuses[0]);
    const linkedIds = new Set(events.map((eventItem) => eventItem.event_id));
    const availableEvents = directory.filter((eventItem) => !linkedIds.has(eventItem.event_id));
    profileEventDirectory = availableEvents;

    if (!availableEvents.length) {
        profileEventPickerVisible = false;
    }

    controls.style.display = availableEvents.length && profileEventPickerVisible ? 'grid' : 'none';
    addButton.style.display = availableEvents.length ? 'inline-flex' : 'inline-flex';
    addButton.textContent = availableEvents.length ? (profileEventPickerVisible ? 'Hide Event Picker' : 'Add To Event') : 'All Events Linked';
    addButton.disabled = !availableEvents.length;
    eventSearch.dataset.selectedEventId = availableEvents.some((eventItem) => String(eventItem.event_id) === String(eventSearch.dataset.selectedEventId || ''))
        ? eventSearch.dataset.selectedEventId
        : '';

    if (!profileEventPickerVisible) {
        hideProfileEventResults();
    } else {
        renderProfileEventResults(eventSearch.value);
    }

    bindProfileEventPicker(eventSearch, addButton, linkButton, statusSelect, controls);

    if (!events.length) {
        list.innerHTML = '<div class="event-notes-card">No event links yet. Use Add To Event to connect this person to upcoming events.</div>';
        return;
    }

    list.innerHTML = events.map((eventItem) => `
        <div class="profile-event-row">
            <div>
                <a href="/events/${eventItem.event_id}" class="event-person-name">${eventItem.event_name}</a>
                <div class="profile-event-meta">${eventItem.location || 'Location TBD'} · ${eventItem.event_date}</div>
                <div class="event-detail-topics">${(eventItem.topics || []).map((topic) => `<span class="event-topic-tag">${topic}</span>`).join('') || '<span class="event-topic-tag muted">No topics</span>'}</div>
            </div>
            <div class="profile-event-actions">
                <select data-profile-event-status="${eventItem.event_id}">${profileEventStatusOptions(eventItem.status)}</select>
                <button type="button" class="events-ghost-btn compact" data-profile-event-remove="${eventItem.event_id}">Remove</button>
            </div>
        </div>
    `).join('');

    list.querySelectorAll('[data-profile-event-status]').forEach((select) => {
        select.addEventListener('change', async () => {
            await patch(`/api/events/people/${personId}/links/${select.dataset.profileEventStatus}`, { status: select.value });
            toast('Profile event status updated', 'success');
            await loadProfileEvents();
        });
    });

    list.querySelectorAll('[data-profile-event-remove]').forEach((button) => {
        button.addEventListener('click', async () => {
            const confirmed = await showConfirmDialog({
                title: 'Remove event link?',
                message: 'This person will no longer be attached to the event.',
                confirmLabel: 'Remove Link',
            });
            if (!confirmed) return;
            await del(`/api/events/people/${personId}/links/${button.dataset.profileEventRemove}`);
            toast('Event link removed', 'success');
            await loadProfileEvents();
        });
    });
}

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

    const container = document.querySelector('.container');
    const windowScroll = window.pageYOffset || document.documentElement.scrollTop || 0;
    const containerScroll = container ? container.scrollTop : 0;
    const scrollPos = Math.max(windowScroll, containerScroll);

    btn.style.display = scrollPos > 300 ? 'flex' : 'none';
}

document.addEventListener('DOMContentLoaded', () => {
    renderUniversalLayout('profile', 'PROFILE');
    document.getElementById('refresh-ai-jobs-btn')?.addEventListener('click', loadAiJobs);
    loadPerson();
    initDragDrop();
    if (typeof syncMobileProfileTopLayout === 'function') {
        syncMobileProfileTopLayout();
        window.addEventListener('resize', syncMobileProfileTopLayout);
    }

    const params = new URLSearchParams(window.location.search);
    const fromParam = params.get('from');
    if (fromParam) {
        const eventIdParam = params.get('eventId');
        const backMap = {
            agenda: { label: 'Back to Agenda', href: '/agenda' },
            dashboard: { label: 'Dashboard', href: '/' },
            settings: { label: 'Settings', href: '/settings' },
            events: { label: 'Back to Event', href: eventIdParam ? `/events/${eventIdParam}` : '/events' }
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

    updateScrollBtn();
    const container = document.querySelector('.container');
    if (container) container.addEventListener('scroll', updateScrollBtn, { passive: true });
    window.addEventListener('scroll', updateScrollBtn, { passive: true });

    const observer = new MutationObserver(() => {
        const c = document.querySelector('.container');
        if (c) c.addEventListener('scroll', updateScrollBtn, { passive: true });
        updateScrollBtn();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    document.addEventListener('click', (e) => {
        if (!isEditingEnv && !isEditingCat && !isEditingDisc && !isEditingStatus) return;
        if (e.target.closest('.tag-group')) return;

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
