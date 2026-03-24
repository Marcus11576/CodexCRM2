let companyState = {
    companies: [],
    activeKey: '',
    search: '',
    loadingList: false,
    loadingDetail: false,
};

function escCompany(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function companyKeyFromPath() {
    const match = window.location.pathname.match(/^\/companies\/(.+)$/i);
    if (!match) return '';
    return window.normalizeCompanyKey(decodeURIComponent(match[1] || ''));
}

function scoreLabel(score) {
    const numeric = Number(score);
    if (!Number.isFinite(numeric)) return '--';
    return `${Math.max(0, Math.min(100, Math.round(numeric)))}%`;
}

function setCompanyPath(companyKey, companyName = '') {
    const key = window.normalizeCompanyKey(companyKey);
    if (!key) {
        window.history.pushState({}, '', '/companies');
        return;
    }
    const params = new URLSearchParams();
    if (companyName) params.set('name', companyName);
    const suffix = params.toString() ? `?${params.toString()}` : '';
    window.history.pushState({}, '', `/companies/${encodeURIComponent(key)}${suffix}`);
}

function renderCompanyList() {
    const target = document.getElementById('company-list');
    const empty = document.getElementById('company-list-empty');
    if (!target || !empty) return;

    if (!companyState.companies.length) {
        target.innerHTML = '';
        empty.style.display = '';
        return;
    }

    empty.style.display = 'none';
    target.innerHTML = companyState.companies.map((company) => {
        const active = company.company_key === companyState.activeKey;
        const companyType = String(company.company_type || '').trim() || 'Type not set';
        const parentName = String(company.parent_company_name || '').trim();
        const parentMeta = parentName ? ` | Parent: ${parentName}` : '';
        const keyArg = encodeURIComponent(String(company.company_key || ''));
        const nameArg = encodeURIComponent(String(company.company_name || ''));
        return `
            <button type="button" class="company-card ${active ? 'is-active' : ''}" onclick="openCompanyFromList(decodeURIComponent('${keyArg}'), decodeURIComponent('${nameArg}'))">
                <div class="company-name">${escCompany(company.company_name || 'Unknown company')}</div>
                <div class="company-meta">${escCompany(companyType)}${escCompany(parentMeta)}</div>
                <div class="company-meta">${escCompany(company.employee_count || 0)} employees | Highest score ${escCompany(scoreLabel(company.highest_employee_score))}</div>
            </button>
        `;
    }).join('');
}

async function loadCompanyList() {
    const query = companyState.search ? `?q=${encodeURIComponent(companyState.search)}&limit=120` : '?limit=120';
    companyState.loadingList = true;
    try {
        const res = await fetch(`${API_BASE}/api/companies${query}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || `Company list failed (${res.status})`);
        companyState.companies = Array.isArray(data.companies) ? data.companies : [];
        renderCompanyList();

        const currentPathKey = companyKeyFromPath();
        if (currentPathKey) {
            companyState.activeKey = currentPathKey;
            renderCompanyList();
            await loadCompanyDetail(currentPathKey);
            return;
        }

        if (!companyState.activeKey && companyState.companies.length) {
            const first = companyState.companies[0];
            companyState.activeKey = first.company_key;
            setCompanyPath(first.company_key, first.company_name || '');
            renderCompanyList();
            await loadCompanyDetail(first.company_key);
            return;
        }

        if (companyState.activeKey) {
            await loadCompanyDetail(companyState.activeKey);
        }
    } catch (error) {
        console.error(error);
        const target = document.getElementById('company-list');
        if (target) {
            target.innerHTML = `<div class="companies-empty">${escCompany(error.message || 'Unable to load companies right now.')}</div>`;
        }
    } finally {
        companyState.loadingList = false;
    }
}

function renderCompanyDetail(company) {
    const target = document.getElementById('company-detail');
    if (!target) return;

    if (!company) {
        target.innerHTML = '<div class="companies-empty">Select a company to view details.</div>';
        return;
    }

    const companyType = String(company.company_type || '').trim() || 'Type not set';
    const parentKeyArg = encodeURIComponent(String(company.parent_company_key || ''));
    const parentNameArg = encodeURIComponent(String(company.parent_company_name || ''));
    const parentLink = company.parent_company_key
        ? `<a class="company-link" href="/companies/${encodeURIComponent(company.parent_company_key)}" onclick="event.preventDefault(); openCompanyFromList(decodeURIComponent('${parentKeyArg}'), decodeURIComponent('${parentNameArg}'))">${escCompany(company.parent_company_name || company.parent_company_key)}</a>`
        : '<span class="companies-empty">No parent company linked</span>';
    const aliases = Array.isArray(company.aliases) && company.aliases.length
        ? company.aliases.map((alias) => `<span class="company-score-pill">${escCompany(alias)}</span>`).join(' ')
        : '<span class="companies-empty">No aliases recorded</span>';
    const children = Array.isArray(company.children) && company.children.length
        ? company.children.map((child) => {
            const childKeyArg = encodeURIComponent(String(child.company_key || ''));
            const childNameArg = encodeURIComponent(String(child.company_name || ''));
            return `<a class="company-link" href="/companies/${encodeURIComponent(child.company_key)}" onclick="event.preventDefault(); openCompanyFromList(decodeURIComponent('${childKeyArg}'), decodeURIComponent('${childNameArg}'))">${escCompany(child.company_name || child.company_key)}</a>`;
        }).join(' | ')
        : '<span class="companies-empty">No child companies linked</span>';

    const employees = Array.isArray(company.employees) ? company.employees : [];
    const employeeRows = employees.length
        ? employees.map((employee) => `
            <tr>
                <td><a class="company-link" href="/person/${encodeURIComponent(employee.person_id || '')}">${escCompany(employee.full_name || 'Unknown')}</a></td>
                <td>${escCompany(employee.title_current || 'No title')}</td>
                <td>${escCompany(scoreLabel(employee.score))}</td>
            </tr>
        `).join('')
        : '<tr><td colspan="3" class="companies-empty">No active employees linked yet.</td></tr>';

    const opportunityCount = Array.isArray(company.opportunities) ? company.opportunities.length : 0;

    target.innerHTML = `
        <div class="company-detail-head">
            <div>
                <div class="panel-kicker">Employer Profile</div>
                <h2 style="margin:0.2rem 0 0.35rem;">${escCompany(company.company_name || 'Unknown company')}</h2>
                <div class="company-meta">${escCompany(company.employee_count || 0)} employees tracked | ${escCompany(opportunityCount)} company opportunities</div>
            </div>
            <div class="company-score-pill">Highest employee score: ${escCompany(scoreLabel(company.highest_employee_score))}</div>
        </div>

        <div class="company-attrs">
            <div class="company-attr"><div class="company-attr-label">Type</div><div class="company-attr-value">${escCompany(companyType)}</div></div>
            <div class="company-attr"><div class="company-attr-label">Parent</div><div class="company-attr-value">${parentLink}</div></div>
            <div class="company-attr"><div class="company-attr-label">Industry</div><div class="company-attr-value">${escCompany(company.industry || 'Not set')}</div></div>
            <div class="company-attr"><div class="company-attr-label">Headquarters</div><div class="company-attr-value">${escCompany(company.headquarters || 'Not set')}</div></div>
            <div class="company-attr"><div class="company-attr-label">Website</div><div class="company-attr-value">${company.website ? `<a class="company-link" href="${escCompany(company.website)}" target="_blank" rel="noopener noreferrer">${escCompany(company.website)}</a>` : 'Not set'}</div></div>
            <div class="company-attr"><div class="company-attr-label">Children</div><div class="company-attr-value">${children}</div></div>
        </div>

        <div style="margin-top:0.9rem;">
            <div class="company-attr-label">Aliases</div>
            <div style="margin-top:0.45rem; display:flex; gap:0.35rem; flex-wrap:wrap;">${aliases}</div>
        </div>

        <div style="margin-top:1rem;">
            <div class="panel-kicker">Employees</div>
            <table class="employees-table">
                <thead>
                    <tr>
                        <th>Person</th>
                        <th>Title</th>
                        <th>Score</th>
                    </tr>
                </thead>
                <tbody>${employeeRows}</tbody>
            </table>
        </div>
    `;
}

async function loadCompanyDetail(companyKey) {
    const key = window.normalizeCompanyKey(companyKey);
    if (!key) {
        renderCompanyDetail(null);
        return;
    }
    companyState.loadingDetail = true;
    try {
        const res = await fetch(`${API_BASE}/api/companies/${encodeURIComponent(key)}`);
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.message || `Company detail failed (${res.status})`);
        companyState.activeKey = key;
        renderCompanyList();
        renderCompanyDetail(data.company || null);
    } catch (error) {
        console.error(error);
        renderCompanyDetail({ company_name: 'Company not found', employees: [], employee_count: 0, highest_employee_score: null });
    } finally {
        companyState.loadingDetail = false;
    }
}

window.openCompanyFromList = async function openCompanyFromList(companyKey, companyName) {
    const key = window.normalizeCompanyKey(companyKey);
    if (!key) return;
    companyState.activeKey = key;
    setCompanyPath(key, companyName || '');
    renderCompanyList();
    await loadCompanyDetail(key);
};

let companySearchDebounce;

document.addEventListener('DOMContentLoaded', async () => {
    const searchInput = document.getElementById('company-search');
    if (searchInput) {
        searchInput.addEventListener('input', () => {
            clearTimeout(companySearchDebounce);
            companySearchDebounce = setTimeout(async () => {
                companyState.search = searchInput.value.trim();
                await loadCompanyList();
            }, 220);
        });
    }

    window.addEventListener('popstate', async () => {
        const key = companyKeyFromPath();
        if (key) {
            companyState.activeKey = key;
            renderCompanyList();
            await loadCompanyDetail(key);
            return;
        }
        companyState.activeKey = '';
        await loadCompanyList();
    });

    await loadCompanyList();
});
