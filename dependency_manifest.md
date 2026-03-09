# Dependency Manifest — Antigravity CRM v2.0.0

This manifest lists all core dependencies required to run the Antigravity CRM platform.

### Backend (Python 3.10+)
- **fastapi**: Core API framework.
- **uvicorn[standard]**: ASGI server for production-grade serving.
- **aiosqlite**: Asynchronous interaction with the SQLite database.
- **pydantic[email]**: Data validation and settings management.
- **openai**: SDK for GPT-4o, Whisper, and TTS.
- **python-multipart**: Required for file upload and form processing.
- **httpx**: Async HTTP client for external service integration and testing.
- **python-dotenv**: Environment variable management.
- **PyMuPDF (fitz)**: Text extraction from PDF uploads.

### Frontend (Browser-Native)
- **Vanilla Javascript (ES6+)**: Primary logic layer.
- **FontAwesome 6.4+**: Iconography.
- **Google Fonts (Outfit & Inter)**: Typography.
- **Browser-Standard CSS3**: "Platinum" design system (using variables, flexbox, and grid).

### Database
- **SQLite 3.35+**: Using WAL (Write-Ahead Logging) for concurrent access support.
