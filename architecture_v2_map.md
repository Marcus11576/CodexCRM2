# Revised Architecture Map — Antigravity CRM v2.0.0

This map outlines the flow of data and the relationship between core components for a 3rd party architectural review.

## 1. System Overview
Antigravity CRM is a relationship intelligence platform built on a Python/FastAPI backend and a Vanilla JS/CSS frontend. It uses OpenAI (GPT-4o) for real-time intelligence extraction and strategic meeting preparation.

## 2. Core Data Flow
1. **Ingestion**: Raw data (interaction notes, emails, M365 sync, file uploads) enters via **Routers** (`backend/routers/`).
2. **Authentication**: All non-public routes are protected via **HttpOnly Session Cookies**. Tokens are no longer stored in LocalStorage.
3. **Processing**: Routers invoke **Services** (`backend/services/`).
    - `ai_service.py` extracts "Intelligence Nuggets" (business, recruitment, personal, OBE).
    - `analytics_service.py` updates relationship health and propensity scores.
4. **Storage**: Data is persisted in **SQLite** via an async bridge (`backend/database.py`).
5. **Security**: The `/uploads/` directory is protected; files are served only to authenticated sessions.
6. **Synthesis**: The `strategist_service.py` runs cross-contact audits.
7. **Consumption**: The **Frontend** fetches JSON via REST endpoints and renders a "Platinum" glassmorphic UI.

## 3. Component Breakdown

### Backend Entrypoints
- `backend/main.py`: FastAPI initialization, lifespans, and global middleware.
- `start.bat`: Local development environment bootstrap.

### Modular Routers
- `people.py`: CRUD for `PERSON` and profile rendering data.
- `interactions.py`: High-frequency logging for the timeline.
- `intelligence.py`: Segmented 4-quadrant interest databank.
- `analytics.py`: Propensity, health, and engagement velocity metrics.
- `compat_v1.py`: Legacy support for older UI components.

### Core Services
- `ai_service.py`: Centralized LLM orchestration (Whisper, TTS, GPT-4o).
- `strategist_service.py`: Generates the "Strategic Synthesis" and "Intelligence Gaps".
- `health_service.py`: Automated system audits and data integrity checks.

### Frontend Structure
- `profile.html`: Main SPA-style container for contact details.
- `static/css/design-system.css`: Global visual tokens and "Platinum" aesthetics.
- `js/profile.js`: Primary DOM controller for the profile page.
- `js/plugins/`: Modular extension points for 3rd party features.

## 4. Connectivity & Extensions
- **M365 Integration**: Background workers (v2) handle continuous email sync by polling Microsoft Graph using a shared OAuth device‑code token. Incoming messages are automatically persisted as `INTERACTION` rows with `external_id` deduplication; sync metadata lives in `M365_ACCOUNT`.
- **REST API**: All backend functionality is exposed via documented OpenAPI (Swagger) routes.
