// Tasks, events, scrolling, and page bootstrap
let profileEventStatuses = ['Target', 'Invited', 'Confirmed', 'Registered'];
let profileEventPickerVisible = false;

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
    if (!confirm('Are you sure you want to delete this task?')) return;

    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });
        if (response.ok) {
            await loadPersonQuiet();
            loadPropensityData();
        } else {
            const error = await response.json();
            alert(`Error deleting task: ${error.detail || 'Unknown error'}`);
        }
    } catch (err) {
        console.error(err);
        alert('Error deleting task');
    }
}

function profileEventStatusOptions(selectedStatus) {
    return profileEventStatuses.map((status) => `<option value="${status}" ${status === selectedStatus ? 'selected' : ''}>${status}</option>`).join('');
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
    const eventSelect = document.getElementById('profile-event-select');
    const statusSelect = document.getElementById('profile-event-status-select');
    const addButton = document.getElementById('profile-add-event-btn');
    const linkButton = document.getElementById('profile-link-event-btn');

    if (!list || !controls || !eventSelect || !statusSelect || !addButton || !linkButton) return;

    renderUniversalLayout('profile', (window.currentPersonData?.full_name || 'PROFILE').toUpperCase());

    statusSelect.innerHTML = profileEventStatusOptions(profileEventStatuses[0]);
    const linkedIds = new Set(events.map((eventItem) => eventItem.event_id));
    const availableEvents = directory.filter((eventItem) => !linkedIds.has(eventItem.event_id));
    eventSelect.innerHTML = '<option value="">Select event</option>' + availableEvents.map((eventItem) => `<option value="${eventItem.event_id}">${eventItem.event_name} · ${eventItem.event_date}</option>`).join('');

    if (!addButton.dataset.bound) {
        addButton.dataset.bound = 'true';
        addButton.addEventListener('click', () => {
            profileEventPickerVisible = !profileEventPickerVisible;
            controls.style.display = profileEventPickerVisible ? 'grid' : 'none';
        });
        linkButton.addEventListener('click', async () => {
            if (!eventSelect.value) {
                toast('Choose an event to link', 'warning');
                return;
            }
            await post(`/api/events/people/${personId}/links`, { event_id: eventSelect.value, status: statusSelect.value });
            toast('Event linked to profile', 'success');
            profileEventPickerVisible = false;
            controls.style.display = 'none';
            await loadProfileEvents();
        });
    }

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

    const fromParam = new URLSearchParams(window.location.search).get('from');
    if (fromParam) {
        const backMap = {
            agenda: { label: 'Back to Agenda', href: '/agenda' },
            dashboard: { label: 'Dashboard', href: '/' },
            settings: { label: 'Settings', href: '/settings' }
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
