// Interaction log, uploads, and direct quick-capture workflow
let selectedLogFiles = [];
let logMediaRecorder = null;
let logAudioChunks = [];
let logAudioStream = null;

function initQuickCaptureInput() {
    const input = document.getElementById('interaction-input');
    if (!input || input.dataset.boundQuickCapture === 'true') return;

    input.dataset.boundQuickCapture = 'true';

    const stopShortcutHijack = (event) => {
        event.stopPropagation();
    };

    input.addEventListener('keydown', stopShortcutHijack);
    input.addEventListener('keyup', stopShortcutHijack);
    input.addEventListener('keypress', stopShortcutHijack);
    input.addEventListener('paste', (event) => {
        stopShortcutHijack(event);
        handleQuickCapturePaste(event);
    });
}

function addLogFiles(files) {
    let added = 0;
    for (const file of files || []) {
        if (!file) continue;
        selectedLogFiles.push(file);
        added += 1;
    }
    if (added > 0) {
        renderSelectedLogFiles();
    }
    return added;
}

function dataUrlToFile(dataUrl, fallbackName = `quick-capture-paste-${Date.now()}.png`) {
    const match = String(dataUrl || '').match(/^data:(.+?);base64,(.+)$/);
    if (!match) return null;
    const mimeType = match[1] || 'application/octet-stream';
    const binary = atob(match[2]);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
    }
    const ext = mimeType === 'image/png' ? 'png' : (mimeType.split('/')[1] || 'bin');
    const fileName = fallbackName.includes('.') ? fallbackName : `${fallbackName}.${ext}`;
    return new File([bytes], fileName, { type: mimeType });
}

async function extractClipboardImageFiles(clipboard) {
    const files = [];
    const timestamp = Date.now();
    const seen = new Set();

    const pushUniqueFile = (file) => {
        if (!file) return;
        const signature = [file.name || '', file.type || '', file.size || 0, file.lastModified || 0].join('|');
        if (seen.has(signature)) return;
        seen.add(signature);
        files.push(file);
    };

    for (const file of Array.from(clipboard.files || [])) {
        pushUniqueFile(file);
    }

    for (const item of Array.from(clipboard.items || [])) {
        if (item.kind === 'file') {
            const blob = item.getAsFile();
            if (!blob) continue;
            const ext = blob.type === 'image/png' ? 'png' : (blob.type.split('/')[1] || 'bin');
            const fileName = blob.name || `quick-capture-paste-${timestamp}.${ext}`;
            pushUniqueFile(new File([blob], fileName, { type: blob.type || 'application/octet-stream' }));
            continue;
        }

        if (item.kind === 'string' && item.type === 'text/html') {
            const html = await new Promise((resolve) => item.getAsString(resolve));
            const match = String(html || '').match(/src=["'](data:image\/[^"']+)["']/i);
            if (!match) continue;
            const file = dataUrlToFile(match[1], `quick-capture-paste-${timestamp}.png`);
            pushUniqueFile(file);
        }
    }

    return files;
}

async function handleQuickCapturePaste(event) {
    const clipboard = event.clipboardData;
    const status = document.getElementById('log-status');
    if (!clipboard) return;

    const files = await extractClipboardImageFiles(clipboard);

    if (!files.length) return;

    event.preventDefault();
    const added = addLogFiles(files);
    if (status && added) {
        status.textContent = `${added === 1 ? 'Screenshot attached from clipboard.' : `${added} files attached from clipboard.`} Capture And Process when ready.`;
        status.style.color = 'var(--accent-cyan)';
    }
}

function renderInteractions(interactions) {
    const noisePhrases = new Set([
        'ping',
        'yes, log this.',
        'yes, log this',
        'yes, log this as intelligence.',
        'yes, log this as intelligence',
        'log this as intelligence.',
        'log this as intelligence',
        'no changes needed for now.',
        'no changes needed for now',
    ]);
    const visibleInteractions = (interactions || []).filter((interaction) => {
        const text = String(interaction?.raw_text || interaction?.summary || '').trim().toLowerCase();
        if (!text) return true;
        return !noisePhrases.has(text);
    });

    const html = visibleInteractions.slice(0, 20).map(interaction => {
        const meta = channelMetaForItem(interaction);
        const happenedAt = interaction.interaction_at || interaction.created_at;
        return `
        <div class="timeline-item">
            <div class="timeline-icon timeline-icon-${meta.tone}" title="${meta.label}" aria-label="${meta.label}">
                <i class="${meta.icon}"></i>
            </div>
            <div class="timeline-content" id="interaction-${interaction.interaction_id}">
                <div class="timeline-meta">
                    <div class="timeline-date">${formatDateTime(happenedAt)}</div>
                    <div class="timeline-channel-chip timeline-channel-chip-${meta.tone}" title="${meta.label}">
                        <i class="${meta.icon}"></i>
                        <span>${meta.label}</span>
                    </div>
                </div>
                <div class="timeline-text" id="text-${interaction.interaction_id}">${interaction.summary || interaction.raw_text || 'No details'}</div>
                <div style="margin-top:0.5rem; display:flex; gap:0.5rem;">
                    <button onclick="editInteraction('${interaction.interaction_id}')" style="font-size:0.75rem; padding:2px 8px; background:rgba(255,255,255,0.1); border:none; border-radius:4px; color:var(--text-primary); cursor:pointer;">Edit</button>
                    <button onclick="deleteInteraction('${interaction.interaction_id}')" style="font-size:0.75rem; padding:2px 8px; background:rgba(255,0,0,0.1); border:none; border-radius:4px; color:var(--accent-red); cursor:pointer;">Delete</button>
                </div>
            </div>
        </div>
    `;
    }).join('');

    document.getElementById('interactions-timeline').innerHTML = html || '<p style="color: var(--text-secondary);">No interactions recorded</p>';
}

function scrollToBriefing() {
    document.getElementById('briefing-section').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderSelectedLogFiles() {
    const container = document.getElementById('selected-files-container');
    if (!container) return;

    container.innerHTML = '';
    selectedLogFiles.forEach((file, index) => {
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
            <i class="fas fa-times" style="cursor:pointer; opacity:0.6;" onclick="removeLogFile(this, ${index})"></i>
        `;
        container.appendChild(chip);
    });
}

function handleLogFileSelect(input) {
    if (!input.files || input.files.length === 0) return;

    addLogFiles(input.files);
    input.value = '';
}

function removeLogFile(el, index) {
    selectedLogFiles.splice(index, 1);
    renderSelectedLogFiles();
}

async function toggleLogAudioRecording() {
    const micBtn = document.getElementById('log-mic-btn');
    const status = document.getElementById('log-status');
    const micSupport = window.microphoneSupportStatus ? window.microphoneSupportStatus() : { supported: true };

    if (!micSupport.supported) {
        if (status) {
            status.textContent = micSupport.reason || 'Microphone recording is unavailable on this device/browser.';
            status.style.color = 'var(--accent-red)';
        }
        return;
    }

    if (logMediaRecorder && logMediaRecorder.state === 'recording') {
        logMediaRecorder.stop();
        return;
    }

    try {
        logAudioChunks = [];
        logAudioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const preferredMimeType = typeof window.preferredAudioRecorderMimeType === 'function'
            ? window.preferredAudioRecorderMimeType()
            : (MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '');
        const options = preferredMimeType ? { mimeType: preferredMimeType } : {};

        logMediaRecorder = new MediaRecorder(logAudioStream, options);
        logMediaRecorder.ondataavailable = (event) => {
            if (event.data && event.data.size > 0) {
                logAudioChunks.push(event.data);
            }
        };

        logMediaRecorder.onstop = async () => {
            const recordedMimeType = (logMediaRecorder && logMediaRecorder.mimeType) || preferredMimeType || 'audio/webm';
            const blob = new Blob(logAudioChunks, { type: recordedMimeType });
            logAudioStream?.getTracks()?.forEach(track => track.stop());
            logAudioStream = null;
            if (micBtn) {
                micBtn.innerHTML = '<i class="fas fa-microphone"></i>';
                micBtn.style.background = 'rgba(53,232,255,0.08)';
                micBtn.style.color = 'var(--accent-cyan)';
            }
            const extension = typeof window.audioExtensionFromMimeType === 'function'
                ? window.audioExtensionFromMimeType(recordedMimeType)
                : 'webm';
            const file = new File([blob], `quick-capture-${Date.now()}.${extension}`, { type: blob.type || recordedMimeType || 'audio/webm' });
            addLogFiles([file]);
            if (status) {
                status.textContent = 'Voice note attached. Capture And Process when ready.';
                status.style.color = 'var(--accent-cyan)';
            }
        };

        logMediaRecorder.start(200);
        if (micBtn) {
            micBtn.innerHTML = '<i class="fas fa-stop"></i>';
            micBtn.style.background = 'rgba(239,68,68,0.14)';
            micBtn.style.color = '#fca5a5';
        }
        if (status) {
            status.textContent = 'Recording voice note... click again to stop.';
            status.style.color = 'var(--accent-cyan)';
        }
    } catch (err) {
        console.error('Log audio capture failed:', err);
        if (status) {
            status.textContent = 'Microphone access failed.';
            status.style.color = 'var(--accent-red)';
        }
    }
}

async function submitInteraction() {
    const input = document.getElementById('interaction-input');
    const status = document.getElementById('log-status');
    const btn = document.getElementById('btn-submit-interaction');

    if (!input) return;
    const text = input.value.trim();

    if (!text && selectedLogFiles.length === 0) {
        input.focus();
        return;
    }

    btn.disabled = true;
    const originalBtnHtml = btn.innerHTML;
    btn.innerHTML = 'Processing... <i class="fas fa-spinner fa-spin"></i>';
    if (status) {
        status.textContent = 'AI processing is running in the background...';
        status.style.color = 'var(--text-muted)';
    }

    try {
        const queuedJobs = [];
        let latestInteractionId = null;

        for (const file of selectedLogFiles) {
            const formData = new FormData();
            formData.append('file', file);

            const fileRes = await fetch(`${API_BASE}/api/interactions/upload/${personId}`, {
                method: 'POST',
                body: formData
            });
            if (!fileRes.ok) {
                const errorData = await fileRes.json().catch(() => ({}));
                throw new Error(errorData.detail || errorData.message || `Failed to upload ${file.name}`);
                continue;
            }
            const fileData = await fileRes.json();
            if (fileData.job) queuedJobs.push(fileData.job);
            if (fileData.interaction_id) {
                latestInteractionId = fileData.interaction_id;
                await logAiFeedback('interaction', 'manual_add', {
                    interaction_id: fileData.interaction_id,
                    source: 'quick_capture_file',
                    filename: file.name
                });
            }
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
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || data.message || 'Failed to save interaction text');
            if (data.job) queuedJobs.push(data.job);
            if (data.interaction_id) {
                latestInteractionId = data.interaction_id;
                await logAiFeedback('interaction', 'manual_add', {
                    interaction_id: data.interaction_id,
                    text,
                    source: 'quick_capture_text'
                });
            }
        }

        input.value = '';
        selectedLogFiles = [];
        renderSelectedLogFiles();

        if (status) {
            status.textContent = queuedJobs.length
                ? `Queued ${queuedJobs.length} AI job(s). Quick Capture is linked to assistant learning.`
                : 'Quick Capture saved. AI processing is currently unavailable.';
            status.style.color = 'var(--accent-cyan)';
        }

        await loadPersonQuiet();
        await loadAiJobs();
        if (typeof startAiJobPolling === 'function' && queuedJobs.length) {
            startAiJobPolling();
        }
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
            await logAiFeedback('interaction', 'edit', {
                interaction_id: id,
                new: newText,
                source: 'quick_capture_edit'
            });
            await loadPersonQuiet();
            toast('Interaction updated', 'success');
        } else {
            toast('Failed to update interaction', 'error');
        }
    } catch (err) {
        console.error(err);
        toast('Error updating interaction', 'error');
    }
}

async function deleteInteraction(id) {
    const confirmed = await showConfirmDialog({
        title: 'Delete interaction?',
        message: 'This removes the interaction and its downstream context from the profile trail.',
        confirmLabel: 'Delete Interaction',
    });
    if (!confirmed) return;
    try {
        const res = await fetch(`${API_BASE}/api/interactions/${id}`, {
            method: 'DELETE'
        });
        if (res.ok) {
            await loadPersonQuiet();
            await loadAiJobs();
            toast('Interaction deleted', 'success');
        } else {
            toast('Failed to delete interaction', 'error');
        }
    } catch (err) {
        console.error(err);
        toast('Error deleting interaction', 'error');
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
                if (result.interaction_id) {
                    await logAiFeedback('interaction', 'manual_add', {
                        interaction_id: result.interaction_id,
                        source: 'profile_drag_drop',
                        filename: file.name
                    });
                }
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
