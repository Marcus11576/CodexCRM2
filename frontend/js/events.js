const EVENT_STATUSES = ['Target', 'Invited', 'Confirmed', 'Registered'];
let eventDirectory = [];
let selectedEventId = null;
let showUpcomingOnly = false;
let editingEventId = null;
const EVENT_VIEW_STATE_KEY = 'crm.events.viewState';
let selectedEventPersonId = null;

function persistEventViewState(extra = {}) {
    const state = {
        eventId: selectedEventId,
        scrollY: window.scrollY || window.pageYOffset || 0,
        upcomingOnly: showUpcomingOnly,
        search: document.getElementById('events-search')?.value || '',
        updatedAt: Date.now(),
        ...extra,
    };
    sessionStorage.setItem(EVENT_VIEW_STATE_KEY, JSON.stringify(state));
}

function readEventViewState() {
    try {
        const raw = sessionStorage.getItem(EVENT_VIEW_STATE_KEY);
        return raw ? JSON.parse(raw) : null;
    } catch (error) {
        console.warn('Unable to read saved event view state', error);
        return null;
    }
}

function buildEventProfileHref(personId) {
    const params = new URLSearchParams();
    params.set('from', 'events');
    if (selectedEventId) params.set('eventId', selectedEventId);
    return `/person/${personId}?${params.toString()}`;
}

function parseTopicsInput(value) {
    return (value || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
}

function formatEventDate(dateStr) {
    if (!dateStr) return 'No date';
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return dateStr;
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function eventStatusPills(counts = {}) {
    return EVENT_STATUSES.map((status) => `<span class="event-status-pill event-status-${status.toLowerCase()}">${status} ${counts[status] || 0}</span>`).join('');
}

async function ensurePeopleDirectory() {
    if (window._eventPeopleDirectory) return;
    const data = await get('/api/people?limit=500');
    window._eventPeopleDirectory = data.people || [];
}

function personDisplayLabel(person) {
    return `${person.full_name}${person.company_name_raw ? ` - ${person.company_name_raw}` : ''}`;
}

function personOptionsMarkup() {
    return (window._eventPeopleDirectory || []).map((person) => `<option value="${personDisplayLabel(person)}" data-person-id="${person.person_id}"></option>`).join('');
}

function resolvePersonSelection(inputId) {
    const input = document.getElementById(inputId);
    if (!input) return null;
    if (input.dataset.selectedPersonId) return input.dataset.selectedPersonId;
    const rawValue = input.value.trim();
    if (!rawValue) return null;

    const people = window._eventPeopleDirectory || [];
    const normalized = rawValue.toLowerCase();
    const partial = people.find((person) => personDisplayLabel(person).toLowerCase() === normalized)
        || people.find((person) => person.full_name?.toLowerCase() === normalized)
        || people.find((person) => personDisplayLabel(person).toLowerCase().includes(normalized));
    return partial ? partial.person_id : null;
}

function hideEventPersonResults() {
    const results = document.getElementById('event-person-results');
    if (!results) return;
    results.hidden = true;
    results.innerHTML = '';
}

function selectEventPerson(person) {
    const input = document.getElementById('event-person-search');
    if (!input || !person) return;
    selectedEventPersonId = person.person_id;
    input.dataset.selectedPersonId = person.person_id;
    input.value = personDisplayLabel(person);
    hideEventPersonResults();
}

function renderEventPersonResults(query = '') {
    const input = document.getElementById('event-person-search');
    const results = document.getElementById('event-person-results');
    if (!input || !results) return;

    const matches = rankSearchMatches(
        window._eventPeopleDirectory || [],
        query,
        (person) => [person.full_name, person.company_name_raw, person.title_current, person.email_primary],
        8
    );

    if (!matches.length) {
        results.hidden = false;
        results.innerHTML = '<div class="ag-picker-empty">No matching people found.</div>';
        return;
    }

    results.hidden = false;
    results.innerHTML = matches.map((person) => `
        <button type="button" class="ag-picker-option ${String(selectedEventPersonId || input.dataset.selectedPersonId || '') === String(person.person_id) ? 'is-selected' : ''}" data-event-person-result="${person.person_id}">
            <div class="ag-picker-title">${person.full_name}</div>
            <div class="ag-picker-meta">${person.title_current || 'No title'}${person.company_name_raw ? ` @ ${person.company_name_raw}` : ''}</div>
        </button>
    `).join('');

    results.querySelectorAll('[data-event-person-result]').forEach((button) => {
        button.addEventListener('mousedown', (event) => event.preventDefault());
        button.addEventListener('click', () => {
            const person = (window._eventPeopleDirectory || []).find((candidate) => String(candidate.person_id) === String(button.dataset.eventPersonResult));
            selectEventPerson(person);
        });
    });
}

function bindEventPersonPicker() {
    const input = document.getElementById('event-person-search');
    if (!input || input.dataset.bound === 'true') return;

    input.dataset.bound = 'true';
    input.addEventListener('input', () => {
        selectedEventPersonId = null;
        input.dataset.selectedPersonId = '';
        renderEventPersonResults(input.value);
    });
    input.addEventListener('focus', () => renderEventPersonResults(input.value));
    input.addEventListener('blur', () => {
        window.setTimeout(() => {
            if (document.activeElement !== input) {
                hideEventPersonResults();
            }
        }, 120);
    });
}

async function loadEvents(preferredEventId = null) {
    const q = document.getElementById('events-search')?.value?.trim() || '';
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (showUpcomingOnly) params.set('upcoming_only', 'true');
    const data = await get(`/api/events${params.toString() ? `?${params.toString()}` : ''}`);
    eventDirectory = data.events || [];
    renderEventList();

    const nextEventId = preferredEventId || selectedEventId || eventDirectory[0]?.event_id || null;
    if (nextEventId) {
        await selectEvent(nextEventId, false);
    } else {
        showEmptyDetail();
    }
}

function renderEventList() {
    const container = document.getElementById('events-list');
    if (!container) return;
    if (eventDirectory.length === 0) {
        container.innerHTML = '<div class="events-empty-state compact"><p>No events yet. Create the first one.</p></div>';
        return;
    }

    container.innerHTML = eventDirectory.map((event) => `
        <button class="event-list-item ${selectedEventId === event.event_id ? 'active' : ''}" type="button" data-event-id="${event.event_id}">
            <div class="event-list-topline">
                <strong>${event.event_name}</strong>
                <span>${formatEventDate(event.event_date)}</span>
            </div>
            <div class="event-list-meta">${event.location || 'Location TBD'}</div>
            <div class="event-list-meta">${(event.topics || []).slice(0, 3).map((topic) => `<span class="event-topic-tag">${topic}</span>`).join(' ') || '<span class="event-topic-tag muted">No topics</span>'}</div>
            <div class="event-list-footer">
                <span>${event.linked_people_count || 0} linked people</span>
                <span>${event.status_counts?.Registered || 0} registered</span>
            </div>
        </button>
    `).join('');

    container.querySelectorAll('[data-event-id]').forEach((button) => {
        button.addEventListener('click', () => selectEvent(button.dataset.eventId, true));
    });
}

function showEmptyDetail() {
    selectedEventId = null;
    document.getElementById('event-detail').style.display = 'none';
    document.getElementById('event-detail-empty').style.display = 'grid';
    renderEventList();
    persistEventViewState({ eventId: null });
}

async function selectEvent(eventId, pushHistory = true) {
    selectedEventId = eventId;
    renderEventList();
    const detail = await get(`/api/events/${eventId}`);
    await renderEventDetail(detail);
    persistEventViewState({ eventId });
    if (pushHistory) {
        window.history.replaceState({}, '', `/events/${eventId}`);
    }
}

function groupedPeopleMarkup(detail) {
    return EVENT_STATUSES.map((status) => {
        const people = detail.people_by_status?.[status] || [];
        return `
            <section class="event-people-group">
                <div class="event-people-group-header">
                    <h3>${status}</h3>
                    <span>${people.length}</span>
                </div>
                <div class="event-people-list">
                    ${people.length ? people.map((person) => `
                        <div class="event-person-row">
                            <div>
                                <a href="${buildEventProfileHref(person.person_id)}" class="event-person-name" data-event-person-link="${person.person_id}">${person.full_name}</a>
                                <div class="event-person-meta">${person.title_current || 'No title'}${person.company_name_raw ? ` @ ${person.company_name_raw}` : ''}</div>
                            </div>
                            <div class="event-person-actions">
                                <select data-person-status="${person.person_id}">
                                    ${EVENT_STATUSES.map((option) => `<option value="${option}" ${option === person.status ? 'selected' : ''}>${option}</option>`).join('')}
                                </select>
                                <button type="button" class="events-ghost-btn compact" data-remove-person="${person.person_id}">Remove</button>
                            </div>
                        </div>
                    `).join('') : '<div class="event-person-empty">No linked people in this status.</div>'}
                </div>
            </section>
        `;
    }).join('');
}

async function renderEventDetail(detail) {
    document.getElementById('event-detail-empty').style.display = 'none';
    const container = document.getElementById('event-detail');
    container.style.display = 'block';
    await ensurePeopleDirectory();
    selectedEventPersonId = null;

    container.innerHTML = `
        <div class="event-detail-header">
            <div>
                <div class="events-kicker">Event Detail</div>
                <h2>${detail.event_name}</h2>
                <div class="event-detail-meta">${formatEventDate(detail.event_date)} · ${detail.location || 'Location TBD'}</div>
            </div>
            <div class="event-detail-actions">
                <select id="event-export-filter" class="events-ghost-btn" style="padding-right:2rem;">
                    <option value="all">Export All</option>
                    ${EVENT_STATUSES.map((status) => `<option value="${status}">${status} Only</option>`).join('')}
                </select>
                <button type="button" id="export-event-btn" class="events-ghost-btn">Export CSV</button>
                <button type="button" id="edit-event-btn" class="events-ghost-btn">Edit</button>
            </div>
        </div>

        <div class="event-detail-topics">${(detail.topics || []).map((topic) => `<span class="event-topic-tag">${topic}</span>`).join('') || '<span class="event-topic-tag muted">No topics</span>'}</div>
        <div class="event-status-strip">${eventStatusPills(detail.status_counts)}</div>
        <div class="event-notes-card">${detail.notes ? detail.notes.replace(/\n/g, '<br>') : 'No notes added yet.'}</div>

        <section class="event-link-card">
            <div class="event-link-card-header">
                <h3>Add Person And Categorise</h3>
                <span>Search by name or company and set their event status here</span>
            </div>
            <div class="event-link-form">
                <div class="events-search-field">
                    <input id="event-person-search" class="events-search-input" autocomplete="off" placeholder="Search person or company">
                    <div id="event-person-results" class="ag-picker-panel" hidden></div>
                </div>
                <select id="event-person-status-select">${EVENT_STATUSES.map((status) => `<option value="${status}">${status}</option>`).join('')}</select>
                <button type="button" id="link-person-btn" class="events-primary-btn">Link Person</button>
            </div>
        </section>

        <section class="event-people-groups">
            ${groupedPeopleMarkup(detail)}
        </section>
    `;

    document.getElementById('edit-event-btn').addEventListener('click', () => openEventModal(detail));
    document.getElementById('export-event-btn').addEventListener('click', () => exportEventParticipants(detail.event_id));
    document.getElementById('link-person-btn').addEventListener('click', () => addPersonFromEvent(detail.event_id));
    bindEventPersonPicker();
    container.querySelectorAll('[data-event-person-link]').forEach((link) => {
        link.addEventListener('click', () => persistEventViewState({ eventId: detail.event_id }));
    });
    container.querySelectorAll('[data-person-status]').forEach((select) => {
        select.addEventListener('change', async () => {
            await patch(`/api/events/${detail.event_id}/people/${select.dataset.personStatus}`, { status: select.value });
            await selectEvent(detail.event_id, false);
            toast('Event status updated', 'success');
        });
    });
    container.querySelectorAll('[data-remove-person]').forEach((button) => {
        button.addEventListener('click', async () => {
            const confirmed = await showConfirmDialog({
                title: 'Remove participant?',
                message: 'This person will no longer be linked to the event.',
                confirmLabel: 'Remove Person',
            });
            if (!confirmed) return;
            await del(`/api/events/${detail.event_id}/people/${button.dataset.removePerson}`);
            await selectEvent(detail.event_id, false);
            toast('Person removed from event', 'success');
        });
    });
}

function exportEventParticipants(eventId) {
    const filter = document.getElementById('event-export-filter')?.value || 'all';
    const params = new URLSearchParams();
    params.set('status_filter', filter);
    downloadFile(`/api/events/${eventId}/participants/export?${params.toString()}`);
}

async function addPersonFromEvent(eventId) {
    const personId = resolvePersonSelection('event-person-search');
    const status = document.getElementById('event-person-status-select').value;
    if (!personId) {
        toast('Choose a valid person to link', 'warning');
        document.getElementById('event-person-search')?.focus();
        return;
    }
    await post(`/api/events/${eventId}/people`, { person_id: personId, status });
    const input = document.getElementById('event-person-search');
    if (input) {
        input.value = '';
        input.dataset.selectedPersonId = '';
    }
    selectedEventPersonId = null;
    hideEventPersonResults();
    toast('Person linked to event', 'success');
    await selectEvent(eventId, false);
}

function openEventModal(detail = null) {
    editingEventId = detail?.event_id || null;
    document.getElementById('event-modal-title').textContent = editingEventId ? 'Edit Event' : 'Create Event';
    document.getElementById('event-name').value = detail?.event_name || '';
    document.getElementById('event-location').value = detail?.location || '';
    document.getElementById('event-date').value = detail?.event_date || '';
    document.getElementById('event-topics').value = (detail?.topics || []).join(', ');
    document.getElementById('event-notes').value = detail?.notes || '';
    document.getElementById('event-modal').style.display = 'flex';
}

function closeEventModal() {
    document.getElementById('event-modal').style.display = 'none';
    editingEventId = null;
    document.getElementById('event-form').reset();
}

async function saveEvent(event) {
    event.preventDefault();
    const payload = {
        event_name: document.getElementById('event-name').value.trim(),
        location: document.getElementById('event-location').value.trim(),
        event_date: document.getElementById('event-date').value,
        topics: parseTopicsInput(document.getElementById('event-topics').value),
        notes: document.getElementById('event-notes').value.trim(),
    };

    if (!payload.event_name || !payload.event_date) {
        toast('Event name and date are required', 'warning');
        return;
    }

    if (editingEventId) {
        const res = await patch(`/api/events/${editingEventId}`, payload);
        closeEventModal();
        toast('Event updated', 'success');
        await loadEvents(res.event.event_id);
    } else {
        const res = await post('/api/events', payload);
        closeEventModal();
        toast('Event created', 'success');
        await loadEvents(res.event.event_id);
    }
}

function restoreEventViewState() {
    const savedState = readEventViewState();
    const pathMatch = window.location.pathname.match(/^\/events\/([^/]+)$/);
    const pathEventId = pathMatch ? pathMatch[1] : null;

    if (savedState?.search) {
        const searchInput = document.getElementById('events-search');
        if (searchInput) searchInput.value = savedState.search;
    }

    if (typeof savedState?.upcomingOnly === 'boolean') {
        showUpcomingOnly = savedState.upcomingOnly;
        const toggle = document.getElementById('toggle-upcoming-btn');
        if (toggle) {
            toggle.textContent = showUpcomingOnly ? 'Showing Upcoming' : 'Upcoming Only';
        }
    }

    return pathEventId || savedState?.eventId || null;
}

function initEventPage() {
    renderUniversalLayout('events', 'EVENTS');
    document.getElementById('new-event-btn').addEventListener('click', () => openEventModal());
    document.getElementById('close-event-modal').addEventListener('click', closeEventModal);
    document.getElementById('cancel-event-modal').addEventListener('click', closeEventModal);
    document.getElementById('event-form').addEventListener('submit', saveEvent);
    document.getElementById('events-search').addEventListener('input', debounce(() => {
        persistEventViewState();
        loadEvents(selectedEventId);
    }, 250));
    document.getElementById('toggle-upcoming-btn').addEventListener('click', async () => {
        showUpcomingOnly = !showUpcomingOnly;
        document.getElementById('toggle-upcoming-btn').textContent = showUpcomingOnly ? 'Showing Upcoming' : 'Upcoming Only';
        persistEventViewState();
        await loadEvents(selectedEventId);
    });

    const initialEventId = restoreEventViewState();
    loadEvents(initialEventId).then(() => {
        const savedState = readEventViewState();
        if (typeof savedState?.scrollY === 'number') {
            requestAnimationFrame(() => window.scrollTo({ top: savedState.scrollY, behavior: 'auto' }));
        }
    }).catch((error) => {
        console.error(error);
        toast(error.message || 'Failed to load events', 'error');
    });

    window.addEventListener('scroll', () => persistEventViewState(), { passive: true });
    window.addEventListener('beforeunload', () => persistEventViewState());
}

document.addEventListener('DOMContentLoaded', initEventPage);
