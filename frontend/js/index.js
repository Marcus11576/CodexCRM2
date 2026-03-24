var API_BASE = window.API_BASE || '';
let currentStatusFilter = null; // for traffic light click
let activeMeetingStatuses = new Set(); // Multi-select Meeting Filter
let selectedCats = new Set(['all']); // Multi-select
let selectedEnvs = new Set(); // Multi-select Env Filter
let selectedDiscs = new Set(); // Multi-select Disc Filter
let selectedStatuses = new Set(); // Multi-select Status Filter
let quickCapturePeople = [];
const PROFILE_NAV_STORAGE_KEY = 'crm.profile.nav.v1';
const relationshipTemperatureApi = window.RelationshipTemperature;
let relationshipAgeRange = { min: 0, max: 100 };
let dashboardMobileControlsOpen = false;
let activeDashboardPriorityPreset = 'default';
const DASHBOARD_PRIORITY_PRESETS = Object.freeze({
    default: {
        label: 'Default',
        summary: 'Ranking mode: Default queue order (Monitor).',
    },
    action: {
        label: 'Highest Priority',
        summary: 'Ranking mode: Highest Action Priority score to lowest (Act Now).',
    },
    commercial: {
        label: 'Commercial Opportunity',
        summary: 'Ranking mode: Highest commercial opportunity signal to lowest (Maintain).',
    },
    critical: {
        label: 'Critical Relationships',
        summary: 'Ranking mode: Highest relationship risk/importance to lowest (Preserve).',
    },
});

// Get initials from name
function getInitials(name) {
    if (!name) return '?';
    const parts = name.split(' ');
    if (parts.length >= 2) {
        return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    }
    return name[0].toUpperCase();
}

function normalizeCatValue(value) {
    const cleaned = String(value || '').trim();
    const catMap = {
        'OBE Member': 'OBE M',
        'OBE M': 'OBE M',
        'OBE Target': 'OBE T',
        'OBE T': 'OBE T',
        'Client Target': 'TGT',
        'Target Client': 'TGT',
        'TGT': 'TGT',
        'Existing Client': 'EXT',
        'EXT': 'EXT',
        'Candidate': 'HPC',
        'High Performing Candidate': 'HPC',
        'HPC': 'HPC',
        'TS Advisory': 'TSA',
        'TSA': 'TSA',
        'General': 'GEN',
        'General Contact': 'GEN',
        'GEN': 'GEN',
    };
    return catMap[cleaned] || cleaned;
}

function normalizeEnvValue(value) {
    const cleaned = String(value || '').trim();
    const envMap = {
        'Gov Dev': 'Developer - Gov',
        'Semi-Gov Dev': 'Developer - Semi-Gov',
        'Private Dev': 'Developer - Private',
        'PMO': 'Management Consultant',
    };
    return envMap[cleaned] || cleaned;
}

function normalizeDiscValue(value) {
    const cleaned = String(value || '').trim();
    const discMap = {
        'Support': 'Support Services',
        'Others': 'Other',
    };
    return discMap[cleaned] || cleaned;
}

function normalizeContactValue(value) {
    const cleaned = String(value || '').replace(/'+$/g, '').trim().toLowerCase();
    const valueMap = { hot: 'Hot', warm: 'Warm', cold: 'Cold', frozen: 'Frozen' };
    return valueMap[cleaned] || String(value || '').trim();
}

function getRelationshipHealthSettings() {
    return relationshipTemperatureApi.getSettings();
}

function getRelationshipAgeSliderMax() {
    return 100;
}

function clampPercent(value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return 0;
    return Math.max(0, Math.min(100, Math.round(num)));
}

function toFiniteNumber(value, fallback = null) {
    if (value === null || value === undefined) return fallback;
    if (typeof value === 'string' && !value.trim()) return fallback;
    const num = Number(value);
    return Number.isFinite(num) ? num : fallback;
}

function parseDashboardDate(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    const parsed = new Date(text.replace(' ', 'T'));
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDashboardDueDistance(value) {
    const parsed = parseDashboardDate(value);
    if (!parsed) return '';
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(parsed);
    target.setHours(0, 0, 0, 0);
    const diffDays = Math.round((target - today) / (1000 * 60 * 60 * 24));
    if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
    if (diffDays === 0) return 'Today';
    return `${diffDays}d out`;
}

function daysSinceDashboardDate(value) {
    const parsed = parseDashboardDate(value);
    if (!parsed) return null;
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const target = new Date(parsed.getFullYear(), parsed.getMonth(), parsed.getDate());
    return Math.max(0, Math.round((today - target) / (1000 * 60 * 60 * 24)));
}

function actionPriorityBand(score) {
    const normalized = clampPercent(score);
    if (normalized >= 70) {
        return {
            className: 'band-red',
            label: 'Needs Action',
            accent: '#fb7185',
            soft: 'rgba(251, 113, 133, 0.2)',
        };
    }
    if (normalized >= 40) {
        return {
            className: 'band-green',
            label: 'In Motion',
            accent: '#22c55e',
            soft: 'rgba(34, 197, 94, 0.18)',
        };
    }
    return {
        className: 'band-blue',
        label: 'Stable',
        accent: '#38bdf8',
        soft: 'rgba(56, 189, 248, 0.18)',
    };
}

function dashboardAgendaHref(contact) {
    const params = new URLSearchParams();
    const personId = String(contact?.person_id || '').trim();
    const contactName = String(contact?.full_name || '').trim();
    if (personId) params.set('person_id', personId);
    if (contactName) params.set('contact_name', contactName);
    const query = params.toString();
    return `/agenda.html${query ? `?${query}` : ''}`;
}

function hasContactEvidenceForScoring(contact, temperature) {
    const recencyDays = toFiniteNumber(contact?.recency_days, null);
    if (Number.isFinite(recencyDays) && recencyDays >= 0) return true;
    const interactionCount = Math.max(0, Math.round(toFiniteNumber(contact?.interaction_count, 0)));
    if (interactionCount > 0) return true;
    return false;
}

function relationshipStageCodeFromContact(contact = {}) {
    return String(
        contact?.relationship_stage_code
        || contact?.relationship_stage
        || ''
    ).trim().toUpperCase();
}

function cadenceDaysForRelationshipStage(stageCode) {
    const code = String(stageCode || '').trim().toUpperCase();
    if (code === 'S1') return 30;
    if (code === 'S2') return 21;
    if (code === 'S3') return 14;
    if (code === 'S4') return 10;
    if (code === 'S5') return 7;
    if (code === 'S6') return 5;
    if (code === 'S7') return 4;
    if (code === 'S8' || code === 'S9') return 4;
    return null;
}

function isLegacyScoringDisabledContext(contact = {}) {
    const scoreBand = String(contact?.score_band || '').trim().toLowerCase();
    const queueReason = String(contact?.queue_reason || '').trim().toLowerCase();
    return scoreBand === 'disabled' || queueReason.includes('legacy scoring disabled');
}

function computeActionPriorityModel(contact, temperature) {
    const stageCode = relationshipStageCodeFromContact(contact);
    const stageCadence = cadenceDaysForRelationshipStage(stageCode);
    const cadenceDays = Math.max(
        4,
        Math.round(toFiniteNumber(stageCadence, toFiniteNumber(contact?.cadence_days, toFiniteNumber(temperature?.cadenceDays, 14))))
    );
    const recency = toFiniteNumber(contact?.recency_days, null);
    const datedFallbackDays =
        daysSinceDashboardDate(contact?.last_interaction_at)
        ?? daysSinceDashboardDate(contact?.last_meaningful_contact_at)
        ?? daysSinceDashboardDate(contact?.last_contact_datetime);
    const lastContactDays = Number.isFinite(recency)
        ? Math.max(0, Math.round(recency))
        : (Number.isFinite(datedFallbackDays) ? Math.max(0, Math.round(datedFallbackDays)) : null);

    const activeTaskCount = Math.max(0, Math.round(toFiniteNumber(contact?.open_task_count, 0)));
    const overdueTaskCount = Math.max(0, Math.round(toFiniteNumber(contact?.overdue_open_task_count, 0)));
    const dueSoonTaskCount = Math.max(0, activeTaskCount - overdueTaskCount);
    const healthScore = clampPercent(toFiniteNumber(contact?.network_health_score, 55));
    const healthPressure = clampPercent(100 - healthScore);
    const hasFutureCover = Boolean(contact?.has_future_cover);
    const queueKey = String(contact?.queue_key || '').trim().toLowerCase();
    const legacyDisabled = isLegacyScoringDisabledContext(contact);
    const hasEvidence = hasContactEvidenceForScoring(contact, temperature);
    const hasDefinedAction = Boolean(
        contact?.follow_up_confirmation_needed
        || String(contact?.follow_up_confirmation_prompt || '').trim()
        || String(contact?.follow_up_confirmation_reason || '').trim()
        || String(contact?.primary_open_task_text || '').trim()
        || activeTaskCount > 0
    );

    const stageSource = String(
        contact?.relationship_stage_label
        || contact?.relationship_stage_code
        || contact?.effective_network_tier_label
        || contact?.effective_network_tier
        || ''
    ).trim();
    const stageLabel = stageSource ? stageSource : 'Unspecified';

    const nextTaskText = String(contact?.primary_open_task_text || '').trim();
    const nextTaskDue = formatDashboardDueDistance(contact?.earliest_open_task_due_date);
    const nextTaskLabel = nextTaskText
        ? `${nextTaskText}${nextTaskDue ? ` (${nextTaskDue})` : ''}`
        : 'No active task scheduled.';

    if (legacyDisabled || !hasEvidence) {
        const disabledReason = 'No score available yet for this contact.';
        const noEvidenceReason = 'No transcript or interaction evidence captured yet.';
        const nextActionLabel = !hasEvidence
            ? 'Add one transcript or interaction to activate Action Priority scoring.'
            : 'Refresh relationship intelligence and confirm a dated next step.';
        return {
            hasScore: false,
            score: null,
            band: {
                className: 'band-none',
                label: 'No Score',
                accent: '#94a3b8',
                soft: 'rgba(148, 163, 184, 0.2)',
            },
            reasonText: legacyDisabled ? disabledReason : noEvidenceReason,
            contactSummary: 'No transcript/interaction history',
            taskSummary: activeTaskCount === 0
                ? 'No active tasks'
                : `${activeTaskCount} active | ${overdueTaskCount} overdue | ${dueSoonTaskCount} due soon`,
            stageLabel,
            healthScore,
            nextActionLabel,
            nextTaskLabel,
            agendaHref: dashboardAgendaHref(contact),
        };
    }

    let contactUrgency = 82;
    if (Number.isFinite(lastContactDays)) {
        if (lastContactDays <= Math.floor(cadenceDays * 0.6)) contactUrgency = 16;
        else if (lastContactDays <= cadenceDays) contactUrgency = 34;
        else if (lastContactDays <= Math.ceil(cadenceDays * 1.5)) contactUrgency = 58;
        else if (lastContactDays <= cadenceDays * 2) contactUrgency = 76;
        else contactUrgency = 92;
    }

    let taskUrgency = 28;
    if (overdueTaskCount > 0) taskUrgency = Math.min(100, 70 + (overdueTaskCount * 12));
    else if (activeTaskCount > 0 && !hasFutureCover) taskUrgency = 46;
    else if (activeTaskCount > 0) taskUrgency = 28;
    else if (hasDefinedAction) taskUrgency = 84;

    let actionUrgency = 30;
    if (hasDefinedAction && activeTaskCount === 0) actionUrgency = 88;
    else if (hasDefinedAction && overdueTaskCount > 0) actionUrgency = 78;
    else if (hasDefinedAction && activeTaskCount > 0) actionUrgency = 42;
    else if (!hasFutureCover) actionUrgency = 62;

    let score = Math.round(
        (contactUrgency * 0.34)
        + (taskUrgency * 0.28)
        + (actionUrgency * 0.2)
        + (healthPressure * 0.18)
    );
    if (activeTaskCount > 0 && overdueTaskCount === 0 && Number.isFinite(lastContactDays) && lastContactDays <= cadenceDays) {
        score -= 10;
    }
    if (hasFutureCover && overdueTaskCount === 0) score -= 6;
    if (queueKey === 'act_now') score += 14;
    else if (queueKey === 'maintain') score += 2;
    else if (queueKey === 'preserve') score -= 8;
    else if (queueKey === 'monitor') score -= 14;
    score = clampPercent(score);

    const band = actionPriorityBand(score);
    const reasonParts = [];
    if (overdueTaskCount > 0) reasonParts.push(`${overdueTaskCount} overdue task${overdueTaskCount === 1 ? '' : 's'}`);
    if (Number.isFinite(lastContactDays) && lastContactDays > cadenceDays) {
        reasonParts.push(`contact gap ${lastContactDays}d (target ${cadenceDays}d)`);
    }
    if (hasDefinedAction && activeTaskCount === 0) reasonParts.push('defined action with no scheduled task');
    if (!hasFutureCover) reasonParts.push('no dated next step booked');
    if (!reasonParts.length) reasonParts.push('cadence and tasks are aligned for this relationship');

    const contactSummary = Number.isFinite(lastContactDays)
        ? `${lastContactDays}d since contact (target ${cadenceDays}d)`
        : `No contact date (target ${cadenceDays}d)`;
    const taskSummary = activeTaskCount === 0
        ? 'No active tasks'
        : `${activeTaskCount} active | ${overdueTaskCount} overdue | ${dueSoonTaskCount} due soon`;
    let nextActionLabel = 'Maintain cadence and keep the next step dated.';
    if (overdueTaskCount > 0) {
        nextActionLabel = 'Clear overdue tasks and confirm the next follow-up date.';
    } else if (hasDefinedAction && activeTaskCount === 0) {
        nextActionLabel = 'Schedule the defined next step in Agenda.';
    } else if (!hasFutureCover) {
        nextActionLabel = 'Book a dated next step to keep momentum.';
    } else if (Number.isFinite(lastContactDays) && lastContactDays > cadenceDays) {
        nextActionLabel = 'Reconnect now and log the outcome.';
    }

    return {
        hasScore: true,
        score,
        band,
        reasonText: reasonParts.join(' | '),
        contactSummary,
        taskSummary,
        stageLabel,
        healthScore,
        nextActionLabel,
        nextTaskLabel,
        agendaHref: dashboardAgendaHref(contact),
    };
}

function buildActionPriorityPreview(contact, temperature) {
    const model = contact?.action_priority || computeActionPriorityModel(contact, temperature);
    const scoreText = model.hasScore ? `${model.score}%` : '--';
    const scoreValue = model.hasScore ? model.score : 0;
    const compactReason = String(model.reasonText || '')
        .split('|')
        .map((part) => part.trim())
        .filter(Boolean)[0] || 'Review relationship momentum and next step.';
    const compactMeta = [model.contactSummary, model.taskSummary]
        .map((text) => String(text || '').trim())
        .filter(Boolean)
        .slice(0, 2);
    return `
                    <div class="contact-task-preview is-pinned action-priority-preview ${escapeHtml(model.band.className)}" style="--priority-accent:${escapeHtml(model.band.accent)}; --priority-soft:${escapeHtml(model.band.soft)};">
                        <div class="action-priority-head">
                            <div class="action-priority-score-wrap">
                                <div class="action-priority-kicker">Action Priority</div>
                                <div class="action-priority-score">${scoreText}</div>
                                <div class="action-priority-band">${escapeHtml(model.band.label)}</div>
                            </div>
                            <div class="action-priority-progress-wrap">
                                <div class="action-priority-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${scoreValue}">
                                    <span style="width:${scoreValue}%"></span>
                                </div>
                                <div class="action-priority-reason">${escapeHtml(compactReason)}</div>
                            </div>
                        </div>
                        <div class="action-priority-meta-row">
                            ${compactMeta.map((item) => `<span class="action-priority-chip">${escapeHtml(item)}</span>`).join('')}
                        </div>
                        <div class="action-priority-next"><strong>Next task:</strong> ${escapeHtml(model.nextTaskLabel)}</div>
                        <div class="action-priority-links">
                            <a href="${escapeHtml(model.agendaHref)}" onclick="event.stopPropagation();">Open in Agenda</a>
                        </div>
                    </div>
                    `;
}

function updateRelationshipTemperatureSummary(feed) {
    const summary = document.getElementById('relationship-age-summary');
    if (!summary) return;

    const contacts = [
        ...(feed?.act_now || []),
        ...(feed?.maintain || []),
        ...(feed?.preserve || []),
        ...(feed?.monitor || []),
    ];
    const counts = { needs_action: 0, in_motion: 0, stable: 0, no_score: 0 };
    contacts.forEach((contact) => {
        const model = contact?.action_priority || computeActionPriorityModel(
            contact,
            contact?.relationship_temperature || relationshipTemperatureApi.getTemperature(contact)
        );
        if (!model?.hasScore) {
            counts.no_score += 1;
            return;
        }
        if (model.score >= 70) counts.needs_action += 1;
        else if (model.score >= 40) counts.in_motion += 1;
        else counts.stable += 1;
    });
    summary.textContent = `Needs Action ${counts.needs_action} | In Motion ${counts.in_motion} | Stable ${counts.stable} | No Score ${counts.no_score}`;
}

function syncRelationshipAgeSlider() {
    const minInput = document.getElementById('relationship-age-min');
    const maxInput = document.getElementById('relationship-age-max');
    const fill = document.getElementById('relationship-age-track-fill');
    const legend = document.getElementById('relationship-age-legend');
    const slider = document.getElementById('relationship-age-slider');
    const minValueBadge = document.getElementById('relationship-age-min-value');
    const maxValueBadge = document.getElementById('relationship-age-max-value');
    const sliderMax = getRelationshipAgeSliderMax();
    if (!minInput || !maxInput || !fill || !legend) return;

    relationshipAgeRange.min = Math.max(0, Math.min(relationshipAgeRange.min, sliderMax));
    relationshipAgeRange.max = Math.max(relationshipAgeRange.min, Math.min(relationshipAgeRange.max, sliderMax));
    minInput.max = String(sliderMax);
    maxInput.max = String(sliderMax);
    minInput.value = String(relationshipAgeRange.min);
    maxInput.value = String(relationshipAgeRange.max);

    const startPct = (relationshipAgeRange.min / sliderMax) * 100;
    const endPct = (relationshipAgeRange.max / sliderMax) * 100;
    fill.style.left = `${startPct}%`;
    fill.style.width = `${Math.max(0, endPct - startPct)}%`;

    if (minValueBadge && maxValueBadge && slider) {
        minValueBadge.textContent = String(relationshipAgeRange.min);
        maxValueBadge.textContent = String(relationshipAgeRange.max);

        const sliderWidth = slider.clientWidth || 1;
        const minBadgeWidth = minValueBadge.offsetWidth || 24;
        const maxBadgeWidth = maxValueBadge.offsetWidth || 24;

        const minPosition = (startPct / 100) * sliderWidth;
        const maxPosition = (endPct / 100) * sliderWidth;
        const clampedMin = Math.min(Math.max(minPosition, minBadgeWidth / 2), sliderWidth - (minBadgeWidth / 2));
        const clampedMax = Math.min(Math.max(maxPosition, maxBadgeWidth / 2), sliderWidth - (maxBadgeWidth / 2));

        minValueBadge.style.left = `${clampedMin}px`;
        maxValueBadge.style.left = `${clampedMax}px`;
    }

    legend.textContent = 'Action Priority: Stable 0-39 | In Motion 40-69 | Needs Action 70-100';
}

function handleRelationshipAgeSliderChange() {
    const minInput = document.getElementById('relationship-age-min');
    const maxInput = document.getElementById('relationship-age-max');
    if (!minInput || !maxInput) return;
    let minValue = Number(minInput.value);
    let maxValue = Number(maxInput.value);
    if (minValue > maxValue) {
        if (document.activeElement === minInput) {
            maxValue = minValue;
            maxInput.value = String(maxValue);
        } else {
            minValue = maxValue;
            minInput.value = String(minValue);
        }
    }
    relationshipAgeRange = { min: minValue, max: maxValue };
    syncRelationshipAgeSlider();
    updateRelationshipAgeSelectedCount(0, 0, true);
    loadDashboard();
}

function resetRelationshipAgeFilter() {
    relationshipAgeRange = { min: 0, max: getRelationshipAgeSliderMax() };
    syncRelationshipAgeSlider();
    updateRelationshipAgeSelectedCount(0, 0, true);
    loadDashboard();
}

function toggleFilterDropdown(type) {
    document.querySelectorAll('.compact-filter-group').forEach((group) => {
        const shouldOpen = group.id !== `${type}-filter-group`;
        if (!shouldOpen) return;
        group.classList.remove('is-open');
    });
    const target = document.getElementById(`${type}-filter-group`);
    if (target) {
        target.classList.toggle('is-open');
    }
}

function closeAllFilterDropdowns() {
    document.querySelectorAll('.compact-filter-group').forEach((group) => {
        group.classList.remove('is-open');
    });
}

function updateCompactFilterLabels() {
    const catLabel = document.getElementById('cat-filter-label');
    const envLabel = document.getElementById('env-filter-label');
    const discLabel = document.getElementById('disc-filter-label');
    const statusLabel = document.getElementById('status-filter-label');
    if (catLabel) {
        catLabel.textContent = selectedCats.has('all') ? 'All' : `${selectedCats.size} selected`;
    }
    if (envLabel) {
        const envCount = selectedEnvs.has('all') ? 0 : selectedEnvs.size;
        envLabel.textContent = envCount === 0 ? 'All' : `${envCount} selected`;
    }
    if (discLabel) {
        const discCount = selectedDiscs.has('all') ? 0 : selectedDiscs.size;
        discLabel.textContent = discCount === 0 ? 'All' : `${discCount} selected`;
    }
    if (statusLabel) {
        statusLabel.textContent = selectedStatuses.size === 0 ? 'All' : `${selectedStatuses.size} selected`;
    }
}

// Format date
function formatDate(dateStr) {
    if (!dateStr) return 'Not set';
    const date = new Date(dateStr);
    const now = new Date();
    const diffDays = Math.ceil((date - now) / (1000 * 60 * 60 * 24));

    if (diffDays < 0) {
        return `${Math.abs(diffDays)}d past`;
    } else if (diffDays === 0) {
        return 'Today';
    } else if (diffDays === 1) {
        return 'Tomorrow';
    } else {
        return `${diffDays}d`;
    }
}

function attachRelationshipTemperature(feed) {
    const mapList = (items) => (items || []).map((contact) => {
        const relationshipTemperature = relationshipTemperatureApi.getTemperature(contact);
        return {
            ...contact,
            relationship_temperature: relationshipTemperature,
            action_priority: computeActionPriorityModel(contact, relationshipTemperature),
        };
    });

    return {
        act_now: mapList(feed?.act_now),
        maintain: mapList(feed?.maintain),
        preserve: mapList(feed?.preserve),
        monitor: mapList(feed?.monitor),
        overlays: {
            no_next_step: mapList(feed?.overlays?.no_next_step),
            no_relationship_signal: mapList(feed?.overlays?.no_relationship_signal),
            recently_reactivated: mapList(feed?.overlays?.recently_reactivated),
            open_task_pressure: mapList(feed?.overlays?.open_task_pressure),
            follow_up_confirmation: mapList(feed?.overlays?.follow_up_confirmation),
            meeting_churn: mapList(feed?.overlays?.meeting_churn),
        },
        summary: feed?.summary || {},
    };
}

function updateOverlaySummary(feed) {
    const target = document.getElementById('dashboard-overlay-summary');
    if (!target) return;
    const summary = feed?.summary || {};
    target.textContent = `No next step ${summary.no_next_step_count || 0} | Follow-up check ${summary.follow_up_confirmation_count || 0} | Meeting churn ${summary.meeting_churn_count || 0} | Task pressure ${summary.open_task_pressure_count || 0} | Invisible ${summary.invisible_count || 0}`;
}

function updateRelationshipAgeSelectedCount(selectedCount = 0, totalCount = 0, loading = false) {
    const target = document.getElementById('relationship-age-selected-count');
    if (!target) return;
    if (loading) {
        target.textContent = 'Updating selection...';
        return;
    }
    target.textContent = `Selected ${selectedCount} of ${totalCount}`;
}

function getDashboardPriorityPresetConfig() {
    return DASHBOARD_PRIORITY_PRESETS[activeDashboardPriorityPreset] || DASHBOARD_PRIORITY_PRESETS.default;
}

function updateDashboardPrioritySummary(visibleCount = null) {
    const target = document.getElementById('dashboard-priority-summary');
    if (!target) return;
    const config = getDashboardPriorityPresetConfig();
    const countSuffix = Number.isFinite(visibleCount) ? ` | ${visibleCount} shown` : '';
    target.textContent = `${config.summary}${countSuffix}`;
}

function syncDashboardPriorityPresetControls() {
    const buttons = document.querySelectorAll('[data-dashboard-preset]');
    buttons.forEach((button) => {
        const preset = button.dataset.dashboardPreset || 'default';
        if (preset === activeDashboardPriorityPreset) {
            button.classList.add('active');
        } else {
            button.classList.remove('active');
        }
    });
    updateDashboardPrioritySummary();
}

function setDashboardPriorityPreset(preset) {
    const normalized = String(preset || 'default').trim().toLowerCase();
    if (!DASHBOARD_PRIORITY_PRESETS[normalized]) return;
    activeDashboardPriorityPreset = normalized;
    activeMeetingStatuses.clear();
    syncDashboardPriorityPresetControls();
    loadDashboard();
}

function dashboardActionPriorityScore(contact) {
    const model = contact?.action_priority || computeActionPriorityModel(
        contact,
        contact?.relationship_temperature || relationshipTemperatureApi.getTemperature(contact)
    );
    if (!model?.hasScore) return -1;
    return clampPercent(model.score);
}

function dashboardCommercialPriorityScore(contact) {
    const directCommercial = toFiniteNumber(contact?.commercial_priority_score, null);
    if (Number.isFinite(directCommercial)) return clampPercent(directCommercial);

    const opportunityReadiness = clampPercent(toFiniteNumber(contact?.opportunity_readiness_score, 0));
    const strategicValue = clampPercent(toFiniteNumber(contact?.strategic_value_score, 0));
    const influence = clampPercent(toFiniteNumber(contact?.influence_score, 0));
    const openOpportunityCount = Math.max(
        0,
        Math.round(toFiniteNumber(contact?.open_opportunity_count, toFiniteNumber(contact?.opportunity_count, 0)))
    );
    const openOpportunitySignal = clampPercent(openOpportunityCount * 20);
    const blended = (
        (opportunityReadiness * 0.45)
        + (strategicValue * 0.25)
        + (influence * 0.2)
        + (openOpportunitySignal * 0.1)
    );
    return clampPercent(blended);
}

function dashboardTierWeightScore(contact) {
    const rawTier = String(contact?.effective_network_tier || contact?.network_tier || '').trim().toUpperCase();
    const matchedTier = rawTier.match(/T([1-4])/);
    const tierCode = matchedTier ? `T${matchedTier[1]}` : rawTier;
    if (tierCode === 'T1') return 100;
    if (tierCode === 'T2') return 80;
    if (tierCode === 'T3') return 60;
    if (tierCode === 'T4') return 40;
    return 20;
}

function dashboardCriticalRelationshipScore(contact) {
    const coverageRisk = clampPercent(toFiniteNumber(contact?.coverage_risk_score, 0));
    const executionPressure = clampPercent(toFiniteNumber(contact?.execution_pressure_score, 0));
    const relationshipHealth = clampPercent(toFiniteNumber(contact?.relationship_health_score, toFiniteNumber(contact?.network_health_score, 55)));
    const relationshipWeakness = clampPercent(100 - relationshipHealth);
    const influence = clampPercent(toFiniteNumber(contact?.influence_score, 0));
    const tierWeight = dashboardTierWeightScore(contact);

    let score = (
        (coverageRisk * 0.32)
        + (executionPressure * 0.24)
        + (relationshipWeakness * 0.18)
        + (influence * 0.12)
        + (tierWeight * 0.14)
    );

    if (!contact?.has_future_cover) score += 12;
    if (contact?.has_task_pressure) score += 10;
    if (Math.max(0, Math.round(toFiniteNumber(contact?.overdue_open_task_count, 0))) > 0) score += 8;
    if (contact?.is_high_priority) score += 10;
    if (contact?.has_meeting_churn) score += 6;

    return clampPercent(score);
}

function dashboardPresetScore(contact) {
    if (activeDashboardPriorityPreset === 'action') return dashboardActionPriorityScore(contact);
    if (activeDashboardPriorityPreset === 'commercial') return dashboardCommercialPriorityScore(contact);
    if (activeDashboardPriorityPreset === 'critical') return dashboardCriticalRelationshipScore(contact);
    return 0;
}

function applyDashboardPriorityPreset(list) {
    const ranked = Array.isArray(list) ? [...list] : [];
    if (activeDashboardPriorityPreset === 'default') return ranked;

    ranked.sort((left, right) => {
        const rightScore = dashboardPresetScore(right);
        const leftScore = dashboardPresetScore(left);
        if (rightScore !== leftScore) return rightScore - leftScore;

        const rightAction = dashboardActionPriorityScore(right);
        const leftAction = dashboardActionPriorityScore(left);
        if (rightAction !== leftAction) return rightAction - leftAction;

        const leftName = String(left?.full_name || '').toLowerCase();
        const rightName = String(right?.full_name || '').toLowerCase();
        return leftName.localeCompare(rightName);
    });

    return ranked;
}

// Helper to filter lists based on UI state
const filterList = (list) => {
    let filtered = list || [];

    // 1. Cat Filter (Multi-select)
    if (!selectedCats.has('all')) {
        filtered = filtered.filter(c => {
            const personCats = (c.cat || '')
                .split(',')
                .map(normalizeCatValue)
                .filter(Boolean);
            // Show if ANY of person's categories are in selectedCats
            return personCats.some(cat => selectedCats.has(cat));
        });
    }

    // 2. Env Filter (Multi-select)
    if (!selectedEnvs.has('all') && selectedEnvs.size > 0) {
        filtered = filtered.filter(c => {
            const personEnvs = (c.env || '')
                .split(',')
                .map(normalizeEnvValue)
                .map(value => value.toLowerCase())
                .filter(Boolean);
            return Array.from(selectedEnvs).some(env => personEnvs.includes(normalizeEnvValue(env).toLowerCase()));
        });
    }

    // 3. Disc Filter (Multi-select)
    if (!selectedDiscs.has('all') && selectedDiscs.size > 0) {
        filtered = filtered.filter(c => {
            const personDisc = normalizeDiscValue(c.disc);
            return selectedDiscs.has(personDisc);
        });
    }

    // 4. Status Filter (Multi-select)
    if (selectedStatuses.size > 0) {
        filtered = filtered.filter(c => {
            return selectedStatuses.has(normalizeContactValue(c.contact_value));
        });
    }

    filtered = filtered.filter((c) => {
        const model = c.action_priority || computeActionPriorityModel(
            c,
            c.relationship_temperature || relationshipTemperatureApi.getTemperature(c)
        );
        const isDefaultRange = relationshipAgeRange.min === 0 && relationshipAgeRange.max === getRelationshipAgeSliderMax();
        if (!model?.hasScore) return isDefaultRange;
        return model.score >= relationshipAgeRange.min && model.score <= relationshipAgeRange.max;
    });

    return filtered;
};

// Load dashboard data
async function loadDashboard() {
    try {
        const loadingState = document.getElementById('loading-state');
        const emptyState = document.getElementById('empty-state');
        if (loadingState) {
            loadingState.style.display = 'block';
            loadingState.innerHTML = `
                    <div class="spinner"></div>
                    <p>Loading contacts...</p>
                `;
        }
        if (emptyState) {
            emptyState.style.display = 'none';
        }
        updateRelationshipAgeSelectedCount(0, 0, true);

        const feedRes = await fetch(`${API_BASE}/api/dashboard/network-feed`);
        const feed = attachRelationshipTemperature(await feedRes.json());
        updateRelationshipTemperatureSummary(feed);
        updateOverlaySummary(feed);

        // Hide loading
        if (loadingState) {
            loadingState.style.display = 'none';
        }

        // --- Filter Logic ---

        const actNow = applyDashboardPriorityPreset(filterList(feed.act_now));
        const maintain = applyDashboardPriorityPreset(filterList(feed.maintain || []));
        const preserve = applyDashboardPriorityPreset(filterList(feed.preserve));
        const monitor = applyDashboardPriorityPreset(filterList(feed.monitor));
        const visibleCount = actNow.length + maintain.length + preserve.length + monitor.length;
        const totalCount = (feed.act_now || []).length + (feed.maintain || []).length + (feed.preserve || []).length + (feed.monitor || []).length;
        updateDashboardPrioritySummary(visibleCount);
        updateRelationshipAgeSelectedCount(visibleCount, totalCount);

        // Update Stats to reflect 'Filtered' counts
        const oCount = document.getElementById('stat-overdue');
        const sCount = document.getElementById('stat-soon');
        const otCount = document.getElementById('stat-ontrack');
        const nsCount = document.getElementById('stat-not-scheduled');
        
        if (oCount) oCount.textContent = actNow.length;
        if (sCount) sCount.textContent = maintain.length;
        if (otCount) otCount.textContent = preserve.length;
        if (nsCount) nsCount.textContent = monitor.length;

        syncDashboardPriorityPresetControls();

        // --- Render ---
        const hasContacts = actNow.length + maintain.length + preserve.length + monitor.length > 0;

        // Clear lists first (important for re-render)
        document.getElementById('overdue-list').innerHTML = '';
        document.getElementById('not-scheduled-list').innerHTML = '';
        document.getElementById('soon-list').innerHTML = '';
        document.getElementById('ontrack-list').innerHTML = '';

        document.getElementById('overdue-section').style.display = 'none';
        document.getElementById('not-scheduled-section').style.display = 'none';
        document.getElementById('soon-section').style.display = 'none';
        document.getElementById('ontrack-section').style.display = 'none';

        if (hasContacts) {
            const shouldShow = (type) => activeMeetingStatuses.size === 0 || activeMeetingStatuses.has(type);
            const orderedVisiblePeople = [];

            if (shouldShow('act_now') && actNow.length > 0) {
                document.getElementById('overdue-section').style.display = 'block';
                document.getElementById('overdue-count').textContent = actNow.length;
                orderedVisiblePeople.push(...actNow);
                actNow.forEach(c => renderContact(c, 'overdue-list'));
            }

            if (shouldShow('monitor') && monitor.length > 0) {
                document.getElementById('not-scheduled-section').style.display = 'block';
                document.getElementById('not-scheduled-count').textContent = monitor.length;
                orderedVisiblePeople.push(...monitor);
                monitor.forEach(c => renderContact(c, 'not-scheduled-list'));
            }

            if (shouldShow('maintain') && maintain.length > 0) {
                document.getElementById('soon-section').style.display = 'block';
                document.getElementById('soon-count').textContent = maintain.length;
                orderedVisiblePeople.push(...maintain);
                maintain.forEach(c => renderContact(c, 'soon-list'));
            }

            if (shouldShow('preserve') && preserve.length > 0) {
                document.getElementById('ontrack-section').style.display = 'block';
                document.getElementById('ontrack-count').textContent = preserve.length;
                orderedVisiblePeople.push(...preserve);
                preserve.forEach(c => renderContact(c, 'ontrack-list'));
            }

            persistProfileNavigationContext(orderedVisiblePeople);
        } else if (emptyState) {
            emptyState.style.display = hasContacts ? 'none' : 'block';
            if (!hasContacts) {
                const paragraphs = emptyState.querySelectorAll('p');
                if (paragraphs[0]) paragraphs[0].textContent = 'No contacts match the current filters';
                if (paragraphs[1]) paragraphs[1].textContent = 'Clear a filter or switch views to see more relationships.';
            }
            persistProfileNavigationContext([]);
        }

    } catch (error) {
        console.error('Dashboard load error:', error);
        updateRelationshipAgeSelectedCount(0, 0);
        document.getElementById('loading-state').style.display = 'block';
        document.getElementById('loading-state').innerHTML = `
                    <p style="color: var(--accent-red);">Failed to load dashboard</p>
                    <p style="font-size: 0.85rem; margin-top: 0.5rem;">Make sure the server is running</p>
                `;
    }
}

function persistProfileNavigationContext(people) {
    try {
        const entries = Array.isArray(people)
            ? people
                .filter((person) => person && person.person_id)
                .map((person) => ({
                    person_id: person.person_id,
                    full_name: person.full_name || 'Unknown Contact',
                    title_current: person.title_current || '',
                    company_name_raw: person.company_name_raw || '',
                }))
            : [];

        window.sessionStorage.setItem(PROFILE_NAV_STORAGE_KEY, JSON.stringify({
            source: 'dashboard',
            updatedAt: Date.now(),
            people: entries,
        }));
    } catch (error) {
        console.error('Failed to persist profile navigation context', error);
    }
}

// Toggle Cat (Multi-select)
function toggleCat(cat) {
    const chips = document.querySelectorAll('#cat-filters .filter-chip');
    const catMap = {
        'OBE Member': 'OBE M',
        'OBE Target': 'OBE T',
        'Client Target': 'TGT',
        'Target Client': 'TGT',
        'Existing Client': 'EXT',
        'Candidate': 'HPC',
        'High Performing Candidate': 'HPC',
        'TS Advisory': 'TSA',
        'General': 'GEN',
        'General Contact': 'GEN'
    };

    const dbValue = normalizeCatValue(catMap[cat] || cat);

    if (cat === 'all') {
        selectedCats.clear();
        selectedCats.add('all');
    } else {
        if (selectedCats.has('all')) {
            selectedCats.delete('all');
        }

        if (selectedCats.has(dbValue)) {
            selectedCats.delete(dbValue);
        } else {
            selectedCats.add(dbValue);
        }

        if (selectedCats.size === 0) {
            selectedCats.add('all');
        }
    }

    // Update UI
    chips.forEach(chip => {
        const text = chip.textContent;
        let isActive = false;
        if (text === 'All') {
            isActive = selectedCats.has('all');
        } else {
            const mapped = normalizeCatValue(catMap[text] || text);
            isActive = selectedCats.has(mapped);
        }

        if (isActive) chip.classList.add('active');
        else chip.classList.remove('active');
    });

    updateCompactFilterLabels();
    loadDashboard();
}

// Toggle Env (Multi-select)
function toggleEnv(env) {
    const envMap = {
        'Gov Dev': 'Developer - Gov',
        'Semi-Gov Dev': 'Developer - Semi-Gov',
        'Private Dev': 'Developer - Private',
        'Consultant': 'Consultant',
        'Main Contractor': 'Main Contractor',
        'Sub Contractor': 'Sub Contractor',
        'PMO': 'Management Consultant'
    };

    if (env === 'all') {
        selectedEnvs.clear();
        selectedEnvs.add('all');
    } else if (env === 'DevMaster') {
        // Multi-select Dev values
        const devValues = ['Developer - Gov', 'Developer - Semi-Gov', 'Developer - Private'];
        const allSelected = devValues.every(v => selectedEnvs.has(v));

        if (selectedEnvs.has('all')) selectedEnvs.delete('all');

        if (allSelected) {
            devValues.forEach(v => selectedEnvs.delete(v));
        } else {
            devValues.forEach(v => selectedEnvs.add(v));
        }
        if (selectedEnvs.size === 0) selectedEnvs.add('all');
    } else {
        const dbValue = normalizeEnvValue(envMap[env] || env);

        if (selectedEnvs.has('all')) selectedEnvs.delete('all');

        if (selectedEnvs.has(dbValue)) {
            selectedEnvs.delete(dbValue);
        } else {
            selectedEnvs.add(dbValue);
        }
        if (selectedEnvs.size === 0) selectedEnvs.add('all');
    }

    // Update UI
    const chips = document.querySelectorAll('#env-filters .filter-chip');
    chips.forEach(chip => {
        const text = chip.textContent;
        if (text === 'Dev') {
            const devValues = ['Developer - Gov', 'Developer - Semi-Gov', 'Developer - Private'];
            const allSelected = devValues.every(v => selectedEnvs.has(v));
            if (allSelected) chip.classList.add('active');
            else chip.classList.remove('active');
        } else if (text === 'All') {
            if (selectedEnvs.has('all')) chip.classList.add('active');
            else chip.classList.remove('active');
        } else {
            const dbValue = normalizeEnvValue(envMap[text] || text);
            if (selectedEnvs.has(dbValue)) {
                chip.classList.add('active');
            } else {
                chip.classList.remove('active');
            }
        }
    });

    updateCompactFilterLabels();
    loadDashboard();
}

// Toggle Disc (Multi-select)
function toggleDisc(disc) {
    const discMap = {
        'Commercial': 'Commercial',
        'Delivery': 'Delivery',
        'Design': 'Design',
        'Corporate': 'Corporate',
        'Support': 'Support Services',
        'Others': 'Other'
    };

    if (disc === 'all') {
        selectedDiscs.clear();
        selectedDiscs.add('all');
    } else {
        const dbValue = normalizeDiscValue(discMap[disc] || disc);
        if (selectedDiscs.has('all')) selectedDiscs.delete('all');

        if (selectedDiscs.has(dbValue)) {
            selectedDiscs.delete(dbValue);
        } else {
            selectedDiscs.add(dbValue);
        }
        if (selectedDiscs.size === 0) selectedDiscs.add('all');
    }

    // Update UI
    const chips = document.querySelectorAll('#disc-filters .filter-chip');
    chips.forEach(chip => {
        const text = chip.textContent;
        if (text === 'All') {
            if (selectedDiscs.has('all')) chip.classList.add('active');
            else chip.classList.remove('active');
            return;
        }

        const dbValue = normalizeDiscValue(discMap[text] || text);
        if (selectedDiscs.has(dbValue)) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });

    updateCompactFilterLabels();
    loadDashboard();
}

// Toggle Status (Multi-select)
function toggleStatus(status) {
    if (status === null) {
        selectedStatuses.clear();
    } else {
        if (selectedStatuses.has(status)) {
            selectedStatuses.delete(status);
        } else {
            selectedStatuses.add(status);
        }
    }

    // Update UI
    const chips = document.querySelectorAll('#status-filters .filter-chip');
    chips.forEach(chip => {
        const title = chip.title;

        // Handle "All" button (no title or title='All')
        if (!title || title === 'All') {
            if (selectedStatuses.size === 0) {
                chip.classList.add('active');
                chip.style.opacity = '1';
            } else {
                chip.classList.remove('active');
                chip.style.opacity = '0.6';
            }
            return;
        }

        if (selectedStatuses.has(title)) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });

    updateCompactFilterLabels();
    loadDashboard();
}

// Filter by status (Multi-select)
function filterByStatus(status) {
    if (activeMeetingStatuses.has(status)) {
        activeMeetingStatuses.delete(status);
    } else {
        activeMeetingStatuses.add(status);
    }

    loadDashboard();
}

// View person details
function viewPerson(personId) {
    window.location.href = `/person/${personId}?from=dashboard`;
}

// Brief me
function briefMe(personId) {
    if (!personId) return;
    window.location.href = `/person/${personId}#briefing-section`;
}

// Quick capture
function resolveQuickCapturePerson() {
    const input = document.getElementById('qc-person-input');
    if (!input) return null;
    if (input.dataset.selectedPersonId) return input.dataset.selectedPersonId;
    const rawValue = input.value.trim().toLowerCase();
    if (!rawValue) return null;
    const exact = quickCapturePeople.find((person) => (person.full_name || '').toLowerCase() === rawValue)
        || quickCapturePeople.find((person) => `${person.full_name} ${person.company_name_raw || ''}`.trim().toLowerCase() === rawValue)
        || quickCapturePeople.find((person) => `${person.full_name} ${person.company_name_raw || ''}`.trim().toLowerCase().includes(rawValue));
    return exact ? exact.person_id : null;
}

function hideQuickCaptureResults() {
    const results = document.getElementById('qc-person-results');
    if (!results) return;
    results.hidden = true;
    results.innerHTML = '';
}

function selectQuickCapturePerson(person) {
    const input = document.getElementById('qc-person-input');
    if (!input || !person) return;
    input.value = person.full_name;
    input.dataset.selectedPersonId = person.person_id;
    hideQuickCaptureResults();
}

function renderQuickCaptureResults(query = '') {
    const input = document.getElementById('qc-person-input');
    const results = document.getElementById('qc-person-results');
    if (!input || !results) return;

    const matches = rankSearchMatches(
        quickCapturePeople,
        query,
        (person) => [person.full_name, person.company_name_raw, person.title_current, person.email_primary],
        8
    );

    if (!matches.length) {
        results.hidden = false;
        results.innerHTML = '<div class="ag-picker-empty">No matching contacts found.</div>';
        return;
    }

    results.hidden = false;
    results.innerHTML = matches.map((person) => `
        <button type="button" class="ag-picker-option ${String(input.dataset.selectedPersonId || '') === String(person.person_id) ? 'is-selected' : ''}" data-qc-person-result="${person.person_id}">
            <div class="ag-picker-title">${person.full_name}</div>
            <div class="ag-picker-meta">${person.title_current || 'No title'}${person.company_name_raw ? ` @ ${person.company_name_raw}` : ''}</div>
        </button>
    `).join('');

    results.querySelectorAll('[data-qc-person-result]').forEach((button) => {
        button.addEventListener('mousedown', (event) => event.preventDefault());
        button.addEventListener('click', () => {
            const person = quickCapturePeople.find((candidate) => String(candidate.person_id) === String(button.dataset.qcPersonResult));
            selectQuickCapturePerson(person);
        });
    });
}

function bindQuickCapturePicker() {
    const input = document.getElementById('qc-person-input');
    if (!input || input.dataset.bound === 'true') return;

    input.dataset.bound = 'true';
    input.addEventListener('input', () => {
        input.dataset.selectedPersonId = '';
        renderQuickCaptureResults(input.value);
    });
    input.addEventListener('focus', () => renderQuickCaptureResults(input.value));
    input.addEventListener('blur', () => {
        window.setTimeout(() => {
            if (document.activeElement !== input) {
                hideQuickCaptureResults();
            }
        }, 120);
    });
}

async function quickCapture() {
    const modal = document.getElementById('quick-capture-modal');
    const personInput = document.getElementById('qc-person-input');

    modal.style.display = 'flex';
    bindQuickCapturePicker();
    personInput.focus();

    if (quickCapturePeople.length === 0) {
        try {
            const res = await fetch(`${API_BASE}/api/people`);
            const data = await res.json();
            quickCapturePeople = data.people || [];
        } catch (err) {
            console.error('Failed to load people for quick capture', err);
        }
    }

    renderQuickCaptureResults(personInput.value);
}

function closeQuickCapture() {
    document.getElementById('quick-capture-modal').style.display = 'none';
    document.getElementById('qc-note-input').value = '';
    const personInput = document.getElementById('qc-person-input');
    personInput.value = '';
    personInput.dataset.selectedPersonId = '';
    hideQuickCaptureResults();
}

async function saveQuickCapture() {
    const nameInput = document.getElementById('qc-person-input');
    const noteInput = document.getElementById('qc-note-input');
    const modal = document.getElementById('quick-capture-modal');

    const name = nameInput.value;
    const note = noteInput.value;

    if (!note) {
        toast('Please enter a note', 'warning');
        return;
    }

    // Find person ID
    const personId = resolveQuickCapturePerson();

    if (!personId) {
        toast('Please choose a valid contact', 'warning');
        return;
    }

    const saveBtn = modal.querySelector('.btn-primary');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Saving...';
    saveBtn.disabled = true;

    try {
        const res = await fetch(`${API_BASE}/api/interactions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                person_id: personId,
                text: note,
                channel: 'quick_capture'
            })
        });

        if (res.ok) {
            closeQuickCapture();
            // Refresh feed if needed
            loadDashboard();
            toast('Note saved', 'success');
        } else {
            toast('Failed to save note', 'error');
        }
    } catch (err) {
        console.error(err);
        toast('Error saving note', 'error');
    } finally {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    }
}

function formatAbsoluteDate(dateStr) {
    if (!dateStr) return 'No date';
    const date = new Date(dateStr);
    if (Number.isNaN(date.getTime())) return dateStr;
    return date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function categoryDisplayLabel(value) {
    const normalized = normalizeCatValue(value);
    if (normalized === 'OBE M') return 'OBE Member';
    if (normalized === 'OBE T') return 'OBE Target';
    if (normalized === 'TGT') return 'Client Target';
    if (normalized === 'EXT') return 'Existing Client';
    if (normalized === 'HPC') return 'Candidate';
    if (normalized === 'TSA') return 'TS Advisory';
    if (normalized === 'GEN') return 'General';
    return normalized || String(value || '').trim();
}

function formatDashboardTitle(contact) {
    const title = String(contact.title_current || '').trim();
    const company = String(contact.company_name_raw || '').trim();
    if (title && company) {
        return title.toLowerCase().includes(company.toLowerCase()) ? title : `${title} @ ${company}`;
    }
    return title || company || 'No title';
}

function buildDashboardAttributeChips(contact) {
    const chips = [];
    const categoryValues = String(contact.cat || '')
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean);
    const categoryDisplay = categoryValues.map(categoryDisplayLabel).filter(Boolean).join(', ');
    if (categoryDisplay) chips.push(`<span class="contact-attr-chip">${escapeHtml(categoryDisplay)}</span>`);
    if (contact.contact_value) chips.push(`<span class="contact-attr-chip contact-attr-chip-status">${escapeHtml(normalizeContactValue(contact.contact_value))}</span>`);
    if (!chips.length && contact.env) {
        chips.push(`<span class="contact-attr-chip">${escapeHtml(normalizeEnvValue(contact.env))}</span>`);
    }
    return chips.slice(0, 2).join('');
}

function buildDashboardAttentionFlags(contact) {
    const flags = [];
    const overdueTaskCount = Math.max(0, Math.round(toFiniteNumber(contact?.overdue_open_task_count, 0)));
    if (overdueTaskCount > 0) {
        flags.push(`<span class="contact-alert-chip tone-danger">${overdueTaskCount} overdue</span>`);
    }
    if (!contact.has_future_cover) {
        flags.push('<span class="contact-alert-chip tone-danger">No next step</span>');
    }
    if (contact.follow_up_confirmation_needed) {
        flags.push('<span class="contact-alert-chip tone-warn">Confirm outcome</span>');
    }
    if ((contact.recent_cancelled_meeting_count || 0) > 0) {
        flags.push('<span class="contact-alert-chip tone-warn">Meeting cancelled</span>');
    } else if ((contact.recent_rescheduled_meeting_count || 0) > 0) {
        flags.push('<span class="contact-alert-chip tone-info">Meeting moved</span>');
    }
    return flags.slice(0, 2);
}

function renderContact(contact, listId) {
    const card = document.createElement('div');
    const temperature = contact.relationship_temperature || relationshipTemperatureApi.getTemperature(contact);
    card.className = `contact-card status-on_track temperature-card temperature-${temperature.stateKey}`;
    card.onclick = () => viewPerson(contact.person_id);
    card.style.setProperty('--temperature-progress', temperature.progress.toFixed(3));
    card.style.setProperty('--temperature-accent', temperature.accent);
    card.style.setProperty('--temperature-soft', temperature.softAccent);

    const initials = getInitials(contact.full_name);
    const avatarHtml = contact.profile_photo_url
        ? `
                    <div class="contact-avatar">
                        <img src="${API_BASE}/api/proxy/image?url=${encodeURIComponent(contact.profile_photo_url)}"
                             loading="lazy"
                             alt="${contact.full_name}"
                             style="width:100%; height:100%; object-fit:cover; border-radius:50%;"
                             onerror="const container=this.parentElement; if(container){container.innerHTML='${initials}'; container.style.background='var(--bg-secondary)';}">
                    </div>`
        : `<div class="contact-avatar">${initials}</div>`;

    const taskPreviewHtml = buildActionPriorityPreview(contact, temperature);
    const attentionFlags = buildDashboardAttentionFlags(contact);
    const attentionFlagsHtml = attentionFlags.length ? `<div class="contact-alert-row">${attentionFlags.join('')}</div>` : '';
    const attributeChips = buildDashboardAttributeChips(contact);
    const mainTitle = formatDashboardTitle(contact);

    card.innerHTML = `
                    <div class="contact-header">
                        ${avatarHtml}
                        <div class="contact-info">
                            <div class="contact-name">${escapeHtml(contact.full_name || 'Unknown Contact')}</div>
                            <div class="contact-title">${escapeHtml(mainTitle)}</div>
                            ${attributeChips ? `<div class="contact-attr-row">${attributeChips}</div>` : ''}
                            ${attentionFlagsHtml}
                        </div>
                    </div>
                    ${taskPreviewHtml}
                    `;

    document.getElementById(listId).appendChild(card);
}

// --- Dashboard Search ---
function performDashboardSearch() {
    const searchInput = document.getElementById('dashboard-search');
    const query = searchInput.value.trim().toLowerCase();

    // Get all contact cards
    const cards = document.querySelectorAll('.contact-card');

    if (!query) {
        // Show all cards if search is empty
        cards.forEach(card => card.style.display = '');
        return;
    }

    // Filter cards based on search query
    cards.forEach(card => {
        const name = card.querySelector('.contact-name')?.textContent.toLowerCase() || '';
        const title = card.querySelector('.contact-title')?.textContent.toLowerCase() || '';

        if (name.includes(query) || title.includes(query)) {
            card.style.display = '';
        } else {
            card.style.display = 'none';
        }
    });
}

function dashboardMobileMode() {
    return window.matchMedia('(max-width: 768px)').matches;
}

function syncDashboardMobileControls(forceOpen = null) {
    const toggle = document.getElementById('dashboard-mobile-controls-toggle');
    const panel = document.getElementById('dashboard-mobile-controls-panel');
    if (!toggle || !panel) return;

    if (!dashboardMobileMode()) {
        dashboardMobileControlsOpen = true;
        panel.classList.add('is-open');
        toggle.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'true');
        return;
    }

    if (forceOpen !== null) {
        dashboardMobileControlsOpen = Boolean(forceOpen);
    }

    panel.classList.toggle('is-open', dashboardMobileControlsOpen);
    toggle.classList.toggle('is-open', dashboardMobileControlsOpen);
    toggle.setAttribute('aria-expanded', dashboardMobileControlsOpen ? 'true' : 'false');
}

function toggleDashboardMobileControls() {
    dashboardMobileControlsOpen = !dashboardMobileControlsOpen;
    if (!dashboardMobileControlsOpen) {
        closeAllFilterDropdowns();
    }
    syncDashboardMobileControls();
}

// --- Navigation Logic ---
function toggleDashboardView() {
    showMeetingFeed();
}

function showMeetingFeed(updateHistory = true) {
    renderUniversalLayout('dashboard', 'RELATIONSHIP INTELLIGENCE');
    document.getElementById('relationship-age-filter').style.display = 'block';
    document.getElementById('status-filter-group').style.display = '';
    const statsGrid = document.querySelector('.stats-grid');
    if (statsGrid) statsGrid.style.display = 'grid';
    const title = document.getElementById('dashboard-mode-title');
    if (title) title.textContent = 'Dashboard';
    syncRelationshipAgeSlider();
    syncDashboardPriorityPresetControls();
    updateCompactFilterLabels();

    // Update History
    if (updateHistory) {
        const url = new URL(window.location);
        history.pushState({ view: 'dashboard' }, '', url.pathname);
    }

    loadDashboard();
    loadEventDashboardWidget();
}

// Handle browser Back button
window.onpopstate = function () {
    showMeetingFeed(false);
};

// Load on page ready
function initDashboardFromUrl() {
    relationshipAgeRange = { min: 0, max: getRelationshipAgeSliderMax() };
    activeDashboardPriorityPreset = 'default';
    dashboardMobileControlsOpen = !dashboardMobileMode();
    syncRelationshipAgeSlider();
    syncDashboardPriorityPresetControls();
    updateCompactFilterLabels();
    syncDashboardMobileControls();
    showMeetingFeed(false);
}

async function loadEventDashboardWidget() {
    try {
        const summary = await get('/api/events/dashboard/summary');
        renderEventDashboardWidget(summary);
    } catch (error) {
        console.error('Event widget load error:', error);
    }
}

function renderEventDashboardWidget(summary) {
    const widget = document.getElementById('event-dashboard-widget');
    const title = document.getElementById('event-dashboard-mini-title');
    const meta = document.getElementById('event-dashboard-mini-meta');
    if (!widget || !title || !meta) return;

    const upcomingEvents = summary.upcoming_events || [];
    if (!upcomingEvents.length) {
        widget.style.display = 'none';
        return;
    }

    const nextEvent = upcomingEvents[0];
    widget.style.display = 'block';
    widget.href = nextEvent?.event_id ? `/events/${nextEvent.event_id}` : '/events';
    title.textContent = nextEvent?.event_name || 'Upcoming events';
    meta.textContent = `${formatDate(nextEvent?.event_date)} | ${summary.upcoming_event_count || 0} upcoming`;
    widget.title = `${summary.upcoming_event_count || 0} upcoming events | ${summary.upcoming_linked_people || 0} linked people`;
}

document.addEventListener('DOMContentLoaded', () => {
    initDashboardFromUrl();
    syncRelationshipAgeSlider();
    loadEventDashboardWidget();
    window.addEventListener('resize', () => {
        syncDashboardMobileControls();
        syncRelationshipAgeSlider();
    });
    document.addEventListener('click', (event) => {
        if (!event.target.closest('.compact-filter-group')) {
            closeAllFilterDropdowns();
        }
    });
});


// --- Twin Chat Logic ---
let twinHistory = [];
let twinState = { busy: false, transcribing: false, actionRunning: false };

function escapeTwinHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatTwinText(value) {
    return escapeTwinHtml(value).replace(/\n/g, '<br>');
}

function twinCompanyHref(item) {
    const name = String(item?.company_name || item?.company_name_raw || '').trim();
    if (typeof window.companyDirectoryHref === 'function') {
        return window.companyDirectoryHref(name || item?.company_key || '');
    }
    const key = String(item?.company_key || name).trim().toLowerCase();
    return key ? `/companies/${encodeURIComponent(key)}` : '/companies';
}


function setTwinComposerState(disabled, placeholder) {
    const input = document.getElementById('twin-input');
    const sendBtn = document.querySelector('#twin-chat-modal .send-btn');
    const micBtn = document.getElementById('twin-mic-btn');
    if (input) {
        input.disabled = disabled;
        if (placeholder) input.placeholder = placeholder;
    }
    if (sendBtn) sendBtn.disabled = disabled;
    if (micBtn) micBtn.disabled = disabled;
}

function appendMessage(role, text, options = {}) {
    const historyDiv = document.getElementById('twin-history');
    const div = document.createElement('div');
    div.className = role === 'user' ? 'user-message' : 'assistant-message';
    div.innerHTML = options.html ? text : formatTwinText(text);
    historyDiv.appendChild(div);
    historyDiv.scrollTop = historyDiv.scrollHeight;
    return div;
}

function createTwinLoadingMessage(text) {
    const node = appendMessage('assistant', text);
    node.style.fontStyle = 'italic';
    return node;
}

function openTwinChat() {
    document.getElementById('twin-chat-modal').style.display = 'flex';
    document.getElementById('twin-input').focus();
    const fab = document.querySelector('.twin-fab');
    if (fab) fab.style.display = 'none';
}

function closeTwinChat() {
    document.getElementById('twin-chat-modal').style.display = 'none';
    const fab = document.querySelector('.twin-fab');
    if (fab) fab.style.display = 'flex';
}

async function sendTwinMessage() {
    const input = document.getElementById('twin-input');
    const message = (input.value || '').trim();
    if (!message || twinState.busy || twinState.actionRunning) return;
    if (message.length > 2000) {
        appendMessage('twin', 'Please keep messages under 2000 characters.');
        return;
    }
    twinState.busy = true;
    setTwinComposerState(true, 'Twin is working...');
    appendMessage('user', message);
    input.value = '';
    const loadingNode = createTwinLoadingMessage('Thinking...');
    try {
        const res = await fetch(`${API_BASE}/api/intelligence/twin/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, history: twinHistory })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.message || 'Twin request failed');
        loadingNode.remove();
        if (data.reply) appendMessage('twin', data.reply);
        if (data.data && Array.isArray(data.data)) renderSearchResults(data.data);
        if (data.pending_action && data.pending_action.type !== 'search') {
            await executeTwinAction(data.pending_action);
        }
        twinHistory.push({ role: 'user', content: message });
        const assistantBits = [];
        if (data.reply) assistantBits.push(data.reply);
        if (data.data && Array.isArray(data.data) && data.data.length) {
            const first = data.data[0] || {};
            const looksLikeCompanies = !!(first.result_type === 'company' || first.company_key);
            if (looksLikeCompanies) {
                const contextList = data.data
                    .map((company) => `${company.company_name || company.company_key || 'Unknown'} (${company.employee_count || 0} employees)`)
                    .join(', ');
                assistantBits.push(`[System Context: ${contextList}]`);
            } else {
                const contextList = data.data
                    .map((person) => `${person.full_name || 'Unknown'} (${person.company_name_raw || 'Unknown'})`)
                    .join(', ');
                assistantBits.push(`[System Context: ${contextList}]`);
            }
        }
        if (assistantBits.length) twinHistory.push({ role: 'assistant', content: assistantBits.join('\n\n') });
    } catch (err) {
        console.error(err);
        loadingNode.remove();
        appendMessage('twin', `Error: ${err.message}`);
    } finally {
        twinState.busy = false;
        setTwinComposerState(false, 'Ask or tell me something...');
        input.focus();
    }
}



async function executeTwinAction(action) {
    if (!action || twinState.actionRunning) return;
    twinState.actionRunning = true;
    const loadingNode = createTwinLoadingMessage('Executing action...');
    try {
        const res = await fetch(`${API_BASE}/api/intelligence/twin/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action_type: action.type, params: action.params })
        });
        const result = await res.json();
        if (!res.ok) throw new Error(result.detail || result.message || 'Action failed');
        loadingNode.remove();
        if (result.data) {
            if (Array.isArray(result.data)) {
                renderSearchResults(result.data);
            } else if (result.data.person_id) {
                appendMessage('twin', `Done: ${result.message || 'Contact ready.'}`);
                setTimeout(() => { window.location.href = `/person/${result.data.person_id}`; }, 800);
            } else {
                appendMessage('twin', result.message || 'Action completed.');
            }
        } else {
            appendMessage('twin', `Done: ${result.message || 'Done'}`);
        }
    } catch (err) {
        loadingNode.remove();
        appendMessage('twin', `Error: ${err.message}`);
    } finally {
        twinState.actionRunning = false;
    }
}

function renderSearchResults(results) {
    if (!results || results.length === 0) {
        appendMessage('twin', 'No results found.');
        return;
    }
    const companyCount = results.filter((item) => item && (item.result_type === 'company' || item.company_key)).length;
    const peopleCount = Math.max(0, results.length - companyCount);
    const historyDiv = document.getElementById('twin-history');
    const container = document.createElement('div');
    container.className = 'chat-message twin';
    container.style.background = 'transparent';
    container.style.border = 'none';
    container.style.padding = '0';
    let html = `<div style="display:flex; flex-direction:column; gap:0.5rem; width:100%;">`;
    html += `<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:0.25rem;"><span style="color:var(--text-muted); font-size:0.7rem; text-transform:uppercase; letter-spacing:1px;">${results.length} results (${peopleCount} contacts, ${companyCount} companies)</span></div>`;
    results.forEach((p) => {
        const isCompanyResult = !!(p && (p.result_type === 'company' || p.company_key));
        if (isCompanyResult) {
            const href = twinCompanyHref(p);
            const parentMeta = p.parent_company_name ? ` | Parent: ${escapeTwinHtml(p.parent_company_name)}` : '';
            const scoreText = Number.isFinite(Number(p.highest_employee_score)) ? `${Math.round(Number(p.highest_employee_score))}%` : '--';
            html += `<div onclick="window.location.href='${escapeTwinHtml(href)}'" style="background: var(--bg-card); border: 1px solid var(--glass-border); padding: 0.75rem; border-radius: 8px; cursor: pointer; transition: transform 0.2s; display: flex; justify-content: space-between; align-items: center;" onmouseover="this.style.borderColor='var(--accent-blue)'" onmouseout="this.style.borderColor='var(--glass-border)'"><div><div style="font-weight:700; color:var(--text-primary);">${escapeTwinHtml(p.company_name || p.company_key || 'Unknown company')}</div><div style="font-size:0.8rem; color:var(--text-secondary);">${escapeTwinHtml(p.company_type || 'Type not set')}${parentMeta}</div><div style="font-size:0.7rem; color:var(--accent-cyan); margin-top:2px;">${escapeTwinHtml(String(p.employee_count || 0))} employees | Highest score ${escapeTwinHtml(scoreText)}</div></div><div style="color:var(--accent-blue);">View</div></div>`;
        } else {
            html += `<div onclick="window.location.href='/person/${escapeTwinHtml(p.person_id || '')}'" style="background: var(--bg-card); border: 1px solid var(--glass-border); padding: 0.75rem; border-radius: 8px; cursor: pointer; transition: transform 0.2s; display: flex; justify-content: space-between; align-items: center;" onmouseover="this.style.borderColor='var(--accent-blue)'" onmouseout="this.style.borderColor='var(--glass-border)'"><div><div style="font-weight:700; color:var(--text-primary);">${escapeTwinHtml(p.full_name || 'Unknown')}</div><div style="font-size:0.8rem; color:var(--text-secondary);">${escapeTwinHtml(p.title_current || 'No Title')} @ ${escapeTwinHtml(p.company_name_raw || 'Unknown')}</div><div style="font-size:0.7rem; color:var(--accent-cyan); margin-top:2px;">${escapeTwinHtml(p.cat || '')}</div></div><div style="color:var(--accent-blue);">View</div></div>`;
        }
    });
    html += `</div>`;
    container.innerHTML = html;
    historyDiv.appendChild(container);
    historyDiv.scrollTop = historyDiv.scrollHeight;
}

async function pollTranscriptionJob(jobId) {
    const readJsonSafe = async (response) => {
        try {
            return await response.json();
        } catch (_err) {
            return {};
        }
    };

    const loadJob = async () => {
        const endpoints = [
            `${API_BASE}/api/intelligence/jobs/${jobId}`,
            `${API_BASE}/api/ai/jobs/${jobId}`,
        ];

        let lastError = 'Unable to read transcription job';
        for (const url of endpoints) {
            const res = await fetch(url);
            if (res.status === 404) {
                lastError = 'Job status endpoint is unavailable';
                continue;
            }
            const payload = await readJsonSafe(res);
            if (!res.ok) {
                throw new Error(payload.detail || payload.message || `Unable to read transcription job (${res.status})`);
            }
            return payload;
        }

        throw new Error(lastError);
    };

    for (let attempt = 0; attempt < 120; attempt++) {
        const job = await loadJob();
        if (job.status === 'completed') return job.result || {};
        if (job.status === 'failed') throw new Error(job.error_text || 'Transcription failed');
        await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    throw new Error('Transcription timed out');
}

async function processAudio(blob, mimeType = '') {
    const input = document.getElementById('twin-input');
    const formData = new FormData();
    const effectiveMime = String(mimeType || blob?.type || 'audio/webm').trim();
    const extension = typeof window.audioExtensionFromMimeType === 'function'
        ? window.audioExtensionFromMimeType(effectiveMime)
        : 'webm';
    formData.append('file', blob, `recording.${extension}`);
    try {
        twinState.transcribing = true;
        setTwinComposerState(true, 'Transcribing audio...');
        input.value = 'Queued for transcription...';
        const res = await fetch(`${API_BASE}/api/intelligence/transcribe`, { method: 'POST', body: formData });
        let data = {};
        try {
            data = await res.json();
        } catch (_err) {
            data = {};
        }
        if (!res.ok || !data.job_id) throw new Error(data.detail || data.message || 'No transcription job returned');
        const result = await pollTranscriptionJob(data.job_id);
        if (result.text) {
            input.value = result.text;
        } else {
            input.value = '';
            input.placeholder = 'Transcription returned no text.';
        }
    } catch (err) {
        console.error(err);
        input.value = '';
        input.placeholder = 'Error transcribing.';
        appendMessage('twin', `Error: ${err.message}`);
    } finally {
        twinState.transcribing = false;
        setTwinComposerState(false, 'Ask or tell me something...');
    }
}

let twinMediaRecorder;
let twinAudioChunks = [];

async function recordTwinAudio() {
    const micBtn = document.getElementById('twin-mic-btn');
    if (twinState.busy || twinState.transcribing) return;
    const micSupport = window.microphoneSupportStatus ? window.microphoneSupportStatus() : { supported: true };
    if (!micSupport.supported) {
        appendMessage('twin', micSupport.reason || 'Microphone recording is unavailable on this device/browser.');
        return;
    }
    if (twinMediaRecorder && twinMediaRecorder.state === 'recording') {
        twinMediaRecorder.stop();
        return;
    }
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const preferredMimeType = typeof window.preferredAudioRecorderMimeType === 'function'
            ? window.preferredAudioRecorderMimeType()
            : (MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '');
        const options = preferredMimeType ? { mimeType: preferredMimeType } : undefined;
        twinMediaRecorder = new MediaRecorder(stream, options);
        twinAudioChunks = [];
        twinMediaRecorder.ondataavailable = (e) => { twinAudioChunks.push(e.data); };
        twinMediaRecorder.onstop = async () => {
            const recordedMimeType = (twinMediaRecorder && twinMediaRecorder.mimeType) || preferredMimeType || 'audio/webm';
            const audioBlob = new Blob(twinAudioChunks, { type: recordedMimeType });
            micBtn.classList.remove('recording');
            micBtn.textContent = 'Mic';
            if (audioBlob.size === 0) {
                appendMessage('twin', 'Recording was empty. Please try again.');
                stream.getTracks().forEach((track) => track.stop());
                return;
            }
            await processAudio(audioBlob, recordedMimeType);
            stream.getTracks().forEach((track) => track.stop());
        };
        twinMediaRecorder.start(200);
        micBtn.classList.add('recording');
        micBtn.textContent = 'Stop';
    } catch (err) {
        console.error('Mic error:', err);
        appendMessage('twin', 'Microphone access was denied.');
    }
}

document.addEventListener('DOMContentLoaded', () => {
    if (typeof window.applyMicrophoneAvailability === 'function') {
        window.applyMicrophoneAvailability('twin-mic-btn', {
            supportedLabel: 'Mic',
            unsupportedLabel: 'No Mic',
        });
    }
});

