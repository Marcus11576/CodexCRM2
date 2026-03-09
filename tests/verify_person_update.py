import asyncio
import httpx
import json

BASE_URL = "http://localhost:8001"
PERSON_ID = "70e3ac1d5fc8" # James Allan

async def verify_update():
    print(f"--- Verifying Profile Update for {PERSON_ID} ---")
    
    async with httpx.AsyncClient() as client:
        # 1. Get current data
        res = await client.get(f"{BASE_URL}/api/people/{PERSON_ID}")
        if res.status_code != 200:
            print(f"FAILED to get person: {res.status_code}")
            return
        
        data = res.json()
        person = data.get('person', {})
        print(f"Current Email: {person.get('email_primary')}")
        
        # 2. Update fields
        test_email = "james.test@jll.com"
        test_phone = "+971000000000"
        
        payload = {
            "email_primary": test_email,
            "phone_primary": test_phone
        }
        
        print(f"Updating with: {payload}")
        update_res = await client.patch(f"{BASE_URL}/api/people/{PERSON_ID}", json=payload)
        
        if update_res.status_code == 200:
            print("PATCH request successful.")
        else:
            print(f"FAILED PATCH: {update_res.status_code} - {update_res.text}")
            return
            
        # 3. Verify persistence
        res = await client.get(f"{BASE_URL}/api/people/{PERSON_ID}")
        data = res.json()
        updated_person = data.get('person', {})
        
        if updated_person.get('email_primary') == test_email and updated_person.get('phone_primary') == test_phone:
            print("SUCCESS: Data persisted correctly.")
        else:
            print(f"FAILED: Data mismatch. Email: {updated_person.get('email_primary')}, Phone: {updated_person.get('phone_primary')}")
            
        # 4. Revert changes
        print("Reverting changes...")
        revert_res = await client.patch(f"{BASE_URL}/api/people/{PERSON_ID}", json={
            "email_primary": person.get('email_primary'),
            "phone_primary": person.get('phone_primary')
        })
        if revert_res.status_code == 200:
            print("Revert successful.")

if __name__ == "__main__":
    asyncio.run(verify_update())
