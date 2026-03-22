from backend.database import run_read
from backend.services.network_orchestration_service import build_network_feed


def _recommended_pilot_ids_from_feed(feed: dict) -> tuple[list[str], dict]:
    everyone = [
        item
        for queue_name in ("act_now", "maintain", "preserve", "monitor")
        for item in feed.get(queue_name, [])
    ]
    by_id = {item["person_id"]: item for item in everyone if item.get("person_id")}
    rich_contacts = sorted(
        everyone,
        key=lambda item: (
            int(item.get("interaction_count") or 0),
            int(item.get("network_health_score") or 0),
            1 if item.get("has_relationship_signal") else 0,
        ),
        reverse=True,
    )
    sparse_contacts = sorted(
        [
            item
            for item in everyone
            if not item.get("has_relationship_signal") or not item.get("has_future_cover")
        ],
        key=lambda item: (
            1 if not item.get("has_relationship_signal") else 0,
            1 if not item.get("has_future_cover") else 0,
            int(item.get("interaction_count") or 0),
        ),
        reverse=True,
    )
    pilot_ids: list[str] = []
    for item in rich_contacts[:30]:
        person_id = str(item.get("person_id") or "").strip()
        if person_id and person_id not in pilot_ids:
            pilot_ids.append(person_id)
    for item in sparse_contacts[:20]:
        person_id = str(item.get("person_id") or "").strip()
        if person_id and person_id not in pilot_ids:
            pilot_ids.append(person_id)
    pilot_ids = pilot_ids[:50]
    pilot_summary = {
        "recommended_size": len(pilot_ids),
        "rich_contacts": len([pid for pid in pilot_ids if pid in by_id and by_id[pid] in rich_contacts[:30]]),
        "sparse_contacts": len([pid for pid in pilot_ids if pid in by_id and by_id[pid] in sparse_contacts[:20]]),
    }
    return pilot_ids, pilot_summary


async def load_explicit_pilot_ids() -> list[str]:
    async def _read(db):
        async with db.execute(
            """
            SELECT person_id
            FROM PERSON
            WHERE is_active = 1
              AND COALESCE(is_pilot_cohort, 0) = 1
            ORDER BY
                datetime(COALESCE(pilot_cohort_assigned_at, last_updated_at, created_at)) DESC,
                full_name COLLATE NOCASE
            """
        ) as cursor:
            return [str(row["person_id"]) for row in await cursor.fetchall() if row["person_id"]]

    return await run_read(_read, label="load explicit pilot cohort")


async def resolve_pilot_cohort(feed: dict | None = None) -> tuple[list[str], dict]:
    current_feed = feed or await build_network_feed()
    recommended_ids, recommended_summary = _recommended_pilot_ids_from_feed(current_feed)
    visible_people = {
        str(item.get("person_id") or "").strip()
        for queue_name in ("act_now", "maintain", "preserve", "monitor")
        for item in current_feed.get(queue_name, [])
        if str(item.get("person_id") or "").strip()
    }
    explicit_ids = [person_id for person_id in await load_explicit_pilot_ids() if person_id in visible_people]
    resolved_ids = explicit_ids if explicit_ids else recommended_ids
    mode = "explicit" if explicit_ids else "recommended"
    summary = {
        **recommended_summary,
        "mode": mode,
        "selected_size": len(resolved_ids),
        "explicit_size": len(explicit_ids),
        "message": (
            f"Explicit pilot cohort: {len(resolved_ids)} contacts. Topic review, databank scope, and assistant resolution are locked to this set."
            if mode == "explicit"
            else (
                f"Recommended pilot cohort: {len(resolved_ids)} contacts, biased toward the richest profiles with a smaller weak-signal slice for missed-contact testing."
            )
        ),
    }
    return resolved_ids, summary


async def is_person_in_pilot_cohort(person_id: str, feed: dict | None = None) -> tuple[bool, dict]:
    pilot_ids, pilot_summary = await resolve_pilot_cohort(feed)
    return str(person_id or "").strip() in set(pilot_ids), pilot_summary
