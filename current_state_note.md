# Antigravity CRM — Current State Note (Baseline v2.0.0)

This document provides a concise summary of the project's health and functionality as of the `baseline-v2.0.0` branch.

## 1. What Works
*   **Core CRUD**: Robust creation, updating, and searching of contact profiles (PERSON table).
*   **Unified Profile Editing**: A single modal handles all profile essentials (Name, Title, Email, Phone, Company) with real-time persistence.
*   **AI Intelligence Extraction**: Automated processing of meeting notes to extract "Nuggets" (Business Focus, Recruitment, Personal Rapport, OBE).
*   **Strategic Briefing**: Dynamic generation of 4-quadrant SIT-REPs using GPT-4o.
*   **Multi-tenant Ready Schema**: The database supports users, roles, and compartmentalized interaction logs.
*   **Platinum UI**: Global design system implemented with a dark glassmorphic aesthetic and high-density information layouts.

## 2. What is Broken / Inconsistent
*   **Global Authentication**: While the `auth` system exists, it is not currently enforced as global middleware; several API routes and the `/uploads/` directory are currently public.
*   **M365 Real-time Sync**: Required by current workflow. A dedicated background worker has been added, feature-flagged via `M365_ENABLED`, and sync status now stored in `M365_ACCOUNT` table. The previous v1 stubs have been replaced with real endpoints and the worker is isolated to prevent failures from crashing the core CRM.
*   **Legacy Route Duplication**: Inconsistencies exist between v1 "compat" routes and v2 native routes in terms of payload handling.

## 3. What is Placeholder / Stub
*   **M365 Connection Status**: OAuth device-code endpoints implemented (`/api/m365/auth/start`, `/api/m365/auth/status`) with token persistence, automatic refresh, and polling. Worker logic now calls Microsoft Graph to retrieve emails filtered by a contact's primary address; results are stored as `INTERACTION` rows with external-id dedup. UI shows sync status, count, and error messages. Legacy compat routes forward to the new implementation.
*   **AI Twin Chat**: The "Twin Chat" feature (`/api/intelligence/twin/chat`) is a stub that acknowledges input but lacks logic.
*   **Analytics V2 Propensity**: Advanced prediction of "Peak Engagement Time" exists as a frontend design requirement with mocked backend endpoints.

## 4. What is Risky (Immediate Technical Debt)
*   **Concurrency limits**: SQLite Single-connection architecture will fail under medium-load concurrent writes (WAL mode is enabled but not a panacea for the current async pool setup).
*   **Code Maintainability**: Extremely large monolithic Javascript files (e.g., `profile.js`) make debugging and unit testing difficult.
*   **Secret Management**: The `.env` file is vulnerable to runtime modification via the `/api/config/ai` route, which writes directly to the file system.
*   **Static Asset Exposure**: Private interaction recordings and photos in `/uploads/` are currently served without file-level permission checks.
