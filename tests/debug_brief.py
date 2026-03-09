import asyncio
import httpx
import json

BASE_URL = "http://localhost:8001"

async def test_brief():
    # We need a valid person_id. Let's try to find one.
    async with httpx.AsyncClient() as client:
        # 1. Get a person
        res = await client.get(f"{BASE_URL}/api/people")
        if res.status_code != 200:
            print(f"Failed to get people: {res.status_code}")
            return
        
        people = res.json().get('people', [])
        if not people:
            print("No people found.")
            return
        
        pid = people[0]['person_id']
        print(f"Testing brief for {people[0]['full_name']} ({pid})...")
        
        # 2. Get brief
        res = await client.get(f"{BASE_URL}/api/intelligence/brief/{pid}")
        if res.status_code == 200:
            print("Success! Response:")
            print(json.dumps(res.json(), indent=2))
        else:
            print(f"FAILED: {res.status_code}")
            print(res.text)

if __name__ == "__main__":
    asyncio.run(test_brief())
