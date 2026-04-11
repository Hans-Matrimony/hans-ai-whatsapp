import os
import asyncio
import httpx
from datetime import datetime, timedelta, timezone
from app.services.whatsapp_api import WhatsAppAPI
from dotenv import load_dotenv

# Load environment
load_dotenv()

MONGO_LOGGER_URL = os.getenv("MONGO_LOGGER_URL")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
FB_API_URL = "https://graph.facebook.com/v18.0"

async def run_one_time_template_send():
    print("🚀 Starting ONE-TIME Inactive Template Send...")
    
    if not MONGO_LOGGER_URL or not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_ID:
        print("❌ Error: Missing environment variables (MONGO_LOGGER_URL, WHATSAPP_ACCESS_TOKEN, or WHATSAPP_PHONE_ID)")
        return

    now = datetime.now(timezone.utc)
    threshold = now - timedelta(hours=20)
    print(f"🕒 Threshold: {threshold.isoformat()} (20+ hours inactive)")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Fetch users from Mongo Logger
        print(f"📡 Fetching users from {MONGO_LOGGER_URL}/messages...")
        try:
            response = await client.get(f"{MONGO_LOGGER_URL}/messages")
            if response.status_code != 200:
                print(f"❌ Error: Mongo Logger API returned {response.status_code}")
                return
            
            data = response.json()
            users = data.get("users", [])
            print(f"👥 Total users found: {len(users)}")
        except Exception as e:
            print(f"❌ Error fetching users: {e}")
            return

        # 2. Filter inactive users
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
                    if last_msg_str.endswith('Z'):
                        last_msg_time = datetime.fromisoformat(last_msg_str.replace('Z', '+00:00'))
                    else:
                        last_msg_time = datetime.fromisoformat(last_msg_str)

                    inactive_hours = (now - last_msg_time).total_seconds() / 3600
                    if inactive_hours >= 20:
                        inactive_users.append({
                            "user_id": user_id,
                            "inactive_hours": inactive_hours
                        })
                        break
                except :
                    continue

        print(f"🔍 Found {len(inactive_users)} users inactive for 20+ hours")
        
        if not inactive_users:
            print("✅ No eligible users found.")
            return

        # 3. Send template
        whatsapp_api = WhatsAppAPI(
            phone_id=WHATSAPP_PHONE_ID,
            access_token=WHATSAPP_ACCESS_TOKEN
        )

        sent_count = 0
        for user_data in inactive_users:
            user_id = user_data["user_id"]
            phone = user_id.replace("+", "")
            print(f"✉️ Sending to {user_id} ({user_data['inactive_hours']:.1f}h inactive)...")
            
            try:
                msg_id = await whatsapp_api.send_template(
                    to=phone,
                    template_name="astrofriend_intro_template",
                    language_code="en"
                )
                if msg_id:
                    print(f"✅ Success: {msg_id}")
                    sent_count += 1
                else:
                    print(f"❌ Failed to send")
            except Exception as e:
                print(f"❌ Error: {e}")
            
            # Rate limiting delay
            await asyncio.sleep(0.5)

    print(f"\n✨ Done! Total templates sent: {sent_count}")

if __name__ == "__main__":
    asyncio.run(run_one_time_template_send())
