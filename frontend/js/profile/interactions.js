// Interaction log, uploads, and editing workflow
let selectedLogFiles = [];

function renderInteractions(interactions) {
    const html = interactions.slice(0, 5).map(interaction => `
        <div class="timeline-item">
            <div class="timeline-icon">...</div>
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

function scrollToBriefing() {
    document.getElementById('briefing-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

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
    input.value = '';
}

function removeLogFile(el, index) {
    selectedLogFiles.splice(index, 1);
    el.parentElement.remove();
}

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
    if (status) status.textContent = 'AI processing is running in the background...';

    try {
        const queuedJobs = [];

        for (const file of selectedLogFiles) {
            const formData = new FormData();
            formData.append('file', file);

            const fileRes = await fetch(`${API_BASE}/api/interactions/upload/${personId}`, {
                method: 'POST',
                body: formData
            });
            if (!fileRes.ok) {
                console.warn(`Failed to upload ${file.name}`);
                continue;
            }
            const fileData = await fileRes.json();
            if (fileData.job) queuedJobs.push(fileData.job);
        }

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
            const data = await res.json();
            if (data.job) queuedJobs.push(data.job);
        }

        input.value = '';
        selectedLogFiles = [];
        if (fileContainer) fileContainer.innerHTML = '';

        if (status) {
            status.textContent = queuedJobs.length ? `Queued ${queuedJobs.length} AI job(s). You can keep working while processing runs.` : 'Interaction saved.';
            status.style.color = 'var(--accent-cyan)';
        }

        await loadPersonQuiet();
        await loadAiJobs();
        setTimeout(() => { if (status) status.textContent = ''; }, 5000);
    } catch (err) {
        console.error(err);
        if (status) {
            status.textContent = 'Error logging intelligence.';
            status.style.color = 'var(--accent-red)';
        }
    } finally {
        btn.disabled = false;
        btn.innerHTML = originalBtnHtml;
    }
}

function editInteraction(id) {
    const textDiv = document.getElementById(`text-${id}`);
    const currentText = textDiv.innerText;
    textDiv.innerHTML = `
        <textarea id="edit-${id}" style="width:100%; height:60px; background:rgba(0,0,0,0.2); border:1px solid var(--glass-border); color:var(--text-primary); padding:0.5rem; border-radius:4px;">${currentText}</textarea>
        <div style="margin-top:0.5rem;">
            <button onclick="saveInteraction('${id}')" class="action-btn primary" style="font-size:0.8rem; padding:4px 8px;">Save</button>
            <button onclick="loadPersonQuiet()" class="action-btn" style="font-size:0.8rem; padding:4px 8px;">Cancel</button>
        </div>
    `;
}

async function saveInteraction(id) {
    const newText = document.getElementById(`edit-${id}`).value;
    try {
        const res = await fetch(`${API_BASE}/api/interactions/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ raw_text: newText })
        });
        if (res.ok) {
            await loadPersonQuiet();
        } else {
            alert('Failed to update interaction');
        }
    } catch (err) {
        console.error(err);
        alert('Error updating interaction');
    }
}

async function deleteInteraction(id) {
    if (!confirm('Are you sure you want to delete this interaction?')) return;
    try {
        const res = await fetch(`${API_BASE}/api/interactions/${id}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            await loadPersonQuiet();
            await loadAiJobs();
        } else {
            alert('Failed to delete interaction');
        }
    } catch (err) {
        console.error(err);
        alert('Error deleting interaction');
    }
}

function initDragDrop() {
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
            if (card) card.style.outline = '';
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
    const queuedJobs = [];
    for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await fetch(`${API_BASE}/api/interactions/upload/${personId}`, {
                method: 'POST',
                body: formData
            });
            if (res.ok) {
                const result = await res.json();
                if (result.job) queuedJobs.push(result.job);
            }
        } catch (e) {
            console.error('Upload failed:', e);
        }
    }

    await loadPersonQuiet();
    if (queuedJobs.length) {
        startAiJobPolling();
        await loadAiJobs();
    }
}
