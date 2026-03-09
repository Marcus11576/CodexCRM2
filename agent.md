# Antigravity CRM: Project Handbook & Agent Intelligence

This document provides complete context for any AI agent or developer inheriting this project. It summarizes the architecture, current state, and the "Platinum Standard" requirements essential for maintaining the system's integrity and aesthetic.

## 1. Project Overview
**Antigravity CRM** is a high-end Relationship Intelligence Platform designed for elite networking and strategic contact management. It features a "Platinum" aesthetic (dark glassmorphism, unblurred scenery, high-contrast accents) and a robust AI pipeline for automated intelligence extraction.

### Core Tech Stack
- **Backend**: FastAPI (Python 3.10+), `aiosqlite` (WAL mode), `Pydantic`
- **Frontend**: Vanilla HTML5/CSS3/JavaScript (No frameworks like React/Vue)
- **Design Standard**: "Platinum" (Dark glass panels, zero motion-based hovers, strict typography: Inter/Outfit)
- **AI Infrastructure**: Prepared data foundation (Artifacts, Signals, Briefs, Feedback)

---

## 2. Current Architecture & Data Flow

### AI Data Foundation (Signals & Traceability)
The system is built on four logical layers to ensure AI reliability and traceability:
1. **Artifacts**: Raw source material (immutable).
2. **Signals**: Extracted intelligence points. Must belong to exactly one category:
   - `Business Focus`
   - `Recruitment & Talent`
   - `Family & Personal`
   - `OBE Focus`
3. **Briefs**: Cached meeting summaries generated *only* from approved signals.
4. **Feedback**: Human-in-the-loop audit trail (Approval/Rejection/Edit) to prevent "silent overwriting".

### Database Schema
- `PERSON`: Core profile data with cached briefings and predictive metrics stubs.
- `INTERACTION`: Unified log for emails, meetings, calls, and WhatsApp imports.
- `AI_ARTIFACT`, `AI_SIGNAL`, `AI_BRIEF`, `AI_FEEDBACK`: New pipeline storage for Phase 2.
- `CONFIG_TAXONOMY`: Canonical source of truth for all status and environment codes.

---

## 3. Current State & Recent Accomplishments

### Completed Milestones
- [x] **Responsive UI Pass**: Dashboard and Profile pages are stable across desktop, tablet, and mobile.
- [x] **Backup & Restore System**: Robust automated backup with SQLite sidecar handling (`-wal`, `-shm`).
- [x] **AI Data Foundation**: Schema and API endpoints for the Artifact-Signal-Feedback loop are verified.
- [x] **Identity Hardening**: Session-based auth and protected uploads are enforced.

### Known Issues & Technical Debt
- **AI Logic**: Currently uses stubs/placeholders for the actual LLM generation in several areas.
- **Mobile UX**: While responsive, full mobile-specific UX optimizations (Phase 3) are not yet implemented.
- **Stub Routes**: Some `v1` and `v2` compatibility routers contain stubs that need production hardening.

---

## 4. Key Entry Points
- **Backend Entry**: [main.py](file:///c:/Users/marcu/.antigravity/antigravity-crm/backend/main.py)
- **Schema Definition**: [database.py](file:///c:/Users/marcu/.antigravity/antigravity-crm/backend/database.py)
- **AI Pipeline Router**: [ai_pipeline.py](file:///c:/Users/marcu/.antigravity/antigravity-crm/backend/routers/ai_pipeline.py)
- **Global Styles**: [design-system.css](file:///c:/Users/marcu/.antigravity/antigravity-crm/frontend/static/design-system.css)

---

## 5. Roadmap & Next Steps
1. **Full AI Implementation**: Connect the pipeline endpoints to real GPT-4/LLM services for signal extraction.
2. **Strategic Hypothesis Module**: Activate the "hypotheses" engine within the profile briefing.
3. **Advanced Mobile UX**: Refine the 3-panel profile layout for dedicated mobile 앱 experience.
4. **Platform Memory**: Implement cross-contact learning via `PLATFORM_MEMORY`.

---

*Verified by Antigravity AI on 2026-03-09.*
