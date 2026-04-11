#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Send astrofriend_intro_template to users inactive for 20+ hours
Uses only built-in libraries (no external dependencies)
"""

import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Simple .env loader
def load_env_file():
    """Load .env file manually"""
    env_paths = [
        os.path.join(os.path.dirname(__file__), '..', '.env'),
        os.path.join(os.path.dirname(__file__), '..', '..', '.env'),
        '.env'
    ]

    for env_file in env_paths:
        if os.path.exists(env_file):
            print(f"✅ Loading .env from: {env_file}")
            with open(env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip().strip('"').strip("'")
            return True
    return False

# Load environment
if not load_env_file():
    print("⚠️  No .env file found")

# Configuration
MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")

def http_request(url, method='GET', headers=None, data=None):
    """Simple HTTP client using built-in urllib"""
    if data and isinstance(data, dict):
        data = json.dumps(data).encode('utf-8')

    req = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, data=data, timeout=30) as response:
            return response.status, response.read().decode('utf-8')
    except Exception as e:
        return 500, str(e)

def send_inactive_template():
    """Send template to all users inactive for 20+ hours"""

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
        return False

    print(f"\n✅ Configuration loaded")
    print(f"   Mongo Logger: {MONGO_LOGGER_URL[:50]}...")
    print(f"   Phone ID: {WHATSAPP_PHONE_ID}")

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=20)

    print(f"\n⏰ Inactivity Threshold: 20+ hours")
    print(f"   Last message before: {threshold.strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print(f"   Template: astrofriend_intro_template")
    print(f"   Language: en")

    # Step 1: Fetch users
    print(f"\n📡 Step 1: Fetching users from MongoDB...")
    status, body = http_request(f"{MONGO_LOGGER_URL}/messages")

    if status != 200:
        print(f"❌ Failed to fetch users (HTTP {status})")
        print(f"   Response: {body[:200]}")
        return False

    try:
        data = json.loads(body)
        users = data.get("users", [])
        print(f"✅ Found {len(users)} total users")
    except Exception as e:
        print(f"❌ Error parsing JSON: {e}")
        return False

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

                if inactive_hours >= 20:
                    inactive_users.append({
                        "user_id": user_id,
                        "inactive_hours": round(inactive_hours, 1)
                    })
                    break
            except Exception as e:
                continue

    print(f"✅ Found {len(inactive_users)} users inactive for 20+ hours")

    if not inactive_users:
        print("\n✨ No eligible users found. Done!")
        return True

    # Show sample users
    print(f"\n📋 Sample users:")
    for i, user in enumerate(inactive_users[:5], 1):
        print(f"   {i}. {user['user_id']} - {user['inactive_hours']}h inactive")
    if len(inactive_users) > 5:
        print(f"   ... and {len(inactive_users) - 5} more")

    # Step 3: Send templates
    print(f"\n📤 Step 3: Sending WhatsApp templates...")

    fb_url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    templates_sent = 0
    errors = []

    # Process users (limit to first 100 to avoid timeout)
    users_to_process = inactive_users[:100]
    print(f"   Processing {len(users_to_process)} users (max 100)...")

    for i, user_data in enumerate(users_to_process, 1):
        user_id = user_data["user_id"]
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

        try:
            print(f"   [{i}/{len(users_to_process)}] Sending to {user_id}...")

            status, body = http_request(fb_url, method='POST', headers=headers, data=payload)

            if status in [200, 201]:
                templates_sent += 1
                response_data = json.loads(body) if body else {}
                message_id = response_data.get('messages', [{}])[0].get('id', 'N/A')
                print(f"      ✅ Sent (ID: {message_id})")
            else:
                error_msg = f"HTTP {status}: {body[:100]}"
                errors.append(f"{user_id}: {error_msg}")
                print(f"      ❌ Failed ({error_msg})")

            # Rate limiting delay
            time.sleep(0.5)

        except Exception as e:
            error_msg = f"Error: {str(e)}"
            errors.append(f"{user_id}: {error_msg}")
            print(f"      ❌ {error_msg}")

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
    return True

if __name__ == "__main__":
    try:
        success = send_inactive_template()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
