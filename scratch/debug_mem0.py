import httpx
import json
import asyncio

async def check_mem0():
    url = "https://rg4g0gkk0wwkk4cc00g4sg0c.api.hansastro.com/memory/+919760347653"
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        if response.status_code == 200:
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Error: {response.status_code}")

if __name__ == "__main__":
    asyncio.run(check_mem0())
