from backend.database import get_db

async def run_integrity_audit():
    """
    Performs a deep audit of the DB and auto-repairs common issues.
    """
    stats = {
        "repaired_labels": 0,
        "orphans_removed": 0,
        "normalized_event_statuses": 0,
        "stale_jobs_requeued": 0,
        "artifacts_flagged_for_review": 0,
        "status": "clean",
    }
    
    async with get_db() as db:

        # 1. Repair "Not set" or "Unknown" labels from legacy data
        res = await db.execute("""
            UPDATE PERSON 
            SET cat = 'GEN' 
            WHERE cat IS NULL OR cat IN ('Not set', 'Unknown', '')
        """)
        stats["repaired_labels"] += res.rowcount

        # 2. Cleanup orphaned topic intelligence (missing person)
        res = await db.execute("""
            DELETE FROM TOPIC_INTELLIGENCE 
            WHERE person_id NOT IN (SELECT person_id FROM PERSON)
        """)
        stats["orphans_removed"] += res.rowcount

        for raw_status, canonical_status in {
            "invited": "Invited",
            "target": "Target",
            "confirmed": "Confirmed",
            "registered": "Registered",
        }.items():
            res = await db.execute(
                "UPDATE PERSON_EVENT SET status = ? WHERE LOWER(TRIM(status)) = ?",
                (canonical_status, raw_status),
            )
            stats["normalized_event_statuses"] += res.rowcount

        res = await db.execute(
            """
            UPDATE AI_JOB
            SET status = 'queued', started_at = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE status = 'running'
              AND started_at IS NOT NULL
              AND datetime(started_at) < datetime('now', '-30 minutes')
            """
        )
        stats["stale_jobs_requeued"] += res.rowcount

        res = await db.execute(
            """
            UPDATE AI_ARTIFACT
            SET status = 'needs_review'
            WHERE status = 'processed'
              AND input_type IN ('document', 'screenshot')
              AND (extracted_text IS NULL OR TRIM(extracted_text) = '')
            """
        )
        stats["artifacts_flagged_for_review"] += res.rowcount

        # 3. Clear stale briefing caches (older than 48h)
        # This ensures briefings are always freshly generated for active contacts.
        await db.execute("""
            UPDATE PERSON 
            SET cached_briefing = NULL 
            WHERE last_updated_at < datetime('now', '-48 hours')
        """)

        await db.commit()
    
    return stats

async def synthesize_global_memory():
    """
    Consolidates fragmented global memory nuggets into coherent entity profiles.
    In Phase 2.6, this deduplicates by (entity_ref, memory_type).
    """
    async with get_db() as db:
        # Identify duplicates
        async with db.execute("""
            SELECT entity_ref, memory_type, COUNT(*) as count 
            FROM PLATFORM_MEMORY 
            GROUP BY entity_ref, memory_type 
            HAVING count > 1
        """) as c:
            dupes = await c.fetchall()
        
        merged_count = 0
        for d in dupes:
            entity = d['entity_ref']
            mtype = d['memory_type']
            
            # Get all texts for this entity
            async with db.execute("SELECT memory_id, memory_text FROM PLATFORM_MEMORY WHERE entity_ref=? AND memory_type=?", (entity, mtype)) as c:
                records = await c.fetchall()
            
            if not records: continue
            
            # Keep the newest one, combine text if distinct
            newest_id = records[0]['memory_id']
            combined_text = " | ".join(list(set([r['memory_text'] for r in records])))
            
            # Update newest
            await db.execute("UPDATE PLATFORM_MEMORY SET memory_text=?, strength=strength+? WHERE memory_id=?", 
                      (combined_text[:500], len(records)-1, newest_id))
            
            # Delete others
            ids_to_del = [r['memory_id'] for r in records if r['memory_id'] != newest_id]
            if ids_to_del:
                placeholders = ','.join(['?'] * len(ids_to_del))
                await db.execute(f"DELETE FROM PLATFORM_MEMORY WHERE memory_id IN ({placeholders})", ids_to_del)
                merged_count += len(ids_to_del)

        await db.commit()
    return {"merged_fragments": merged_count}

async def get_platinum_score():
    """
    Calculates a 'Platinum Score' based on data completeness and health.
    """
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as total FROM PERSON") as c:
            row = await c.fetchone()
            total_people = row[0]
        
        if total_people == 0: return 100
        
        # Deduction for missing critical profile info
        async with db.execute("SELECT COUNT(*) FROM PERSON WHERE cat='GEN' OR env IS NULL OR disc IS NULL") as c:
            row = await c.fetchone()
            incomplete = row[0]
        
        # Deduction for low-engagement interactions
        async with db.execute("SELECT COUNT(*) FROM INTERACTION WHERE success_rating < 2") as c:
            row = await c.fetchone()
            low_value = row[0]
        
        score = 100 - ( (incomplete / total_people) * 20 ) - ( min(low_value, 100) / 10 )
    
    return max(int(score), 0)
