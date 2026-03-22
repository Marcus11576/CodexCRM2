import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_URL = os.getenv("UI_BASE_URL", "http://127.0.0.1:8009")
PETER_ID = os.getenv("UI_PROFILE_PETER_ID", "8da2891e3d44")
IAN_ID = os.getenv("UI_PROFILE_IAN_ID", "00449722db88")
DOWNLOADS_DIR = Path(os.getenv("UI_DOWNLOADS_DIR", r"C:\Users\marcu\Downloads"))
ARTIFACT_DIR = Path("tests/artifacts/ui_profile_upload_chat")
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


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


def wait_for(driver, condition, timeout=90):
    return WebDriverWait(driver, timeout).until(condition)


def resolve_upload_fixture(patterns: list[str]) -> Path:
    for pattern in patterns:
        matches = list(DOWNLOADS_DIR.glob(pattern))
        if matches:
            return matches[0].resolve()
    raise FileNotFoundError(f"No upload fixture found in {DOWNLOADS_DIR} for patterns: {patterns}")


def run():
    image_path = resolve_upload_fixture(["Fran*Headshot.png", "*Headshot*.png", "*clipboard_image*.png"])
    pdf_path = resolve_upload_fixture(["Fran*Profile.pdf", "Profile*.pdf", "*Profile*.pdf"])
    summary = {
        "base_url": BASE_URL,
        "image_path": str(image_path),
        "pdf_path": str(pdf_path),
        "steps": [],
    }

    driver = build_driver()
    try:
        # Peter profile: upload image + PDF
        driver.get(f"{BASE_URL}/person/{PETER_ID}")
        wait_for(driver, EC.presence_of_element_located((By.ID, "profile-name")))
        driver.execute_script("openChat();")
        wait_for(driver, EC.visibility_of_element_located((By.ID, "chat-modal")))

        file_input = driver.find_element(By.ID, "chat-file-upload")
        file_input.send_keys(str(image_path))
        wait_for(
            driver,
            lambda d: "upload received" in d.find_element(By.ID, "chat-history").text.lower()
            or "image uploaded" in d.find_element(By.ID, "chat-history").text.lower(),
        )
        driver.save_screenshot(str(ARTIFACT_DIR / "peter-after-image.png"))
        summary["steps"].append({"step": "upload_image_via_chat", "status": "ok"})

        file_input = driver.find_element(By.ID, "chat-file-upload")
        file_input.send_keys(str(pdf_path))
        wait_for(driver, lambda d: "[FILE]" in d.find_element(By.ID, "chat-history").text)
        wait_for(
            driver,
            lambda d: "upload received" in d.find_element(By.ID, "chat-history").text.lower()
            or "document uploaded" in d.find_element(By.ID, "chat-history").text.lower(),
        )
        driver.save_screenshot(str(ARTIFACT_DIR / "peter-after-pdf.png"))
        summary["steps"].append({"step": "upload_pdf_via_chat", "status": "ok"})

        # Ian profile: confirm role-level employment update from chat
        driver.get(f"{BASE_URL}/person/{IAN_ID}")
        wait_for(driver, EC.presence_of_element_located((By.ID, "profile-name")))
        driver.execute_script("openChat();")
        wait_for(driver, EC.visibility_of_element_located((By.ID, "chat-modal")))
        chat_input = driver.find_element(By.ID, "chat-input")
        chat_input.clear()
        chat_input.send_keys("Just add end date 2026-03-22 to his WSP role.")
        driver.find_element(By.CSS_SELECTOR, "#chat-modal .send-btn").click()
        wait_for(
            driver,
            lambda d: "update employment history" in d.find_element(By.ID, "chat-history").text.lower()
            or "applied:" in d.find_element(By.ID, "chat-history").text.lower(),
        )
        driver.save_screenshot(str(ARTIFACT_DIR / "ian-end-date-update.png"))
        summary["steps"].append({"step": "chat_role_end_date_update", "status": "ok"})

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        driver.quit()


if __name__ == "__main__":
    run()
