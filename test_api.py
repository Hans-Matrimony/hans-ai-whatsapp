import asyncio
import os
import sys

# Configure API to point to your local Node instance (we'll start it)
os.environ["MONGO_LOGGER_URL"] = "http://localhost:5000"

# Add parent directory to path so we can import the app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services import user_metadata

async def run_tests():
    print("=" * 60)
    print("User Metadata HTTP API Test")
    print("=" * 60)
    
    # 1. Initialize
    print("\n1. Initializing Service")
    user_metadata.init_user_metadata_service("http://localhost:5000")
    print(f"Service configured with URL: {user_metadata.MONGO_LOGGER_URL}")
    
    test_phone = "919999999999"
    
    # 2. Save new test user
    print("\n2. Testing Upsert (save_user_metadata)")
    success = await user_metadata.save_user_metadata(
        phone=test_phone,
        name="Test User",
        gender="male",
        dob="1990-01-01",
        place="Delhi"
    )
    print(f"Save success: {success}")
    
    # 3. Get user metadata
    print("\n3. Testing Fetch (get_user_metadata)")
    data = await user_metadata.get_user_metadata(test_phone)
    if data:
        print(f"Found User:")
        print(f"  Name: {data.get('name')}")
        print(f"  Gender: {data.get('gender')}")
        print(f"  DOB: {data.get('dob')}")
        print(f"  Place: {data.get('place')}")
    else:
        print("User not found!")
        
    # 4. Update specific fields
    print("\n4. Testing Update (update_user_metadata)")
    updated = await user_metadata.update_user_metadata(test_phone, {"tob": "10:30 AM"})
    print(f"Update success: {updated}")
    
    # Verify update
    data = await user_metadata.get_user_metadata(test_phone)
    print(f"Verified new TOB: {data.get('tob')}")
    
    # 5. Increment questions
    print("\n5. Testing Analytics (increment questions)")
    inc = await user_metadata.increment_user_questions(test_phone)
    print(f"Increment success: {inc}")
    
    # 6. Add topic
    topic = await user_metadata.add_topic_discussed(test_phone, "career")
    print(f"Topic success: {topic}")
    
    # 7. Get stats
    print("\n6. Testing Stats (get_user_stats)")
    stats = await user_metadata.get_user_stats()
    print(f"Stats: {stats}")
    
if __name__ == "__main__":
    # Fix encoding
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(run_tests())
