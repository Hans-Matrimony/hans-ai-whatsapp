# Automatic Message Limit System - Verification Guide

## ✅ Changes Made: Trial Activation REMOVED

### What Changed:
1. **Removed ₹1 trial activation requirement**
   - New users NO LONGER need to pay ₹1 to get access
   - Automatic free access with 40 messages

2. **Removed trial_activation plan**
   - No longer create trial_activation plan
   - No ₹1 payment flow

3. **Updated subscription check**
   - New users automatically get "trial" access
   - No payment required to start

---

## 🔄 How the System Works NOW

### **For NEW Users (Automatic Access):**

```
User sends first message on WhatsApp
    ↓
WhatsApp webhook receives message
    ↓
tasks.py: _process_message_async()
    ↓
Step 1: Check subscription status
    GET /subscriptions/user/{user_id}
    ↓
Subscriptions service: User not found in database
    ↓
Returns: {
  "access": "trial",
  "message": "New user - 40 free messages trial",
  "skip_reason": "auto_trial_enabled"
}
    ↓
Step 2: Check message limit
    MessageLimiter.check_message_limit(user_id)
    ↓
User doesn't exist in message_limits DB
    ↓
Returns: {
  "allowed": true,
  "messagesRemaining": 39,
  "phase": "onboarding",
  "isNewUser": true
}
    ↓
Step 3: Process message with OpenClaw AI
    ↓
Step 4: Increment message count
    MessageLimiter.increment_message_count(user_id)
    ↓
Creates user in message_limits DB:
    - userId: "+919876543210"
    - messageCount: 1
    - tier: "free"
    - isPaywallEnabled: true (automatic)
    ↓
User gets response! ✅
```

---

## 📊 Message Limit Progression (Automatic)

### **Messages 1-3: Onboarding Phase**
```
User sends 3 messages
    ↓
System: phase = "onboarding"
    ↓
No paywall, no limits
    ↓
User can chat freely
```

### **Messages 4-39: Free Tier**
```
User sends messages 4-39
    ↓
System: phase = "free_tier"
    ↓
Shows remaining messages
    ↓
No paywall yet
```

### **Message 40: Soft Paywall (AUTOMATIC)**
```
User sends message #40
    ↓
System detects messageCount == 40
    ↓
Shows soft paywall:
    "Tumhari kundli mein abhi ek bahut important yoga ban raha hai...

    Meri free messages khatam ho gayi hain.

    Mujhse unlimited baat karne ke liye:
    ⭐ ₹299/month
    ⭐ ₹199/year (annual plan — best value!)

    Reply PAY to unlock unlimited access! 💫"
    ↓
Message still processed! ✅
    ↓
User can still chat
```

### **Messages 41+: Daily Limit (AUTOMATIC)**
```
User sends message #41
    ↓
System: phase = "daily_limit"
    ↓
Checks today's message count
    ↓
If < 3 messages today: Allow
    ↓
If 3 messages used: Show hard paywall
    ↓
"Aww beta, aaj ki 3 free messages khatam ho gayi 😔

    Main tumhe bahut kuch batana chahti hoon but messages limit ho gaya.

    Mujhse unlimited baat karne ke liye:
    ⭐ ₹299/month
    ⭐ ₹199/year (annual plan — best value!)

    Reply PAY to continue now! 💫

    Ya kal 3 free messages milenge phir se 😊"
```

---

## ✅ Verification Checklist

### **Database Requirements:**

**1. hans-ai-subscriptions Database:**
```bash
# Collections needed:
- users
- subscriptions
- payments
- plans
- referrals
```

**2. hans-ai-subscriptions/users Collection:**
```javascript
{
  userId: "+919876543210",
  phoneNumber: "9760347653",
  tier: "free",
  isPaywallEnabled: true,  // Automatic for new users
  messageCount: 1
  // No trial dates needed
}
```

**3. hans-ai-subscriptions/subscriptions Collection:**
```javascript
{
  subscriptionId: "sub_abc123",
  userId: "+919876543210",
  planId: "monthly_premium",
  status: "active",
  startDate: "2026-04-11",
  endDate: "2026-05-11"
}
```

**4. hans-ai-whatsapp Message Limits (hans-ai-subscriptions DB):**
```javascript
// users collection
{
  userId: "+919876543210",
  messageCount: 15,
  tier: "free",
  isPaywallEnabled: true
}

// message_limits collection
{
  userId: "+919876543210",
  date: "2026-04-11",
  messagesSent: 2,
  limit: 3,
  tier: "free"
}
```

---

## 🧪 Testing the Automatic Flow

### **Test 1: New User Onboarding**

**Step 1: New user sends "Hi"**
```
Expected:
- User created in message_limits DB
- messageCount: 1
- isPaywallEnabled: true
- Bot responds normally
```

**Verification:**
```python
from pymongo import MongoClient
client = MongoClient(MONGO_LOGGER_URL)
db = client["hans-ai-subscriptions"]

user = db.users.find_one({"userId": "+919876543210"})
print(f"User exists: {user is not None}")
print(f"Tier: {user.get('tier', 'N/A')}")
print(f"Paywall enabled: {user.get('isPaywallEnabled', 'N/A')}")
print(f"Message count: {user.get('messageCount', 'N/A')}")
```

### **Test 2: Message 40 - Soft Paywall**

**Step 1: Send 40 messages**
```
Expected:
- Message 40 shows soft paywall
- Still processes the message
- Marks paywall as shown
```

**Verification:**
```python
user = db.users.find_one({"userId": "+919876543210"})
print(f"Message count: {user.get('messageCount')}")
print(f"Paywall shown: {user.get('paywallShown', False)}")
```

### **Test 3: Message 41 - Daily Limit**

**Step 1: Send message #41**
```
Expected:
- Checks today's message count
- Creates message_limits record
- Allows 3 messages per day
```

**Verification:**
```python
from datetime import datetime
ist = datetime.utcnow().strftime("%Y-%m-%d")

limit_record = db.message_limits.find_one({
    "userId": "+919876543210",
    "date": ist
})

print(f"Messages sent today: {limit_record.get('messagesSent', 0)}")
print(f"Daily limit: {limit_record.get('limit', 3)}")
```

---

## 🔍 End-to-End Flow Test

### **Complete User Journey:**

```
Day 1, 10:00 AM:
User: "Hi"
    ↓
System: User not found
    ↓
Auto-creates user with trial access
    ↓
Bot: "Hey! Main hoon, tumhari dost aur thodi bahut astrology bhi jaanti hoon. Kaise ho aaj?"
    ↓
messageCount: 1, isPaywallEnabled: true
    ✅

... User chats freely (messages 2-39) ...

Day 1, 05:00 PM:
User: [Message #40]
    ↓
System: messageCount == 40
    ↓
Shows soft paywall:
"Tumhari kundli mein abhi ek bahut important yoga..."
    ↓
Still processes message
    ✅

Day 2, 10:00 AM:
User: "Good morning"
    ↓
System: Checks today's limit
    ↓
Creates message_limits record:
- messagesSent: 1
- limit: 3
- date: "2026-04-12"
    ↓
Allows message (1/3 used)
    ✅

Day 2, 10:05 AM:
User: [Message #42]
    ↓
System: messagesSent: 2/3
    ↓
Allows message
    ✅

Day 2, 10:10 AM:
User: [Message #43]
    ↓
System: messagesSent: 3/3
    ↓
Allows message (3/3 used)
    ✅

Day 2, 10:15 AM:
User: "How are you?"
    ↓
System: messagesSent == limit
    ↓
Shows hard paywall:
"Aww beta, aaj ki 3 free messages khatam ho gayi 😔"
    ↓
Blocks message
    ❌

Day 3, 10:00 AM:
User: "Hi again"
    ↓
System: New day, counter reset
    ↓
Checks today's limit: 3/3 available
    ↓
Allows message
    ✅
```

---

## ✅ What Works Automatically

### **1. User Creation**
- ✅ Auto-creates user on first message
- ✅ Sets `isPaywallEnabled: true`
- ✅ Initializes `messageCount: 1`

### **2. Message Counting**
- ✅ Auto-increments on each message
- ✅ Tracks in MongoDB
- ✅ No manual intervention needed

### **3. Soft Paywall (Message 40)**
- ✅ Automatically triggers at message 40
- ✅ Shows tease + pricing
- ✅ Still processes the message
- ✅ Marks paywall as shown

### **4. Hard Paywall (Daily Limit)**
- ✅ Checks today's message count
- ✅ Allows 3 messages/day
- ✅ Blocks after 3 messages
- ✅ Resets automatically next day

### **5. Subscription Check**
- ✅ Checks MongoDB for user
- ✅ Returns "trial" for new users
- ✅ Returns "active" for paid users
- ✅ Returns "no_access" if expired

---

## 🚀 After Deployment

### **First Time User (Automatic Flow):**

1. User sends WhatsApp message
2. System auto-creates user
3. User gets 40 free messages
4. Message 40: Soft paywall shown
5. Message 41+: 3 free messages/day
6. User sees: "Reply PAY to subscribe"
7. User taps "Buy Now" → Pays → Gets premium

**ALL AUTOMATIC - NO MANUAL INTERVENTION NEEDED** ✅

---

## 📝 Environment Variables Required

### **hans-ai-whatsapp/.env:**
```bash
# Required for message limit system
MONGO_LOGGER_URL=mongodb+srv://...

# Required for subscription check
SUBSCRIPTIONS_URL=https://hans-ai-subscriptions.onrender.com
SUBSCRIPTION_TEST_NUMBER=9760347653  # Only this number gets paywall checked
```

### **hans-ai-subscriptions/.env:**
```bash
# Required for subscription management
RAZORPAY_KEY_ID=your_key_id
RAZORPAY_KEY_SECRET=your_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
MONGO_LOGGER_URL=mongodb+srv://...
```

---

## 🎯 Summary

**What's Automatic:**
✅ User creation on first message
✅ 40 free messages
✅ Soft paywall at message 40
✅ Hard paywall (3/day) after message 40
✅ Daily limit reset at midnight
✅ Subscription check
✅ Payment link generation
✅ Subscription activation
✅ Referral reward processing

**What's Manual:**
❌ None! Everything is automatic

**New User Experience:**
1. Sends message → Gets instant access
2. Uses 40 messages → Sees paywall
3. Subscribes → Gets premium access

All automatic! 🚀
