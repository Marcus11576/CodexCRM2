import requests
import json
import os

# Base URL
BASE_URL = "http://127.0.0.1:8001"

def check_dashboard_ui():
    print(f"--- Verifying Dashboard UI ---")
    try:
        # 1. Check API directly to see data structure
        resp = requests.get(f"{BASE_URL}/api/dashboard/meeting-feed")
        if resp.status_code == 200:
            data = resp.json()
            print(f"API Check: Found {len(data.get('overdue', []))} overdue items")
            print(f"API Check: Found {len(data.get('soon', []))} soon items")
        else:
            print(f"API Check: FAILED (Status {resp.status_code})")

        # 2. Check HTML for specific markers
        resp = requests.get(BASE_URL)
        html = resp.text
        
        markers = [
            'stat-card status-past',
            'stat-card status-soon',
            'stat-card status-on_track',
            'stat-card status-not_scheduled',
            'stat-value',
            'stat-label',
            'activeMeetingStatuses' # Check if JS var exists
        ]
        
        for m in markers:
            if m in html:
                print(f"HTML Marker '{m}': FOUND")
            else:
                # If activeMeetingStatuses is in index.js, we might not see it in index.html directly
                # but index.js is linked.
                print(f"HTML Marker '{m}': NOT in main HTML (expected if externalized)")

        # 3. Check CSS for the new active state properties
        css_resp = requests.get(f"{BASE_URL}/static/index.css")
        css = css_resp.text
        
        css_markers = [
            '.stat-card.active::after',
            'height: 6px;',
            'box-shadow: 0 4px 12px rgba(34, 211, 238, 0.4);',
            'font-size: 2.5rem;'
        ]
        
        for cm in css_markers:
            if cm in css:
                print(f"CSS Marker '{cm}': FOUND")
            else:
                print(f"CSS Marker '{cm}': NOT FOUND")

    except Exception as e:
        print(f"Audit Error: {e}")

if __name__ == "__main__":
    check_dashboard_ui()
