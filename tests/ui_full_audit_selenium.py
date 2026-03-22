import json
import os
import sys
import uuid
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

BASE_URL = os.getenv('UI_BASE_URL', 'http://127.0.0.1:8009')
ARTIFACT_DIR = Path('tests/artifacts/ui_full_audit')
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
EMAIL = f"ui.audit.{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = 'Password123!'
FULL_NAME = 'UI Audit User'


def ensure_user():
    import asyncio

    existing = asyncio.run(get_user_by_email(EMAIL))
    if existing:
        return existing
    return asyncio.run(create_user(EMAIL, FULL_NAME, PASSWORD, role='admin'))


def build_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1600,1200')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    chrome_binary = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
    if os.path.exists(chrome_binary):
        options.binary_location = chrome_binary
    return webdriver.Chrome(options=options)


def wait_for(driver, condition, timeout=25):
    return WebDriverWait(driver, timeout).until(condition)


def save_artifact(driver, name):
    driver.save_screenshot(str(ARTIFACT_DIR / f'{name}.png'))


def save_page_source(driver, name):
    (ARTIFACT_DIR / f'{name}.html').write_text(driver.page_source, encoding='utf-8')


def auth_disabled():
    try:
        with urlopen(f'{BASE_URL}/api/auth/status', timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        return bool(data.get('auth_disabled'))
    except Exception:
        return False


def fetch_json(path: str):
    with urlopen(f'{BASE_URL}{path}', timeout=20) as response:
        return json.loads(response.read().decode('utf-8'))


def pick_profile_targets():
    payload = fetch_json('/api/people')
    people = payload.get('people') or []
    by_id = {str(person.get('person_id')): person for person in people if person.get('person_id')}
    preferred = ['8da2891e3d44', '01ae4293a1ad']  # Peter, Mark
    picked = [pid for pid in preferred if pid in by_id]
    if len(picked) < 2:
        for person in people:
            pid = str(person.get('person_id') or '')
            if not pid or pid in picked:
                continue
            picked.append(pid)
            if len(picked) >= 2:
                break
    return picked


def verify_profile_action_priority(driver, person_id):
    driver.get(f'{BASE_URL}/person/{person_id}')
    wait_for(driver, EC.presence_of_element_located((By.ID, 'profile-action-priority-widget')), timeout=30)
    wait_for(
        driver,
        lambda d: 'ACTION PRIORITY' in d.find_element(By.ID, 'profile-action-priority-widget').text.upper(),
        timeout=30,
    )
    widget_text = driver.find_element(By.ID, 'profile-action-priority-widget').text
    detail = fetch_json(f'/api/people/{person_id}')
    context = ((detail.get('person') or {}).get('network_score_context') or {})
    interaction_count = int(context.get('interaction_count') or 0)
    recency_days = context.get('recency_days')
    expects_no_score = interaction_count <= 0 and recency_days is None

    if expects_no_score and 'No Score' not in widget_text:
        raise AssertionError(
            f'Expected No Score for profile {person_id} (interaction_count={interaction_count}, recency_days={recency_days}).'
        )
    if not expects_no_score and 'No Score' in widget_text:
        raise AssertionError(
            f'Expected score for profile {person_id} (interaction_count={interaction_count}, recency_days={recency_days}).'
        )
    save_artifact(driver, f'profile-{person_id}')


def login(driver):
    driver.get(f'{BASE_URL}/login')
    wait_for(driver, EC.presence_of_element_located((By.ID, 'email')))
    save_artifact(driver, 'login')
    driver.find_element(By.ID, 'email').send_keys(EMAIL)
    driver.find_element(By.ID, 'password').send_keys(PASSWORD)
    driver.find_element(By.ID, 'submit-btn').click()
    wait_for(driver, lambda d: '/login' not in d.current_url, timeout=30)
    wait_for(driver, EC.presence_of_element_located((By.ID, 'cat-filters')), timeout=30)
    save_artifact(driver, 'dashboard')


def verify_page(driver, path, locator, name):
    driver.get(f'{BASE_URL}{path}')
    try:
        wait_for(driver, EC.presence_of_element_located(locator), timeout=30)
    except Exception:
        save_artifact(driver, f'{name}-failure')
        save_page_source(driver, f'{name}-failure')
        raise
    save_artifact(driver, name)


def run():
    driver = build_driver()
    summary = {'base_url': BASE_URL, 'pages': []}
    try:
        if auth_disabled():
            driver.get(f'{BASE_URL}/')
            wait_for(driver, EC.presence_of_element_located((By.ID, 'cat-filters')), timeout=30)
            save_artifact(driver, 'dashboard')
        else:
            ensure_user()
            login(driver)
        summary['pages'].append({'page': 'dashboard', 'status': 'ok'})

        verify_page(driver, '/agenda', (By.ID, 'task-list'), 'agenda')
        summary['pages'].append({'page': 'agenda', 'status': 'ok'})

        verify_page(driver, '/analytics', (By.ID, 'effortChart'), 'analytics')
        summary['pages'].append({'page': 'analytics', 'status': 'ok'})

        verify_page(driver, '/events', (By.ID, 'events-list'), 'events')
        summary['pages'].append({'page': 'events', 'status': 'ok'})

        verify_page(driver, '/activities', (By.ID, 'intel-feed'), 'activities')
        summary['pages'].append({'page': 'activities', 'status': 'ok'})

        verify_page(driver, '/settings', (By.ID, 'section-cat'), 'settings')
        summary['pages'].append({'page': 'settings', 'status': 'ok'})

        for person_id in pick_profile_targets():
            verify_profile_action_priority(driver, person_id)
            summary['pages'].append({'page': f'profile:{person_id}', 'status': 'ok'})

        print(json.dumps(summary, indent=2))
    finally:
        driver.quit()


if __name__ == '__main__':
    run()
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
