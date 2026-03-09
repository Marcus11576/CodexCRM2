import asyncio
import httpx
import json

BASE_URL = "http://localhost:8000"

async def test_analytics():
    print("--- Phase 3 Analytics Verification ---")
    
    async with httpx.AsyncClient() as client:
        # 1. Test Network Pulse
        print("Testing /api/analytics/network-pulse...")
        res = await client.get(f"{BASE_URL}/api/analytics/network-pulse")
        if res.status_code == 200:
            data = res.json()
            print(f"Success. Trends found: {len(data.get('trends', []))}")
            print(f"Hot Companies found: {len(data.get('hot_companies', []))}")
        else:
            print(f"FAILED: {res.status_code} - {res.text}")

        # 2. Test Influence Matrix
        print("\nTesting /api/analytics/influence-matrix...")
        res = await client.get(f"{BASE_URL}/api/analytics/influence-matrix")
        if res.status_code == 200:
            data = res.json()
            print(f"Success. Nodes found: {len(data.get('matrix', []))}")
        else:
            print(f"FAILED: {res.status_code} - {res.text}")

        # 3. Test Propensity (Random person from matrix)
        if data.get('matrix'):
            pid = data['matrix'][0]['person_id']
            print(f"\nTesting /api/analytics/propensity/{pid}...")
            res = await client.get(f"{BASE_URL}/api/analytics/propensity/{pid}")
            if res.status_code == 200:
                print(f"Success. Health: {res.json().get('health')}%")
            else:
                print(f"FAILED: {res.status_code} - {res.text}")

if __name__ == "__main__":
    asyncio.run(test_analytics())
