// Relationship links card for profile pages.

function relationshipTargetHref(personId) {
    return `/person/${encodeURIComponent(personId || '')}`;
}

function renderRelationshipLinks(relationships) {
    const list = document.getElementById('relationship-links-list');
    if (!list) return;

    if (!Array.isArray(relationships) || relationships.length === 0) {
        list.innerHTML = `
            <div class="relationship-links-empty">
                No linked people found yet. Shared companies and named mentions in notes will appear here.
            </div>
        `;
        return;
    }

    list.innerHTML = relationships.slice(0, 8).map((relationship) => {
        const meta = relationshipDisplayMeta(relationship.relationship_type);
        const title = escapeHtml(relationship.title_current || 'No title');
        const company = escapeHtml(relationship.company_name_raw || 'Unknown company');
        const reasonParts = [relationship.reason, ...(relationship.secondary_reasons || [])]
            .filter(Boolean)
            .slice(0, 2)
            .map(escapeHtml);
        const confidencePct = Math.round(Number(relationship.confidence || 0) * 100);
        const evidenceLine = relationship.mention_excerpt
            ? `<div class="relationship-link-evidence">Evidence: ${escapeHtml(relationship.mention_excerpt)}</div>`
            : relationship.link_basis === 'same_company'
                ? `<div class="relationship-link-evidence">Evidence: shared company only, review before treating as a confirmed relationship.</div>`
                : '';

        return `
            <a class="relationship-link-row" href="${relationshipTargetHref(relationship.person_id)}">
                <div class="relationship-link-avatar">
                    ${avatarHtml(relationship, 'sm')}
                </div>
                <div class="relationship-link-copy">
                    <div class="relationship-link-top">
                        <div class="relationship-link-name">${escapeHtml(relationship.full_name || 'Unknown')}</div>
                        <div class="relationship-link-badge relationship-link-badge-${meta.tone}" title="${meta.label}">
                            <i class="${meta.icon}"></i>
                            <span>${meta.label}</span>
                        </div>
                    </div>
                    <div class="relationship-link-meta">${title} @ ${company}</div>
                    <div class="relationship-link-reason">${reasonParts.join(' | ')} | Confidence ${confidencePct}%</div>
                    ${evidenceLine}
                </div>
            </a>
        `;
    }).join('');
}
