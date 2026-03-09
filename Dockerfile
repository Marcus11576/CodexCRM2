FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts
COPY .env.example ./.env.example
COPY start.bat ./start.bat
COPY agent.md ./agent.md
COPY *.md ./

RUN mkdir -p /var/data/uploads /var/data/backups /var/data/backups_external

ENV ENV=production
ENV PORT=8009
ENV DB_PATH=/var/data/crm.db
ENV UPLOADS_DIR=/var/data/uploads
ENV BACKUP_DIR=/var/data/backups
ENV BACKUP_EXTERNAL_DIR=/var/data/backups_external
ENV AUTH_DISABLED=false
ENV COOKIE_SECURE=true

EXPOSE 8009

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8009"]
