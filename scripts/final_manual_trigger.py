import os
import json
import time
from urllib import request, parse
from datetime import datetime, timedelta, timezone

# --- HELPERS ---
def load_env_manual(filepath):
    """Simple env parser to avoid dependency on python-dotenv"""
    env_vars = {}
    print(f"DEBUG: Looking for env file at: {os.path.abspath(filepath)}")
    if not os.path.exists(filepath):
        print(f"DEBUG: File NOT found.")
        return env_vars
    print(f"DEBUG: File found. Reading...")
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, val = line.split('=', 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    print(f"DEBUG: Loaded {len(env_vars)} variables.")
    return env_vars

def http_request(url, method='GET', headers=None, data=None):
    """Simple HTTP client using built-in urllib"""
    if data and isinstance(data, dict):
        data = json.dumps(data).encode('utf-8')
    
    req = request.Request(url, method=method, headers=headers or {})
    try:
        with request.urlopen(req, data=data, timeout=30) as response:
            return response.status, response.read().decode('utf-8')
    except Exception as e:
        return 500, str(e)

# --- CONFIG ---
# Try multiple locations for .env file
env_paths = ['../.env', '../../.env', '.env']
env = {}
for env_path in env_paths:
    env = load_env_manual(env_path)
    if env.get("MONGO_LOGGER_URL"):
        print(f"✅ Loaded .env from: {env_path}")
        break

MONGO_LOGGER_URL = env.get("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = env.get("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = env.get("WHATSAPP_ACCESS_TOKEN")

# --- MAIN ---
def run():
    print("Starting MANUAL ONE-TIME Re-engagement Trigger...")
    
    if not all([MONGO_LOGGER_URL, WHATSAPP_PHONE_ID, WHATSAPP_ACCESS_TOKEN]):
        print(f"Error: Missing configuration. MONGO={bool(MONGO_LOGGER_URL)}, PHONE={bool(WHATSAPP_PHONE_ID)}, TOKEN={bool(WHATSAPP_ACCESS_TOKEN)}")
        return

    now = datetime.now(timezone.utc)
    threshold_hours = 20
    print(f"Threshold: {threshold_hours}h (Last message before {(now - timedelta(hours=threshold_hours)).isoformat()})")

    # 1. Fetch Users
    print(f"Fetching users from MongoDB Logger...")
    status, body = http_request(f"{MONGO_LOGGER_URL}/messages")
    
    if status != 200:
        print(f"Error: Failed to fetch users (HTTP {status}): {body}")
        return

    try:
        data = json.loads(body)
        users = data.get("users", [])
        print(f"Found {len(users)} users in total.")
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        return

    # 2. Filter Users
    eligible_users = []
    for user in users:
        user_id = user.get("userId", "")
        if not user_id or not user_id.startswith("+"):
            continue

        is_eligible = False
        for session in user.get("sessions", []):
            if "whatsapp" not in session.get("channel", "").lower():
                continue
            
            last_msg_str = session.get("lastMessageTime", "")
            if not last_msg_str: continue

            try:
                # Handle 'Z' or offset
                if last_msg_str.endswith('Z'):
                    last_msg_time = datetime.fromisoformat(last_msg_str.replace('Z', '+00:00'))
                else:
                    last_msg_time = datetime.fromisoformat(last_msg_str)
                
                diff_hours = (now - last_msg_time).total_seconds() / 3600
                if diff_hours >= threshold_hours:
                    is_eligible = True
                    break
            except: continue

        if is_eligible:
            eligible_users.append(user_id)

    print(f"Found {len(eligible_users)} eligible users inactive for 20+ hours.")
    
    if not eligible_users:
        print("Done: No eligible users found.")
        return

    # 3. Send Template
    fb_url = f"https://graph.facebook.com/v18.0/{WHATSAPP_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    sent_count = 0
    for user_id in eligible_users:
        phone = user_id.replace("+", "")
        print(f"Sending 'astrofriend_intro_template' to {user_id}...")
        
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
            print(f"Success!")
            sent_count += 1
        else:
            print(f"Failed (HTTP {status}): {body}")
        
        # Small delay to avoid rate limits
        time.sleep(0.5)

    print(f"FINISHED. Total templates sent: {sent_count}")

if __name__ == "__main__":
    run()
