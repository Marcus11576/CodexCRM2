# Brief Setup Note — Antigravity CRM

Follow these steps to initialize and run the Antigravity CRM environment for review.

### 1. Prerequisites
- Python 3.10 or higher.
- An **OpenAI API Key** with access to `gpt-4o`.
- Internet access for AI synthesis and external font loading.

### 2. Fast-Start Instructions
1.  **Clone / Unzip**: Ensure you are in the project root directory.
2.  **Environment Setup**:
    ```powershell
    # Copy the example environment file
    copy .env.example .env
    ```
    *Open `.env` and paste your `OPENAI_API_KEY`.*
3.  **Install Dependencies**:
    ```powershell
    pip install -r requirements.txt
    ```
4.  **Launch the System**:
    ```powershell
    .\start.bat
    ```
    *The server will initialize the database schema automatically if `crm.db` is missing.*

### 3. Accessing the Application
- **Main App**: [http://localhost:8001/](http://localhost:8001/)
- **Authentication**: The system now uses **Secure HttpOnly Cookies**. You must sign in to access any `/api/` or `/uploads/` resources.
- **API Docs (Swagger)**: [http://localhost:8001/docs](http://localhost:8001/docs)

### 4. Verification
Run the following script to ensure the AI and Database are correctly bridged:
```powershell
python tests/verify_site_access.py
```
