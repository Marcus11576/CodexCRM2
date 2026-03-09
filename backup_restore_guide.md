# Antigravity CRM - Backup & Restore System

This document outlines the procedures for ensuring data safety and recovery for the Antigravity CRM.

## 1. What is Backed Up?
The system creates a compressed `.zip` archive containing:
- **Database**: `crm.db` (All contacts, interactions, and intelligence).
- **Uploads**: All files, photos, and audio briefs in the `uploads/` directory.
- **Configuration**: The `.env` file containing application settings.

## 2. Backup Schedule & Retention
- **Frequency**: Automated backups run every 24 hours via the "Nightly Heartbeat" and immediately upon server startup if no backup exists for the day.
- **Retention Rules**:
    - **Daily**: Keeps the last 7 daily backups.
    - **Weekly**: Keeps the last 4 weekly backups.
    - **Monthly**: Keeps the last 3 monthly backups.

## 3. Storage Locations
Backups are stored in two distinct locations for redundancy:
1.  **Local**: `C:/Users/marcu/.antigravity/antigravity-crm/backups/`
2.  **External**: `C:/Users/marcu/Antigravity_Backups_External/`

## 4. How to Restore Data
Restoring data will overwrite your current database and files. **Stop the server before restoring.**

### One-Click Restore Steps:
1.  Open a terminal in the project folder.
2.  Run the restore command:
    ```powershell
    python scripts/restore.py
    ```
3.  Select the desired backup from the list provided.
4.  When prompted, type **RESTORE** (case-sensitive) to confirm.
5.  Wait for the "RESTORE COMPLETE: SUCCESS" message.
6.  Restart the CRM server.

## 5. How to Verify Success
- **Check Logs**: Monitor the server console for `BACKUP: Automated backup complete`.
- **Verify Files**: Ensure new zip files appear in both the `backups/` and external folders.
- **Test Script**: Developers can run `python tests/test_backup_restore.py` at any time to verify system integrity.
