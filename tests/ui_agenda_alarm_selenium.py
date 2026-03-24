import json
import os
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from backend.services.auth_service import create_user, get_user_by_email

BASE_URL = os.getenv("UI_BASE_URL", "http://127.0.0.1:8009")
ARTIFACT_DIR = Path("tests/artifacts/ui_agenda_alarm")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
EMAIL = f"ui.alarm.{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "Password123!"
FULL_NAME = "UI Alarm Audit User"


def ensure_user():
    import asyncio

    existing = asyncio.run(get_user_by_email(EMAIL))
    if existing:
        return existing
    return asyncio.run(create_user(EMAIL, FULL_NAME, PASSWORD, role="admin"))


def build_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1600,1200")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    chrome_binary = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    if os.path.exists(chrome_binary):
        options.binary_location = chrome_binary
    return webdriver.Chrome(options=options)


def wait_for(driver, condition, timeout=30):
    return WebDriverWait(driver, timeout).until(condition)


def auth_disabled():
    try:
        with urlopen(f"{BASE_URL}/api/auth/status", timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        return bool(data.get("auth_disabled"))
    except Exception:
        return False


def login(driver):
    driver.get(f"{BASE_URL}/login")
    wait_for(driver, EC.presence_of_element_located((By.ID, "email")))
    driver.find_element(By.ID, "email").send_keys(EMAIL)
    driver.find_element(By.ID, "password").send_keys(PASSWORD)
    driver.find_element(By.ID, "submit-btn").click()
    wait_for(driver, lambda d: "/login" not in d.current_url, timeout=30)


def run():
    summary = {"base_url": BASE_URL, "checks": []}
    driver = build_driver()
    created_task_id = None
    try:
        if not auth_disabled():
            ensure_user()
            login(driver)

        driver.get(f"{BASE_URL}/agenda")
        wait_for(driver, EC.presence_of_element_located((By.ID, "task-list")))
        wait_for(driver, EC.presence_of_element_located((By.ID, "agenda-alarm-clock")))
        wait_for(driver, EC.presence_of_element_located((By.ID, "agenda-notify-btn")))
        summary["checks"].append({"check": "alarm_ui_present", "status": "ok"})

        now = datetime.now()
        due = now - timedelta(minutes=1)
        due_date = due.strftime("%Y-%m-%d")
        due_time = due.strftime("%H:%M")
        task_text = f"Selenium alarm test {uuid.uuid4().hex[:6]}"

        create_payload = {
            "task_text": task_text,
            "person_id": None,
            "due_date": due_date,
            "due_time": due_time,
            "priority": "high",
        }
        created_task_id = driver.execute_async_script(
            """
            const payload = arguments[0];
            const done = arguments[arguments.length - 1];
            fetch('/api/tasks', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(async (res) => {
                if (!res.ok) {
                    const text = await res.text();
                    throw new Error('Create task failed: ' + text);
                }
                return res.json();
            })
            .then((data) => done(data.task_id || null))
            .catch((err) => done({ error: String(err) }));
            """,
            create_payload,
        )

        if isinstance(created_task_id, dict) and created_task_id.get("error"):
            raise RuntimeError(created_task_id["error"])
        if not created_task_id:
            raise RuntimeError("Task creation returned no task_id")

        driver.refresh()
        wait_for(driver, EC.presence_of_element_located((By.ID, "task-list")))
        wait_for(driver, lambda d: len(d.find_elements(By.CSS_SELECTOR, "#agenda-alarm-feed .agenda-alarm-item")) >= 1, timeout=45)
        summary["checks"].append({"check": "in_page_alarm_triggered", "status": "ok"})

        clock_text = driver.find_element(By.ID, "agenda-alarm-clock").text.strip()
        next_text = driver.find_element(By.ID, "agenda-alarm-next").text.strip()
        if not clock_text:
            raise RuntimeError("Alarm clock text is empty")
        if not next_text:
            raise RuntimeError("Alarm next text is empty")
        summary["checks"].append({"check": "alarm_clock_and_status_text", "status": "ok"})

        driver.save_screenshot(str(ARTIFACT_DIR / "agenda_alarm.png"))
        print(json.dumps(summary, indent=2))
    finally:
        if created_task_id:
            try:
                driver.execute_async_script(
                    """
                    const taskId = arguments[0];
                    const done = arguments[arguments.length - 1];
                    fetch(`/api/tasks/${taskId}`, { method: 'DELETE' })
                        .then(() => done(true))
                        .catch(() => done(false));
                    """,
                    created_task_id,
                )
            except Exception:
                pass
        driver.quit()


if __name__ == "__main__":
    run()
