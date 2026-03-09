const API = typeof API_BASE !== 'undefined' ? API_BASE : '';
        let allItems = [];

        // ===== BOOT =====
        async function boot() {
            const res = await fetch(`${API}/api/taxonomy/all`);
            allItems = await res.json();
            renderAll();
            updateStats();
        }

        function updateStats() {
            const active = allItems.filter(i => i.is_active);
            const cat = active.filter(i => i.category_type === 'cat').length;
            const env = active.filter(i => i.category_type === 'env').length;
            const disc = active.filter(i => i.category_type === 'disc').length;
            document.getElementById('stat-cat').textContent = cat;
            document.getElementById('stat-env').textContent = env;
            document.getElementById('stat-disc').textContent = disc;
            document.getElementById('stat-total').textContent = cat + env + disc;
        }

        // ===== RENDER =====
        const SECTION_DEFS = [
            {
                type: 'cat',
                icon: '🏷️',
                iconBg: 'rgba(99,102,241,0.15)',
                title: 'Contact Categories',
                desc: 'Pipeline classification for each contact (e.g. OBE Member, Target Client)',
                containerId: 'section-cat'
            },
            {
                type: 'env',
                icon: '🏢',
                iconBg: 'rgba(34,211,238,0.12)',
                title: 'Environments',
                desc: 'Organisation type (e.g. Developer - Gov, Main Contractor)',
                containerId: 'section-env'
            },
            {
                type: 'disc',
                icon: '🔧',
                iconBg: 'rgba(52,211,153,0.12)',
                title: 'Disciplines',
                desc: 'Professional specialism (e.g. Commercial, Design, Delivery)',
                containerId: 'section-disc'
            }
        ];

        function renderAll() {
            SECTION_DEFS.forEach(def => {
                const items = allItems.filter(i => i.category_type === def.type);
                document.getElementById(def.containerId).innerHTML = renderSection(def, items);
            });
            attachEvents();
        }

        function renderSection(def, items) {
            const activeCount = items.filter(i => i.is_active).length;
            return `
  <div class="section" id="sec-${def.type}">
    <div class="section-header">
      <div class="section-title">
        <div class="section-icon" style="background:${def.iconBg}">${def.icon}</div>
        <div>
          <h2>${def.title} <span class="count-badge">${activeCount} active</span></h2>
          <p>${def.desc}</p>
        </div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="toggleAddForm('${def.type}')">+ Add New</button>
    </div>

    <div class="col-header">
      <span>Color</span>
      <span>Label</span>
      <span>Short Code</span>
      <span>Active</span>
      <span></span>
      <span></span>
    </div>

    <div class="tax-table" id="list-${def.type}">
      ${items.map(item => renderRow(item)).join('')}
    </div>

    <!-- ADD FORM -->
    <div class="add-form" id="add-form-${def.type}">
      <div class="color-dot new-color" id="new-color-${def.type}" style="background:#63b3ed;">
        <input type="color" value="#63b3ed" onchange="updateNewColor('${def.type}', this.value)">
      </div>
      <input class="editable" id="new-label-${def.type}" placeholder="e.g. Strategic Partner" />
      <input class="editable value-field" id="new-value-${def.type}" placeholder="e.g. STP" />
      <div></div>
      <button class="btn btn-primary btn-sm" onclick="addItem('${def.type}')">Save</button>
      <button class="btn btn-ghost btn-sm" onclick="toggleAddForm('${def.type}')">Cancel</button>
    </div>
  </div>`;
        }

        function renderRow(item) {
            return `
  <div class="tax-row ${item.is_active ? '' : 'inactive'}" id="row-${item.config_id}" data-id="${item.config_id}">
    <div class="color-dot" style="background:${item.color || '#666'};" title="Click to change color">
      <input type="color" value="${item.color || '#666666'}"
        onchange="updateColor('${item.config_id}', this.value, this.parentElement)">
    </div>

    <input class="editable" value="${escHtml(item.label)}"
      onblur="saveField('${item.config_id}', 'label', this.value)"
      onkeydown="if(event.key==='Enter')this.blur()"
      title="Click to edit label" />

    <input class="editable value-field" value="${escHtml(item.value)}"
      onblur="saveField('${item.config_id}', 'value', this.value)"
      onkeydown="if(event.key==='Enter')this.blur()"
      title="Click to edit short code" />

    <div class="col-toggle">
      <label class="toggle" title="${item.is_active ? 'Active — click to deactivate' : 'Inactive — click to activate'}">
        <input type="checkbox" ${item.is_active ? 'checked' : ''}
          onchange="toggleActive('${item.config_id}', this.checked)">
        <div class="toggle-track"></div>
        <div class="toggle-thumb"></div>
      </label>
    </div>

    <div></div>

    <div class="row-actions">
      ${item.is_active
                    ? `<button class="btn btn-danger btn-sm" onclick="deleteItem('${item.config_id}')">Remove</button>`
                    : `<button class="btn btn-success btn-sm" onclick="restoreItem('${item.config_id}')">Restore</button>`
                }
    </div>
  </div>`;
        }

        // ===== EVENTS =====
        function attachEvents() {
            // nothing extra needed — events are inline
        }

        function toggleAddForm(type) {
            const form = document.getElementById(`add-form-${type}`);
            form.classList.toggle('visible');
            if (form.classList.contains('visible')) {
                document.getElementById(`new-label-${type}`).focus();
            }
        }

        function updateNewColor(type, hex) {
            document.getElementById(`new-color-${type}`).style.background = hex;
        }

        function updateColor(id, hex, dot) {
            dot.style.background = hex;
            saveField(id, 'color', hex);
        }

        // ===== API ACTIONS =====
        async function saveField(id, field, value) {
            const item = allItems.find(i => i.config_id === id);
            if (item && item[field] === value) return; // no change
            const body = {};
            body[field] = value;
            try {
                const res = await fetch(`${API}/api/taxonomy/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (!res.ok) throw new Error('Save failed');
                if (item) item[field] = value;
                toast('✓ Saved', 'success');
                updateStats();
            } catch (e) {
                toast('Save failed: ' + e.message, 'error');
            }
        }

        async function toggleActive(id, active) {
            try {
                await fetch(`${API}/api/taxonomy/${id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ is_active: active ? 1 : 0 })
                });
                const item = allItems.find(i => i.config_id === id);
                if (item) item.is_active = active ? 1 : 0;
                // re-render row
                const row = document.getElementById(`row-${id}`);
                if (row) row.outerHTML = renderRow(item);
                updateStats();
                toast(active ? '✓ Activated' : '✓ Deactivated', 'success');
            } catch (e) {
                toast('Error: ' + e.message, 'error');
            }
        }

        async function deleteItem(id) {
            if (!confirm('Deactivate this taxonomy entry? It will be hidden from dropdowns but preserved in historical data.')) return;
            await toggleActive(id, false);
        }

        async function restoreItem(id) {
            await toggleActive(id, true);
        }

        async function addItem(type) {
            const label = document.getElementById(`new-label-${type}`).value.trim();
            const value = document.getElementById(`new-value-${type}`).value.trim();
            const colorEl = document.getElementById(`new-color-${type}`);
            const color = colorEl.querySelector('input[type=color]').value;

            if (!label) { toast('Label is required', 'error'); return; }
            if (!value) { toast('Short code is required', 'error'); return; }

            try {
                const res = await fetch(`${API}/api/taxonomy`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category_type: type, label, value, color, is_active: 1 })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || 'Add failed');

                // Add to local state
                allItems.push({ config_id: data.config_id, category_type: type, label, value, color, is_active: 1 });

                // Refresh section
                const def = SECTION_DEFS.find(d => d.type === type);
                const items = allItems.filter(i => i.category_type === type);
                document.getElementById(`section-${type}`).innerHTML = renderSection(def, items);

                updateStats();
                toast('✓ Added: ' + label, 'success');
            } catch (e) {
                toast('Error: ' + e.message, 'error');
            }
        }

        // ===== UTILITIES =====
        function escHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        }

        let toastTimer;
        function toast(msg, type = 'success') {
            const el = document.getElementById('toast');
            el.textContent = msg;
            el.className = `show ${type}`;
            clearTimeout(toastTimer);
            toastTimer = setTimeout(() => { el.className = ''; }, 2800);
        }

        // ===== BOOT =====
        boot();