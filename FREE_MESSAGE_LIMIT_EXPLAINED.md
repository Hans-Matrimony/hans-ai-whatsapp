# Free Message Limit & Referral System Explained

## 📊 Current Free Message System (Working)

### How it Works NOW:

**For NEW Users (Paywall Enabled):**
```
Message 1-3:    Onboarding phase (no paywall)
Message 4-39:   Free tier (full experience)
Message 40:     Soft paywall shown (tease + pricing)
Message 41+:    Daily limit of 3 free messages/day
```

**Example Flow:**
```
Day 1:
  User sends 5 messages
  → Messages 1-3: Onboarding (no paywall)
  → Messages 4-5: Free tier (37 remaining)

Day 5:
  User sends 40 messages total
  → Message 40: Soft paywall shown

Day 6:
  User sends message 41
  → Daily limit check: 3 free messages remaining today
  → After 3 messages: Hard paywall "Come back tomorrow for 3 more free messages"
```

**For EXISTING Users (Paywall Disabled):**
```
- Unlimited messages (grandfathered in)
- isPaywallEnabled = false
```

**For PREMIUM Users:**
```
- tier = "premium"
- Unlimited messages
```

---

## 🔄 Referral System (NOT IMPLEMENTED YET)

The user mentioned:
- **40 messages** for referral
- **3 messages** daily limit after paywall

**Current system already has:**
- ✅ 40 free messages before paywall
- ✅ 3 daily free messages after paywall

**What's MISSING:**
- ❌ Referral system (share with friend → get 40 bonus messages)

---

## 💡 What Needs to Be Built for Referral System

### 1. Referral Code Generation

```python
# In user_metadata.py or new referral_service.py

def generate_referral_code(user_id: str) -> str:
    """Generate unique referral code for user"""
    import random
    import string

    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    # e.g., "ASTRO123"

    # Save to MongoDB
    users_collection.update_one(
        {"userId": user_id},
        {"$set": {"referralCode": code, "referralCount": 0}}
    )

    return code
```

### 2. Referral Link Sharing

```python
# New command in tasks.py

async def handle_refer_command(phone: str, user_id: str):
    """Handle REFER command - send referral link"""

    referral_code = generate_referral_code(user_id)
    referral_link = f"https://wa.me/?text=Join+Astro+Friend!+Use+code:+{referral_code}"

    message = f"""🎁 **Share & Earn 40 Free Messages!**

Share your referral code with friends:
📱 **Code: {referral_code}**

When they sign up, you get **40 bonus messages**!

Share now: {referral_link}"""

    await send_whatsapp_message(phone, message)
```

### 3. Referral Tracking

```python
# In message_limiter.py

def apply_referral_bonus(user_id: str, referral_code: str) -> bool:
    """Apply referral bonus when new user signs up with code"""

    # Find referrer
    referrer = users_collection.find_one({"referralCode": referral_code})

    if referrer:
        # Add 40 bonus messages to referrer
        users_collection.update_one(
            {"userId": referrer["userId"]},
            {
                "$inc": {
                    "messageCount": -40,  # Decrease count (add 40 more messages)
                    "referralCount": 1,
                    "totalBonusMessages": 40
                }
            }
        )

        # Mark new user as referred
        users_collection.update_one(
            {"userId": user_id},
            {"$set": {"referredBy": referrer["userId"]}}
        )

        return True

    return False
```

### 4. Message Limit Update

```python
# In message_limiter.py check_message_count()

def check_message_count(user_id: str) -> dict:
    user = users_collection.find_one({"userId": user_id})

    message_count = user.get("messageCount", 0)

    # Check if user has bonus messages from referrals
    bonus_messages = user.get("totalBonusMessages", 0)
    effective_limit = FREE_MESSAGE_LIMIT + bonus_messages

    if message_count < effective_limit:
        remaining = effective_limit - message_count
        return {"allowed": True, "messagesRemaining": remaining}

    # Continue with existing logic...
```

---

## 🧪 Testing the Current System

### Test 1: New User Flow

```bash
# Check if user exists (should return None for new user)
curl https://hans-ai-subscriptions.onrender.com/user/+919876543210

# Expected: {"error": "User not found"}
```

**WhatsApp Test:**
1. New user sends message #1
2. Check MongoDB: messageCount = 1, tier = "free", isPaywallEnabled = true
3. User sends message #3
4. User sends message #40 → Should see soft paywall
5. User sends message #41 → Should have 3 daily free messages
6. User sends 3 more messages → Hard paywall "Come back tomorrow"

### Test 2: Check User Stats

```python
# Add endpoint to subscriptions service
@app.get("/user/{user_id}/stats")
def get_user_stats(user_id: str):
    limiter = MessageLimiter()
    stats = limiter.get_user_stats(user_id)
    return stats
```

**Test:**
```bash
curl https://hans-ai-subscriptions.onrender.com/user/+919876543210/stats

# Expected response:
{
  "userId": "+919876543210",
  "messageCount": 15,
  "tier": "free",
  "isPaywallEnabled": true,
  "dailyMessagesRemaining": 3,
  "phase": "free_tier"
}
```

---

## 🔍 Environment Variables Check

**Current ENV vars:**
```bash
# In hans-ai-whatsapp/.env
SUBSCRIPTIONS_URL=https://hans-ai-subscriptions.onrender.com
SUBSCRIPTION_TEST_NUMBER=9760347653
MONGO_LOGGER_URL=mongodb+srv://...
```

**What controls paywall:**
- `SUBSCRIPTION_TEST_NUMBER` - Only THIS number gets paywall checked
- Other numbers: Paywall is skipped (unlimited access for testing)

---

## ✅ What's Working NOW

1. **Message counting** - Messages tracked in MongoDB
2. **Daily limit** - 3 free messages/day after paywall
3. **Soft paywall** - Shown at message 40
4. **Hard paywall** - Daily limit reached
5. **Premium users** - Unlimited access
6. **Existing users** - Grandfathered (unlimited)

---

## ❌ What's NOT Implemented (Referral System)

1. **Referral code generation** - Not built
2. **Referral link sharing** - No "REFER" command
3. **Referral tracking** - No bonus system
4. **Bonus messages** - Not added to limit
5. **Referral analytics** - Not tracked

---

## 🚀 Next Steps for Referral System

1. **Create referral_service.py** - Handle referral logic
2. **Add REFER command** - Users can get referral code
3. **Update message_limiter.py** - Add bonus messages to limit
4. **Track referrals** - Store who referred whom
5. **Test referral flow** - Verify bonus messages work

---

## 📝 Database Schema Updates Needed

```javascript
// users collection - add these fields
{
  "userId": "+919876543210",
  "messageCount": 15,
  "tier": "free",
  "isPaywallEnabled": true,

  // NEW FIELDS FOR REFERRAL
  "referralCode": "ASTRO123",           // User's unique referral code
  "referralCount": 5,                   // How many people they referred
  "totalBonusMessages": 200,            // Total bonus messages earned
  "referredBy": "+919999999999"         // Who referred them (if any)
}
```

---

## 🎯 Summary

**Current Status:**
- ✅ Free message limit working (40 messages + 3/day)
- ✅ Paywall system functional
- ❌ Referral system NOT implemented

**For NEW users who don't purchase:**
- Get 40 free messages
- Then 3 free messages per day
- See paywall at message 40
- See hard paywall after daily limit

**To implement referral system:**
- Need ~200 lines of code
- Need database schema updates
- Need new REFER command
- Need bonus message tracking
