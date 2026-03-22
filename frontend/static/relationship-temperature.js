(function () {
    const SETTINGS_KEY = 'antigravity.relationshipTemperatureSettings';
    const DEFAULT_SETTINGS = {
        hotCadenceDays: 14,
        warmCadenceDays: 30,
        coldCadenceDays: 60,
        freezeStatuses: ['Frozen', 'Parked', 'Paused', 'Dormant', 'Lost'],
        coverGraceDays: 14,
    };

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function normalizeFreezeStatuses(value) {
        const raw = Array.isArray(value)
            ? value
            : String(value || '')
                .split(',')
                .map((entry) => entry.trim());

        const normalized = raw
            .map((entry) => String(entry || '').trim())
            .filter(Boolean);

        return normalized.length ? [...new Set(normalized)] : [...DEFAULT_SETTINGS.freezeStatuses];
    }

    function normalizeSettings(input) {
        return {
            hotCadenceDays: clamp(Math.round(Number(input?.hotCadenceDays) || DEFAULT_SETTINGS.hotCadenceDays), 3, 120),
            warmCadenceDays: clamp(Math.round(Number(input?.warmCadenceDays) || DEFAULT_SETTINGS.warmCadenceDays), 3, 180),
            coldCadenceDays: clamp(Math.round(Number(input?.coldCadenceDays) || DEFAULT_SETTINGS.coldCadenceDays), 3, 365),
            freezeStatuses: normalizeFreezeStatuses(input?.freezeStatuses),
            coverGraceDays: clamp(Math.round(Number(input?.coverGraceDays) || DEFAULT_SETTINGS.coverGraceDays), 0, 90),
        };
    }

    function getSettings() {
        try {
            return normalizeSettings(JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}'));
        } catch (error) {
            return normalizeSettings(DEFAULT_SETTINGS);
        }
    }

    function saveSettings(input) {
        const normalized = normalizeSettings(input);
        localStorage.setItem(SETTINGS_KEY, JSON.stringify(normalized));
        return normalized;
    }

    function resetSettings() {
        return saveSettings(DEFAULT_SETTINGS);
    }

    function normalizeContactValue(value) {
        const cleaned = String(value || '').trim().toLowerCase();
        if (cleaned === 'hot') return 'Hot';
        if (cleaned === 'cold') return 'Cold';
        return 'Warm';
    }

    function normalizeCategory(value) {
        const cleaned = String(value || '').trim().toUpperCase();
        if (cleaned === 'OBE MEMBER') return 'OBE M';
        if (cleaned === 'OBE TARGET') return 'OBE T';
        if (cleaned === 'TARGET CLIENT') return 'TGT';
        if (cleaned === 'CLIENT TARGET') return 'TGT';
        if (cleaned === 'EXISTING CLIENT') return 'EXT';
        if (cleaned === 'CANDIDATE') return 'HPC';
        return cleaned;
    }

    function getCadenceDays(contact, settings = getSettings()) {
        const contactValue = normalizeContactValue(contact?.contact_value);
        let cadenceDays = settings.warmCadenceDays;

        if (contactValue === 'Hot') cadenceDays = settings.hotCadenceDays;
        if (contactValue === 'Cold') cadenceDays = settings.coldCadenceDays;

        const engagementStatus = String(contact?.engagement_status || '').trim().toLowerCase();
        if (engagementStatus === 'active') cadenceDays *= 0.9;
        if (engagementStatus === 'dormant') cadenceDays *= 1.2;
        if (engagementStatus === 'lost') cadenceDays *= 1.4;

        const categories = String(contact?.cat || '')
            .split(',')
            .map(normalizeCategory);
        if (categories.includes('TGT') || categories.includes('HPC')) cadenceDays *= 0.9;
        if (categories.includes('EXT')) cadenceDays *= 1.18;
        if (categories.includes('OBE M')) cadenceDays *= 1.1;
        if (contact?.is_ts_advisory_candidate) cadenceDays *= 0.95;

        return clamp(Math.round(cadenceDays), 7, 180);
    }

    function isFrozen(contact, settings = getSettings()) {
        const engagementStatus = String(contact?.engagement_status || '').trim();
        const normalizedStatus = engagementStatus.toLowerCase();
        if (!normalizedStatus) return false;

        const configured = normalizeFreezeStatuses(settings.freezeStatuses).map((entry) => entry.toLowerCase());
        if (configured.includes(normalizedStatus)) return true;

        return ['frozen', 'parked', 'paused', 'on hold', 'hold'].some((token) => normalizedStatus.includes(token));
    }

    function parseFutureDate(value) {
        if (!value) return null;
        const parsed = new Date(String(value).replace(' ', 'T'));
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    function getCoverDate(contact) {
        const candidates = [
            parseFutureDate(contact?.next_meeting_date),
            parseFutureDate(contact?.next_contact_due_date),
        ].filter(Boolean);
        if (!candidates.length) return null;
        candidates.sort((a, b) => a.getTime() - b.getTime());
        return candidates[0];
    }

    function hasTaskCover(contact, taskPreview, settings = getSettings()) {
        if (taskPreview) return true;

        const futureDate = getCoverDate(contact);
        if (!futureDate) return false;

        const now = new Date();
        const diffDays = Math.ceil((futureDate - now) / (1000 * 60 * 60 * 24));
        return diffDays >= -settings.coverGraceDays;
    }

    function getTemperature(contact, options = {}) {
        const settings = options.settings || getSettings();
        const taskPreview = options.taskPreview || null;
        const cadenceDays = getCadenceDays(contact, settings);
        const cover = hasTaskCover(contact, taskPreview, settings);
        const frozen = isFrozen(contact, settings);
        const ageDays = Number(contact?.last_success_age_days);
        const ageKnown = Number.isFinite(ageDays) && ageDays >= 0;
        const meetingStatus = String(contact?.meeting_status || 'not_scheduled').toLowerCase();
        const nextMeetingDate = parseFutureDate(contact?.next_meeting_date);
        const nextMeetingInDays = nextMeetingDate
            ? Math.ceil((nextMeetingDate - new Date()) / (1000 * 60 * 60 * 24))
            : null;
        const bookedMeetingSoon = Number.isFinite(nextMeetingInDays) && nextMeetingInDays >= 0 && nextMeetingInDays <= 7;
        const bookedMeetingImminent = Number.isFinite(nextMeetingInDays) && nextMeetingInDays >= 0 && nextMeetingInDays <= 2;
        const contactValue = normalizeContactValue(contact?.contact_value);
        const engagementStatus = String(contact?.engagement_status || '').trim() || 'Unspecified';
        const freezeReason = String(contact?.engagement_status || '').trim() || 'Frozen by status';

        if (frozen) {
            return {
                score: 100,
                stateKey: 'frozen',
                stateLabel: 'Frozen',
                accent: '#94a3b8',
                softAccent: 'rgba(148, 163, 184, 0.2)',
                cadenceDays,
                ageDays,
                ageKnown,
                pressure: 0,
                progress: 0.08,
                isFrozen: true,
                hasCover: cover,
                headline: freezeReason,
                detail: ageKnown
                    ? `${ageDays}d since meaningful contact | cadence muted`
                    : 'Warnings muted until reactivated',
                stage: 'Warnings suppressed',
                recommendation: 'Review when this relationship is reactivated',
                contactValue,
                engagementStatus,
            };
        }

        const pressure = ageKnown ? ageDays / Math.max(cadenceDays, 1) : 1.8;
        let score = ageKnown
            ? Math.round(100 - Math.max(0, pressure - 0.25) * 58)
            : 28;

        if (cover) score += 14;
        if (bookedMeetingSoon) score += 18;
        if (bookedMeetingImminent) score += 10;
        if (meetingStatus === 'on_track') score += 8;
        if (meetingStatus === 'soon') score += 2;
        if (meetingStatus === 'overdue') score -= 12;
        if (meetingStatus === 'not_scheduled') score -= 8;
        if (contactValue === 'Hot') score -= 4;
        if (contactValue === 'Cold') score += 4;
        if (String(contact?.engagement_status || '').trim().toLowerCase() === 'active') score += 4;

        if (!ageKnown && bookedMeetingSoon) {
            score = Math.max(score, bookedMeetingImminent ? 82 : 66);
        }

        score = clamp(score, 0, 100);

        let stateKey = 'critical';
        let stateLabel = 'Critical';
        let accent = '#ef4444';
        let softAccent = 'rgba(239, 68, 68, 0.18)';

        if (score >= 78) {
            stateKey = 'on_track';
            stateLabel = 'On Track';
            accent = '#38bdf8';
            softAccent = 'rgba(56, 189, 248, 0.16)';
        } else if (score >= 58) {
            stateKey = 'due_soon';
            stateLabel = 'Due Soon';
            accent = '#f59e0b';
            softAccent = 'rgba(245, 158, 11, 0.18)';
        } else if (score >= 34) {
            stateKey = 'needs_attention';
            stateLabel = 'Needs Attention';
            accent = '#f97316';
            softAccent = 'rgba(249, 115, 22, 0.2)';
        }

        const progress = clamp((100 - score) / 100, 0, 1);
        const headline = ageKnown
            ? `${ageDays}d since meaningful contact`
            : 'No meaningful contact captured';
        const detailParts = [`Cadence ${cadenceDays}d`];
        if (bookedMeetingSoon) {
            detailParts.push(nextMeetingInDays === 0 ? 'meeting booked today' : `meeting booked in ${nextMeetingInDays}d`);
        } else {
            detailParts.push(cover ? 'next step covered' : 'no next step booked');
        }
        if (engagementStatus && engagementStatus.toLowerCase() !== 'unspecified') {
            detailParts.push(engagementStatus);
        }

        let stage = 'Cadence protected';
        if (stateKey === 'due_soon') stage = `Approaching cadence at ${cadenceDays}d`;
        if (stateKey === 'needs_attention') stage = `Past cadence target of ${cadenceDays}d`;
        if (stateKey === 'critical') stage = `Well beyond cadence target of ${cadenceDays}d`;

        let recommendation = 'Maintain a light touch and keep momentum warm';
        if (stateKey === 'due_soon') recommendation = 'Line up the next touchpoint before temperature slips';
        if (stateKey === 'needs_attention') recommendation = 'Re-open the loop with a clear reason to connect';
        if (stateKey === 'critical') recommendation = 'Prioritize a meaningful re-engagement now';

        return {
            score,
            stateKey,
            stateLabel,
            accent,
            softAccent,
            cadenceDays,
            ageDays,
            ageKnown,
            pressure,
            progress,
            isFrozen: false,
            hasCover: cover,
            headline,
            detail: detailParts.join(' | '),
            stage,
            recommendation,
            contactValue,
            engagementStatus,
        };
    }

    function matchesScoreRange(temperature, range) {
        const min = Math.max(0, Number(range?.min) || 0);
        const max = Math.min(100, Number(range?.max) || 100);
        return temperature.score >= min && temperature.score <= max;
    }

    function buildLegend(settings = getSettings()) {
        return `Hot ${settings.hotCadenceDays}d | Warm ${settings.warmCadenceDays}d | Cold ${settings.coldCadenceDays}d | Frozen statuses stay quiet`;
    }

    window.RelationshipTemperature = {
        SETTINGS_KEY,
        DEFAULT_SETTINGS,
        normalizeSettings,
        getSettings,
        saveSettings,
        resetSettings,
        getCadenceDays,
        getTemperature,
        isFrozen,
        matchesScoreRange,
        buildLegend,
    };
})();
