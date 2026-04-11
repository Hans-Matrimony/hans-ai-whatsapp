# Complete Subscription & Payment Flow Guide

## 📋 Table of Contents
1. [Overview](#overview)
2. [User Journey](#user-journey)
3. [Payment Methods](#payment-methods)
4. [Backend Architecture](#backend-architecture)
5. [Webhook Flow](#webhook-flow)
6. [Database Schema](#database-schema)
7. [Referral Integration](#referral-integration)
8. [Troubleshooting](#troubleshooting)

---

## 🎯 Overview

The subscription system manages user access to Hans AI Astrology service through:
- **7-day free trial** (activated by ₹1 payment)
- **Paid subscriptions** (monthly, quarterly, yearly plans)
- **Referral rewards** (1 month free for both users)
- **Message limits** (40 free messages, then 3/day)

---

## 🚀 User Journey

### Scenario 1: New User Sign-Up

```
Step 1: User sends first message on WhatsApp
    ↓
System checks: Is user in database?
    ↓
No → Create new user record
    - userId: "+919876543210"
    - tier: "free"
    - messageCount: 1
    - isPaywallEnabled: true (for new users)
    ↓
User gets 40 free messages before paywall
    ↓
After 40 messages: User sees soft paywall
    ↓
After paywall: User gets 3 free messages/day
```

### Scenario 2: Trial Activation (₹1 Payment)

```
Step 1: User's free trial expires
    ↓
Bot: "Your 7-day free trial has ended. Pay ₹1 to activate 7-day trial."
    ↓
Step 2: User types "PAY"
    ↓
Bot: Shows plans with "Buy Now" buttons
    ↓
Step 3: User taps "Buy Now - ₹1" (Trial Activation)
    ↓
Bot: Sends payment link (Razorpay)
    ↓
Step 4: User clicks link → Pays ₹1 on Razorpay
    ↓
Razorpay sends webhook to subscriptions service
    ↓
System creates/updates user:
    - trialStartDate: today
    - trialEndDate: today + 7 days
    ↓
User can now chat for 7 days freely!
```

### Scenario 3: Premium Subscription Purchase

```
Step 1: Trial expires or user wants premium
    ↓
User: "PAY"
    ↓
Bot: Shows all plans:
    *Basic Plan* - ₹99/30 days
    [Buy Now - ₹99]

    *Premium Plan* - ₹199/60 days
    [Buy Now - ₹199]

    *Yearly Plan* - ₹999/365 days
    [Buy Now - ₹999]
    ↓
Step 2: User taps "Buy Now - ₹199"
    ↓
System calls subscriptions service:
    POST /payments/create-payment-link
    {
      "userId": "+919876543210",
      "planId": "monthly_premium",
      "currency": "INR"
    }
    ↓
Subscriptions service calls Razorpay API:
    - Creates payment link with "Astro Friend" branding
    - Returns short URL: https://rzp.io/abc123
    ↓
WhatsApp Bot sends link to user:
    "Complete your payment: https://rzp.io/abc123"
    ↓
Step 3: User pays on Razorpay
    ↓
Razorpay sends webhook to subscriptions service:
    POST /payments/webhook
    {
      "event": "payment_link.paid",
      "payload": {
        "payment_link": {
          "entity": {
            "notes": {
              "userId": "+919876543210",
              "planId": "monthly_premium"
            }
          }
        }
      }
    }
    ↓
System processes payment:
    1. Verify Razorpay signature
    2. Create subscription in database:
       - userId: "+919876543210"
       - planId: "monthly_premium"
       - status: "active"
       - startDate: today
       - endDate: today + 30 days
    3. Create payment record
    4. Process referral reward (if user was referred)
    ↓
Step 4: User can now chat freely for 30 days!
```

### Scenario 4: Referral Flow

```
Step 1: User A types "REFER"
    ↓
System generates referral code:
    - Format: HANS2024ABC
    - Stored in MongoDB
    ↓
Bot sends:
    "🎁 Share your Astrofriend!
    Your referral code: HANS2024ABC
    Share this with friends who need guidance."
    ↓
Step 2: User A shares code with User B
    ↓
Step 3: User B sends: "My friend said to use HANS2024ABC"
    ↓
System detects code → Calls referral service:
    POST /referrals/apply
    {
      "userId": "+919999999999",
      "referralCode": "HANS2024ABC"
    }
    ↓
Referral service:
    1. Validates code exists
    2. Checks not self-referral
    3. Creates referral record (status: "pending")
    4. Links User B to User A
    ↓
Bot confirms: "Perfect! You've been referred by a friend 🌟"
    ↓
Step 4: User B subscribes
    ↓
Razorpay webhook triggers subscription creation
    ↓
System automatically processes referral reward:
    POST /referrals/process-reward
    {
      "userId": "+919999999999"
    }
    ↓
Referral service:
    1. Finds referrer (User A)
    2. Extends User A's subscription by 30 days
    3. Extends User B's subscription by 30 days
    4. Updates referral status to "completed"
    5. Increments referral stats
    ↓
Both users get 1 month FREE premium! 🎁
```

---

## 💳 Payment Methods

### Method 1: Razorpay Payment Links (PRIMARY)

**How it works:**
1. User taps "Buy Now" button
2. System creates Razorpay Payment Link via API
3. User receives link on WhatsApp
4. User clicks → Opens Razorpay hosted page
5. User pays (UPI, card, netbanking, etc.)
6. Razorpay sends webhook
7. Subscription activated

**Advantages:**
- ✅ No custom frontend needed
- ✅ Mobile-optimized
- ✅ Supports all payment methods
- ✅ "Astro Friend" branding
- ✅ Secure (PCI DSS compliant)

**API Call:**
```python
POST https://api.razorpay.com/v1/payment_links
{
  "amount": 9900,  # ₹99 in paise
  "currency": "INR",
  "description": "Premium Plan - Hans AI Astrology",
  "customer": {
    "name": "+919876543210",
    "contact": "9760347653",
    "email": "user9760347653@whatsapp.com"
  },
  "options": {
    "checkout": {
      "name": "Astro Friend",
      "theme": {
        "color": "#7E57C2"
      }
    }
  },
  "notes": {
    "userId": "+919876543210",
    "planId": "monthly_premium"
  },
  "callback_url": "https://hans-ai-subscriptions.onrender.com/payments/payment-link-callback",
  "callback_method": "get"
}
```

### Method 2: WhatsApp Flow (NATIVE PAYMENTS)

**Status:** Configured but currently falls back to Payment Links

**How it should work:**
1. User taps "Pay Now" in WhatsApp
2. System sends WhatsApp Flow message
3. Payment UI opens inside WhatsApp
4. User completes payment without leaving app
5. Meta processes payment via Razorpay
6. Webhook sent to system
7. Subscription activated

**Current Implementation:**
```python
# In whatsapp_api.py
async def send_flow(
    to: str,
    header: str,
    body: str,
    flow_id: str,
    flow_cta: str = "Pay Now"
)
```

**Why it falls back:**
- Flow needs pre-configuration in Meta Business Manager
- Payment config must be set up in Flow
- Currently using Payment Links as primary method

### Method 3: WhatsApp Native Payments (ORDER_DETAILS)

**Status:** Available but not actively used

**Implementation:**
```python
# In whatsapp_api.py
async def send_native_payment(
    to: str,
    header: str,
    body: str,
    plan_name: str,
    amount_paise: int,
    reference_id: str,
    payment_config_id: str
)
```

**Uses:** v21.0 API with `order_details` type for India-specific native payments

---

## 🔧 Backend Architecture

### Services Involved:

**1. hans-ai-whatsapp (WhatsApp Bot)**
```
whatsapp_webhook.py (FastAPI)
    ↓
Receives WhatsApp messages
    ↓
tasks.py (Celery tasks)
    ↓
Processes messages, checks subscriptions
    ↓
Calls subscriptions service
```

**2. hans-ai-subscriptions (Subscriptions Management)**
```
server.py (FastAPI)
    ↓
Manages users, subscriptions, payments
    ↓
Handles Razorpay webhooks
    ↓
MongoDB database
```

### Message Flow:

```
User Message → WhatsApp webhook
    ↓
1. Check if PAY/REFER command
2. Check subscription access
3. Check message limit
4. Process with OpenClaw AI
5. Increment message count
    ↓
Send AI response
```

### Subscription Check Flow:

```
tasks.py: _check_subscription_access(phone)
    ↓
GET /subscriptions/user/{user_id}
    ↓
server.py: get_user_subscription(user_id)
    ↓
MongoDB: users collection
    ↓
Returns: {
  "access": "trial" | "active" | "no_access",
  "tier": "free" | "premium",
  "trialEndDate": "2026-04-18T10:00:00Z",
  "subscriptionEndDate": "2026-05-18T10:00:00Z"
}
    ↓
Bot decides:
  - trial: Allow access
  - active: Allow access
  - no_access: Send payment nudge
```

---

## 🔄 Webhook Flow

### Razorpay Webhook Handling

**Endpoint:** `POST /payments/webhook`

**Events Handled:**

1. **payment.captured** (Order payments)
2. **payment_link.paid** (Payment link payments)

**Flow:**

```
Razorpay → POST webhook
    ↓
1. Verify signature (HMAC SHA256)
    ↓
2. Extract userId and planId from notes
    ↓
3. Call _create_subscription_from_payment()
    ↓
4. Create subscription in database
    ↓
5. Create payment record
    ↓
6. Process referral reward
    ↓
7. Return {status: "success"}
```

**Webhook Payload:**
```json
{
  "event": "payment_link.paid",
  "payload": {
    "payment_link": {
      "entity": {
        "id": "plink_abc123",
        "amount": 9900,
        "currency": "INR",
        "status": "paid",
        "notes": {
          "userId": "+919876543210",
          "planId": "monthly_premium"
        }
      }
    },
    "payment": {
      "entity": {
        "id": "pay_abc123",
        "amount": 9900,
        "currency": "INR",
        "status": "captured",
        "method": "upi",
        "razorpay_payment_id": "pay_abc123",
        "razorpay_signature": "..."
      }
    }
  }
  }
}
```

**Signature Verification:**
```python
def verify_webhook_signature(body, signature, secret):
    """
    Verify Razorpay webhook signature
    Prevents fake webhook requests
    """
    expected_signature = hmac.new(
        secret.encode(),
        body,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(
        expected_signature,
        signature
    )
```

---

## 🗄️ Database Schema

### MongoDB: hans-ai-subscriptions

**users Collection:**
```javascript
{
  _id: ObjectId,
  userId: "+919876543210",
  phoneNumber: "9760347653",
  name: "User Name",
  email: "user@example.com",
  channel: "whatsapp",
  createdAt: ISODate("2026-04-11T10:00:00Z"),
  updatedAt: ISODate("2026-04-11T10:00:00Z"),

  // Trial system
  trialStartDate: ISODate("2026-04-11T10:00:00Z"),
  trialEndDate: ISODate("2026-04-18T10:00:00Z"),

  // Message limit system
  messageCount: Number,              // Total messages sent
  tier: "free" | "premium",
  isPaywallEnabled: Boolean,

  // Referral system
  referralCode: "HANS2024ABC",
  referredBy: "+919999999999",
  referralCodeUsed: "HANS2024XYZ",
  totalReferrals: Number,
  freeMonthsEarned: Number
}
```

**subscriptions Collection:**
```javascript
{
  _id: ObjectId,
  subscriptionId: "sub_abc123",
  userId: "+919876543210",
  planId: "monthly_premium",
  status: "active" | "expired" | "cancelled",
  startDate: ISODate("2026-04-11T10:00:00Z"),
  endDate: ISODate("2026-05-11T10:00:00Z"),
  autoRenew: false,
  isReferralReward: Boolean,
  createdAt: ISODate("2026-04-11T10:00:00Z"),
  updatedAt: ISODate("2026-04-11T10:00:00Z")
}
```

**payments Collection:**
```javascript
{
  _id: ObjectId,
  paymentId: "pay_abc123",
  subscriptionId: "sub_abc123",
  userId: "+919876543210",
  amount: 9900,  // in paise
  currency: "INR",
  status: "completed",
  paymentMethod: "upi" | "card" | "netbanking" | "wallet",
  razorpayOrderId: "order_abc123",
  razorpayPaymentId: "pay_abc123",
  razorpaySignature: "signature_abc123",
  createdAt: ISODate("2026-04-11T10:00:00Z"),
  completedAt: ISODate("2026-04-11T10:01:00Z")
}
```

**plans Collection:**
```javascript
{
  _id: ObjectId,
  planId: "monthly_premium",
  name: "Premium Plan",
  description: "30 days unlimited astrology",
  price: 19900,  // ₹199 in paise
  currency: "INR",
  durationDays: 30,
  features: [
    "Unlimited chat",
    "Detailed kundli analysis",
    "Gemstone recommendations",
    "Priority support"
  ],
  isActive: true,
  createdAt: ISODate("2026-04-11T10:00:00Z")
}
```

**referrals Collection:**
```javascript
{
  _id: ObjectId,
  referrerId: "+919760347653",
  referredUserId: "+919999999999",
  referralCode: "HANS2024ABC",
  status: "pending" | "completed",
  rewardGiven: Boolean,
  createdAt: ISODate("2026-04-11T10:00:00Z"),
  completedAt: ISODate("2026-04-11T11:00:00Z")
}
```

**message_limits Collection:**
```javascript
{
  _id: ObjectId,
  userId: "+919876543210",
  date: "2026-04-11",
  messagesSent: Number,      // Messages sent today
  limit: 3,                  // Daily limit
  tier: "free" | "premium",
  createdAt: ISODate,
  updatedAt: ISODate
}
```

---

## 🔗 Referral Integration

### How Referral System Integrates with Payments

```
User B subscribes
    ↓
Razorpay webhook: payment_link.paid
    ↓
_create_subscription_from_payment()
    ↓
Creates subscription for User B
    ↓
Calls: process_referral_reward(user_id)
    ↓
Checks if User B was referred:
    1. Find User B in database
    2. Check if "referredBy" field exists
    3. Find referral record
    ↓
If referral exists:
    1. Get referrer (User A) ID
    2. Check if reward already given
    3. Extend User A's subscription by 30 days
    4. Extend User B's subscription by 30 days
    5. Update referral record:
       - status: "completed"
       - rewardGiven: true
       - completedAt: now
    6. Update User A stats:
       - totalReferrals: +1
       - freeMonthsEarned: +1
    ↓
Both users get premium extension!
```

### Referral Database Updates

**On subscription (after payment webhook):**

```python
# 1. Get referred user
referred_user = users.find_one({"userId": user_id})

# 2. Check if referred
if referred_user.get("referredBy"):
    referrer_id = referred_user["referredBy"]

    # 3. Extend referrer's subscription
    referrer_sub = subscriptions.find_one({
        "userId": referrer_id,
        "status": "active"
    })

    if referrer_sub:
        new_end_date = parse_date(referrer_sub["endDate"]) + timedelta(days=30)
        subscriptions.update_one(
            {"userId": referrer_id, "status": "active"},
            {"$set": {"endDate": new_end_date.isoformat()}}
        )

    # 4. Extend referred user's subscription
    user_sub = subscriptions.find_one({
        "userId": user_id,
        "status": "active"
    })

    if user_sub:
        new_end_date = parse_date(user_sub["endDate"]) + timedelta(days=30)
        subscriptions.update_one(
            {"userId": user_id, "status": "active"},
            {"$set": {"endDate": new_end_date.isoformat()}}
        )

    # 5. Mark referral as completed
    referrals.update_one(
        {"referredUserId": user_id, "referrerId": referrer_id},
        {"$set": {"status": "completed", "rewardGiven": true}}
    )

    # 6. Update referrer stats
    users.update_one(
        {"userId": referrer_id},
        {"$inc": {"totalReferrals": 1, "freeMonthsEarned": 1}}
    )
```

---

## 🔍 Environment Variables

### hans-ai-whatsapp/.env
```bash
# Subscriptions Service
SUBSCRIPTIONS_URL=https://hans-ai-subscriptions.onrender.com
SUBSCRIPTION_TEST_NUMBER=9760347653

# MongoDB (for chat logs)
MONGO_LOGGER_URL=mongodb+srv://...

# WhatsApp
WHATSAPP_PHONE_ID=your_phone_id
WHATSAPP_ACCESS_TOKEN=your_access_token
WHATSAPP_FLOW_ID=your_flow_id  # Optional, for WhatsApp Flows
WHATSAPP_PAYMENT_CONFIG_ID=your_config_id  # Optional
WHATSAPP_PAYMENT_MID=your_mid  # Optional

# OpenClaw AI
OPENCLAW_URL=https://openclaw.onrender.com
OPENCLAW_GATEWAY_TOKEN=your_token

# Redis
REDIS_URL=redis://localhost:6379/0
```

### hans-ai-subscriptions/.env
```bash
# Razorpay
RAZORPAY_KEY_ID=rzp_live_xxxxx
RAZORPAY_KEY_SECRET=your_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret

# Database
MONGO_LOGGER_URL=mongodb+srv://...

# Base URL
BASE_URL=https://hans-ai-subscriptions.onrender.com
```

---

## 📱 Complete User Flow Example

### Day 1: New User

```
10:00 AM - User sends "Hi" on WhatsApp
    ↓
System: Creates user in database
    - userId: "+919876543210"
    - messageCount: 1
    - tier: "free"
    - isPaywallEnabled: true
    ↓
Bot: "Hey! Main hoon, tumhari dost aur thodi bahut astrology bhi jaanti hoon. Kaise ho aaj?"
    ↓
10:05 AM - User: "Meri kundli batao"
    ↓
Bot: (Asks for birth details)
    ↓
User: Provides details
    ↓
Bot: Gives kundli reading
    ↓
messageCount: 2

... (User continues chatting) ...

5:00 PM - User reaches 40 messages
    ↓
System: Shows soft paywall
    ↓
Bot: "Tumhari kundli mein abhi ek bahut important yoga ban raha hai...

Meri free messages khatam ho gayi hain.

Mujhse unlimited baat karne ke liye:
⭐ ₹299/month
⭐ ₹199/year (annual plan — best value!)

Reply PAY to unlock unlimited access! 💫"
```

### Day 2: Trial Activation

```
10:00 AM - User: "PAY"
    ↓
System: Sends beautiful plan list with Buy buttons
    ↓
User sees:
*Basic Plan*
💰 ₹99 for 30 days
✓ Unlimited chat
✓ Detailed kundli analysis

[Buy Now - ₹99]

*Premium Plan*
💰 ₹199 for 60 days
✓ Everything in Basic
✓ Priority support

[Buy Now - ₹199]

*Yearly Plan*
💰 ₹999 for 365 days
✓ Best value
✓ All features

[Buy Now - ₹999]
    ↓
10:02 AM - User taps "Buy Now - ₹99"
    ↓
System: Calls subscriptions service
    ↓
Subscriptions service: Creates Razorpay Payment Link
    - Amount: ₹99
    - Description: "Basic Plan - Hans AI Astrology"
    - Branding: "Astro Friend"
    - Color: #7E57C2
    ↓
Returns: https://rzp.io/abc123
    ↓
Bot: "Complete your payment here: https://rzp.io/abc123"
    ↓
10:03 AM - User clicks link → Pays ₹99 via UPI
    ↓
10:04 AM - Razorpay sends webhook
    ↓
Subscriptions service:
    1. Verifies payment
    2. Creates subscription:
       - subscriptionId: "sub_xyz789"
       - userId: "+919876543210"
       - planId: "monthly_basic"
       - status: "active"
       - startDate: "2026-04-11"
       - endDate: "2026-05-11"
    3. Creates payment record
    4. Processes referral reward (if any)
    ↓
User can now chat for 30 days!
```

### Day 30: Subscription Expiry

```
System checks subscription: endDate < now
    ↓
Status: expired
    ↓
Bot: "Your subscription has ended. Reply PAY to renew!"
```

---

## 🐛 Troubleshooting

### Issue: Payment link not working

**Check:**
1. Razorpay credentials correct?
2. Plan exists in database?
3. Amount in paise (₹99 = 9900)?
4. Callback URL configured?

**Debug:**
```bash
curl https://hans-ai-subscriptions.onrender.com/health
```

### Issue: Webhook not received

**Check:**
1. Razorpay webhook configured?
2. Webhook URL correct in Razorpay dashboard?
3. Webhook secret matches?
4. Service accessible from internet?

**Test:**
```bash
# Check webhook status
curl https://hans-ai-subscriptions.onrender.com/health/webhook
```

### Issue: Referral reward not applied

**Check:**
1. User was referred? (check `referredBy` field)
2. Referral record exists?
3. Reward not already given?
4. Subscription active?

**Debug:**
```python
from client import get_db
db = get_db()

# Check user
user = db.users.find_one({"userId": "+919999999999"})
print(f"Referred by: {user.get('referredBy')}")

# Check referral
referral = db.referrals.find_one({"referredUserId": "+919999999999"})
print(f"Referral status: {referral.get('status')}")
print(f"Reward given: {referral.get('rewardGiven')}")
```

### Issue: Message limit not working

**Check:**
1. User in `SUBSCRIPTION_TEST_NUMBER`?
2. `isPaywallEnabled` true?
3. `messageCount` incrementing?

**Debug:**
```python
from app.services.message_limiter import MessageLimiter
from pymongo import MongoClient

client = MongoClient(MONGO_LOGGER_URL)
limiter = MessageLimiter(client)

stats = limiter.get_user_stats("+919876543210")
print(stats)
```

---

## 📊 Monitoring

### Key Metrics to Track:

1. **Conversion Rate:**
   - Free → Trial activation
   - Trial → Paid subscription
   - Plan-wise conversions

2. **Referral Performance:**
   - Referral rate (users who refer)
   - Referral conversion (referred users who pay)
   - Cost per acquisition (CPA)

3. **Message Stats:**
   - Messages per user (free vs paid)
   - Paywall engagement (PAY click rate)
   - Daily active users

4. **Revenue:**
   - MRR (Monthly Recurring Revenue)
   - ARPU (Average Revenue Per User)
   - Churn rate

---

## 🎯 Summary

**Subscription Flow:**
1. User gets 40 free messages
2. Then 3 free messages/day
3. Paywall triggers at message 40
4. User taps "Buy Now"
5. System sends Razorpay payment link
6. User pays
7. Razorpay webhook activates subscription
8. User gets premium access
9. Referral reward processed (if applicable)
10. User can chat freely

**Payment Methods:**
- Primary: Razorpay Payment Links
- Fallback: WhatsApp Flow (not actively used)
- Future: WhatsApp Native Payments (available)

**Referral System:**
- User types REFER → Gets code
- Shares code with friend
- Friend subscribes → Both get 1 month free
- Automatic processing via webhook

**Database:**
- MongoDB (hans-ai-subscriptions)
- Collections: users, subscriptions, payments, plans, referrals, message_limits

**Services:**
- hans-ai-whatsapp: WhatsApp bot
- hans-ai-subscriptions: Subscription management
- Razorpay: Payment processing
- MongoDB: Data storage
