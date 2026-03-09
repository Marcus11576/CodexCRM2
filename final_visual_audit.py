import requests

BASE = "http://127.0.0.1:8001"

def audit_ui(path, markers):
    print(f"AUDITING: {path}")
    try:
        r = requests.get(f"{BASE}{path}")
        if r.status_code != 200:
            print(f"  [FAIL] Status {r.status_code}")
            return
        
        for m in markers:
            if m in r.text:
                print(f"  [PASS] UI Marker Found: {m}")
            else:
                print(f"  [MISSING] UI Marker: {m}")
    except Exception as e:
        print(f"  [ERROR] {e}")

# 1. Dashboard (index)
audit_ui("/", ["platinum-bg", "platinum-frosted", "app-container", "top-bar"])

# 2. Activities (Centrifuge)
audit_ui("/activities", ["centrifuge-wrapper", "momentum-dial", "orbit-inner", "intel-feed"])

# 3. Valid Profile
r = requests.get(f"{BASE}/api/people?limit=1")
if r.status_code == 200:
    pid = r.json()['people'][0]['person_id']
    audit_ui(f"/person/{pid}", ["profile-header", "platinum-bg", "platinum-frosted", "section-card"])
    
    # Check Profile API for this person
    r_api = requests.get(f"{BASE}/api/people/{pid}")
    if "person" in r_api.json():
        print(f"  [PASS] Profile API structure verified for {pid}")
    else:
        print(f"  [FAIL] Profile API structure missing 'person' key")
