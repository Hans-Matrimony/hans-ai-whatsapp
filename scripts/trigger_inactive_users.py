#!/usr/bin/env python3
"""
Send astrofriend_intro_template to users inactive for 20+ hours

Usage:
1. Ensure .env file exists in hans-ai-whatsapp/ directory with:
   - MONGO_LOGGER_URL
   - WHATSAPP_PHONE_ID
   - WHATSAPP_ACCESS_TOKEN

2. Run: python scripts/trigger_inactive_users.py
"""

import os
import sys
import json
import time
from datetime import datetime, timedelta, timezone

# Add parent directory to path to import from app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Get environment variables
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

def http_request(url, method='GET', headers=None, data=None):
    """Simple HTTP client"""
    import urllib.request
    if data and isinstance(data, dict):
        data = json.dumps(data).encode('utf-8')

    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as response:
            return response.status, response.read().decode('utf-8')
    except Exception as e:
        return 500, str(e)

def main():
    print("=" * 60)
    print("🚀 Sending astrofriend_intro_template to Inactive Users")
    print("=" * 60)

    # Check configuration
    if not all([MONGO_LOGGER_URL, WHATSAPP_PHONE_ID, WHATSAPP_ACCESS_TOKEN]):
        print("\n❌ ERROR: Missing environment variables!")
        print("\nRequired:")
        print(f"  - MONGO_LOGGER_URL: {'✅' if MONGO_LOGGER_URL else '❌'}")
        print(f"  - WHATSAPP_PHONE_ID: {'✅' if WHATSAPP_PHONE_ID else '❌'}")
        print(f"  - WHATSAPP_ACCESS_TOKEN: {'✅' if WHATSAPP_ACCESS_TOKEN else '❌'}")
        print("\nPlease ensure these are set in your .env file or environment.")
        return

    print(f"\n✅ Configuration loaded")
    print(f"   Mongo Logger: {MONGO_LOGGER_URL[:50]}...")
    print(f"   Phone ID: {WHATSAPP_PHONE_ID}")

    now = datetime.now(timezone.utc)
    threshold_hours = 20
    threshold = now - timedelta(hours=threshold_hours)

    print(f"\n⏰ Inactivity Threshold: {threshold_hours}+ hours")
    print(f"   Last message before: {threshold.strftime('%Y-%m-%d %H:%M:%S')} UTC")

    # Step 1: Fetch users from Mongo Logger
    print(f"\n📡 Step 1: Fetching users from MongoDB...")
    try:
        status, body = http_request(f"{MONGO_LOGGER_URL}/messages")

        if status != 200:
            print(f"❌ Failed to fetch users (HTTP {status})")
            print(f"   Response: {body[:200]}")
            return

        data = json.loads(body)
        users = data.get("users", [])
        print(f"✅ Found {len(users)} total users")
    except Exception as e:
        print(f"❌ Error fetching users: {e}")
        return

    # Step 2: Filter inactive users
    print(f"\n🔍 Step 2: Filtering inactive users (20+ hours)...")
    eligible_users = []

    for user in users:
        user_id = user.get("userId", "")
        if not user_id or not user_id.startswith("+"):
            continue

        for session in user.get("sessions", []):
            channel = session.get("channel", "").lower()
            if "whatsapp" not in channel:
                continue

            last_msg_str = session.get("lastMessageTime", "")
            if not last_msg_str:
                continue

            try:
                # Parse timestamp
                if last_msg_str.endswith('Z'):
                    last_msg_time = datetime.fromisoformat(last_msg_str.replace('Z', '+00:00'))
                else:
                    last_msg_time = datetime.fromisoformat(last_msg_str)

                # Calculate inactive hours
                inactive_hours = (now - last_msg_time).total_seconds() / 3600

                if inactive_hours >= threshold_hours:
                    eligible_users.append({
                        "user_id": user_id,
                        "inactive_hours": round(inactive_hours, 1),
                        "last_message": last_msg_time.strftime('%Y-%m-%d %H:%M:%S')
                    })
                    break
            except Exception as e:
                continue

    print(f"✅ Found {len(eligible_users)} eligible users")

    if not eligible_users:
        print("\n✨ No eligible users found. Done!")
        return

    # Show sample users
    print(f"\n📋 Sample users:")
    for i, user in enumerate(eligible_users[:5]):
        print(f"   {i+1}. {user['user_id']} - {user['inactive_hours']}h inactive")

    if len(eligible_users) > 5:
        print(f"   ... and {len(eligible_users) - 5} more")

    # Step 3: Send WhatsApp template
    print(f"\n📤 Step 3: Sending WhatsApp template...")
    print(f"   Template: astrofriend_intro_template")
    print(f"   Language: en")

    fb_url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    sent_count = 0
    failed_count = 0

    for i, user in enumerate(eligible_users, 1):
        user_id = user["user_id"]
        phone = user_id.replace("+", "")

        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": "astrofriend_intro_template",
                "language": {"code": "en"}
            }
        }

        status, body = http_request(fb_url, method='POST', headers=headers, data=payload)

        if status in [200, 201]:
            sent_count += 1
            print(f"   ✅ [{i}/{len(eligible_users)}] {user_id} - Sent")
        else:
            failed_count += 1
            print(f"   ❌ [{i}/{len(eligible_users)}] {user_id} - Failed (HTTP {status})")

        # Rate limiting: 0.5 second delay between messages
        if i < len(eligible_users):
            time.sleep(0.5)

    # Summary
    print("\n" + "=" * 60)
    print("✨ CAMPAIGN COMPLETE")
    print("=" * 60)
    print(f"📊 Total eligible users: {len(eligible_users)}")
    print(f"✅ Successfully sent: {sent_count}")
    print(f"❌ Failed: {failed_count}")
    print("=" * 60)

if __name__ == "__main__":
    main()
