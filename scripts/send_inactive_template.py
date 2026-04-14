#!/usr/bin/env python3
"""
Send astrofriend_intro_template to users inactive for 22+ hours
This script runs the same logic as the admin endpoint but standalone

Template: astrofriend_intro_template
Body: "Mai Astrofriend Aapka Astrology Dost Jahan aap jaan sakte hain
      apne Garh ke baare kundali ke baare mai or aap mujhse koi bhi
      baat share kar sakte hain 🙂"
Button: "Hey Astrofriend"
"""

import os
import sys
import asyncio
from datetime import datetime, timedelta, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.whatsapp_api import WhatsAppAPI
import httpx

# Simple .env loader
def load_env_file():
    """Load .env file manually"""
    env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    if os.path.exists(env_file):
        with open(env_file, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

# Load environment
load_env_file()

# Configuration
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

async def send_inactive_template():
    """Send template to all users inactive for 22+ hours"""

    print("=" * 70)
    print("🚀 SENDING WHATSAPP TEMPLATE TO INACTIVE USERS")
    print("=" * 70)

    # Check configuration
    if not all([MONGO_LOGGER_URL, WHATSAPP_PHONE_ID, WHATSAPP_ACCESS_TOKEN]):
        print("\n❌ ERROR: Missing environment variables!")
        print("\nRequired:")
        print(f"  MONGO_LOGGER_URL: {'✅' if MONGO_LOGGER_URL else '❌ Missing'}")
        print(f"  WHATSAPP_PHONE_ID: {'✅' if WHATSAPP_PHONE_ID else '❌ Missing'}")
        print(f"  WHATSAPP_ACCESS_TOKEN: {'✅' if WHATSAPP_ACCESS_TOKEN else '❌ Missing'}")
        print("\nPlease set these in your .env file or environment.")
        return

    print(f"\n✅ Configuration loaded")
    print(f"   Mongo Logger: {MONGO_LOGGER_URL[:50]}...")
    print(f"   Phone ID: {WHATSAPP_PHONE_ID}")

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=22)

    print(f"\n⏰ Inactivity Threshold: 22+ hours")
    print(f"   Last message before: {threshold.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   Template: astrofriend_intro_template")
    print(f"   Language: en")

    # Step 1: Fetch users
    print(f"\n📡 Step 1: Fetching users from MongoDB...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{MONGO_LOGGER_URL}/messages")

            if response.status_code != 200:
                print(f"❌ Failed to fetch users (HTTP {response.status_code})")
                print(f"   Response: {response.text[:200]}")
                return

            data = response.json()
            users = data.get("users", [])
            print(f"✅ Found {len(users)} total users")
        except Exception as e:
            print(f"❌ Error fetching users: {e}")
            return

        # Step 2: Filter inactive users
        print(f"\n🔍 Step 2: Filtering inactive users...")
        inactive_users = []

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

                    if inactive_hours >= 22:
                        inactive_users.append({
                            "user_id": user_id,
                            "inactive_hours": round(inactive_hours, 1)
                        })
                        break
                except Exception as e:
                    continue

        print(f"✅ Found {len(inactive_users)} users inactive for 22+ hours")

        if not inactive_users:
            print("\n✨ No eligible users found. Done!")
            return

        # Show sample users
        print(f"\n📋 Sample users:")
        for i, user in enumerate(inactive_users[:5], 1):
            print(f"   {i}. {user['user_id']} - {user['inactive_hours']}h inactive")
        if len(inactive_users) > 5:
            print(f"   ... and {len(inactive_users) - 5} more")

        # Step 3: Send templates
        print(f"\n📤 Step 3: Sending WhatsApp templates...")
        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        # Template components with button
        template_components = [
            {
                "type": "button",
                "sub_type": "quick_reply",
                "index": 0,
                "parameters": [
                    {
                        "type": "payload",
                        "payload": "hey_astrofriend"
                    }
                ]
            }
        ]

        templates_sent = 0
        errors = []

        # Process users (limit to first 100 to avoid timeout)
        users_to_process = inactive_users[:100]
        print(f"   Processing {len(users_to_process)} users (max 100)...")

        for i, user_data in enumerate(users_to_process, 1):
            user_id = user_data["user_id"]
            phone = user_id.replace("+", "")

            try:
                print(f"   [{i}/{len(users_to_process)}] Sending to {user_id}...")

                message_id = await whatsapp_api.send_template(
                    to=phone,
                    template_name="astrofriend_intro_template",
                    components=template_components,
                    language_code="en"
                )

                if message_id:
                    templates_sent += 1
                    print(f"      ✅ Sent (ID: {message_id})")
                else:
                    error_msg = f"Failed to send to {user_id}"
                    errors.append(error_msg)
                    print(f"      ❌ Failed")

                # Rate limiting delay
                await asyncio.sleep(0.5)

            except Exception as e:
                error_msg = f"Error sending to {user_id}: {str(e)}"
                errors.append(error_msg)
                print(f"      ❌ Error: {e}")

        # Summary
        print("\n" + "=" * 70)
        print("✨ CAMPAIGN COMPLETE")
        print("=" * 70)
        print(f"📊 Users processed: {len(users_to_process)}")
        print(f"✅ Templates sent successfully: {templates_sent}")
        print(f"❌ Failed: {len(errors)}")

        if errors:
            print(f"\n❌ Errors (first 10):")
            for error in errors[:10]:
                print(f"   - {error}")

        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(send_inactive_template())
