// Profile signals, personal intelligence, and employment timeline

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

// hook up review button after page load
window.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('review-signals-btn');
    if (btn) btn.addEventListener('click', reviewSignals);
});

async function reviewSignals() {
    try {
        const res = await fetch(`${API_BASE}/api/intelligence/assistant/${personId}/review`, { method: 'POST' });
        if (!res.ok) throw new Error('Review failed');
        const data = await res.json();
        showReviewModal(data);
    } catch (e) {
        alert('Error reviewing signals: ' + e.message);
        console.error(e);
    }
}

function showReviewModal(data) {
    const existing = document.getElementById('signal-review-modal');
    if (existing) existing.remove();
    const modal = document.createElement('div');
    modal.id = 'signal-review-modal';
    modal.style = `position:fixed; top:50%; left:50%; transform:translate(-50%,-50%);
                background:rgba(15,23,42,0.97); border:1px solid rgba(255,255,255,0.15);
                backdrop-filter:none; border-radius:16px; padding:1.5rem;
                z-index:9999; max-width:90%; max-height:90vh; overflow-y:auto; box-shadow:0 24px 80px rgba(0,0,0,0.6);`;
    const signalsHtml = (data.signals || []).map(s => `
        <div class="review-signal" data-id="${s.intel_id}">
            <div><b>Category:</b> ${s.category}</div>
            <div><b>Text:</b> ${s.text}</div>
            <div><b>Snippet:</b> ${s.snippet || ''}</div>
            <div style="margin-top:4px;"><button onclick="approveSignal('${s.intel_id}')">Approve</button> <button onclick="rejectSignal('${s.intel_id}')">Reject</button> <button onclick="editSignal('${s.intel_id}')">Edit</button> <button onclick="promoteSignal('${s.intel_id}')">Promote</button> <button onclick="demoteSignal('${s.intel_id}')">Demote</button></div>
        </div>`).join('');
    const briefHtml = `<pre style="white-space:pre-wrap;">${JSON.stringify(data.brief,null,2)}</pre>`;
    modal.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; font-weight:800; font-size:1rem; color:var(--accent-cyan); margin-bottom:1rem;">
            <span>Signal Review</span>
            <button onclick="addSignal()" style="font-size:0.8rem; padding:4px 8px; background:var(--accent-amber); color:#0a0a1a; border:none; border-radius:6px; cursor:pointer;">+ Add Signal</button>
        </div>
        <div>${signalsHtml || '<em>No signals found.</em>'}</div>
        <hr style="margin:1rem 0;">
        <div style="font-weight:600; color:#f472b6; margin-bottom:0.5rem;">Brief Preview</div>
        ${briefHtml}
        <div style="text-align:right; margin-top:1rem;"><button onclick="document.getElementById('signal-review-modal').remove()" style="padding:6px 12px;">Close</button></div>
    `;
    document.body.appendChild(modal);
}

// simple feedback helpers
async function sendFeedback(eventType, intelId, details) {
    try {
        const response = await fetch(`${API_BASE}/api/ai/feedback`, {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                target_type:'signal',
                target_id:intelId,
                event_type:eventType,
                details:{
                    source:'signal_review_modal',
                    ...details
                },
                user_id:window.currentUserId || null
            })
        });
        if (response.ok) {
            await fetchintelligence();
        }
    } catch (e) { console.error(e); }
}

function approveSignal(id) { sendFeedback('approve', id); }
function rejectSignal(id) { sendFeedback('reject', id); }
function promoteSignal(id) { sendFeedback('promote', id); }
function demoteSignal(id) { sendFeedback('demote', id); }
function editSignal(id) {
    const el = document.querySelector(`.review-signal[data-id="${id}"] > div:nth-child(2)`);
    if (!el) return;
    const old = el.textContent.replace(/^Text:\s*/, '');
    const newText = prompt('Edit signal text:', old);
    if (newText && newText !== old) {
        fetch(`${API_BASE}/api/people/${personId}/intelligence/${id}`, {
            method: 'PATCH', headers:{'Content-Type':'application/json'}, body: JSON.stringify({text:newText})
        });
        sendFeedback('edit', id, {old: old, new: newText});
        fetchintelligence();
        el.textContent = 'Text: ' + newText;
    }
}

function addSignal() {
    const cat = prompt('Category (business_focus, recruitment_talent, family_personal, obe_focus):');
    if (!cat) return;
    const text = prompt('Signal text:');
    if (!text) return;
    fetch(`${API_BASE}/api/ai/signals`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({person_id: personId, category: cat, content: text, source_snippet: text, confidence: 3, manual: true})
    })
    .then(r=>r.json())
    .then(json => {
        reviewSignals();
        fetchintelligence();
    });
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
            `${k.name}${k.age ? ` (${k.age})` : ''}${k.school ? `, ${k.school}` : ''}${k.interests?.length ? ` � loves ${k.interests.join(', ')}` : ''}`
        ).join('<br>');
        rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">???????? Kids</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${kidsHtml}</div></div>`);
    }
    if (pd.hobbies?.length) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? Hobbies</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.hobbies.join(', ')}</div></div>`);
    if (pd.sports_teams?.length) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">? Supports</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.sports_teams.join(', ')}</div></div>`);
    if (pd.university) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? University</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.university}</div></div>`);
    if (pd.hometown) rows.push(`<div><span style="color:#f472b6; font-size:0.7rem;">?? From</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.hometown}</div></div>`);
    if (pd.personality) rows.push(`<div style="grid-column:span 2;"><span style="color:#f472b6; font-size:0.7rem;">?? Personality</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px; font-style:italic;">${pd.personality}</div></div>`);
    if (pd.upcoming_events?.length) rows.push(`<div style="grid-column:span 2;"><span style="color:#f472b6; font-size:0.7rem;">?? Upcoming</span><div style="color:var(--text-secondary); font-size:0.85rem; margin-top:2px;">${pd.upcoming_events.join(' � ')}</div></div>`);
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
            const dateStr = start ? `${start}${end ? ' � ' + end : ' � now'}` : '�';
            const loc = role.location || '';
            const rowBg = isCurrent ? 'rgba(53,232,255,0.04)' : (idx % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)');
            return `
                        <div style="display:contents;" class="career-row" id="career-row-${idx}">
                            <div style="padding:7px 10px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); color:${isCurrent ? 'var(--accent-cyan)' : 'white'}; font-size:0.8rem; font-weight:${isCurrent ? '700' : '500'}; line-height:1.3;">${role.title || '�'}${loc ? `<div style="font-size:0.7rem; color:var(--text-muted); font-weight:400; margin-top:1px;">?? ${loc}</div>` : ''}</div>
                            <div style="padding:7px 10px; background:${rowBg}; border-bottom:1px solid rgba(255,255,255,0.04); color:var(--text-secondary); font-size:0.8rem; line-height:1.3;">${role.company || '�'}</div>
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
        timelineEl.innerHTML = `<p style="color:var(--text-muted); font-size:0.85rem;">No career history yet � click + Add Role.</p>`;
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

