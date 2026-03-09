import requests
import json

BASE_URL = "http://127.0.0.1:8001"

def check_route(path):
    url = f"{BASE_URL}{path}"
    try:
        r = requests.get(url)
        print(f"CHECK: {path} -> {r.status_code}")
        if r.status_code == 200:
            print(f"  [SUCCESS] Content Length: {len(r.text)}")
            if "<title>" in r.text:
                title = r.text.split("<title>")[1].split("</title>")[0]
                print(f"  [SUCCESS] Title: {title}")
        return r
    except Exception as e:
        print(f"CHECK: {path} -> FAILED: {e}")
        return None

def verify_data():
    print("\n--- DATA VALIDATION ---")
    # 1. Get a valid person ID from the API
    r = check_route("/api/people?limit=1")
    if r and r.status_code == 200:
        data = r.json()
        people = data.get('people', [])
        if people:
            pid = people[0]['person_id']
            name = people[0]['full_name']
            print(f"  [VALID] Found Person: {name} ({pid})")
            
            # 2. Check profile page for this person
            check_route(f"/person/{pid}")
            
            # 3. Check profile API
            r_api = check_route(f"/api/people/{pid}")
            if r_api and r_api.status_code == 200:
                data = r_api.json()
                if "person" in data:
                    print(f"  [VALID] API Profile Data structure for {pid} is correct.")
                else:
                    print(f"  [ERROR] API Profile Data structure for {pid} is MISSING 'person' key!")
                    print(f"  Keys: {data.keys()}")
        else:
            print("  [ERROR] No people found in database!")

    # 4. Check Analytics
    check_route("/api/v2/analytics/momentum")
    check_route("/api/v2/analytics/recent-intel")

print("--- PHYSICAL SITE AUDIT ---")
check_route("/")
check_route("/activities")
verify_data()
print("\n--- AUDIT COMPLETE ---")
