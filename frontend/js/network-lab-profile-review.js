const apiBase = window.API_BASE || '';
const PROFILE_SIGNATURE_CACHE_PREFIX = 'ag.network_lab_profile.signature.v2.';
const LEGACY_PROFILE_SIGNATURE_CACHE_PREFIXES = ['ag.network_lab_profile.signature.v1.'];
const PROFILE_TRANSCRIPT_TAG_CACHE_PREFIX = 'ag.network_lab_profile.transcript_tags.v1.';
const LEGACY_PROFILE_TRANSCRIPT_TAG_CACHE_PREFIXES = ['ag.network_lab_profile.transcript_tags.v0.'];

const profileState = {
    payload: null,
    stage2Base: {},
    stage2: {},
    latestProfileSignature: '',
    transcriptMode: 'stage',
    evidenceById: new Map(),
    segmentTagsByMode: {
        stage: new Map(),
        knowledge: new Map()
    },
    segmentTagErrorsByMode: {
        stage: new Map(),
        knowledge: new Map()
    },
    segmentTagHasRun: {
        stage: false,
        knowledge: false
    },
    segmentTagBusy: false,
    segmentTagRunId: 0,
    segmentTagModelName: '',
    segmentTagLastError: '',
    actionWidgetBusy: false,
    actionWidgetRunId: 0,
    reactivePollHandle: 0,
    reactivePollBusy: false,
    activeEvidenceId: null,
    modalEditing: false,
    modalBusy: false,
    deletingEvidenceIds: new Set()
};

const DEFAULT_RELATIONSHIP_STAGES = [
    { code: 'S1', label: 'S1 Introduction', summary: 'Very early relationship with light contact only.' },
    { code: 'S2', label: 'S2 Understand', summary: 'Building understanding of the person, role, company, and context.' },
    { code: 'S3', label: 'S3 Position', summary: 'Taylor Sterling positioning is visible, but relationship depth is still early.' },
    { code: 'S4', label: 'S4 Nurture', summary: 'Relationship is active and healthy with no defined opportunity yet.' },
    { code: 'S5', label: 'S5 Problem Identified', summary: 'A need, pressure, or talent gap is visible.' },
    { code: 'S6', label: 'S6 Active Discussion', summary: 'A role, assignment, or commercial need is being discussed.' },
    { code: 'S7', label: 'S7 Conversion Pending', summary: 'Commercial commitment is being shaped.' },
    { code: 'S8', label: 'S8 Active Client', summary: 'A live assignment is underway.' },
    { code: 'S9', label: 'S9 Active Nurture', summary: 'A mature trusted relationship is being maintained between assignments.' }
];

const DEFAULT_OPPORTUNITY_STAGES = [
    { code: 'O1', label: 'O1 Mature Problem Identified', summary: 'An emerging need is visible.' },
    { code: 'O2', label: 'O2 Mature Active Discussion', summary: 'A role or commercial need is under active discussion.' },
    { code: 'O3', label: 'O3 Mature Conversion Pending', summary: 'Commercial terms or commitment are being shaped.' },
    { code: 'O4', label: 'O4 Mature Problem Identified', summary: 'A new need is identified inside a mature relationship.' },
    { code: 'O5', label: 'O5 Mature Active Discussion', summary: 'A repeat or follow-on role is in active discussion.' },
    { code: 'O6', label: 'O6 Mature Conversion Pending', summary: 'A repeat or follow-on assignment is being shaped commercially.' },
    { code: 'O7', label: 'O7 Mature Active Client', summary: 'A live assignment is underway.' }
];

const DEFAULT_STAGE_TRANSCRIPT_RULES = [
    { code: 'O7', label: 'O7 Mature Active Client', keywords: ['live assignment', 'assignment underway', 'onboarding', 'mobilized', 'mobilised', 'currently delivering'] },
    { code: 'O6', label: 'O6 Mature Conversion Pending', keywords: ['repeat assignment', 'follow-on', 'renewal', 'extension', 'commercial terms'] },
    { code: 'O3', label: 'O3 Mature Conversion Pending', keywords: ['commercial terms', 'scope', 'proposal', 'contract', 'commitment', 'fee', 'sign off', 'signoff'] },
    { code: 'O5', label: 'O5 Mature Active Discussion', keywords: ['repeat role', 'follow-on role', 'again with us', 'continuing brief'] },
    { code: 'O2', label: 'O2 Mature Active Discussion', keywords: ['role', 'assignment', 'mandate', 'hiring', 'hire', 'live role', 'open role', 'replacement', 'succession', 'headcount'] },
    { code: 'O4', label: 'O4 Mature Problem Identified', keywords: ['new need in existing account', 'new issue with existing client', 'fresh pressure in existing relationship'] },
    { code: 'O1', label: 'O1 Mature Problem Identified', keywords: ['need', 'pressure', 'gap', 'challenge', 'shortage', 'demand', 'critical'] },
    { code: 'S4', label: 'S4 Nurture', keywords: ['relationship is warm', 'active relationship', 'keep in touch', 'maintain relationship'] },
    { code: 'S3', label: 'S3 Position', keywords: ['taylor sterling', 'presentation', 'introduced', 'understands what we do', 'positioning', "taylor stirling's abilities", "presentation of exactly what taylor stirling's abilities are", 'presenting taylor sterling', 'presenting taylor stirling', 'presentation with taylor sterling'] },
    { code: 'S2', label: 'S2 Understand', keywords: ['their role', 'their company', 'team size', 'context', 'responsible for', 'market focus'] },
    { code: 'S1', label: 'S1 Introduction', keywords: ['first call', 'intro call', 'initial conversation', 'just met'] },
    { code: 'S9', label: 'S9 Active Nurture', keywords: ['trusted relationship', 'between assignments', 'repeat relationship', 'active nurture'] }
];

const DEFAULT_KNOWLEDGE_BUCKET_DEFS = [
    {
        box_id: 1,
        code: 'K1',
        box_key: 'family_status',
        box_title: 'Family Status',
        keywords: ['partner', 'spouse', 'wife', 'husband', 'married', 'single', 'divorced', 'children', 'daughter', 'son', 'kids', 'pet', 'dog', 'cat', 'family based', 'grandparents', 'grandfather', 'grandkids', 'grandchildren', 'years old', '50s', '60s', '70s', 'in his 60s', 'in her 60s', 'in his 70s', 'in her 70s', 'in his 50s', 'in her 50s', 'live in the us', 'some of them live in']
    },
    {
        box_id: 2,
        code: 'K2',
        box_key: 'family_interests',
        box_title: 'Family Interests',
        keywords: ['family travel', 'family holiday', 'weekend', 'kids activities', 'school activities', 'family routine', 'walking the dog', 'summer trip']
    },
    {
        box_id: 3,
        code: 'K3',
        box_key: 'personal_interests',
        box_title: 'Personal Interests',
        keywords: ['running', 'golf', 'fishing', 'gym', 'cars', 'food', 'books', 'watches', 'hiking', 'fitness', 'travel', 'skiing', 'ski']
    },
    {
        box_id: 4,
        code: 'K4',
        box_key: 'business_understanding',
        box_title: 'Business Understanding',
        keywords: ['company', 'division', 'role', 'director', 'team', 'market focus', 'projects', 'project management', 'sector', 'seniority', 'leadership', 'responsible', 'board', 'managing director', 'consultant', 'cost consultant', 'omnium', 'gcc', 'dubai', 'united arab emirates', 'footprint', 'emar', 'acom', 'dg jones', 'no longer an active part of the business']
    },
    {
        box_id: 5,
        code: 'K5',
        box_key: 'challenges_demands',
        box_title: 'Challenges and Demands',
        keywords: ['pressure', 'critical', 'struggling', 'workload', 'gap', 'shortage', 'delivery', 'resource', 'internal change', 'demand', 'knee operations', 'knee operation', 'operation', 'operations', 'surgery', 'surgeries']
    },
    {
        box_id: 6,
        code: 'K6',
        box_key: 'recruitment_signals',
        box_title: 'Recruitment Signals',
        keywords: ['hiring', 'hire', 'live role', 'active role', 'position', 'replacement', 'succession', 'build-out', 'team growth', 'mandate', 'placed', 'placed about', 'growth', '160 people']
    },
    {
        box_id: 7,
        code: 'K7',
        box_key: 'market_intelligence',
        box_title: 'Market Intelligence',
        keywords: ['market', 'salary', 'inflation', 'candidate shortage', 'pipeline', 'sector', 'competitor', 'competition', 'client behavior', 'regional demand']
    },
    {
        box_id: 8,
        code: 'K8',
        box_key: 'taylor_sterling_positioning',
        box_title: 'Taylor Sterling Positioning',
        keywords: ['taylor sterling', 'taylor stirling', 'presentation', 'introduced our services', 'understands what we do', 'know what we do', 'they do know what we do', 'model', 'objection', 'interest in support', 'abilities', 'presenting taylor sterling', 'presenting taylor stirling', 'presentation with taylor sterling']
    },
    {
        box_id: 9,
        code: 'K9',
        box_key: 'obe_interest',
        box_title: 'OBE Interest',
        keywords: ['obe', 'breakfast', 'roundtable', 'event', 'join network', 'attend', 'host', 'introduction']
    },
    {
        box_id: 10,
        code: 'K10',
        box_key: 'action_follow_up',
        box_title: 'Action / Follow-Up',
        keywords: ['follow up', 'next step', 'arrange meeting', 'send', 'share', 'invite', 'reconnect', 'next week', 'next couple of weeks', 'need to sit down', 'sit down', 'go through', 'after the e-break', 'week and a half', 'i spoke to his colleague', 'spoke to his colleague']
    },
    {
        box_id: 11,
        code: 'K11',
        box_key: 'relationship_signal',
        box_title: 'Relationship Signal',
        keywords: ['warm', 'trust', 'open', 'responsive', 'engaged', 'hesitation', 'guarded', 'distance', 'momentum', 'last spoke', 'known peter for', 'known for about', 'plenty of discussions over the years', 'plenty of business over the years', 'used us a lot before', 'not used us recently']
    }
];

let RELATIONSHIP_STAGES = DEFAULT_RELATIONSHIP_STAGES.map((item) => ({ ...item }));
let OPPORTUNITY_STAGES = DEFAULT_OPPORTUNITY_STAGES.map((item) => ({ ...item }));
let STAGE_TRANSCRIPT_RULES = DEFAULT_STAGE_TRANSCRIPT_RULES.map((item) => ({ ...item }));
let KNOWLEDGE_BUCKET_DEFS = DEFAULT_KNOWLEDGE_BUCKET_DEFS.map((item) => ({ ...item }));
let KNOWLEDGE_TRANSCRIPT_RULES = [];
let STAGE_LABEL_LOOKUP = {};
const LEGACY_OPPORTUNITY_STAGE_CODE_MAP = {
    S5: 'O1',
    S6: 'O2',
    S7: 'O3',
    S5M: 'O4',
    S6M: 'O5',
    S7M: 'O6',
    S8: 'O7',
    R1: 'O1',
    R2: 'O2',
    R3: 'O3',
    R4: 'O4',
    R5: 'O5',
    R6: 'O6',
    R7: 'O7'
};

function normalizeOpportunityCode(code) {
    const normalized = String(code || '').trim().toUpperCase();
    return LEGACY_OPPORTUNITY_STAGE_CODE_MAP[normalized] || normalized;
}

function normalizeKnowledgeCode(code, boxId) {
    const raw = String(code || '').trim().toUpperCase();
    const match = raw.match(/^K?\s*(\d{1,2})$/);
    if (match) return `K${Number(match[1])}`;
    return `K${Number(boxId || 0)}`;
}

function normalizeOpportunityLabel(code, label) {
    const stageCode = normalizeOpportunityCode(code);
    let raw = String(label || '').trim();
    raw = raw.replace(/^[SRO][0-9M]+\s+/i, '').trim();
    if (stageCode.startsWith('O')) {
        if (raw && !/^mature\s+/i.test(raw)) raw = `Mature ${raw}`;
        return `${stageCode} ${raw || 'Mature Stage'}`.trim();
    }
    return raw ? `${stageCode} ${raw}`.trim() : stageCode;
}

function rebuildTaggingRuntime() {
    KNOWLEDGE_TRANSCRIPT_RULES = KNOWLEDGE_BUCKET_DEFS.map((bucket) => ({
        key: bucket.box_key,
        label: `${String(bucket.code || `K${Number(bucket.box_id || 0) || 0}`).toUpperCase()} ${bucket.box_title}`,
        className: `kb-${bucket.box_key}`,
        keywords: Array.isArray(bucket.keywords) ? bucket.keywords : []
    }));
    STAGE_LABEL_LOOKUP = {};
    for (const item of [...RELATIONSHIP_STAGES, ...OPPORTUNITY_STAGES]) {
        const code = String((item && item.code) || '').toUpperCase();
        if (code && !STAGE_LABEL_LOOKUP[code]) {
            STAGE_LABEL_LOOKUP[code] = String((item && item.label) || code);
        }
    }
}

function safeList(value) {
    return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') : [];
}

function safeTextList(value) {
    return Array.isArray(value)
        ? value.map((item) => String(item || '').trim()).filter(Boolean)
        : [];
}

function applyTranscriptTaggingConfig(config) {
    const source = config && typeof config === 'object' ? config : {};

    const relationship = safeList(source.stage_relationship).map((item) => ({
        code: String(item.code || '').trim().toUpperCase(),
        label: String(item.label || item.code || '').trim(),
        summary: String(item.summary || '').trim()
    })).filter((item) => item.code);
    if (relationship.length) {
        const byCode = new Map(relationship.map((item) => [item.code, item]));
        const merged = DEFAULT_RELATIONSHIP_STAGES.map((fallback) => ({
            ...(byCode.get(String(fallback.code || '').toUpperCase()) || fallback)
        }));
        const extras = relationship.filter((item) => !DEFAULT_RELATIONSHIP_STAGES.some((fallback) => fallback.code === item.code));
        RELATIONSHIP_STAGES = [...merged, ...extras];
    } else {
        RELATIONSHIP_STAGES = DEFAULT_RELATIONSHIP_STAGES.map((item) => ({ ...item }));
    }

    const opportunity = safeList(source.stage_opportunity).map((item) => ({
        code: normalizeOpportunityCode(item.code),
        label: normalizeOpportunityLabel(item.code, item.label || item.code || ''),
        summary: String(item.summary || '').trim()
    })).filter((item) => item.code);
    if (opportunity.length) {
        const byCode = new Map(opportunity.map((item) => [item.code, item]));
        const merged = DEFAULT_OPPORTUNITY_STAGES.map((fallback) => ({
            ...(byCode.get(String(fallback.code || '').toUpperCase()) || fallback)
        }));
        const extras = opportunity.filter((item) => !DEFAULT_OPPORTUNITY_STAGES.some((fallback) => fallback.code === item.code));
        OPPORTUNITY_STAGES = [...merged, ...extras];
    } else {
        OPPORTUNITY_STAGES = DEFAULT_OPPORTUNITY_STAGES.map((item) => ({ ...item }));
    }

    const stageRules = safeList(source.stage_rules).map((item) => ({
        code: normalizeOpportunityCode(item.code),
        label: normalizeOpportunityLabel(item.code, item.label || item.code || ''),
        keywords: safeTextList(item.keywords)
    })).filter((item) => item.code);
    if (stageRules.length) STAGE_TRANSCRIPT_RULES = stageRules;
    else STAGE_TRANSCRIPT_RULES = DEFAULT_STAGE_TRANSCRIPT_RULES.map((item) => ({ ...item }));

    const knowledgeBuckets = safeList(source.knowledge_buckets).map((item, index) => ({
        box_id: Number(item.box_id || (index + 1)),
        code: normalizeKnowledgeCode(item.code, Number(item.box_id || (index + 1))),
        box_key: String(item.box_key || '').trim(),
        box_title: String(item.box_title || item.box_key || '').trim(),
        keywords: safeTextList(item.keywords)
    })).filter((item) => item.box_key);
    if (knowledgeBuckets.length) KNOWLEDGE_BUCKET_DEFS = knowledgeBuckets;
    else KNOWLEDGE_BUCKET_DEFS = DEFAULT_KNOWLEDGE_BUCKET_DEFS.map((item) => ({ ...item }));

    rebuildTaggingRuntime();
}

applyTranscriptTaggingConfig(null);

function esc(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function personIdFromPath() {
    const queryId = new URL(window.location.href).searchParams.get('person_id');
    if (queryId && String(queryId).trim()) return String(queryId).trim();
    const segments = window.location.pathname.split('/').filter(Boolean);
    const candidate = String(segments[segments.length - 1] || '').trim();
    const lowered = candidate.toLowerCase();
    if (!candidate || lowered === 'network-lab-profile.html' || lowered === 'network-lab' || lowered === 'profile') {
        return '';
    }
    return decodeURIComponent(candidate);
}

function normalizeWhitespace(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}

function formatDateLabel(value) {
    const text = String(value || '').trim();
    if (!text) return 'Unknown';
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) return text.slice(0, 10) || text;
    return parsed.toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatDateTimeLabel(value) {
    const text = String(value || '').trim();
    if (!text) return 'Unknown time';
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) return text;
    return parsed.toLocaleString('en-GB', {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false
    });
}

function previewLine(value, limit = 220) {
    const line = normalizeWhitespace(value);
    if (!line) return '';
    if (line.length <= limit) return line;
    return `${line.slice(0, limit - 3).trimEnd()}...`;
}

function profilePayloadSignature(payload = {}) {
    const stage2Raw = payload.relationship_business_flow_stage2
        || ((payload.briefing && payload.briefing.relationship_business_flow_stage2) || {});
    const relationshipCode = String(((stage2Raw.relationship_stage || {}).code) || '').toUpperCase();
    const opportunityCode = String(((stage2Raw.opportunity_stage || {}).code) || '').toUpperCase();
    const overrideCode = String(((payload.person || {}).relationship_stage_override) || '').toUpperCase();
    const items = Array.isArray(payload.evidence_inputs) ? payload.evidence_inputs : [];
    const evidenceSig = items
        .map((item) => {
            const id = String((item && item.evidence_id) || '').trim();
            const dateAt = String((item && item.date_at) || (item && item.date_label) || '').trim();
            const contentLength = String(((item && item.content) || '').length);
            return `${id}:${dateAt}:${contentLength}`;
        })
        .join('|');
    return `${relationshipCode}|${opportunityCode}|${overrideCode}|${evidenceSig}`;
}

function profileSignatureStorageKey(personId) {
    return `${PROFILE_SIGNATURE_CACHE_PREFIX}${String(personId || '').trim()}`;
}

function readStoredProfileSignature(personId) {
    const key = profileSignatureStorageKey(personId);
    if (!key || key.endsWith('.')) return '';
    try {
        return String(window.localStorage.getItem(key) || '');
    } catch (_error) {
        return '';
    }
}

function writeStoredProfileSignature(personId, signature) {
    const key = profileSignatureStorageKey(personId);
    const value = String(signature || '').trim();
    if (!key || key.endsWith('.') || !value) return;
    try {
        window.localStorage.setItem(key, value);
    } catch (_error) {
        // Non-blocking if storage is unavailable.
    }
}

function transcriptTagCacheStorageKey(personId) {
    return `${PROFILE_TRANSCRIPT_TAG_CACHE_PREFIX}${String(personId || '').trim()}`;
}

function resetTranscriptTagRuntime() {
    profileState.segmentTagsByMode.stage = new Map();
    profileState.segmentTagsByMode.knowledge = new Map();
    profileState.segmentTagErrorsByMode.stage = new Map();
    profileState.segmentTagErrorsByMode.knowledge = new Map();
    profileState.segmentTagHasRun.stage = false;
    profileState.segmentTagHasRun.knowledge = false;
    profileState.segmentTagModelName = '';
    profileState.segmentTagLastError = '';
}

function safeSegmentRow(segment, fallbackIndex) {
    return {
        index: Number((segment && segment.index) || fallbackIndex || 0),
        segment_hash: String((segment && segment.segment_hash) || ''),
        text: String((segment && segment.text) || ''),
        tag_code: String((segment && segment.tag_code) || ''),
        tag_label: String((segment && segment.tag_label) || ''),
        tag_class: String((segment && segment.tag_class) || ''),
        mapped: !!(segment && segment.mapped),
        confidence: Number((segment && segment.confidence) || 0),
        reason: String((segment && segment.reason) || ''),
        source: String((segment && segment.source) || '')
    };
}

function serializeTranscriptModeCache(mode) {
    const cache = profileState.segmentTagsByMode && profileState.segmentTagsByMode[mode] instanceof Map
        ? profileState.segmentTagsByMode[mode]
        : new Map();
    const errorCache = profileState.segmentTagErrorsByMode && profileState.segmentTagErrorsByMode[mode] instanceof Map
        ? profileState.segmentTagErrorsByMode[mode]
        : new Map();
    return {
        has_run: !!(profileState.segmentTagHasRun && profileState.segmentTagHasRun[mode]),
        model_name: String(profileState.segmentTagModelName || ''),
        rows: Array.from(cache.entries()).map(([evidenceId, row]) => ({
            evidence_id: String(evidenceId || ''),
            model_name: String((row && row.model_name) || ''),
            segments: Array.isArray(row && row.segments)
                ? row.segments.map((segment, index) => safeSegmentRow(segment, index))
                : [],
            error: String((row && row.error) || '')
        })),
        errors: Array.from(errorCache.entries()).map(([evidenceId, message]) => ({
            evidence_id: String(evidenceId || ''),
            error: String(message || '')
        }))
    };
}

function restoreTranscriptModeCache(mode, modePayload) {
    const cache = new Map();
    const errorCache = new Map();
    const payload = modePayload && typeof modePayload === 'object' ? modePayload : {};
    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    for (const row of rows) {
        const evidenceId = String((row && row.evidence_id) || '').trim();
        if (!evidenceId) continue;
        const segments = Array.isArray(row && row.segments)
            ? row.segments.map((segment, index) => safeSegmentRow(segment, index))
            : [];
        cache.set(evidenceId, {
            evidence_id: evidenceId,
            model_name: String((row && row.model_name) || ''),
            segments,
            error: String((row && row.error) || '')
        });
    }
    const errors = Array.isArray(payload.errors) ? payload.errors : [];
    for (const row of errors) {
        const evidenceId = String((row && row.evidence_id) || '').trim();
        if (!evidenceId) continue;
        const message = String((row && row.error) || '').trim();
        if (message) errorCache.set(evidenceId, message);
    }
    const hasRun = !!payload.has_run || cache.size > 0 || errorCache.size > 0;
    const modelName = String(payload.model_name || '').trim();
    return { cache, errorCache, hasRun, modelName };
}

function readStoredTranscriptTagCache(personId, signature) {
    const key = transcriptTagCacheStorageKey(personId);
    const expectedSignature = String(signature || '').trim();
    if (!key || key.endsWith('.') || !expectedSignature) return false;
    try {
        const raw = window.localStorage.getItem(key);
        if (!raw) return false;
        const payload = JSON.parse(raw);
        if (!payload || typeof payload !== 'object') return false;
        if (String(payload.signature || '').trim() !== expectedSignature) return false;
        const modes = payload.modes && typeof payload.modes === 'object' ? payload.modes : {};
        let restored = false;
        let restoredModelName = '';
        let restoredError = '';
        for (const mode of ['stage', 'knowledge']) {
            const modeState = restoreTranscriptModeCache(mode, modes[mode]);
            profileState.segmentTagsByMode[mode] = modeState.cache;
            profileState.segmentTagErrorsByMode[mode] = modeState.errorCache;
            profileState.segmentTagHasRun[mode] = modeState.hasRun;
            if (!restoredModelName && modeState.modelName) restoredModelName = modeState.modelName;
            if (!restoredError && modeState.errorCache.size > 0) {
                const firstError = modeState.errorCache.values().next();
                restoredError = String((firstError && firstError.value) || '').trim();
            }
            if (modeState.cache.size > 0 || modeState.errorCache.size > 0 || modeState.hasRun) restored = true;
        }
        if (restoredModelName) profileState.segmentTagModelName = restoredModelName;
        if (restoredError) profileState.segmentTagLastError = restoredError;
        return restored;
    } catch (_error) {
        return false;
    }
}

function writeStoredTranscriptTagCache(personId = personIdFromPath()) {
    const key = transcriptTagCacheStorageKey(personId);
    const signature = String(profileState.latestProfileSignature || '').trim();
    if (!key || key.endsWith('.') || !signature) return;
    try {
        const payload = {
            signature,
            updated_at: new Date().toISOString(),
            modes: {
                stage: serializeTranscriptModeCache('stage'),
                knowledge: serializeTranscriptModeCache('knowledge')
            }
        };
        window.localStorage.setItem(key, JSON.stringify(payload));
    } catch (_error) {
        // Non-blocking if storage is unavailable.
    }
}

let legacyProfileSignatureCleared = false;
function clearLegacyProfileSignatureCache() {
    if (legacyProfileSignatureCleared) return;
    legacyProfileSignatureCleared = true;
    try {
        for (const prefix of LEGACY_PROFILE_SIGNATURE_CACHE_PREFIXES) {
            const removeKeys = [];
            for (let idx = 0; idx < window.localStorage.length; idx += 1) {
                const key = String(window.localStorage.key(idx) || '');
                if (key.startsWith(prefix)) removeKeys.push(key);
            }
            removeKeys.forEach((key) => window.localStorage.removeItem(key));
        }
    } catch (_error) {
        // Ignore localStorage availability issues.
    }
}

let legacyTranscriptTagCacheCleared = false;
function clearLegacyTranscriptTagCache() {
    if (legacyTranscriptTagCacheCleared) return;
    legacyTranscriptTagCacheCleared = true;
    try {
        for (const prefix of LEGACY_PROFILE_TRANSCRIPT_TAG_CACHE_PREFIXES) {
            const removeKeys = [];
            for (let idx = 0; idx < window.localStorage.length; idx += 1) {
                const key = String(window.localStorage.key(idx) || '');
                if (key.startsWith(prefix)) removeKeys.push(key);
            }
            removeKeys.forEach((key) => window.localStorage.removeItem(key));
        }
    } catch (_error) {
        // Ignore localStorage availability issues.
    }
}

function knowledgeCompletenessClass(value) {
    const score = Number(value || 0);
    if (score <= 20) return 'score-low';
    if (score <= 40) return 'score-surface';
    if (score <= 60) return 'score-working';
    if (score <= 80) return 'score-strong';
    return 'score-rich';
}

function stageClass(code) {
    const value = String(code || '').toUpperCase();
    if (value === 'S1' || value === 'S2') return 'stage-early';
    if (value === 'S3' || value === 'S4') return 'stage-nurture';
    if (value === 'S5' || value === 'S5M' || value === 'O1' || value === 'O4' || value === 'R1' || value === 'R4') return 'stage-problem';
    if (value === 'S6' || value === 'S6M' || value === 'O2' || value === 'O5' || value === 'R2' || value === 'R5') return 'stage-discussion';
    if (value === 'S7' || value === 'S7M' || value === 'O3' || value === 'O6' || value === 'R3' || value === 'R6') return 'stage-conversion';
    if (value === 'S8' || value === 'O7' || value === 'R7') return 'stage-client';
    if (value === 'S9') return 'stage-mature';
    return 'stage-unknown';
}

function normalizedStage(definition, selectedStage) {
    if (selectedStage && String(selectedStage.code || '').toUpperCase() === definition.code) {
        return {
            ...definition,
            selected: true,
            confidence_pct: Number(selectedStage.confidence_pct || 0),
            summary: String(selectedStage.summary || definition.summary || '')
        };
    }
    return {
        ...definition,
        selected: false,
        confidence_pct: 0,
        summary: String(definition.summary || '')
    };
}

function renderStageOption(definition, selectedStage, progress = {}) {
    const stage = normalizedStage(definition, selectedStage);
    const isSelected = !!stage.selected;
    const isLocked = !!progress.locked;
    const orderIndexMap = progress.orderIndexMap && typeof progress.orderIndexMap === 'object'
        ? progress.orderIndexMap
        : {};
    const selectedIndex = Number(progress.selectedIndex);
    const targetIndex = Number(progress.targetIndex);
    const stageIndex = Number(orderIndexMap[stage.code]);
    const hasSelectedIndex = Number.isFinite(selectedIndex) && selectedIndex >= 0;
    const isComplete = !isSelected && hasSelectedIndex && Number.isFinite(stageIndex) && stageIndex >= 0 && stageIndex < selectedIndex;
    const isTarget = !isLocked && !isSelected && Number.isFinite(targetIndex) && targetIndex >= 0 && Number.isFinite(stageIndex) && stageIndex === targetIndex;
    const stateChip = isSelected
        ? '<span class="stage-state">Selected</span>'
        : isTarget
            ? '<span class="stage-state">Target</span>'
            : '';
    const metaText = isSelected
        ? `Confidence ${esc(stage.confidence_pct)}%`
        : isTarget
            ? 'Next target in flow'
            : isLocked
                ? 'Locked until Relationship reaches S8'
            : isComplete
                ? 'Complete'
                : 'Not selected';
    return `
        <article class="stage-option ${stageClass(stage.code)} ${isSelected ? 'is-selected' : (isTarget ? 'is-target' : (isComplete ? 'is-complete' : 'is-idle'))} ${isLocked ? 'is-locked' : ''}">
            <div class="stage-option-head">
                <span class="stage-code">${esc(stage.code)}</span>
                ${stateChip}
            </div>
            <h4>${esc(stage.label.replace(/^[SRO][0-9]M?\s+/, ''))}</h4>
            <p>${esc(stage.summary || '')}</p>
            <div class="stage-option-meta">${metaText}</div>
        </article>
    `;
}

function renderStageLane(title, definitions, selectedStage, options = {}) {
    const locked = !!options.locked;
    const selectedLabel = locked
        ? 'Locked until S8 reached'
        : selectedStage
            ? `${selectedStage.label || selectedStage.code}`
            : 'No stage selected yet';
    const orderedCodes = (definitions || []).map((definition) => String(definition.code || '').toUpperCase());
    const orderIndexMap = {};
    orderedCodes.forEach((code, index) => {
        orderIndexMap[code] = index;
    });
    const selectedCode = String((selectedStage && selectedStage.code) || '').toUpperCase();
    const selectedIndex = Object.prototype.hasOwnProperty.call(orderIndexMap, selectedCode)
        ? Number(orderIndexMap[selectedCode])
        : -1;
    const targetIndex = locked
        ? -1
        : selectedIndex >= 0
        ? (selectedIndex + 1 < orderedCodes.length ? selectedIndex + 1 : -1)
        : (orderedCodes.length ? 0 : -1);
    return `
        <section class="stage-lane">
            <div class="stage-lane-head">
                <h3>${esc(title)}</h3>
                <span class="chip">${esc(selectedLabel)}</span>
            </div>
            <div class="stage-lane-grid">
                ${definitions.map((definition) => renderStageOption(definition, selectedStage, { orderIndexMap, selectedIndex, targetIndex, locked })).join('')}
            </div>
        </section>
    `;
}

function _relationshipStageByCode(code) {
    return RELATIONSHIP_STAGES.find(
        (item) => String((item && item.code) || '').toUpperCase() === String(code || '').toUpperCase()
    ) || null;
}

function _relationshipJourneyHighestIndex(selectedStage) {
    const rawCode = String((selectedStage && selectedStage.code) || '').toUpperCase();
    if (!rawCode) return 0;
    if (rawCode === 'S9') return 9;
    const match = rawCode.match(/^S([1-8])$/);
    if (!match) return 0;
    return Number(match[1]);
}

function _relationshipJourneyLabel(definition, index) {
    const baseLabel = String((definition && definition.label) || `S${index}`).replace(/^S[0-9]\s+/, '').trim();
    return `S${index} ${baseLabel || `Stage ${index}`}`;
}

function relationshipJourneyCodeLabel(code) {
    const normalized = String(code || '').trim().toUpperCase();
    const match = normalized.match(/^S([1-9])$/);
    if (!match) return normalized || 'Unknown';
    const index = Number(match[1]);
    const source = _relationshipStageByCode(normalized);
    return _relationshipJourneyLabel(source || { label: normalized }, index);
}

function renderRelationshipJourneyLane(stage2 = {}) {
    const selectedStage = stage2.relationship_stage || null;
    const highestIndex = _relationshipJourneyHighestIndex(selectedStage);
    const selectedCode = String((selectedStage && selectedStage.code) || '').toUpperCase();
    const selectedLabel = selectedStage
        ? `${selectedStage.label || selectedStage.code}${selectedCode === 'S9' ? ' (Journey complete)' : ''}`
        : 'No stage selected yet';

    const cards = Array.from({ length: 9 }, (_, offset) => {
        const index = offset + 1;
        const sourceCode = `S${index}`;
        const source = _relationshipStageByCode(sourceCode) || {
            code: sourceCode,
            label: `S${index}`,
            summary: ''
        };
        const covered = highestIndex >= index;
        const current = covered && highestIndex === index;
        const target = !covered && highestIndex < 9 && index === (highestIndex + 1);
        const summary = String(source.summary || '').trim();
        const stateText = current ? 'Current' : target ? 'Target' : covered ? 'Covered' : 'Pending';
        return `
            <article class="stage-option ${stageClass(sourceCode)} ${covered ? 'is-covered' : 'is-idle'} ${current ? 'is-current' : ''} ${target ? 'is-target' : ''}">
                <div class="stage-option-head">
                    <span class="stage-code">S${index}</span>
                    <span class="stage-state">${esc(stateText)}</span>
                </div>
                <h4>${esc(_relationshipJourneyLabel(source, index).replace(/^S[0-9]\s+/, ''))}</h4>
                <p>${esc(summary || 'No summary configured for this journey step.')}</p>
                <div class="stage-option-meta">${covered ? `Journey reached S${index}` : target ? `Next target S${index}` : `Awaiting S${index}`}</div>
            </article>
        `;
    }).join('');

    return `
        <section class="stage-lane relationship-journey-lane">
            <div class="stage-lane-head">
                <h3>Relationship Journey (S1-S9)</h3>
                <span class="chip">${esc(selectedLabel)}</span>
            </div>
            <div class="stage-lane-grid">
                ${cards}
            </div>
        </section>
    `;
}

function renderStages(stage2 = {}) {
    const root = document.getElementById('stage2-flow-root');
    if (!root) return;
    const relationshipCode = String((stage2.relationship_stage && stage2.relationship_stage.code) || '').toUpperCase();
    const opportunityUnlocked = relationshipCode === 'S8' || relationshipCode === 'S9';
    root.innerHTML = [
        renderRelationshipJourneyLane(stage2),
        renderStageLane(
            'Opportunity Journey (O1-O7)',
            OPPORTUNITY_STAGES,
            stage2.opportunity_stage || null,
            { locked: !opportunityUnlocked }
        )
    ].join('');
}

function normalizeStage2ForDisplay(stage2 = {}) {
    const output = stage2 && typeof stage2 === 'object' ? { ...stage2 } : {};
    const relationship = output.relationship_stage && typeof output.relationship_stage === 'object'
        ? output.relationship_stage
        : {};
    const relationshipCode = String((relationship && relationship.code) || '').toUpperCase();
    const opportunityUnlocked = relationshipCode === 'S8' || relationshipCode === 'S9';
    const opportunity = output.opportunity_stage && typeof output.opportunity_stage === 'object'
        ? { ...output.opportunity_stage }
        : null;
    if (!opportunityUnlocked) {
        output.opportunity_stage = null;
        return output;
    }
    if (!opportunity) return output;
    const normalizedCode = normalizeOpportunityCode(opportunity.code);
    if (normalizedCode === String(opportunity.code || '').toUpperCase()) {
        return output;
    }
    const definition = OPPORTUNITY_STAGES.find((item) => String(item.code || '').toUpperCase() === normalizedCode);
    opportunity.code = normalizedCode;
    if (definition) {
        opportunity.label = definition.label || opportunity.label || normalizedCode;
        opportunity.summary = definition.summary || opportunity.summary || '';
    }
    output.opportunity_stage = opportunity;
    return output;
}

function relationshipStageCodeRank(code) {
    const match = String(code || '').trim().toUpperCase().match(/^S([1-9])$/);
    if (!match) return 0;
    return Number(match[1] || 0);
}

function relationshipStageFromTagCode(code) {
    const normalized = normalizeOpportunityCode(String(code || '').trim().toUpperCase());
    if (/^S[1-9]$/.test(normalized)) return normalized;
    if (/^O[1-7]$/.test(normalized) || /^R[1-7]$/.test(normalized)) return 'S8';
    return '';
}

function relationshipStageDefinition(code) {
    const normalized = String(code || '').trim().toUpperCase();
    if (!normalized) return null;
    return RELATIONSHIP_STAGES.find((item) => String(item.code || '').toUpperCase() === normalized) || null;
}

function relationshipStageObject(code, extras = {}) {
    const normalized = String(code || '').trim().toUpperCase();
    const definition = relationshipStageDefinition(normalized);
    return {
        code: normalized,
        label: String((definition && definition.label) || normalized),
        summary: String((definition && definition.summary) || ''),
        confidence_pct: Number(extras.confidence_pct || 0),
        reasons: Array.isArray(extras.reasons) ? extras.reasons : [],
        ...extras
    };
}

function deriveRelationshipStageFromTranscriptTags(payload = {}) {
    const items = filterTranscriptItems(Array.isArray(payload.evidence_inputs) ? payload.evidence_inputs : []);
    const cache = profileState.segmentTagsByMode && profileState.segmentTagsByMode.stage instanceof Map
        ? profileState.segmentTagsByMode.stage
        : null;
    if (!cache || !cache.size || !items.length) return null;

    const counts = new Map();
    let total = 0;
    for (const item of items) {
        const evidenceId = String((item && item.evidence_id) || '').trim();
        if (!evidenceId) continue;
        const cached = cache.get(evidenceId);
        const segments = Array.isArray(cached && cached.segments) ? cached.segments : [];
        for (const segment of segments) {
            if (!(segment && segment.mapped)) continue;
            const stageCode = relationshipStageFromTagCode(segment.tag_code);
            if (!stageCode) continue;
            counts.set(stageCode, Number(counts.get(stageCode) || 0) + 1);
            total += 1;
        }
    }
    if (!counts.size || total <= 0) return null;

    const ranked = Array.from(counts.entries())
        .map(([code, count]) => ({ code, count, rank: relationshipStageCodeRank(code) }))
        .sort((left, right) => {
            if (right.count !== left.count) return right.count - left.count;
            return right.rank - left.rank;
        });

    let selected = ranked[0];
    if (selected && selected.code === 'S9' && selected.count < 2) {
        const fallback = ranked.find((row) => row.code !== 'S9');
        if (fallback) selected = fallback;
    }
    if (!selected) return null;

    const confidencePct = Math.max(0, Math.min(100, Math.round((selected.count / total) * 100)));
    return {
        ...relationshipStageObject(selected.code, { confidence_pct: confidencePct }),
        source: 'transcript_tags',
        support_count: selected.count,
        support_total: total
    };
}

function applyPersonRelationshipOverride(stage2 = {}, payload = {}) {
    const person = payload && payload.person && typeof payload.person === 'object' ? payload.person : {};
    const overrideCode = String(person.relationship_stage_override || '').trim().toUpperCase();
    if (!/^S[1-9]$/.test(overrideCode)) {
        return { stage2, hasOverride: false };
    }
    const merged = {
        ...stage2,
        relationship_stage: relationshipStageObject(overrideCode, {
            confidence_pct: 100,
            source: 'person_override',
            summary: `Manual override applied (${overrideCode}).`
        })
    };
    return { stage2: merged, hasOverride: true };
}

function resolveStage2ForDisplay(payload = {}) {
    const base = profileState.stage2Base && typeof profileState.stage2Base === 'object'
        ? { ...profileState.stage2Base }
        : {};
    const overrideResult = applyPersonRelationshipOverride(base, payload);
    if (overrideResult.hasOverride) return overrideResult.stage2;
    const derived = deriveRelationshipStageFromTranscriptTags(payload);
    if (!derived) return overrideResult.stage2;
    const baseStage = overrideResult.stage2 && overrideResult.stage2.relationship_stage && typeof overrideResult.stage2.relationship_stage === 'object'
        ? overrideResult.stage2.relationship_stage
        : null;
    const baseCode = String((baseStage && baseStage.code) || '').trim().toUpperCase();
    const derivedCode = String(derived.code || '').trim().toUpperCase();
    const baseRank = relationshipStageCodeRank(baseCode);
    const derivedRank = relationshipStageCodeRank(derivedCode);
    if (baseCode && baseRank > 0 && derivedRank > 0 && derivedRank < baseRank) {
        const reasons = Array.isArray(baseStage && baseStage.reasons) ? [...baseStage.reasons] : [];
        reasons.push(`Continuity guard retained ${baseCode}; transcript tags inferred ${derivedCode}.`);
        return {
            ...overrideResult.stage2,
            relationship_stage: {
                ...baseStage,
                reasons: Array.from(new Set(reasons)).slice(0, 8),
                continuity_guard_applied: true,
                inferred_from_transcript_tags: derivedCode
            }
        };
    }
    return {
        ...overrideResult.stage2,
        relationship_stage: derived
    };
}

function refreshStageDisplayFromTranscript() {
    if (!profileState.payload) return;
    const resolved = resolveStage2ForDisplay(profileState.payload);
    profileState.stage2 = normalizeStage2ForDisplay(resolved);
    renderStages(profileState.stage2);
}

function mergeKnowledgeBuckets(stage1 = {}) {
    const incoming = Array.isArray(stage1.boxes) ? stage1.boxes : [];
    const byKey = new Map();
    for (const box of incoming) {
        const key = String((box && box.box_key) || '').trim();
        if (key) byKey.set(key, box);
    }

    return KNOWLEDGE_BUCKET_DEFS.map((definition) => {
        const incomingBox = byKey.get(definition.box_key) || {};
        const known = Array.isArray(incomingBox.what_is_known) ? incomingBox.what_is_known : [];
        const missing = Array.isArray(incomingBox.what_is_missing) ? incomingBox.what_is_missing : [];
        const completeness = Number(incomingBox.completeness_pct || 0);
        const confidence = Number(incomingBox.confidence_pct || 0);
        const sourceCount = Math.max(0, Number(incomingBox.source_count || 0));
        const normalizedKnown = known.map((item) => {
            if (item && typeof item === 'object') {
                return {
                    point: String(item.point || '').trim(),
                    supporting_context: String(item.supporting_context || '').trim(),
                    confidence_pct: Math.max(0, Math.min(100, Number(item.confidence_pct || 0)))
                };
            }
            return {
                point: String(item || '').trim(),
                supporting_context: '',
                confidence_pct: Math.max(0, Math.min(100, confidence))
            };
        }).filter((item) => item.point);
        const densityRatio = Math.min(1, normalizedKnown.length / 5);
        const contextualRatio = normalizedKnown.length
            ? normalizedKnown.filter((item) => item.supporting_context.length >= 24).length / normalizedKnown.length
            : 0;
        const confidenceRatio = normalizedKnown.length
            ? normalizedKnown.reduce((acc, item) => acc + (Number(item.confidence_pct || 0) / 100), 0) / normalizedKnown.length
            : Math.max(0, Math.min(1, confidence / 100));
        const sourceRatio = Math.min(1, sourceCount / 3);
        const contextualDepth = normalizedKnown.length
            ? Math.round(((densityRatio * 0.34) + (contextualRatio * 0.36) + (sourceRatio * 0.2) + (confidenceRatio * 0.1)) * 100)
            : 0;
        let contextualDepthPct = Math.max(0, Math.min(100, contextualDepth));
        if (definition.box_key === 'action_follow_up' && normalizedKnown.length) {
            const actionFlags = normalizedKnown.reduce(
                (acc, point) => {
                    const flags = actionFollowUpSignalFlags(`${point.point || ''} ${point.supporting_context || ''}`);
                    return {
                        specificNextStep: acc.specificNextStep || flags.specificNextStep,
                        sendShareIntro: acc.sendShareIntro || flags.sendShareIntro,
                        timing: acc.timing || flags.timing
                    };
                },
                { specificNextStep: false, sendShareIntro: false, timing: false }
            );
            if (actionFlags.specificNextStep) {
                let floor = 78;
                if (actionFlags.timing) floor = 88;
                if (actionFlags.timing && actionFlags.sendShareIntro) floor = 92;
                contextualDepthPct = Math.max(contextualDepthPct, floor);
            }
        }
        const contextualState = contextualDepthPct >= 80
            ? 'Deep'
            : contextualDepthPct >= 55
            ? 'Working'
            : contextualDepthPct >= 30
            ? 'Surface'
            : 'Thin';
        const populated = contextualDepthPct > 0 || completeness > 0;
        return {
            ...definition,
            code: String(incomingBox.code || definition.code || `K${definition.box_id || 0}`).toUpperCase(),
            completeness_pct: Math.max(0, Math.min(100, completeness)),
            confidence_pct: Math.max(0, Math.min(100, confidence)),
            source_count: sourceCount,
            contextual_depth_pct: contextualDepthPct,
            contextual_state: contextualState,
            last_updated: String(incomingBox.last_updated || ''),
            what_is_known: normalizedKnown,
            what_is_missing: missing,
            populated
        };
    });
}

function renderKnowledgeCard(box) {
    const depthScore = Math.max(0, Math.min(100, Number(box.contextual_depth_pct || 0)));
    const scoreClass = knowledgeCompletenessClass(depthScore);
    const known = Array.isArray(box.what_is_known) ? box.what_is_known : [];
    const missing = Array.isArray(box.what_is_missing) ? box.what_is_missing : [];
    const lastUpdated = box.last_updated ? formatDateLabel(box.last_updated) : 'No date';
    const codeLabel = String(box.code || `K${box.box_id || ''}`).toUpperCase();
    const contextualState = String(box.contextual_state || 'Thin').trim();
    const contextualStateClass = contextualState.toLowerCase();
    const sourceCount = Math.max(0, Number(box.source_count || 0));
    return `
        <article class="knowledge-card ${scoreClass} ${box.populated ? 'is-populated' : 'is-empty'}">
            <div class="knowledge-card-head">
                <div>
                    <div class="knowledge-card-kicker">${esc(codeLabel)}</div>
                    <h3>${esc(box.box_title || 'Bucket')}</h3>
                </div>
                <div class="knowledge-head-right">
                    <div class="knowledge-score">${esc(depthScore)}%</div>
                    <div class="knowledge-state ${esc(contextualStateClass)}">${esc(contextualState)} Context</div>
                </div>
            </div>
            <div class="knowledge-meta">
                <span class="chip">Coverage ${esc(box.completeness_pct)}%</span>
                <span class="chip">Confidence ${esc(box.confidence_pct)}%</span>
                <span class="chip">${sourceCount === 1 ? '1 source' : `${esc(sourceCount)} sources`}</span>
                <span class="chip">Updated ${esc(lastUpdated)}</span>
            </div>
            <div class="knowledge-block">
                <div class="lens-label">Known</div>
                ${
                    known.length
                        ? `<ul>${known.slice(0, 2).map((item) => {
                            const point = String((item && item.point) || '').trim();
                            const context = String((item && item.supporting_context) || '').trim();
                            return `<li>${esc(point)}${context ? `<div class="knowledge-point-context">${esc(context)}</div>` : ''}</li>`;
                        }).join('')}</ul>`
                        : '<div class="empty">No retained points yet.</div>'
                }
            </div>
            <div class="knowledge-block">
                <div class="lens-label">Missing</div>
                ${
                    missing.length
                        ? `<ul>${missing.slice(0, 2).map((item) => `<li>${esc(item)}</li>`).join('')}</ul>`
                        : '<div class="empty">Awaiting stronger evidence.</div>'
                }
            </div>
        </article>
    `;
}

function renderKnowledgeBank(stage1 = {}) {
    const root = document.getElementById('knowledge-bank-root');
    if (!root) return;
    const mergedBuckets = mergeKnowledgeBuckets(stage1);
    root.innerHTML = mergedBuckets.map((box) => renderKnowledgeCard(box)).join('');
}

function normalizeForMatching(value) {
    return normalizeWhitespace(value).toLowerCase();
}

function actionFollowUpSignalFlags(value) {
    const normalized = normalizeForMatching(value);
    if (!normalized) {
        return {
            specificNextStep: false,
            sendShareIntro: false,
            timing: false
        };
    }
    const specificNextStep = /\b(next step|follow[\s-]?up|reconnect|arrange|schedule|set up|need to|i need to|we need to|sit down|go through|walk through|review|present|presentation|plan to|will)\b/i.test(normalized);
    const sendShareIntro = /\b(send|share|introduction|introduce|invite|forward|deck|material|materials|presentation|present|walk through|go through)\b/i.test(normalized);
    const timing = /\b(today|tomorrow|this week|next week|next couple of weeks|week and a half|after|before|by|on|in about|q[1-4]|quarter|month|months|\d+\s+(day|days|week|weeks|month|months))\b/i.test(normalized);
    return { specificNextStep, sendShareIntro, timing };
}

function isTaylorSterlingPresentationText(value) {
    const text = normalizeForMatching(value);
    if (!text) return false;
    const hasCompany = text.includes('taylor sterling') || text.includes('taylor stirling');
    if (!hasCompany) return false;
    return (
        text.includes('presentation')
        || text.includes('presenting')
        || text.includes('understands what we do')
        || text.includes("abilities")
        || text.includes('what we do')
    );
}

function keywordScoreForText(normalizedText, keyword) {
    const token = normalizeForMatching(keyword);
    if (!token || !normalizedText) return 0;
    if (token.includes(' ') || token.includes('-')) {
        return normalizedText.includes(token) ? 2 : 0;
    }
    const pattern = new RegExp(`(^|[^a-z0-9])${token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z0-9]|$)`, 'i');
    return pattern.test(normalizedText) ? 1 : 0;
}

function scoreRuleMatch(text, keywords = []) {
    let score = 0;
    for (const keyword of keywords) {
        score += keywordScoreForText(text, keyword);
    }
    return score;
}

function classifyByRules(text, rules) {
    const source = String(text || '').replace(/\r/g, '\n');
    const sentenceCandidates = source
        .split(/\n+/)
        .flatMap((line) => String(line || '').split(/(?<=[.!?])\s+/))
        .map((part) => normalizeForMatching(part))
        .filter(Boolean);
    if (!sentenceCandidates.length) return null;

    let best = null;
    let bestScore = 0;
    for (const normalized of sentenceCandidates) {
        for (const rule of rules) {
            const score = scoreRuleMatch(normalized, rule.keywords || []);
            if (score > bestScore) {
                bestScore = score;
                best = rule;
            }
        }
    }
    return bestScore > 0 ? { ...best, score: bestScore } : null;
}

function fallbackStageTag(stage2) {
    const stage = stage2.relationship_stage || stage2.opportunity_stage;
    if (!stage) return null;
    return {
        label: `${stage.label || stage.code || 'Stage'}`,
        className: stageClass(stage.code),
        mode: 'stage'
    };
}

function stageTagFromCode(code) {
    const normalizedCode = String(code || '').toUpperCase();
    if (!normalizedCode) return null;
    return {
        label: STAGE_LABEL_LOOKUP[normalizedCode] || normalizedCode,
        className: stageClass(normalizedCode),
        mode: 'stage'
    };
}

function buildTagForText(text, mode, stage2, allowFallback = true) {
    if (mode === 'knowledge') {
        if (isTaylorSterlingPresentationText(text)) {
            const tsBucket = KNOWLEDGE_BUCKET_DEFS.find((item) => item.box_key === 'taylor_sterling_positioning');
            const tsCode = String((tsBucket && tsBucket.code) || 'K8').toUpperCase();
            return {
                label: `${tsCode} Taylor Sterling Positioning`,
                className: 'kb-taylor_sterling_positioning',
                mode: 'knowledge'
            };
        }
        const match = classifyByRules(text, KNOWLEDGE_TRANSCRIPT_RULES);
        if (match) {
            return {
                label: match.label,
                className: match.className,
                mode: 'knowledge'
            };
        }
        return { label: 'Unmapped', className: 'kb-unknown', mode: 'knowledge' };
    }

    if (isTaylorSterlingPresentationText(text)) {
        return stageTagFromCode('S3') || { label: 'S3 Position', className: 'stage-nurture', mode: 'stage' };
    }

    const match = classifyByRules(text, STAGE_TRANSCRIPT_RULES);
    if (match) {
        return {
            label: match.label,
            className: stageClass(match.code),
            mode: 'stage'
        };
    }

    if (allowFallback) {
        const fallback = fallbackStageTag(stage2);
        if (fallback) return fallback;
    }
    return { label: 'Unmapped', className: 'stage-unknown', mode: 'stage' };
}

const TRANSCRIPT_BLOCK_MAX_LINES = 3;
const TRANSCRIPT_BLOCK_MAX_CHARS = 420;
const TRANSCRIPT_LINE_CHUNK_MAX = 260;

function chunkTranscriptLine(line, mode = 'stage') {
    const source = String(line || '').trim();
    if (!source) return [];
    const sentenceParts = source.split(/(?<=[.!?])\s+/).map((part) => part.trim()).filter(Boolean);
    if (String(mode || '').trim().toLowerCase() === 'knowledge' && sentenceParts.length) {
        return sentenceParts;
    }
    if (source.length <= TRANSCRIPT_LINE_CHUNK_MAX) return [source];
    if (sentenceParts.length <= 1) {
        const chunks = [];
        for (let idx = 0; idx < source.length; idx += TRANSCRIPT_LINE_CHUNK_MAX) {
            const chunk = source.slice(idx, idx + TRANSCRIPT_LINE_CHUNK_MAX).trim();
            if (chunk) chunks.push(chunk);
        }
        return chunks;
    }
    const chunks = [];
    let buffer = '';
    for (const sentence of sentenceParts) {
        const projected = buffer ? `${buffer} ${sentence}` : sentence;
        if (buffer && projected.length > TRANSCRIPT_LINE_CHUNK_MAX) {
            chunks.push(buffer);
            buffer = sentence;
        } else {
            buffer = projected;
        }
    }
    if (buffer) chunks.push(buffer);
    return chunks;
}

function splitTranscriptSegments(content, mode = 'stage') {
    const source = String(content || '').replace(/\r/g, '').trim();
    if (!source) return [];
    const normalizedMode = String(mode || 'stage').trim().toLowerCase();
    const blockMaxLines = normalizedMode === 'knowledge' ? 1 : TRANSCRIPT_BLOCK_MAX_LINES;
    const lines = source
        .split(/\n+/)
        .map((line) => normalizeWhitespace(line))
        .filter(Boolean)
        .flatMap((line) => chunkTranscriptLine(line, normalizedMode));
    if (!lines.length) return [];

    const blocks = [];
    let currentLines = [];
    let currentLength = 0;
    for (const line of lines) {
        const projected = currentLength + line.length + (currentLines.length ? 1 : 0);
        if (
            currentLines.length
            && (projected > TRANSCRIPT_BLOCK_MAX_CHARS || currentLines.length >= blockMaxLines)
        ) {
            blocks.push(currentLines.join(' ').trim());
            currentLines = [line];
            currentLength = line.length;
            continue;
        }
        currentLines.push(line);
        currentLength = projected;
    }
    if (currentLines.length) blocks.push(currentLines.join(' ').trim());
    return blocks.filter(Boolean);
}

function splitTranscriptLines(content) {
    const source = String(content || '').replace(/\r/g, '').trim();
    if (!source) return [];
    return source.split(/\n+/).map((line) => line.trim()).filter(Boolean);
}

function normalizeTranscriptIntentText(value) {
    return normalizeWhitespace(value).toLowerCase();
}

function isChatLikeTranscriptSource(item) {
    const source = normalizeTranscriptIntentText(
        (item && (item.source_type || item.source_kind || item.channel)) || ''
    );
    return source === 'chat' || source === 'typed' || source === 'note';
}

function isNonTranscriptRequestText(value) {
    const text = normalizeTranscriptIntentText(value);
    if (!text || text.length > 320) return false;
    const stageRequest = [
        /\b(?:show|list|open|display)\s+(?:me\s+|the\s+)?(?:all\s+)?stages?\b/,
        /\b(?:show|open|display)\s+(?:the\s+)?stage\s+view\b/,
        /\bswitch(?:\s+to)?\s+(?:the\s+)?stage\s+view\b/
    ].some((pattern) => pattern.test(text));
    if (stageRequest) return true;
    return [
        /\b(?:complete|completion|completing|completed|compleate)\s+(?:the\s+)?profile\b/,
        /\bprofile\s+(?:complete|completion|completing|completed|compleate)\b/,
        /\bmissing\s+(?:profile\s+)?(?:information|infortmation|info|data|details?|fields?)\b/,
        /\bwhat\s+(?:information|infortmation|info|data|details?|fields?)\s+(?:is|are)\s+missing\b/,
        /\bwhich\s+(?:information|infortmation|info|data|details?|fields?)\s+(?:is|are)\s+missing\b/,
        /\bwhat\s+do\s+you\s+need\s+to\s+(?:complete|completion|completing|completed|compleate)\s+(?:the\s+)?profile\b/,
        /\bwhat\s+should\s+i\s+(?:provide|providing|provideing|provided)\s+to\s+(?:complete|completion|completing|completed|compleate)\s+(?:the\s+)?profile\b/,
        /\b(?:provide|providing|provideing|provided)\s+(?:data|information|infortmation|info|details?)\s+(?:to|for)\s+(?:complete|completion|completing|completed|compleate)\s+(?:the\s+)?profile\b/,
        /\b(?:information|infortmation|info|data|details?|fields?)\s+(?:needed|required)\s+(?:to|for)\s+(?:complete|completion|completing|completed|compleate)\s+(?:the\s+)?profile\b/
    ].some((pattern) => pattern.test(text));
}

function filterTranscriptItems(items) {
    return (Array.isArray(items) ? items : []).filter((item) => {
        if (!item || typeof item !== 'object') return false;
        if (!isChatLikeTranscriptSource(item)) return true;
        const content = String(item.content || item.preview || item.title || '').trim();
        return !isNonTranscriptRequestText(content);
    });
}

function unknownTagForMode(mode) {
    return mode === 'knowledge'
        ? { label: 'Unmapped', className: 'kb-unknown', mode: 'knowledge' }
        : { label: 'Unmapped', className: 'stage-unknown', mode: 'stage' };
}

function modeTagDefinitions(mode) {
    if (mode === 'knowledge') {
        return KNOWLEDGE_BUCKET_DEFS.map((item) => {
            const code = String(item.code || '').toUpperCase();
            return {
                code,
                label: `${code} ${String(item.box_title || item.box_key || code)}`.trim(),
                className: `kb-${String(item.box_key || '').trim()}`
            };
        }).filter((item) => item.code);
    }
    return [...RELATIONSHIP_STAGES, ...OPPORTUNITY_STAGES]
        .map((item) => {
            const code = String(item.code || '').toUpperCase();
            return {
                code,
                label: String(item.label || code),
                className: stageClass(code)
            };
        })
        .filter((item) => item.code);
}

function modeTagLookup(mode) {
    return new Map(modeTagDefinitions(mode).map((item) => [item.code, item]));
}

function transcriptTagCoverage(content, mode, stage2, evidenceId = '') {
    const lines = splitTranscriptLines(content);
    const segments = splitTranscriptSegments(content, mode);
    const evidenceKey = String(evidenceId || '');
    const cache = profileState.segmentTagsByMode && profileState.segmentTagsByMode[mode] instanceof Map
        ? profileState.segmentTagsByMode[mode]
        : new Map();
    const errorCache = profileState.segmentTagErrorsByMode && profileState.segmentTagErrorsByMode[mode] instanceof Map
        ? profileState.segmentTagErrorsByMode[mode]
        : new Map();
    const cached = cache.get(evidenceKey);
    const failedMessage = String(
        errorCache.get(evidenceKey)
        || (cached && typeof cached === 'object' ? cached.error : '')
        || ''
    ).trim();
    if (!segments.length) {
        return {
            tag: unknownTagForMode(mode),
            processedSegments: 0,
            taggedSegments: 0,
            mappedSegments: 0,
            totalSegments: 0,
            totalLines: lines.length,
            pending: false,
            failed: false,
            error: ''
        };
    }

    if (failedMessage) {
        return {
            tag: unknownTagForMode(mode),
            processedSegments: 0,
            taggedSegments: 0,
            mappedSegments: 0,
            totalSegments: segments.length,
            totalLines: lines.length,
            pending: false,
            failed: true,
            error: failedMessage
        };
    }

    if (!cached || !Array.isArray(cached.segments) || cached.segments.length !== segments.length) {
        const pending = !!profileState.segmentTagBusy;
        return {
            tag: unknownTagForMode(mode),
            processedSegments: 0,
            taggedSegments: 0,
            mappedSegments: 0,
            totalSegments: segments.length,
            totalLines: lines.length,
            pending,
            failed: false,
            error: ''
        };
    }

    let taggedSegments = 0;
    let mappedSegments = 0;
    const tagCounts = new Map();
    for (const segmentTag of cached.segments) {
        const resolvedTag = segmentTag && segmentTag.mapped
            ? {
                label: String(segmentTag.tag_label || 'Unmapped'),
                className: String(segmentTag.tag_class || unknownTagForMode(mode).className),
                mode
            }
            : unknownTagForMode(mode);
        if (!(segmentTag && segmentTag.mapped)) continue;
        taggedSegments += 1;
        mappedSegments += 1;
        const key = `${resolvedTag.className}|${resolvedTag.label}`;
        const existing = tagCounts.get(key) || { tag: resolvedTag, count: 0 };
        existing.count += 1;
        tagCounts.set(key, existing);
    }

    if (tagCounts.size) {
        const dominant = Array.from(tagCounts.values()).sort((left, right) => right.count - left.count)[0];
        return {
            tag: dominant.tag,
            processedSegments: segments.length,
            taggedSegments,
            mappedSegments,
            totalSegments: segments.length,
            totalLines: lines.length,
            pending: false,
            failed: false,
            error: ''
        };
    }

    return {
        tag: unknownTagForMode(mode),
        processedSegments: segments.length,
        taggedSegments,
        mappedSegments,
        totalSegments: segments.length,
        totalLines: lines.length,
        pending: false,
        failed: false,
        error: ''
    };
}

function renderTranscriptRow(item, mode, stage2, rowKey) {
    const evidenceId = String(rowKey || '');
    const encodedEvidenceId = encodeURIComponent(evidenceId);
    const rowContent = String(item.content || item.preview || item.title || '');
    const coverage = transcriptTagCoverage(rowContent, mode, stage2, evidenceId);
    const tag = coverage.tag;
    const editable = interactionEditable(item);
    const deleting = profileState.deletingEvidenceIds instanceof Set
        ? profileState.deletingEvidenceIds.has(evidenceId)
        : false;
    const coverageLabel = coverage.failed
        ? 'Tagging failed'
        : coverage.pending
            ? 'Calculating model tags...'
            : coverage.totalSegments > 0
                ? `${coverage.mappedSegments}/${coverage.totalSegments} blocks mapped`
                : 'No transcript blocks';
    const summary = previewLine(item.preview || item.title || item.content || '(No transcript text)', 220);
    const dateTimeLabel = formatDateTimeLabel(item.date_at || item.date_label);
    const sourceLabel = normalizeWhitespace(item.source_type || item.source_kind || 'Input');
    const deleteButton = editable
        ? `<button
                class="transcript-row-delete"
                type="button"
                data-evidence-id="${encodedEvidenceId}"
                title="Delete this transcript block"
                ${deleting ? 'disabled' : ''}
            >${deleting ? 'Deleting...' : 'Delete block'}</button>`
        : '';
    return `
        <div class="transcript-row-wrap">
            <button class="transcript-row ${tag.className}" type="button" data-evidence-id="${encodedEvidenceId}">
                <div class="transcript-row-top">
                    <span class="transcript-time">${esc(dateTimeLabel)}</span>
                    <span class="transcript-source">${esc(sourceLabel)}</span>
                    <span class="transcript-source">${esc(coverageLabel)}</span>
                </div>
                <div class="transcript-row-main">
                    <span class="transcript-chip ${tag.className}">${esc(tag.label)}</span>
                    <span class="transcript-summary-line">${esc(summary)}</span>
                </div>
            </button>
            ${deleteButton}
        </div>
    `;
}

function transcriptCoverageTotals(items, mode, stage2) {
    return items.reduce(
        (acc, item) => {
            const coverage = transcriptTagCoverage(
                String(item.content || item.preview || item.title || ''),
                mode,
                stage2,
                String(item.evidence_id || '')
            );
            acc.processedSegments += coverage.processedSegments;
            acc.taggedSegments += coverage.taggedSegments;
            acc.mappedSegments += coverage.mappedSegments;
            acc.totalSegments += coverage.totalSegments;
            acc.totalLines += coverage.totalLines;
            if (coverage.pending) acc.pendingRows += 1;
            if (coverage.failed) acc.failedRows += 1;
            return acc;
        },
        { processedSegments: 0, taggedSegments: 0, mappedSegments: 0, totalSegments: 0, totalLines: 0, pendingRows: 0, failedRows: 0 }
    );
}

function modeCacheReady(mode, payload = profileState.payload || {}) {
    const normalizedMode = String(mode || '').trim().toLowerCase();
    if (!['stage', 'knowledge'].includes(normalizedMode)) return false;
    const items = filterTranscriptItems(Array.isArray(payload.evidence_inputs) ? payload.evidence_inputs : []);
    if (!items.length) return true;
    const cache = profileState.segmentTagsByMode && profileState.segmentTagsByMode[normalizedMode] instanceof Map
        ? profileState.segmentTagsByMode[normalizedMode]
        : null;
    if (!cache) return false;
    for (const [index, item] of items.entries()) {
        const evidenceId = String((item && item.evidence_id) || `row-${index}`).trim();
        const content = String((item && item.content) || (item && item.preview) || (item && item.title) || '').trim();
        const segments = splitTranscriptSegments(content, normalizedMode);
        const cached = cache.get(evidenceId);
        const cachedSegments = Array.isArray(cached && cached.segments) ? cached.segments : [];
        if (cachedSegments.length !== segments.length) return false;
    }
    return true;
}

async function recalculateTranscriptTagsForModes(modes, options = {}) {
    const payload = profileState.payload || {};
    const onlyMissing = !!options.onlyMissing;
    const normalizedModes = Array.from(
        new Set(
            (Array.isArray(modes) ? modes : [])
                .map((mode) => String(mode || '').trim().toLowerCase())
                .filter((mode) => ['stage', 'knowledge'].includes(mode))
        )
    );
    for (const mode of normalizedModes) {
        if (onlyMissing && modeCacheReady(mode, payload)) continue;
        await recalculateTranscriptTags({ mode });
    }
}

function updateTranscriptProgress(coverageTotals) {
    const progressRoot = document.getElementById('transcript-progress');
    const progressFill = document.getElementById('transcript-progress-fill');
    const progressLabel = document.getElementById('transcript-progress-label');
    const processedSegments = Math.max(0, Number((coverageTotals && coverageTotals.processedSegments) || 0));
    const taggedSegments = Math.max(0, Number((coverageTotals && coverageTotals.taggedSegments) || 0));
    const mappedSegments = Math.max(0, Number((coverageTotals && coverageTotals.mappedSegments) || 0));
    const totalSegments = Math.max(0, Number((coverageTotals && coverageTotals.totalSegments) || 0));
    const totalLines = Math.max(0, Number((coverageTotals && coverageTotals.totalLines) || 0));
    const pendingRows = Math.max(0, Number((coverageTotals && coverageTotals.pendingRows) || 0));
    const failedRows = Math.max(0, Number((coverageTotals && coverageTotals.failedRows) || 0));
    const processedPercent = totalSegments > 0 ? Math.round((processedSegments / totalSegments) * 100) : 0;
    const mappedPercent = totalSegments > 0 ? Math.round((mappedSegments / totalSegments) * 100) : 0;
    if (progressRoot) progressRoot.setAttribute('aria-valuenow', String(processedPercent));
    if (progressFill) progressFill.style.width = `${processedPercent}%`;
    if (progressLabel) {
        const lineLabel = totalLines === 1 ? '1 source line' : `${totalLines} source lines`;
        const pendingLabel = pendingRows > 0 ? ` | ${pendingRows} row(s) still tagging` : '';
        const failedLabel = failedRows > 0 ? ` | ${failedRows} row(s) failed` : '';
        progressLabel.textContent = `${processedPercent}% processed (${processedSegments}/${totalSegments} blocks) | ${mappedPercent}% mapped (${mappedSegments}/${totalSegments}) | ${lineLabel}${pendingLabel}${failedLabel}`;
    }
}

function renderTranscript(payload) {
    const listRoot = document.getElementById('transcript-list');
    const summaryRoot = document.getElementById('transcript-summary');
    if (!listRoot || !summaryRoot) return;

    const items = filterTranscriptItems(Array.isArray(payload && payload.evidence_inputs) ? payload.evidence_inputs : []);
    profileState.evidenceById = new Map(
        items.map((item, index) => [String(item.evidence_id || `row-${index}`), item])
    );

    if (!items.length) {
        summaryRoot.textContent = 'No transcript inputs available.';
        updateTranscriptProgress({ processedSegments: 0, taggedSegments: 0, mappedSegments: 0, totalSegments: 0, totalLines: 0, pendingRows: 0, failedRows: 0 });
        listRoot.innerHTML = '<div class="empty">No interactions or manual inputs found for transcript view.</div>';
        return;
    }

    const modeLabel = profileState.transcriptMode === 'knowledge' ? 'Knowledge view' : 'Stage view';
    const coverageTotals = transcriptCoverageTotals(items, profileState.transcriptMode, profileState.stage2);
    const singleInputNote = items.length === 1 && coverageTotals.totalSegments > 1
        ? ' | Single input contains full transcript; click row to expand.'
        : '';
    const pendingNote = coverageTotals.pendingRows > 0 ? ` | ${coverageTotals.pendingRows} row(s) still tagging.` : '';
    const failedNote = coverageTotals.failedRows > 0 ? ` | ${coverageTotals.failedRows} row(s) failed tagging.` : '';
    const modelNote = profileState.segmentTagModelName ? ` | Model ${profileState.segmentTagModelName}` : '';
    const errorNote = profileState.segmentTagLastError ? ` | Last error: ${previewLine(profileState.segmentTagLastError, 120)}` : '';
    summaryRoot.textContent = `${items.length} inputs | ${modeLabel} | ${coverageTotals.processedSegments}/${coverageTotals.totalSegments} blocks processed (${coverageTotals.mappedSegments} mapped)${modelNote} | Click a row to open full transcript detail.${singleInputNote}${pendingNote}${failedNote}${errorNote}`;
    updateTranscriptProgress(coverageTotals);
    listRoot.innerHTML = items
        .map((item, index) => renderTranscriptRow(item, profileState.transcriptMode, profileState.stage2, String(item.evidence_id || `row-${index}`)))
        .join('');
}

async function tagEvidenceWithModel(item, mode) {
    const personId = personIdFromPath();
    const evidenceId = String((item && item.evidence_id) || '').trim();
    const content = String((item && item.content) || (item && item.preview) || (item && item.title) || '').trim();
    if (!personId || !evidenceId || !content) {
        return { evidence_id: evidenceId, segments: [] };
    }
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 45000);
    let response = null;
    try {
        response = await fetch(`${apiBase}/api/network-lab/profile/${encodeURIComponent(personId)}/transcript-segment-tags`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            signal: controller.signal,
            body: JSON.stringify({
                mode,
                evidence_id: evidenceId,
                content,
                transcript_tagging: (profileState.payload && profileState.payload.transcript_tagging) || null
            })
        });
    } catch (error) {
        if (error && error.name === 'AbortError') {
            throw new Error('Transcript tagging timed out after 45 seconds');
        }
        throw error;
    } finally {
        window.clearTimeout(timeoutId);
    }
    let data = null;
    try {
        data = await response.json();
    } catch (error) {
        data = null;
    }
    if (!response.ok) {
        throw new Error(parseErrorDetail(data, `Transcript tagging failed (HTTP ${response.status})`));
    }
    return data && typeof data === 'object' ? data : { evidence_id: evidenceId, segments: [] };
}

async function saveSegmentTagOverride(item, mode, segmentText, tagCode) {
    const personId = personIdFromPath();
    const evidenceId = String((item && item.evidence_id) || '').trim();
    if (!personId || !evidenceId || !segmentText || !tagCode) {
        throw new Error('Missing transcript override details');
    }

    const response = await fetch(`${apiBase}/api/network-lab/profile/${encodeURIComponent(personId)}/transcript-segment-tags/override`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            mode,
            evidence_id: evidenceId,
            segment_text: segmentText,
            tag_code: tagCode,
            transcript_tagging: (profileState.payload && profileState.payload.transcript_tagging) || null
        })
    });
    let data = null;
    try {
        data = await response.json();
    } catch (_error) {
        data = null;
    }
    if (!response.ok) {
        throw new Error(parseErrorDetail(data, `Override save failed (HTTP ${response.status})`));
    }
    return data && typeof data === 'object' ? data : null;
}

async function syncInteractionStageOverride(item, mode, tagCode) {
    if (mode !== 'stage') return null;
    const interactionId = String((item && item.interaction_id) || '').trim();
    if (!interactionId) return null;
    const relationshipCode = relationshipStageFromTagCode(tagCode);
    if (!relationshipCode) return null;
    const response = await fetch(`${apiBase}/api/interactions/${encodeURIComponent(interactionId)}/stage-override`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            relationship_stage_code: relationshipCode,
            clear_override: false
        })
    });
    let data = null;
    try {
        data = await response.json();
    } catch (_error) {
        data = null;
    }
    if (!response.ok) {
        throw new Error(parseErrorDetail(data, `Stage override sync failed (HTTP ${response.status})`));
    }
    return data && typeof data === 'object' ? data : null;
}

async function applySegmentTagOverrideFromModal(evidenceId, segmentIndex, requestedCode) {
    const mode = String(profileState.transcriptMode || 'stage').trim().toLowerCase();
    if (!['stage', 'knowledge'].includes(mode)) return;
    if (profileState.modalBusy) return;
    const item = profileState.evidenceById.get(String(evidenceId || ''));
    if (!item) return;
    const segments = splitTranscriptSegments(String(item.content || item.preview || item.title || ''), mode);
    if (!Number.isInteger(segmentIndex) || segmentIndex < 0 || segmentIndex >= segments.length) return;

    const tagCode = String(requestedCode || '').trim().toUpperCase();
    const segmentText = String(segments[segmentIndex] || '').trim();
    if (!tagCode || !segmentText) return;

    profileState.modalBusy = true;
    setTranscriptModalStatus('Saving manual tag override...');
    updateTranscriptModalActionUi(item);

    try {
        const saved = await saveSegmentTagOverride(item, mode, segmentText, tagCode);
        try {
            const synced = await syncInteractionStageOverride(item, mode, tagCode);
            if (synced && profileState.payload && profileState.payload.person) {
                profileState.payload.person.relationship_stage_override = String(synced.relationship_stage_override || '').trim().toUpperCase();
                profileState.payload.person.stage_override_source_interaction_id = String(synced.stage_override_source_interaction_id || '').trim();
                profileState.payload.person.stage_override_updated_at = String(synced.stage_override_updated_at || '').trim();
            }
        } catch (_syncError) {
            // Stage sync errors should not block manual transcript tag save.
        }
        const modeCache = profileState.segmentTagsByMode && profileState.segmentTagsByMode[mode] instanceof Map
            ? profileState.segmentTagsByMode[mode]
            : new Map();
        const errorCache = profileState.segmentTagErrorsByMode && profileState.segmentTagErrorsByMode[mode] instanceof Map
            ? profileState.segmentTagErrorsByMode[mode]
            : new Map();
        if (!(profileState.segmentTagsByMode[mode] instanceof Map)) profileState.segmentTagsByMode[mode] = modeCache;
        if (!(profileState.segmentTagErrorsByMode[mode] instanceof Map)) profileState.segmentTagErrorsByMode[mode] = errorCache;
        const existing = modeCache.get(String(evidenceId)) || { evidence_id: String(evidenceId), segments: [] };
        const cachedSegments = Array.isArray(existing.segments) ? [...existing.segments] : [];
        while (cachedSegments.length < segments.length) {
            const idx = cachedSegments.length;
            cachedSegments.push({
                index: idx,
                text: String(segments[idx] || ''),
                tag_code: '',
                tag_label: '',
                tag_class: mode === 'knowledge' ? 'kb-unknown' : 'stage-unknown',
                mapped: false,
                confidence: 0,
                reason: '',
                source: ''
            });
        }
        cachedSegments[segmentIndex] = {
            index: segmentIndex,
            segment_hash: String((saved && saved.segment_hash) || ''),
            text: segmentText,
            tag_code: String((saved && saved.tag_code) || tagCode),
            tag_label: String((saved && saved.tag_label) || tagCode),
            tag_class: String((saved && saved.tag_class) || (mode === 'knowledge' ? 'kb-unknown' : 'stage-unknown')),
            mapped: true,
            confidence: 1,
            reason: 'Manual tag override',
            source: 'manual_override'
        };

        modeCache.set(String(evidenceId), {
            ...existing,
            evidence_id: String(evidenceId),
            model_name: String(existing.model_name || profileState.segmentTagModelName || ''),
            segments: cachedSegments,
            error: ''
        });
        errorCache.delete(String(evidenceId));
        writeStoredTranscriptTagCache();
        setTranscriptModalStatus('Manual tag saved.', 'success');
        renderTranscript(profileState.payload || {});
        refreshStageDisplayFromTranscript();
        const refreshedItem = profileState.evidenceById.get(String(evidenceId)) || item;
        renderTranscriptModal(refreshedItem);
        notify('Manual tag saved', 'success');
    } catch (error) {
        const message = String((error && error.message) || 'Unable to save manual tag').trim();
        setTranscriptModalStatus(message, 'error');
        notify(message, 'error');
        renderTranscriptModal(item);
    } finally {
        profileState.modalBusy = false;
        updateTranscriptModalActionUi(activeEvidenceItem() || item);
    }
}

async function recalculateTranscriptTags(options = {}) {
    const mode = String(options.mode || profileState.transcriptMode || 'stage').trim().toLowerCase();
    if (!['stage', 'knowledge'].includes(mode)) return;
    const payload = profileState.payload || {};
    const items = filterTranscriptItems(Array.isArray(payload.evidence_inputs) ? payload.evidence_inputs : []);
    const cache = profileState.segmentTagsByMode && profileState.segmentTagsByMode[mode] instanceof Map
        ? profileState.segmentTagsByMode[mode]
        : new Map();
    const errorCache = profileState.segmentTagErrorsByMode && profileState.segmentTagErrorsByMode[mode] instanceof Map
        ? profileState.segmentTagErrorsByMode[mode]
        : new Map();
    profileState.segmentTagHasRun[mode] = true;
    cache.clear();
    errorCache.clear();
    profileState.segmentTagLastError = '';
    const runId = Date.now();
    profileState.segmentTagRunId = runId;
    profileState.segmentTagBusy = true;
    renderTranscript(payload);
    if (mode === 'stage') refreshStageDisplayFromTranscript();

    try {
        let failedCount = 0;
        for (const [index, item] of items.entries()) {
            const evidenceId = String((item && item.evidence_id) || `row-${index}`).trim();
            if (!evidenceId) continue;
            try {
                const requestItem = String((item && item.evidence_id) || '').trim()
                    ? item
                    : { ...item, evidence_id: evidenceId };
                const result = await tagEvidenceWithModel(requestItem, mode);
                if (profileState.segmentTagRunId !== runId) return;
                cache.set(evidenceId, {
                    evidence_id: evidenceId,
                    model_name: String((result && result.model_name) || ''),
                    segments: Array.isArray(result && result.segments) ? result.segments : [],
                    error: ''
                });
                errorCache.delete(evidenceId);
                if (result && result.model_name) profileState.segmentTagModelName = String(result.model_name);
            } catch (error) {
                if (profileState.segmentTagRunId !== runId) return;
                const errorMessage = String((error && error.message) || 'Transcript tagging failed').trim();
                failedCount += 1;
                profileState.segmentTagLastError = errorMessage;
                errorCache.set(evidenceId, errorMessage);
                cache.set(evidenceId, {
                    evidence_id: evidenceId,
                    model_name: '',
                    segments: [],
                    error: errorMessage
                });
            }
            if (profileState.segmentTagRunId !== runId) return;
            if (mode === profileState.transcriptMode) {
                renderTranscript(payload);
                if (mode === 'stage') refreshStageDisplayFromTranscript();
                if (profileState.activeEvidenceId === evidenceId && !profileState.modalEditing) {
                    const active = profileState.evidenceById.get(evidenceId);
                    if (active) renderTranscriptModal(active);
                }
            }
        }
        if (failedCount > 0) {
            notify(`${failedCount} transcript row(s) failed tagging`, 'error');
        }
    } catch (error) {
        profileState.segmentTagLastError = String((error && error.message) || 'Transcript tagging failed').trim();
        notify(profileState.segmentTagLastError, 'error');
    } finally {
        if (profileState.segmentTagRunId === runId) {
            profileState.segmentTagBusy = false;
            writeStoredTranscriptTagCache();
            if (mode === profileState.transcriptMode) {
                renderTranscript(payload);
                if (mode === 'stage') refreshStageDisplayFromTranscript();
            }
        }
    }
}

function activeEvidenceItem() {
    if (!profileState.activeEvidenceId) return null;
    return profileState.evidenceById.get(String(profileState.activeEvidenceId)) || null;
}

function interactionEditable(item) {
    return !!String((item && item.interaction_id) || '').trim();
}

function setTranscriptModalStatus(message, type = '') {
    const statusEl = document.getElementById('transcript-modal-status');
    if (!statusEl) return;
    const text = String(message || '').trim();
    statusEl.textContent = text;
    statusEl.classList.remove('error', 'success');
    if (type === 'error') statusEl.classList.add('error');
    if (type === 'success') statusEl.classList.add('success');
}

function parseErrorDetail(data, fallback = 'Request failed') {
    if (data && typeof data === 'object') {
        const detail = String(data.detail || data.message || '').trim();
        if (detail) return detail;
    }
    return fallback;
}

function notify(message, type = 'info') {
    if (typeof window.toast === 'function') {
        window.toast(message, type);
        return;
    }
    if (type === 'error') console.error(message);
    else console.log(message);
}

function updateTranscriptModalActionUi(item) {
    const editToggle = document.getElementById('transcript-edit-toggle');
    const saveButton = document.getElementById('transcript-save');
    const cancelButton = document.getElementById('transcript-cancel');
    const deleteButton = document.getElementById('transcript-delete');
    const editorWrap = document.getElementById('transcript-modal-edit-wrap');
    const body = document.getElementById('transcript-modal-body');
    const editor = document.getElementById('transcript-modal-editor');
    const editable = interactionEditable(item);
    const editing = !!profileState.modalEditing;
    const busy = !!profileState.modalBusy;

    if (editToggle) {
        editToggle.hidden = !editable || editing;
        editToggle.disabled = busy || !editable;
    }
    if (saveButton) {
        saveButton.hidden = !editable || !editing;
        saveButton.disabled = busy;
    }
    if (cancelButton) {
        cancelButton.hidden = !editable || !editing;
        cancelButton.disabled = busy;
    }
    if (deleteButton) {
        deleteButton.hidden = !editable;
        deleteButton.disabled = busy || !editable;
    }
    if (editorWrap) {
        editorWrap.hidden = !editing;
    }
    if (body) {
        body.hidden = editing;
    }
    document.querySelectorAll('.segment-tag-select').forEach((select) => {
        select.disabled = busy || editing;
    });
    if (editing && editor && !busy) {
        editor.focus();
        editor.setSelectionRange(editor.value.length, editor.value.length);
    }
}

function enterTranscriptEditMode() {
    const item = activeEvidenceItem();
    if (!item || !interactionEditable(item)) return;
    const editor = document.getElementById('transcript-modal-editor');
    profileState.modalEditing = true;
    if (editor) editor.value = String(item.content || item.preview || item.title || '').trim();
    setTranscriptModalStatus('Editing transcript text. Save to apply changes.');
    updateTranscriptModalActionUi(item);
}

function exitTranscriptEditMode(clearStatus = false) {
    profileState.modalEditing = false;
    if (clearStatus) setTranscriptModalStatus('');
    updateTranscriptModalActionUi(activeEvidenceItem());
}

async function saveTranscriptEdit() {
    const item = activeEvidenceItem();
    const editor = document.getElementById('transcript-modal-editor');
    if (!item || !editor || !interactionEditable(item)) return;

    const updatedText = String(editor.value || '').trim();
    if (updatedText === String(item.content || '').trim()) {
        exitTranscriptEditMode(true);
        renderTranscriptModal(item);
        return;
    }

    profileState.modalBusy = true;
    setTranscriptModalStatus('Saving transcript...', '');
    updateTranscriptModalActionUi(item);

    try {
        const response = await fetch(`${apiBase}/api/interactions/${encodeURIComponent(item.interaction_id)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ raw_text: updatedText })
        });
        let data = null;
        try {
            data = await response.json();
        } catch (err) {
            data = null;
        }
        if (!response.ok) {
            throw new Error(parseErrorDetail(data, `Save failed (HTTP ${response.status})`));
        }

        profileState.modalEditing = false;
        setTranscriptModalStatus('Transcript updated.', 'success');
        notify('Transcript updated', 'success');

        await loadProfile(true, { autoTag: true });
        const refreshed = profileState.evidenceById.get(String(item.interaction_id));
        if (refreshed) {
            profileState.activeEvidenceId = String(item.interaction_id);
            renderTranscriptModal(refreshed);
        } else {
            closeTranscriptModal();
        }
    } catch (error) {
        setTranscriptModalStatus(error.message || 'Unable to update transcript.', 'error');
        notify(error.message || 'Unable to update transcript', 'error');
    } finally {
        profileState.modalBusy = false;
        updateTranscriptModalActionUi(activeEvidenceItem());
    }
}

async function deleteTranscriptInteraction() {
    const item = activeEvidenceItem();
    if (!item || !interactionEditable(item)) return;
    const evidenceId = String((item && item.evidence_id) || profileState.activeEvidenceId || '').trim();
    if (!evidenceId) return;
    await deleteTranscriptInteractionByEvidenceId(evidenceId, { fromModal: true });
}

async function deleteTranscriptInteractionByEvidenceId(evidenceId, options = {}) {
    const normalizedEvidenceId = String(evidenceId || '').trim();
    if (!normalizedEvidenceId) return;
    const item = profileState.evidenceById.get(normalizedEvidenceId);
    if (!item || !interactionEditable(item)) return;
    if (!(profileState.deletingEvidenceIds instanceof Set)) {
        profileState.deletingEvidenceIds = new Set();
    }
    if (profileState.deletingEvidenceIds.has(normalizedEvidenceId)) return;
    const fromModal = !!options.fromModal;
    const ok = window.confirm('Delete this transcript block? This cannot be undone.');
    if (!ok) return;

    profileState.deletingEvidenceIds.add(normalizedEvidenceId);
    if (fromModal) {
        profileState.modalBusy = true;
        setTranscriptModalStatus('Deleting transcript block...', '');
        updateTranscriptModalActionUi(item);
    } else {
        renderTranscript(profileState.payload || {});
    }

    try {
        const response = await fetch(`${apiBase}/api/interactions/${encodeURIComponent(item.interaction_id)}`, {
            method: 'DELETE'
        });
        let data = null;
        try {
            data = await response.json();
        } catch (err) {
            data = null;
        }
        if (!response.ok) {
            throw new Error(parseErrorDetail(data, `Delete failed (HTTP ${response.status})`));
        }

        notify('Transcript block deleted', 'success');
        if (fromModal || String(profileState.activeEvidenceId || '').trim() === normalizedEvidenceId) {
            closeTranscriptModal();
        }
        await loadProfile(true, { autoTag: true });
    } catch (error) {
        const message = error.message || 'Unable to delete transcript block.';
        if (fromModal) setTranscriptModalStatus(message, 'error');
        notify(message, 'error');
    } finally {
        profileState.deletingEvidenceIds.delete(normalizedEvidenceId);
        if (fromModal) {
            profileState.modalBusy = false;
            updateTranscriptModalActionUi(activeEvidenceItem());
        } else {
            renderTranscript(profileState.payload || {});
        }
    }
}

function renderTranscriptModal(item) {
    const modal = document.getElementById('transcript-modal');
    const title = document.getElementById('transcript-modal-title');
    const meta = document.getElementById('transcript-modal-meta');
    const body = document.getElementById('transcript-modal-body');
    if (!modal || !title || !meta || !body) return;

    const dateTimeLabel = formatDateTimeLabel(item.date_at || item.date_label);
    const sourceLabel = normalizeWhitespace(item.source_type || item.source_kind || 'Input');
    const rawText = String(item.content || item.preview || item.title || '').trim();
    const segments = splitTranscriptSegments(rawText, profileState.transcriptMode);
    const modeLabel = profileState.transcriptMode === 'knowledge' ? 'Knowledge' : 'Stage';
    const evidenceId = String(item.evidence_id || profileState.activeEvidenceId || '').trim();
    const cache = profileState.segmentTagsByMode && profileState.segmentTagsByMode[profileState.transcriptMode] instanceof Map
        ? profileState.segmentTagsByMode[profileState.transcriptMode].get(evidenceId)
        : null;
    const cachedSegments = Array.isArray(cache && cache.segments) ? cache.segments : [];
    const tagOptions = modeTagDefinitions(profileState.transcriptMode);
    const tagLookup = modeTagLookup(profileState.transcriptMode);
    const editable = interactionEditable(item);
    const editor = document.getElementById('transcript-modal-editor');

    title.textContent = item.title || 'Transcript detail';
    meta.textContent = `${dateTimeLabel} | ${sourceLabel} | ${modeLabel} color mode`;
    if (editor) editor.value = rawText;
    body.innerHTML = segments.length
        ? segments
            .map((segment, index) => {
                const modelTag = cachedSegments[index];
                const resolvedCode = String((modelTag && modelTag.tag_code) || '').toUpperCase();
                const mappedTag = resolvedCode ? tagLookup.get(resolvedCode) : null;
                const tag = modelTag && modelTag.mapped
                    ? mappedTag
                        ? {
                            code: resolvedCode,
                            label: mappedTag.label,
                            className: mappedTag.className
                        }
                        : {
                            code: resolvedCode,
                            label: String(modelTag.tag_label || resolvedCode || 'Unmapped'),
                            className: String(modelTag.tag_class || (profileState.transcriptMode === 'knowledge' ? 'kb-unknown' : 'stage-unknown'))
                        }
                    : {
                        code: '',
                        label: profileState.segmentTagBusy ? 'Tagging...' : 'Unmapped',
                        className: profileState.transcriptMode === 'knowledge' ? 'kb-unknown' : 'stage-unknown'
                    };
                const optionRows = tagOptions
                    .map((option) => {
                        const selected = option.code === tag.code ? ' selected' : '';
                        return `<option value="${esc(option.code)}"${selected}>${esc(option.label)}</option>`;
                    })
                    .join('');
                const placeholderSelected = tag.code ? '' : ' selected';
                const disabledAttr = profileState.modalBusy ? ' disabled' : '';
                return `
                    <div class="transcript-segment ${tag.className}">
                        <div class="transcript-segment-head">
                            <span class="segment-tag ${tag.className}">${esc(tag.label)}</span>
                            <label class="segment-tag-picker">
                                <span class="segment-tag-picker-label">Tag</span>
                                <select
                                    class="segment-tag-select"
                                    data-evidence-id="${encodeURIComponent(evidenceId)}"
                                    data-segment-index="${index}"${disabledAttr}
                                >
                                    <option value=""${placeholderSelected}>Select tag</option>
                                    ${optionRows}
                                </select>
                            </label>
                        </div>
                        <p>${esc(segment)}</p>
                    </div>
                `;
            })
            .join('')
        : '<div class="empty">No transcript content in this input.</div>';

    if (!editable) {
        setTranscriptModalStatus('This evidence input is read-only in this view. Interaction transcripts can be edited or deleted.', '');
    }
    updateTranscriptModalActionUi(item);
}

function openTranscriptModalById(evidenceId) {
    const modal = document.getElementById('transcript-modal');
    if (!modal) return;
    const item = profileState.evidenceById.get(String(evidenceId || ''));
    if (!item) return;

    profileState.activeEvidenceId = String(evidenceId);
    profileState.modalEditing = false;
    profileState.modalBusy = false;
    setTranscriptModalStatus('');
    renderTranscriptModal(item);
    modal.classList.add('is-open');
    modal.setAttribute('aria-hidden', 'false');
}

function closeTranscriptModal() {
    const modal = document.getElementById('transcript-modal');
    if (!modal) return;
    modal.classList.remove('is-open');
    modal.setAttribute('aria-hidden', 'true');
    profileState.activeEvidenceId = null;
    profileState.modalEditing = false;
    profileState.modalBusy = false;
    setTranscriptModalStatus('');
}

function updateTranscriptToggleUi() {
    const buttons = document.querySelectorAll('.view-toggle-btn');
    buttons.forEach((button) => {
        const mode = String(button.getAttribute('data-mode') || '');
        const active = mode === profileState.transcriptMode;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function setTranscriptMode(mode) {
    const normalized = String(mode || '').trim().toLowerCase();
    if (!['stage', 'knowledge'].includes(normalized)) return;
    profileState.transcriptMode = normalized;
    updateTranscriptToggleUi();
    renderTranscript(profileState.payload || {});
    if (profileState.activeEvidenceId && !profileState.modalEditing) {
        const item = profileState.evidenceById.get(profileState.activeEvidenceId);
        if (item) renderTranscriptModal(item);
    }
}

async function recalculateTranscript() {
    if (profileState.segmentTagBusy) return;
    const recalcButton = document.getElementById('transcript-recalculate');
    const statusLine = document.getElementById('status-line');
    if (recalcButton) {
        recalcButton.disabled = true;
        recalcButton.textContent = 'Recalculating...';
    }
    if (statusLine) statusLine.textContent = 'Recalculating transcript tags (Stage + Knowledge)...';
    try {
        await loadProfile(false, { autoTag: false, autoTagOnChange: false });
        await recalculateTranscriptTagsForModes(['stage', 'knowledge']);
        if (profileState.activeEvidenceId && !profileState.modalEditing) {
            const item = profileState.evidenceById.get(profileState.activeEvidenceId);
            if (item) renderTranscriptModal(item);
        }
        if (statusLine) {
            statusLine.textContent = profileState.segmentTagLastError
                ? 'Transcript tagging completed with errors.'
                : 'Transcript tags recalculated.';
        }
    } catch (error) {
        if (statusLine) statusLine.textContent = `Transcript recalculate failed: ${String((error && error.message) || error)}`;
        notify(String((error && error.message) || 'Transcript recalculate failed'), 'error');
    } finally {
        if (recalcButton) {
            recalcButton.disabled = false;
            recalcButton.textContent = 'Recalculate';
        }
    }
}

function togglePanel(target) {
    const body = document.getElementById(`panel-${target}`);
    const shell = document.getElementById(`panel-shell-${target}`);
    const button = document.querySelector(`.collapse-toggle[data-target="${target}"]`);
    if (!body || !button) return;

    const collapsed = body.classList.toggle('is-collapsed');
    if (shell) shell.classList.toggle('is-collapsed', collapsed);
    button.textContent = collapsed ? 'Expand' : 'Collapse';
    button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
}

function initInteractions() {
    const refreshButton = document.getElementById('force-refresh-button');
    if (refreshButton) {
        refreshButton.addEventListener('click', () => loadProfile(true, { autoTag: false }));
    }

    const transcriptList = document.getElementById('transcript-list');
    if (transcriptList) {
        transcriptList.addEventListener('click', (event) => {
            const deleteButton = event.target.closest('.transcript-row-delete');
            if (deleteButton) {
                event.preventDefault();
                event.stopPropagation();
                const encodedDeleteId = deleteButton.getAttribute('data-evidence-id');
                if (!encodedDeleteId) return;
                void deleteTranscriptInteractionByEvidenceId(decodeURIComponent(encodedDeleteId), { fromModal: false });
                return;
            }
            const row = event.target.closest('.transcript-row');
            if (!row) return;
            const encodedId = row.getAttribute('data-evidence-id');
            if (!encodedId) return;
            openTranscriptModalById(decodeURIComponent(encodedId));
        });
    }

    document.querySelectorAll('.view-toggle-btn').forEach((button) => {
        button.addEventListener('click', () => setTranscriptMode(button.getAttribute('data-mode')));
    });

    const recalculateButton = document.getElementById('transcript-recalculate');
    if (recalculateButton) {
        recalculateButton.addEventListener('click', recalculateTranscript);
    }

    document.querySelectorAll('.collapse-toggle').forEach((button) => {
        button.addEventListener('click', () => togglePanel(button.getAttribute('data-target')));
    });

    const modal = document.getElementById('transcript-modal');
    const modalClose = document.getElementById('transcript-modal-close');
    const editToggle = document.getElementById('transcript-edit-toggle');
    const saveButton = document.getElementById('transcript-save');
    const cancelButton = document.getElementById('transcript-cancel');
    const deleteButton = document.getElementById('transcript-delete');
    if (modalClose) {
        modalClose.addEventListener('click', closeTranscriptModal);
    }
    if (editToggle) {
        editToggle.addEventListener('click', enterTranscriptEditMode);
    }
    if (saveButton) {
        saveButton.addEventListener('click', saveTranscriptEdit);
    }
    if (cancelButton) {
        cancelButton.addEventListener('click', () => {
            exitTranscriptEditMode(true);
            const item = activeEvidenceItem();
            if (item) renderTranscriptModal(item);
        });
    }
    if (deleteButton) {
        deleteButton.addEventListener('click', deleteTranscriptInteraction);
    }
    if (modal) {
        modal.addEventListener('change', (event) => {
            const select = event.target.closest('.segment-tag-select');
            if (!select) return;
            const evidenceId = decodeURIComponent(String(select.getAttribute('data-evidence-id') || ''));
            const segmentIndex = Number(select.getAttribute('data-segment-index'));
            const tagCode = String(select.value || '').trim();
            if (!evidenceId || !tagCode || Number.isNaN(segmentIndex)) return;
            void applySegmentTagOverrideFromModal(evidenceId, segmentIndex, tagCode);
        });
        modal.addEventListener('click', (event) => {
            if (event.target === modal) closeTranscriptModal();
        });
    }

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') closeTranscriptModal();
    });
}

function clampPercent(value) {
    return Math.max(0, Math.min(100, Number(value || 0)));
}

function parseDateValue(value) {
    const text = String(value || '').trim();
    if (!text) return null;
    const parsed = new Date(text);
    if (Number.isNaN(parsed.getTime())) return null;
    return parsed;
}

function daysSinceDate(dateValue) {
    if (!(dateValue instanceof Date) || Number.isNaN(dateValue.getTime())) return null;
    return Math.max(0, Math.floor((Date.now() - dateValue.getTime()) / 86400000));
}

function relationshipStageIndex(code) {
    const normalized = String(code || '').trim().toUpperCase();
    const match = normalized.match(/^S([1-9])$/);
    if (!match) return 0;
    return Number(match[1]);
}

function stageCadenceDays(relationshipCode, opportunityCode) {
    const relationship = String(relationshipCode || '').trim().toUpperCase();
    const opportunity = String(opportunityCode || '').trim().toUpperCase();
    let days = 14;
    if (relationship === 'S1') days = 30;
    else if (relationship === 'S2') days = 21;
    else if (relationship === 'S3') days = 14;
    else if (relationship === 'S4') days = 10;
    else if (relationship === 'S5') days = 7;
    else if (relationship === 'S6') days = 5;
    else if (relationship === 'S7') days = 4;
    else if (relationship === 'S8' || relationship === 'S9') days = 4;
    if (['O2', 'O3', 'O5', 'O6', 'O7'].includes(opportunity)) {
        days = Math.min(days, 4);
    } else if (['O1', 'O4'].includes(opportunity)) {
        days = Math.min(days, 7);
    }
    return days;
}

function stagePressureScore(relationshipCode, opportunityCode) {
    const relationship = String(relationshipCode || '').trim().toUpperCase();
    const opportunity = String(opportunityCode || '').trim().toUpperCase();
    let score = 45;
    if (relationship === 'S1') score = 24;
    else if (relationship === 'S2') score = 32;
    else if (relationship === 'S3') score = 44;
    else if (relationship === 'S4') score = 52;
    else if (relationship === 'S5') score = 68;
    else if (relationship === 'S6') score = 76;
    else if (relationship === 'S7') score = 84;
    else if (relationship === 'S8') score = 74;
    else if (relationship === 'S9') score = 66;
    if (['O2', 'O3', 'O5', 'O6', 'O7'].includes(opportunity)) score = Math.min(100, score + 8);
    if (['O1', 'O4'].includes(opportunity)) score = Math.min(100, score + 4);
    return score;
}

function actionPriorityBand(priorityScore) {
    const score = clampPercent(priorityScore);
    if (score >= 70) return { className: 'band-red', label: 'Needs Action' };
    if (score >= 40) return { className: 'band-green', label: 'In Motion' };
    return { className: 'band-blue', label: 'Stable' };
}

function newestContactDateFromEvidence(payload = {}) {
    const inputs = filterTranscriptItems(Array.isArray(payload.evidence_inputs) ? payload.evidence_inputs : []);
    if (!inputs.length) return null;
    const interactions = inputs.filter((item) => String((item && item.source_kind) || '').trim().toLowerCase() === 'interaction');
    const source = interactions.length ? interactions : inputs;
    let newest = null;
    for (const item of source) {
        const parsed = parseDateValue((item && item.date_at) || (item && item.date_label));
        if (!parsed) continue;
        if (!newest || parsed.getTime() > newest.getTime()) newest = parsed;
    }
    return newest;
}

function taskDueDate(task) {
    if (!task || typeof task !== 'object') return null;
    const dueDate = String(task.due_date || '').trim();
    if (!dueDate) return null;
    const dueTime = String(task.due_time || '').trim();
    const normalizedTime = dueTime
        ? `${dueTime}${dueTime.length === 5 ? ':00' : ''}`
        : '23:59:59';
    const parsed = new Date(`${dueDate}T${normalizedTime}`);
    if (!Number.isNaN(parsed.getTime())) return parsed;
    const fallback = new Date(`${dueDate}T23:59:59`);
    return Number.isNaN(fallback.getTime()) ? null : fallback;
}

function taskDueLabel(task, dueAt) {
    if (!dueAt) return 'No due date';
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dueDay = new Date(dueAt.getFullYear(), dueAt.getMonth(), dueAt.getDate());
    const dayDiff = Math.round((dueDay.getTime() - today.getTime()) / 86400000);
    if (dayDiff < 0) return `${Math.abs(dayDiff)}d overdue`;
    if (dayDiff === 0) return 'Due today';
    if (dayDiff === 1) return 'Due tomorrow';
    return `Due ${formatDateLabel(String(task.due_date || '').trim())}`;
}

function sortTasksByDueDate(tasks) {
    return [...(Array.isArray(tasks) ? tasks : [])].sort((left, right) => {
        const leftDue = taskDueDate(left);
        const rightDue = taskDueDate(right);
        const leftDueMs = leftDue ? leftDue.getTime() : Number.POSITIVE_INFINITY;
        const rightDueMs = rightDue ? rightDue.getTime() : Number.POSITIVE_INFINITY;
        if (leftDueMs !== rightDueMs) return leftDueMs - rightDueMs;
        const leftCreated = parseDateValue(left && left.created_at);
        const rightCreated = parseDateValue(right && right.created_at);
        const leftCreatedMs = leftCreated ? leftCreated.getTime() : 0;
        const rightCreatedMs = rightCreated ? rightCreated.getTime() : 0;
        return leftCreatedMs - rightCreatedMs;
    });
}

function actionFollowUpBucket(stage1 = {}) {
    const merged = mergeKnowledgeBuckets(stage1);
    return merged.find((box) => String((box && box.box_key) || '').trim() === 'action_follow_up') || null;
}

function computeActionPriorityModel(payload, stage2 = {}, stage1 = {}, tasks = []) {
    const relationshipStage = stage2 && stage2.relationship_stage && typeof stage2.relationship_stage === 'object'
        ? stage2.relationship_stage
        : null;
    const opportunityStage = stage2 && stage2.opportunity_stage && typeof stage2.opportunity_stage === 'object'
        ? stage2.opportunity_stage
        : null;
    const relationshipCode = String((relationshipStage && relationshipStage.code) || '').trim().toUpperCase();
    const opportunityCode = String((opportunityStage && opportunityStage.code) || '').trim().toUpperCase();
    const cadenceDays = stageCadenceDays(relationshipCode, opportunityCode);
    const lastContactAt = newestContactDateFromEvidence(payload);
    const daysSinceContact = daysSinceDate(lastContactAt);
    const openStatuses = new Set(['open', 'in_progress']);
    const activeTasks = (Array.isArray(tasks) ? tasks : []).filter((task) => openStatuses.has(String((task && task.status) || '').toLowerCase()));
    const now = new Date();
    const overdueTasks = activeTasks.filter((task) => {
        const due = taskDueDate(task);
        return !!due && due.getTime() < now.getTime();
    });
    const dueSoonTasks = activeTasks.filter((task) => {
        const due = taskDueDate(task);
        if (!due) return false;
        const diffDays = Math.floor((due.getTime() - now.getTime()) / 86400000);
        return diffDays >= 0 && diffDays <= cadenceDays;
    });
    const actionBucket = actionFollowUpBucket(stage1);
    const actionDepth = clampPercent(actionBucket && actionBucket.contextual_depth_pct);
    const actionKnown = Array.isArray(actionBucket && actionBucket.what_is_known) ? actionBucket.what_is_known : [];
    const ledgerActions = Array.isArray(payload && payload.action_ledger && payload.action_ledger.actions)
        ? payload.action_ledger.actions
        : [];
    const openLedgerActions = ledgerActions.filter((action) => !['done', 'cancelled', 'closed'].includes(String((action && action.status) || '').trim().toLowerCase()));
    const hasDefinedAction = actionDepth >= 70 || openLedgerActions.length > 0 || actionKnown.length > 0;
    const context = payload && payload.person && payload.person.network_score_context && typeof payload.person.network_score_context === 'object'
        ? payload.person.network_score_context
        : {};
    const hasFutureCover = Boolean(context.has_future_cover);
    const queueKey = String(context.queue_key || '').trim().toLowerCase();
    const hasEvidence = daysSinceContact !== null;
    const relationshipHealthRaw = Number(
        (payload && payload.scores && payload.scores.relationship_health_score)
        ?? (payload && payload.score)
        ?? 55
    );
    const relationshipHealth = clampPercent(relationshipHealthRaw);
    const healthPressure = clampPercent(100 - relationshipHealth);
    const topTask = sortTasksByDueDate(activeTasks)[0] || null;
    const topTaskDueAt = topTask ? taskDueDate(topTask) : null;
    const topActionText = String(
        ((openLedgerActions[0] && openLedgerActions[0].action_text) || '')
        || ((actionKnown[0] && actionKnown[0].point) || '')
    ).trim();

    if (!hasEvidence) {
        const stageLabelNoScore = relationshipStage
            ? String(relationshipStage.label || relationshipCode || 'Unknown stage').trim()
            : (relationshipCode ? relationshipJourneyCodeLabel(relationshipCode) : 'Unknown stage');
        return {
            hasScore: false,
            priority: null,
            band: { className: 'band-none', label: 'No Score' },
            reasonText: 'No transcript or interaction evidence captured yet.',
            cadenceDays,
            relationshipCode,
            stageLabel: stageLabelNoScore,
            opportunityCode,
            daysSinceContact,
            relationshipHealth,
            actionDepth,
            activeTaskCount: activeTasks.length,
            overdueTaskCount: overdueTasks.length,
            dueSoonTaskCount: dueSoonTasks.length,
            topTask,
            topTaskDueLabel: topTask ? taskDueLabel(topTask, topTaskDueAt) : '',
            topActionText: topActionText ? previewLine(topActionText, 150) : '',
        };
    }

    let contactUrgency = 82;
    if (daysSinceContact !== null) {
        if (daysSinceContact <= Math.floor(cadenceDays * 0.6)) contactUrgency = 16;
        else if (daysSinceContact <= cadenceDays) contactUrgency = 34;
        else if (daysSinceContact <= Math.ceil(cadenceDays * 1.5)) contactUrgency = 58;
        else if (daysSinceContact <= cadenceDays * 2) contactUrgency = 76;
        else contactUrgency = 92;
    }

    let taskUrgency = 28;
    if (overdueTasks.length > 0) taskUrgency = Math.min(100, 70 + (overdueTasks.length * 12));
    else if (activeTasks.length > 0 && !hasFutureCover) taskUrgency = 46;
    else if (activeTasks.length > 0) taskUrgency = 28;
    else if (hasDefinedAction) taskUrgency = 84;

    let actionUrgency = 30;
    if (hasDefinedAction && activeTasks.length === 0) actionUrgency = 88;
    else if (hasDefinedAction && overdueTasks.length > 0) actionUrgency = 78;
    else if (hasDefinedAction && activeTasks.length > 0) actionUrgency = 42;
    else if (!hasFutureCover) actionUrgency = 62;

    let priority = Math.round(
        (contactUrgency * 0.34)
        + (taskUrgency * 0.28)
        + (actionUrgency * 0.2)
        + (healthPressure * 0.18)
    );

    if (activeTasks.length > 0 && overdueTasks.length === 0 && daysSinceContact !== null && daysSinceContact <= cadenceDays) {
        priority -= 10;
    }
    if (hasFutureCover && overdueTasks.length === 0) priority -= 6;
    if (queueKey === 'act_now') priority += 14;
    else if (queueKey === 'maintain') priority += 2;
    else if (queueKey === 'preserve') priority -= 8;
    else if (queueKey === 'monitor') priority -= 14;
    priority = clampPercent(priority);

    const reasonParts = [];
    if (overdueTasks.length > 0) reasonParts.push(`${overdueTasks.length} overdue task${overdueTasks.length === 1 ? '' : 's'}`);
    if (daysSinceContact > cadenceDays) reasonParts.push(`contact gap ${daysSinceContact}d (target ${cadenceDays}d)`);
    if (hasDefinedAction && activeTasks.length === 0) reasonParts.push('defined action without scheduled task');
    if (!hasFutureCover) reasonParts.push('no dated next step booked');
    const reasonText = reasonParts.length
        ? reasonParts.join(' | ')
        : 'Cadence and tasks are aligned for this relationship.';

    const stageLabel = relationshipStage
        ? String(relationshipStage.label || relationshipCode || 'Unknown stage').trim()
        : (relationshipCode ? relationshipJourneyCodeLabel(relationshipCode) : 'Unknown stage');
    const band = actionPriorityBand(priority);

    return {
        hasScore: true,
        priority,
        band,
        reasonText,
        cadenceDays,
        relationshipCode,
        stageLabel,
        opportunityCode,
        daysSinceContact,
        relationshipHealth,
        actionDepth,
        activeTaskCount: activeTasks.length,
        overdueTaskCount: overdueTasks.length,
        dueSoonTaskCount: dueSoonTasks.length,
        topTask,
        topTaskDueLabel: topTask ? taskDueLabel(topTask, topTaskDueAt) : '',
        topActionText: topActionText ? previewLine(topActionText, 150) : '',
    };
}

function actionPriorityAgendaUrl(person = {}) {
    const params = new URLSearchParams();
    const personId = String(person.person_id || personIdFromPath() || '').trim();
    const contactName = String(person.full_name || '').trim();
    const employer = String(person.company_name_raw || '').trim();
    if (personId) params.set('person_id', personId);
    if (contactName) params.set('contact_name', contactName);
    if (employer) params.set('employer', employer);
    const suffix = params.toString();
    return `/agenda.html${suffix ? `?${suffix}` : ''}`;
}

function renderActionPriorityWidgetMarkup(model, person = {}) {
    const hasScore = !!(model && model.hasScore);
    const score = hasScore ? clampPercent(model && model.priority) : null;
    const band = (model && model.band) || actionPriorityBand(score);
    const barWidth = hasScore ? clampPercent(score) : 0;
    const scoreText = hasScore ? `${score}%` : '--';
    const daysSinceLabel = model.daysSinceContact === null
        ? 'No contact date'
        : (model.daysSinceContact === 0 ? 'Today' : `${model.daysSinceContact}d ago`);
    const taskLine = model.activeTaskCount === 0
        ? 'No active tasks'
        : `${model.activeTaskCount} active | ${model.overdueTaskCount} overdue | ${model.dueSoonTaskCount} due within cadence`;
    const stageLine = model.opportunityCode
        ? `${model.stageLabel} + ${model.opportunityCode}`
        : model.stageLabel;
    const nextActionLine = model.topActionText
        ? model.topActionText
        : 'No explicit next action captured yet.';
    const nextTaskLine = model.topTask
        ? `${String(model.topTask.task_text || '').trim()} (${model.topTaskDueLabel})`
        : 'No active task scheduled.';
    const agendaUrl = actionPriorityAgendaUrl(person);
    return `
        <div class="action-priority-head">
            <div class="action-priority-score-wrap">
                <div class="action-priority-kicker">Action Priority</div>
                <div class="action-priority-score">${esc(scoreText)}</div>
                <div class="action-priority-band">${esc(band.label)}</div>
            </div>
            <div>
                <div class="action-priority-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${esc(hasScore ? score : 0)}">
                    <span style="width:${esc(barWidth)}%"></span>
                </div>
                <div class="action-priority-reason">${esc(model.reasonText || '')}</div>
            </div>
        </div>
        <div class="action-priority-metrics">
            <span class="chip">Last contact ${esc(daysSinceLabel)} (target ${esc(model.cadenceDays)}d)</span>
            <span class="chip">${esc(taskLine)}</span>
            <span class="chip">Stage ${esc(stageLine)}</span>
            <span class="chip">K10 Action ${esc(Math.round(model.actionDepth || 0))}%</span>
            <span class="chip">Health ${esc(Math.round(model.relationshipHealth || 0))}%</span>
        </div>
        <div class="action-priority-next"><strong>Next action:</strong> ${esc(nextActionLine)}</div>
        <div class="action-priority-next"><strong>Next task:</strong> ${esc(nextTaskLine)}</div>
        <div class="action-priority-links">
            <a href="${esc(agendaUrl)}">Open tasks in Agenda</a>
        </div>
    `;
}

function applyActionPriorityBand(root, className) {
    if (!root) return;
    root.classList.remove('band-blue', 'band-green', 'band-red', 'band-none');
    root.classList.add(className || 'band-blue');
}

async function renderActionPriorityWidget(payload, stage2 = {}, stage1 = {}) {
    const root = document.getElementById('action-priority-widget');
    if (!root) return;
    const runId = (profileState.actionWidgetRunId || 0) + 1;
    profileState.actionWidgetRunId = runId;
    profileState.actionWidgetBusy = true;
    root.classList.add('is-loading');
    applyActionPriorityBand(root, 'band-blue');
    root.textContent = 'Calculating action priority...';
    const person = (payload && payload.person) || {};
    const personId = String(person.person_id || personIdFromPath() || '').trim();
    if (!personId) {
        root.textContent = 'Action priority unavailable (missing person id).';
        profileState.actionWidgetBusy = false;
        return;
    }
    try {
        const response = await fetch(`${apiBase}/api/tasks?status=all&person_id=${encodeURIComponent(personId)}`, {
            cache: 'no-store'
        });
        if (!response.ok) throw new Error(`Task load failed (HTTP ${response.status})`);
        const tasks = await response.json();
        if (profileState.actionWidgetRunId !== runId) return;
        const model = computeActionPriorityModel(payload, stage2, stage1, Array.isArray(tasks) ? tasks : []);
        root.classList.remove('is-loading');
        applyActionPriorityBand(root, model.band.className);
        root.innerHTML = renderActionPriorityWidgetMarkup(model, person);
    } catch (_error) {
        if (profileState.actionWidgetRunId !== runId) return;
        root.classList.remove('is-loading');
        applyActionPriorityBand(root, 'band-blue');
        root.textContent = 'Action priority unavailable right now.';
    } finally {
        if (profileState.actionWidgetRunId === runId) {
            profileState.actionWidgetBusy = false;
        }
    }
}

function renderHeader(payload) {
    const person = payload.person || {};
    const titleEl = document.getElementById('page-title');
    const metaEl = document.getElementById('header-meta');
    if (titleEl) titleEl.textContent = person.full_name || 'Profile';
    if (metaEl) {
        metaEl.textContent = [person.company_name_raw, person.title_current].filter(Boolean).join(' | ');
    }
}

async function loadProfile(forceRefresh = false, options = {}) {
    const statusLine = document.getElementById('status-line');
    const refreshButton = document.getElementById('force-refresh-button');
    const autoTag = !!(options && options.autoTag === true);
    const autoTagOnChange = !options || options.autoTagOnChange !== false;
    if (refreshButton) refreshButton.disabled = true;
    if (statusLine) statusLine.textContent = forceRefresh ? 'Refreshing...' : 'Loading...';

    try {
        const personId = personIdFromPath();
        if (!personId) {
            throw new Error('Missing person id in URL');
        }
        const response = forceRefresh
            ? await fetch(`${apiBase}/api/network-lab/profile/${personId}/relationship-intelligence/refresh`, {
                method: 'POST',
                cache: 'no-store'
            })
            : await fetch(`${apiBase}/api/network-lab/profile/${personId}/relationship-intelligence`, {
                cache: 'no-store'
            });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const payload = await response.json();
        const incomingSignature = profilePayloadSignature(payload);
        const storedSignature = readStoredProfileSignature(personId);
        const changedSinceLastSeen = !!storedSignature && storedSignature !== incomingSignature;
        const firstSeenSignature = !storedSignature;
        profileState.latestProfileSignature = incomingSignature;
        applyTranscriptTaggingConfig(payload.transcript_tagging || null);
        const stage2Raw = payload.relationship_business_flow_stage2 || ((payload.briefing && payload.briefing.relationship_business_flow_stage2) || {});
        const stage2Base = normalizeStage2ForDisplay(stage2Raw);
        const stage1 = payload.knowledge_bank_stage1 || {};

        profileState.payload = payload;
        profileState.stage2Base = stage2Base;
        resetTranscriptTagRuntime();
        const restoredTagCache = readStoredTranscriptTagCache(personId, incomingSignature);
        profileState.stage2 = resolveStage2ForDisplay(payload);
        renderHeader(payload);
        renderStages(profileState.stage2);
        renderKnowledgeBank(stage1);
        void renderActionPriorityWidget(payload, profileState.stage2, stage1);
        renderTranscript(payload);
        if (statusLine) statusLine.textContent = `Loaded (${(payload.pipeline_meta && payload.pipeline_meta.cache_status) || 'miss'} cache).`;
        writeStoredProfileSignature(personId, incomingSignature);
        if (autoTag || (autoTagOnChange && (changedSinceLastSeen || (firstSeenSignature && !restoredTagCache)))) {
            recalculateTranscriptTagsForModes(['stage', 'knowledge'], { onlyMissing: true }).catch((error) => {
                profileState.segmentTagLastError = String((error && error.message) || 'Transcript tagging failed').trim();
                if (profileState.transcriptMode) renderTranscript(profileState.payload || payload);
            });
        }
    } catch (error) {
        if (statusLine) statusLine.textContent = `Load failed: ${error.message}`;
    } finally {
        if (refreshButton) refreshButton.disabled = false;
    }
}

async function pollProfileIfChanged() {
    if (profileState.reactivePollBusy) return;
    if (document.hidden) return;
    const personId = personIdFromPath();
    if (!personId) return;
    profileState.reactivePollBusy = true;
    try {
        const response = await fetch(`${apiBase}/api/network-lab/profile/${personId}/relationship-intelligence`, {
            cache: 'no-store'
        });
        if (!response.ok) return;
        const payload = await response.json();
        const incomingSignature = profilePayloadSignature(payload);
        if (!incomingSignature) return;
        if (incomingSignature === profileState.latestProfileSignature) return;
        await loadProfile(false, { autoTag: true });
        const statusLine = document.getElementById('status-line');
        if (statusLine) statusLine.textContent = 'Auto-updated after new transcript input.';
    } catch (_error) {
        // Keep polling silent; manual refresh remains available.
    } finally {
        profileState.reactivePollBusy = false;
    }
}

function startReactivePolling() {
    if (profileState.reactivePollHandle) {
        window.clearInterval(profileState.reactivePollHandle);
    }
    profileState.reactivePollHandle = window.setInterval(() => {
        void pollProfileIfChanged();
    }, 8000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            void pollProfileIfChanged();
        }
    });
}

function boot() {
    clearLegacyProfileSignatureCache();
    clearLegacyTranscriptTagCache();
    initInteractions();
    updateTranscriptToggleUi();
    startReactivePolling();
    loadProfile(false, { autoTag: false, autoTagOnChange: true });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
} else {
    boot();
}
