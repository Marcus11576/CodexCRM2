// Profile page bootstrap and section chrome helpers.
(function () {
    const STORAGE_KEY = 'antigravity.profile.sections.v1';
    const DEFAULT_COLLAPSED = new Set(['people-links', 'ai-jobs']);

    function readState() {
        try {
            return JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}');
        } catch (_err) {
            return {};
        }
    }

    function writeState(next) {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    }

    function countItems(section) {
        if (!section) return '';
        if (section.id === 'intel-databank-section') {
            return `${section.querySelectorAll('.nugget-item').length} items`;
        }
        if (section.id === 'recent-interactions-section') {
            return `${section.querySelectorAll('.interaction-card, .timeline-item, .executive-log-item').length} entries`;
        }
        if (section.id === 'relationship-links-section') {
            return `${section.querySelectorAll('.relationship-link-row').length} links`;
        }
        if (section.id === 'ai-job-status-section') {
            return `${section.querySelectorAll('.profile-event-item, .profile-events-item, .job-status-card').length} jobs`;
        }
        if (section.id === 'briefing-section') {
            return '';
        }
        return '';
    }

    function setCollapsed(section, collapsed, button, badge) {
        section.classList.toggle('section-collapsed', collapsed);
        section.dataset.collapsed = collapsed ? 'true' : 'false';
        if (button) {
            button.textContent = collapsed ? 'Expand' : 'Collapse';
            button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        }
        if (badge) {
            badge.textContent = countItems(section);
        }
    }

    function enhanceSection(section, state) {
        const key = section.dataset.collapsible;
        const header = section.querySelector('.section-header, .profile-events-header, .briefing-toolbar');
        if (!key || !header) return;

        let controls = header.querySelector('.section-utility-actions');
        if (!controls) {
            controls = document.createElement('div');
            controls.className = 'section-utility-actions';
            header.appendChild(controls);
        }

        let badge = controls.querySelector('.section-utility-count');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'section-utility-count';
            controls.appendChild(badge);
        }

        let button = controls.querySelector('.section-utility-toggle');
        if (!button) {
            button = document.createElement('button');
            button.type = 'button';
            button.className = 'section-utility-toggle';
            button.addEventListener('click', () => {
                const nextState = readState();
                const nextCollapsed = section.dataset.collapsed !== 'true';
                nextState[key] = nextCollapsed;
                writeState(nextState);
                setCollapsed(section, nextCollapsed, button, badge);
            });
            controls.appendChild(button);
        }

        const collapsed = Object.prototype.hasOwnProperty.call(state, key)
            ? !!state[key]
            : DEFAULT_COLLAPSED.has(key);
        setCollapsed(section, collapsed, button, badge);
    }

    function initProfileSectionChrome() {
        try {
            const state = readState();
            document.querySelectorAll('[data-collapsible]').forEach((section) => {
                enhanceSection(section, state);
            });
        } catch (err) {
            console.error('Profile section chrome failed', err);
        }
    }

    window.initProfileSectionChrome = initProfileSectionChrome;

    document.addEventListener('DOMContentLoaded', () => {
        initProfileSectionChrome();
    });
})();
