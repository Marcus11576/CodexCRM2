// â”€â”€ CONSTANTS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const SEG = {
    morning: { start: 0, end: 720, icon: 'AM', label: 'Morning', color: 'var(--morning-col)', defaultTime: '09:00', cls: 'sel-morning' },
    afternoon: { start: 720, end: 1440, icon: 'PM', label: 'Afternoon', color: 'var(--afternoon-col)', defaultTime: '13:00', cls: 'sel-afternoon' }
};

function timeToMins(t) {
    if (!t) return -1;
    const [h, m] = t.split(':').map(Number);
    return h * 60 + m;
}
function getSegment(timeStr) {
    const mins = timeToMins(timeStr);
    if (mins < 0) return 'morning';
    if (mins < 720) return 'morning';
    return 'afternoon';
}

// â”€â”€ STATE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
let allTasks = [];
let currentView = 'day';
let currentFilter = 'active';
let selectedDate = new Date();
let calYear = selectedDate.getFullYear();
let calMonth = selectedDate.getMonth();
let selectedPrio = 'medium';
let taskDotMap = {};
let agendaSearchTerm = '';
let agendaPersonId = '';
let agendaEmployer = '';
let agendaContactName = '';

const toDateStr = d => {
    const y = d.getFullYear(), m = String(d.getMonth() + 1).padStart(2, '0'), dd = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${dd}`;
};
const today = toDateStr(new Date());

function updateStateURL() {
    const params = new URLSearchParams();
    params.set('view', currentView);
    params.set('filter', currentFilter);
    params.set('date', toDateStr(selectedDate));
    window.history.replaceState(null, '', '#' + params.toString());
}

function restoreStateFromURL() {
    const hash = window.location.hash.substring(1);
    if (!hash) return;
    const params = new URLSearchParams(hash);
    if (params.has('view')) currentView = params.get('view');
    if (params.has('filter')) currentFilter = params.get('filter');
    if (params.has('date')) selectedDate = new Date(params.get('date') + 'T00:00:00');
    calYear = selectedDate.getFullYear();
    calMonth = selectedDate.getMonth();
}

function restoreAgendaSearchFromQuery() {
    const params = new URLSearchParams(window.location.search);
    agendaSearchTerm = (params.get('q') || '').trim();
    agendaPersonId = (params.get('person_id') || '').trim();
    agendaEmployer = (params.get('employer') || '').trim();
    agendaContactName = (params.get('contact_name') || '').trim();
    if (agendaSearchTerm || agendaPersonId || agendaEmployer) {
        currentView = 'all';
        currentFilter = 'all';
    }
}

function hasAgendaSearchScope() {
    return Boolean(agendaSearchTerm || agendaPersonId || agendaEmployer);
}

function formatDisplay(str) {
    if (!str) return '';
    const d = new Date(str + 'T00:00:00');
    return d.toLocaleDateString('en-GB', { weekday: 'short', month: 'short', day: 'numeric' });
}

function normalizeTaskSearchValue(value) {
    return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function taskMatchesAgendaSearch(task) {
    const haystack = [
        task.task_text,
        task.person_name,
        task.company_name_raw,
        task.cat,
    ].map(normalizeTaskSearchValue).filter(Boolean).join(' ');
    const term = normalizeTaskSearchValue(agendaSearchTerm);
    const employer = normalizeTaskSearchValue(agendaEmployer);
    const personIdMatch = agendaPersonId && String(task.person_id || '') === agendaPersonId;
    const employerMatch = employer && normalizeTaskSearchValue(task.company_name_raw).includes(employer);
    const profileScopeMatch = (agendaPersonId || employer) ? (personIdMatch || employerMatch) : true;
    const termMatch = !term || haystack.includes(term);
    return profileScopeMatch && termMatch;
}

function syncAgendaSearchUI() {
    const input = document.getElementById('task-search-input');
    const clear = document.getElementById('task-search-clear');
    const context = document.getElementById('task-search-context');
    if (input) input.value = agendaSearchTerm;
    if (clear) clear.hidden = !(agendaSearchTerm || agendaPersonId || agendaEmployer);
    if (context) {
        const parts = [];
        if (agendaPersonId && agendaContactName) parts.push(`Contact: ${agendaContactName}`);
        else if (agendaSearchTerm) parts.push(`Search: ${agendaSearchTerm}`);
        if (agendaEmployer) parts.push(`Employer: ${agendaEmployer}`);
        if (parts.length) {
            context.hidden = false;
            context.textContent = parts.join(' · ');
        } else {
            context.hidden = true;
            context.textContent = '';
        }
    }
}

function setAgendaSearch(value) {
    agendaSearchTerm = String(value || '').trim();
    syncAgendaSearchUI();
    renderTasks();
}

function clearAgendaSearch() {
    agendaSearchTerm = '';
    agendaPersonId = '';
    agendaEmployer = '';
    agendaContactName = '';
    currentView = 'all';
    currentFilter = 'all';
    document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('vb-all')?.classList.add('active');
    document.querySelectorAll('.fpill').forEach(p => p.classList.remove('active'));
    document.getElementById('fp-all')?.classList.add('active');
    syncAgendaSearchUI();
    renderTasks();
    updateStateURL();
}
function formatRelative(str) {
    if (!str) return { label: '', cls: '' };
    const d = new Date(str + 'T00:00:00');
    const t = new Date(); t.setHours(0, 0, 0, 0);
    const diff = Math.round((d - t) / 86400000);
    if (diff < 0) return { label: `${Math.abs(diff)}d overdue`, cls: 'overdue' };
    if (diff === 0) return { label: 'Today', cls: 'today' };
    if (diff === 1) return { label: 'Tomorrow', cls: '' };
    return { label: formatDisplay(str), cls: '' };
}
function fmt12(t) {
    if (!t) return '';
    const [h, m] = t.split(':').map(Number);
    const ampm = h >= 12 ? 'PM' : 'AM';
    const h12 = h > 12 ? h - 12 : h === 0 ? 12 : h;
    return `${h12}:${String(m).padStart(2, '0')} ${ampm}`;
}

function getTaskSortWeight(task) {
    if (task.status === 'open') return 0;
    if (task.status === 'in_progress') return 1;
    if (task.status === 'done') return 2;
    return 3;
}

function sortTasksForDisplay(tasks) {
    return tasks.sort((a, b) => {
        const timeCompare = (a.due_time || '').localeCompare(b.due_time || '');
        if (timeCompare !== 0) return timeCompare;

        const statusCompare = getTaskSortWeight(a) - getTaskSortWeight(b);
        if (statusCompare !== 0) return statusCompare;

        return (a.created_at || '').localeCompare(b.created_at || '');
    });
}

// â”€â”€ DATA â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
async function loadTasks() {
    try {
        const r = await fetch('/api/tasks?status=all');
        allTasks = await r.json();
        buildDotMap();
        renderCalendar(); renderMini(); renderTasks();

        // Restore scroll position if returning
        const scrollPos = sessionStorage.getItem('agendaScrollPos');
        if (scrollPos) {
            window.scrollTo(0, parseInt(scrollPos));
            sessionStorage.removeItem('agendaScrollPos');
        }
    } catch (e) { toast('Failed to load tasks', 'error'); }
}

function buildDotMap() {
    taskDotMap = {};
    const now = new Date(); now.setHours(0, 0, 0, 0);
    allTasks.forEach(t => {
        if (!t.due_date || t.status === 'done' || t.status === 'cancelled') return;
        const d = t.due_date.slice(0, 10);
        if (!taskDotMap[d]) taskDotMap[d] = { count: 0, hasOverdue: false };
        taskDotMap[d].count++;
        if (new Date(d + 'T00:00:00') < now) taskDotMap[d].hasOverdue = true;
    });
}

// â”€â”€ CALENDAR â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

function renderCalendar() {
    document.getElementById('cal-title').textContent = `${MONTHS[calMonth]} ${calYear}`;
    const grid = document.getElementById('cal-grid');
    grid.innerHTML = '';
    ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'].forEach(d => {
        const el = document.createElement('div');
        el.className = 'cal-day-lbl'; el.textContent = d; grid.appendChild(el);
    });
    const first = new Date(calYear, calMonth, 1);
    const startDow = (first.getDay() + 6) % 7;
    const dIM = new Date(calYear, calMonth + 1, 0).getDate();
    const prevDIM = new Date(calYear, calMonth, 0).getDate();

    for (let i = 0; i < startDow; i++) {
        const el = document.createElement('div'); el.className = 'cal-day other';
        el.textContent = prevDIM - startDow + 1 + i; grid.appendChild(el);
    }
    for (let d = 1; d <= dIM; d++) {
        const ds = `${calYear}-${String(calMonth + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const el = document.createElement('div'); el.className = 'cal-day';
        el.textContent = d;
        if (ds === today) el.classList.add('today');
        if (ds === toDateStr(selectedDate)) el.classList.add('selected');
        // dots
        if (taskDotMap[ds]) {
            const dots = document.createElement('div'); dots.className = 'cal-dots';
            const n = Math.min(taskDotMap[ds].count, 3);
            for (let i = 0; i < n; i++) {
                const dot = document.createElement('div'); dot.className = 'cal-dot';
                dot.style.background = taskDotMap[ds].hasOverdue ? 'var(--accent-red)' : 'var(--accent-cyan)';
                dots.appendChild(dot);
            }
            el.appendChild(dots);
        }
        el.onclick = () => {
            selectedDate = new Date(ds + 'T00:00:00');
            setView('day');
            renderCalendar();
            renderTasks();
            updateStateURL();
        };
        grid.appendChild(el);
    }
    const rem = 42 - startDow - dIM;
    for (let i = 1; i <= rem; i++) {
        const el = document.createElement('div'); el.className = 'cal-day other'; el.textContent = i; grid.appendChild(el);
    }
}
function prevMonth() { calMonth--; if (calMonth < 0) { calMonth = 11; calYear--; } renderCalendar(); }
function nextMonth() { calMonth++; if (calMonth > 11) { calMonth = 0; calYear++; } renderCalendar(); }

// â”€â”€ MINI LIST â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function renderMini() {
    const el = document.getElementById('mini-list');
    const up = allTasks.filter(t => ['open', 'in_progress'].includes(t.status) && t.due_date)
        .sort((a, b) => (a.due_date + a.due_time || '').localeCompare(b.due_date + b.due_time || '')).slice(0, 5);
    if (!up.length) { el.innerHTML = '<div style="font-size:.73rem;color:var(--text-muted);padding:6px 0;">No upcoming tasks</div>'; return; }
    el.innerHTML = up.map(t => {
        const rel = formatRelative(t.due_date);
        const c = rel.cls === 'overdue' ? 'var(--accent-red)' : rel.cls === 'today' ? 'var(--accent-orange)' : 'var(--accent-cyan)';
        return `<div class="mini-item" onclick="jumpTo('${t.due_date}')">
      <div class="mini-dot" style="background:${c}"></div>
      <div class="mini-text">${esc(t.task_text)}</div>
      <div class="mini-date">${rel.label || formatDisplay(t.due_date)}</div>
    </div>`;
    }).join('');
}
function jumpTo(ds) {
    selectedDate = new Date(ds + 'T00:00:00');
    calYear = selectedDate.getFullYear(); calMonth = selectedDate.getMonth();
    setView('day'); renderCalendar(); renderTasks();
    updateStateURL();
}

// â”€â”€ VIEW / FILTER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function setView(v) {
    currentView = v;
    document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
    document.getElementById(`vb-${v}`).classList.add('active');
    document.getElementById('week-strip-wrap').style.display = v === 'week' ? 'block' : 'none';
    if (v === 'week') renderWeekStrip();
    renderTasks();
    updateStateURL();
}
function setFilter(f) {
    currentFilter = f;
    document.querySelectorAll('.fpill').forEach(b => b.classList.remove('active'));
    document.getElementById(`fp-${f}`).classList.add('active');
    renderTasks();
    updateStateURL();
}
function renderWeekStrip() {
    const strip = document.getElementById('week-strip');
    const sel = toDateStr(selectedDate);
    const mon = new Date(selectedDate);
    mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    strip.innerHTML = '';
    for (let i = 0; i < 7; i++) {
        const d = new Date(mon); d.setDate(mon.getDate() + i);
        const ds = toDateStr(d);
        const el = document.createElement('div');
        el.className = `wday${ds === today ? ' today-w' : ''}${ds === sel ? ' sel-w' : ''}`;
        el.innerHTML = `<div class="wday-name">${days[i]}</div><div class="wday-num">${d.getDate()}</div>${taskDotMap[ds] ? '<div class="wday-dot"></div>' : ''}`;
        el.onclick = () => { selectedDate = d; renderWeekStrip(); renderTasks(); updateStateURL(); };
        strip.appendChild(el);
    }
}

// â”€â”€ TASK RENDERING â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function getFiltered() {
    let tasks = [...allTasks];
    tasks = tasks.filter(taskMatchesAgendaSearch);
    if (currentFilter === 'active') {
        tasks = tasks.filter(t => ['open', 'in_progress'].includes(t.status));
    } else if (currentFilter !== 'all') {
        tasks = tasks.filter(t => t.status === currentFilter);
    }
    if (hasAgendaSearchScope()) {
        return tasks;
    }
    if (currentView === 'day') {
        const ds = toDateStr(selectedDate);
        tasks = tasks.filter(t => t.due_date ? t.due_date.slice(0, 10) === ds : (!['done', 'cancelled'].includes(currentFilter) && ds === today));
    } else if (currentView === 'week') {
        const mon = new Date(selectedDate); mon.setDate(mon.getDate() - ((mon.getDay() + 6) % 7));
        const sun = new Date(mon); sun.setDate(mon.getDate() + 6);
        const mS = toDateStr(mon), sS = toDateStr(sun);
        tasks = tasks.filter(t => t.due_date && t.due_date.slice(0, 10) >= mS && t.due_date.slice(0, 10) <= sS);
    }
    return tasks;
}

function renderTasks() {
    const tasks = getFiltered();
    const ptitle = document.getElementById('panel-title');
    const psub = document.getElementById('panel-sub');
    const open = tasks.filter(t => t.status === 'open').length;
    const inProgress = tasks.filter(t => t.status === 'in_progress').length;
    const done = tasks.filter(t => t.status === 'done').length;

    if (hasAgendaSearchScope()) {
        ptitle.textContent = 'Task Search';
    } else if (currentView === 'day') {
        const ds = toDateStr(selectedDate);
        ptitle.textContent = ds === today ? 'Today' : formatDisplay(ds);
    } else if (currentView === 'week') {
        ptitle.textContent = 'This Week';
    } else {
        ptitle.textContent = 'All Tasks';
    }
    const summaryParts = [`${open} open`];
    if (inProgress) summaryParts.push(`${inProgress} in progress`);
    if (done) summaryParts.push(`${done} done`);
    if (agendaSearchTerm || agendaPersonId || agendaEmployer) summaryParts.push('filtered');
    psub.textContent = summaryParts.join(', ');

    const container = document.getElementById('task-list');

    if (!tasks.length) {
        container.innerHTML = `<div class="empty-state">
      <div class="empty-icon">OK</div>
      <div class="empty-title">All clear</div>
      <div class="empty-sub">No tasks for this ${currentView === 'day' ? 'day' : currentView === 'week' ? 'week' : 'period'}.<br>
      <button onclick="openModal()" style="margin-top:.75rem;padding:6px 16px;border-radius:9px;border:1px solid var(--glass-border);background:rgba(255,255,255,0.07);color:var(--accent-cyan);font-size:.78rem;font-weight:700;cursor:pointer;">+ Add a task</button></div>
    </div>`;
        return;
    }

    // For day view, split into Morning / Afternoon / Evening / Anytime
    if (currentView === 'day') {
        const groups = { morning: [], afternoon: [] };
        tasks.forEach(t => {
            const seg = getSegment(t.due_time);
            groups[seg].push(t);
        });
        ['morning', 'afternoon'].forEach(s => {
            sortTasksForDisplay(groups[s]);
        });

        let html = '';
        const order = ['morning', 'afternoon'];
        order.forEach(s => {
            if (!groups[s].length) return;
            const sg = SEG[s];
            html += `<div class="seg-block">
        <div class="seg-header">
          <span class="seg-icon">${sg.icon}</span>
          <span class="seg-title" style="color:${sg.color}">${sg.label}</span>
          <span class="seg-count">${groups[s].length}</span>
          <div class="seg-line"></div>
        </div>
        <div class="seg-tasks">${groups[s].map(renderCard).join('')}</div>
      </div>`;
        });
        container.innerHTML = html;
    } else {
        // Week/All: group by date then by segment
        const dateGroups = {};
        tasks.forEach(t => {
            const k = t.due_date ? t.due_date.slice(0, 10) : 'no-date';
            if (!dateGroups[k]) dateGroups[k] = [];
            dateGroups[k].push(t);
        });
        const sortedDates = Object.keys(dateGroups).sort();
        let html = '';
        sortedDates.forEach(dk => {
            const dayTasks = dateGroups[dk];
            const dayLabel = dk === 'no-date' ? 'No Date' : (dk === today ? 'Today - ' : '') + formatDisplay(dk);
            // Sub-group by segment within each day
            const segs = { morning: [], afternoon: [] };
            dayTasks.forEach(t => segs[getSegment(t.due_time)].push(t));
            Object.values(segs).forEach(sortTasksForDisplay);

            html += `<div class="seg-block">
        <div class="seg-header">
          <span class="seg-title" style="color:var(--text-secondary);font-size:.72rem;">${dayLabel}</span>
          <span class="seg-count">${dayTasks.length}</span>
          <div class="seg-line"></div>
        </div>`;

            const order = ['morning', 'afternoon'];
            order.forEach(s => {
                if (!segs[s].length) return;
                const sg = SEG[s];
                html += `<div style="margin-bottom:.4rem;">
          <div style="display:flex;align-items:center;gap:.4rem;padding:.2rem 0;margin-bottom:.25rem;">
            <span style="font-size:.85rem;">${sg.icon}</span>
            <span style="font-size:.6rem;font-weight:800;text-transform:uppercase;color:${sg.color};letter-spacing:1px;">${sg.label}</span>
          </div>
          <div class="seg-tasks">${segs[s].map(renderCard).join('')}</div>
        </div>`;
            });
            html += '</div>';
        });
        container.innerHTML = html;
    }
}

function renderCard(t) {
    const isDone = t.status === 'done';
    const isInProgress = t.status === 'in_progress';
    const rel = t.due_date ? formatRelative(t.due_date.slice(0, 10)) : { label: '', cls: '' };
    const timeBadge = t.due_time ? `<span class="task-time-badge">${fmt12(t.due_time)}</span>` : '';
    const personHtml = t.person_name && t.person_id
        ? `<span class="task-person" onclick="event.stopPropagation(); goToContact('${t.person_id}')" style="cursor:pointer;text-decoration:underline;text-underline-offset:2px;" title="Open profile"><span style="width:5px;height:5px;border-radius:50%;background:var(--accent-cyan);display:inline-block;"></span>${esc(t.person_name)}</span>`
        : (t.person_name ? `<span class="task-person"><span style="width:5px;height:5px;border-radius:50%;background:var(--accent-cyan);display:inline-block;"></span>${esc(t.person_name)}</span>` : '');
    const dueHtml = rel.label && currentView !== 'day'
        ? `<span class="task-due ${rel.cls}">${rel.label}</span>` : '';
    const statusHtml = isInProgress ? '<span class="task-status-badge in-progress">In Progress</span>' : '';
    const checkMark = isDone ? `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>` : '';
    const progressAction = isDone
        ? ''
        : `<button class="tact status ${isInProgress ? 'active' : ''}" onclick="event.stopPropagation(); setTaskStatus('${t.task_id}', '${isInProgress ? 'open' : 'in_progress'}')" title="${isInProgress ? 'Move back to open' : 'Mark in progress'}">${isInProgress ? 'Open' : 'Doing'}</button>`;
    const segment = getSegment(t.due_time);
    const nextSegment = segment === 'morning' ? 'afternoon' : 'morning';
    const segmentAction = isDone
        ? ''
        : `<button class="tact segment ${segment}" onclick="event.stopPropagation(); setTaskSegment('${t.task_id}', '${nextSegment}')" title="Move to ${nextSegment}">${nextSegment === 'afternoon' ? 'Afternoon' : 'Morning'}</button>`;
    const linkedinHtml = t.linkedin_url
        ? `<div class="task-linkedin" onclick="event.stopPropagation(); window.open('${t.linkedin_url}', '_blank')" title="View LinkedIn">
                     <svg viewBox="0 0 24 24"><path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z"/></svg>
                   </div>` : '';

    return `<div class="task-card priority-${t.priority || 'medium'}${rel.cls === 'overdue' ? ' overdue' : ''}${isDone ? ' done' : ''}${isInProgress ? ' in-progress' : ''}"
                id="tc-${t.task_id}"
                onclick="handleTaskClick(event, '${t.task_id}', '${t.person_id || ''}', '${t.linkedin_url || ''}')">
    <div class="chk${isDone ? ' on' : ''}" onclick="event.stopPropagation(); toggleDone('${t.task_id}',${isDone})">${checkMark}</div>
    <div class="task-body">
      <div class="task-text">${esc(t.task_text)}</div>
      <div class="task-meta">${timeBadge}${statusHtml}${personHtml}${dueHtml}</div>
    </div>
    <div class="task-actions" style="display:flex; align-items:center; gap:0.5rem;">
      ${progressAction}
      ${segmentAction}
      ${linkedinHtml}
      <button class="tact del" onclick="event.stopPropagation(); deleteTask('${t.task_id}')" title="Delete">Del</button>
    </div>
  </div>`;
}

function goToContact(personId) {
    if (!personId) return;
    sessionStorage.setItem('agendaScrollPos', window.scrollY);
    updateStateURL();
    window.location.href = `/person/${personId}?from=agenda`;
}

function handleTaskClick(e, taskId, personId, linkedinUrl) {
    if (e.target.closest('.task-person') || e.target.closest('.task-actions') || e.target.closest('.chk')) return;
    if (!personId) return;
    goToContact(personId);
}

async function setTaskStatus(id, status) {
    try {
        await fetch(`/api/tasks/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status })
        });
        const t = allTasks.find(x => x.task_id === id);
        if (t) t.status = status;
        buildDotMap();
        renderCalendar();
        renderMini();
        renderTasks();
        const messages = {
            open: 'Task moved to open',
            in_progress: 'Task marked in progress',
            done: 'Done!'
        };
        toast(messages[status] || 'Task updated', 'success');
    } catch (e) {
        toast('Update failed', 'error');
    }
}

async function toggleDone(id, isDone) {
    await setTaskStatus(id, isDone ? 'open' : 'done');
}


async function setTaskSegment(id, segment) {
    const due_time = segment === 'afternoon' ? '13:00' : '09:00';
    try {
        await fetch(`/api/tasks/${id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ due_time })
        });
        const t = allTasks.find(x => x.task_id === id);
        if (t) t.due_time = due_time;
        renderMini();
        renderTasks();
        toast(`Task moved to ${segment}`, 'success');
    } catch (e) {
        toast('Move failed', 'error');
    }
}
async function deleteTask(id) {
    if (!confirm('Delete this task?')) return;
    try {
        await fetch(`/api/tasks/${id}`, { method: 'DELETE' });
        allTasks = allTasks.filter(t => t.task_id !== id);
        buildDotMap();
        renderCalendar();
        renderMini();
        renderTasks();
        toast('Task deleted', 'success');
    } catch (e) {
        toast('Delete failed', 'error');
    }
}

function openModal() {
    document.getElementById('f-date').value = toDateStr(selectedDate);
    document.getElementById('f-time').value = '';
    document.getElementById('f-text').value = '';
    document.getElementById('f-person-q').value = '';
    document.getElementById('f-person-id').value = '';
    document.getElementById('f-person-chip').style.display = 'none';
    document.getElementById('person-drop').style.display = 'none';
    // Reset segment buttons
    document.querySelectorAll('.seg-q-btn').forEach(b => b.className = 'seg-q-btn');
    setSegment('morning');
    setPri('medium');
    document.getElementById('modal').classList.add('open');
    setTimeout(() => document.getElementById('f-text').focus(), 350);
}
function closeModal() { document.getElementById('modal').classList.remove('open'); }
function overlayClose(e) { if (e.target.id === 'modal') closeModal(); }

function setSegment(s) {
    // Reset all buttons
    ['morning', 'afternoon'].forEach(x => {
        document.getElementById(`sq-${x}`).className = 'seg-q-btn';
    });
    document.getElementById(`sq-${s}`).classList.add(SEG[s].cls);
    if (SEG[s].defaultTime) {
        document.getElementById('f-time').value = SEG[s].defaultTime;
    } else {
        document.getElementById('f-time').value = '';
    }
}

function setPri(p) {
    selectedPrio = p;
    const styles = {
        high: ['rgba(255,59,48,0.15)', 'var(--accent-red)', 'rgba(255,59,48,0.3)'],
        medium: ['rgba(245,158,11,0.15)', 'var(--accent-orange)', 'rgba(245,158,11,0.3)'],
        low: ['rgba(16,185,129,0.15)', 'var(--accent-green)', 'rgba(16,185,129,0.3)']
    };
    ['high', 'medium', 'low'].forEach(x => {
        const btn = document.getElementById(`pb-${x}`);
        if (x === p) {
            const s = styles[x];
            btn.style.cssText = `background:${s[0]};color:${s[1]};border-color:${s[2]};`;
        } else {
            btn.style.cssText = '';
        }
    });
}

let psearchT;
async function personSearch(q) {
    clearTimeout(psearchT);
    const drop = document.getElementById('person-drop');
    if (!q.trim()) { drop.style.display = 'none'; return; }
    psearchT = setTimeout(async () => {
        const res = await fetch(`/api/people?q=${encodeURIComponent(q)}`);
        const data = await res.json();
        const people = data.people || [];
        if (!people.length) { drop.style.display = 'none'; return; }
        drop.innerHTML = people.map(p =>
            `<div class="pdrop-item" onclick="selPerson('${p.person_id}','${esc(p.full_name)}','${esc(p.company_name_raw || '')}')">
        <div class="pdrop-name">${esc(p.full_name)}</div>
        <div class="pdrop-sub">${esc(p.title_current || '')}${p.company_name_raw ? ` Â· ${esc(p.company_name_raw)}` : ''}</div>
      </div>`).join('');
        drop.style.display = 'block';
    }, 220);
}
function selPerson(id, name, company) {
    document.getElementById('f-person-id').value = id;
    document.getElementById('f-person-q').value = name;
    document.getElementById('person-drop').style.display = 'none';
    const chip = document.getElementById('f-person-chip');
    chip.textContent = `âœ“ ${name}${company ? ` Â· ${company}` : ''}`;
    chip.style.display = 'block';
}

async function saveTask() {
    const text = document.getElementById('f-text').value.trim();
    if (!text) { document.getElementById('f-text').focus(); return; }
    const personId = document.getElementById('f-person-id').value || null;
    const dueDate = document.getElementById('f-date').value || null;
    const dueTime = document.getElementById('f-time').value || '09:00';
    try {
        const r = await fetch('/api/tasks', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ task_text: text, person_id: personId, due_date: dueDate, due_time: dueTime, priority: selectedPrio })
        });
        if (!r.ok) throw new Error();
        closeModal();
        await loadTasks();
        toast('Task created', 'success');
    } catch (e) { toast('Save failed', 'error'); }
}

// â”€â”€ UTILS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
function esc(s) { return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function toast(msg, type = '') {
    const t = document.getElementById('toast');
    t.textContent = msg; t.className = `toast show ${type}`;
    setTimeout(() => t.className = 'toast', 3000);
}

// â”€â”€ INIT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
restoreStateFromURL();
restoreAgendaSearchFromQuery();
document.getElementById('f-date').value = today;
document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
document.getElementById(`vb-${currentView}`).classList.add('active');
document.querySelectorAll('.fpill').forEach(p => p.classList.remove('active'));
document.getElementById(`fp-${currentFilter}`).classList.add('active');
syncAgendaSearchUI();

loadTasks();









