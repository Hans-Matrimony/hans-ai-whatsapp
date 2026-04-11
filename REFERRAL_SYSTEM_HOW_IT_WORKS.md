# Complete Referral System - How It Works

## 🎯 Referral Flow - Step by Step

### **Scenario: User A refers User B**

---

## 👨‍👩 **Step 1: User A Gets Referral Code**

```
User A: "REFER"
    ↓
WhatsApp Bot sends:
🎁 *Share your Astrofriend!*

Your referral code: *HANS2024ABC*

Share this with friends who need guidance. When they subscribe:
✓ You get 1 month FREE premium
✓ They also get 1 month FREE premium

📊 *Your Stats:*
Total referrals: 0
Free months earned: 0

Share link: [WhatsApp link]
```

**What happens in background:**
```
tasks.py: User types "REFER"
    ↓
Calls: GET /referrals/my-link/+919876053210
    ↓
referral_handler.py: get_referral_link()
    ↓
1. Checks if user has referral code
2. If not, generates new code:
   - Format: HANS + 4 digits + 3 letters
   - Example: HANS2024ABC
   - Ensures uniqueness
3. Stores in MongoDB:
   users collection:
     {
       referralCode: "HANS2024ABC",
       totalReferrals: 0,
       freeMonthsEarned: 0
     }
4. Returns code + stats + share link
    ↓
Bot sends formatted message
```

---

## 🤝 **Step 2: User A Shares with User B**

**Method 1: Share Code**
```
User A: "Hey! Use my code: HANS2024ABC"
```

**Method 2: Share Link**
```
User A: Clicks the share link
    ↓
WhatsApp opens with message:
"Share your Astrofriend! Use referral code: HANS2024ABC
 for 🎁 1 month FREE premium"
```

---

## 📝 **Step 3: User B Applies Referral Code**

**Automatic Detection:**
```
User B: "My friend told me to use HANS2024ABC"
    ↓
tasks.py: _check_and_apply_referral_code()
    ↓
Detects pattern: HANS2024ABC
    ↓
Calls: POST /referrals/apply
{
  "userId": "+919999999999",
  "referralCode": "HANS2024ABC"
}
    ↓
referral_handler.py: apply_referral_code()
    ↓
1. Validates code exists in DB
2. Finds referrer (User A)
    - referrerId: "+9197605210"
3. Checks not self-referral
4. Creates referral record:
   referrals collection:
     {
       referrerId: "+9197605210",
       referredUserId: "+919999999999",
       referralCode: "HANS2024ABC",
       status: "pending",
       rewardGiven: false,
       createdAt: "2026-04-11T10:00:00Z"
     }
5. Updates User B:
   users collection:
     {
       userId: "+919999999999",
       referredBy: "+9197605210",
       referralCodeUsed: "HANS2024ABC"
     }
    ↓
Bot confirms:
"Perfect! You've been referred by a friend 🌟

You'll get 1 month FREE premium when you subscribe!"
```

---

## 💳 **Step 4: User B Subscribes**

```
User B: "PAY"
    ↓
Bot shows plans with "Buy Now" buttons
    ↓
User B taps: "Buy Now - ₹199"
    ↓
System sends payment link
    ↓
User B pays ₹199 via Razorpay
    ↓
Razorpay sends webhook:
POST /payments/webhook
{
  "event": "payment_link.paid",
  "payload": {
    "payment": {
      "entity": {
        "id": "pay_abc123",
        "amount": 19900,
        "notes": {
          "userId": "+919999999999",
          "planId": "monthly_premium"
        }
      }
    }
  }
}
    ↓
server.py: razorpay_webhook()
    ↓
_calls: _create_subscription_from_payment()
    ↓
Creates subscription:
  - subscriptionId: "sub_abc123"
  - userId: "+919999999999"
  - planId: "monthly_premium"
  - status: "active"
  - startDate: "2026-04-11"
  - endDate: "2026-05-11" (30 days)
    ↓
_calls: referral_handler.process_referral_reward()
```

---

## 🎁 **Step 5: Referral Reward Processing**

**Automatic Processing:**
```
referral_handler.py: process_referral_reward()
    ↓
1. Check if User B was referred:
   - Finds: referredBy: "+9197605210"
    ↓
2. Find referral record:
   - status: "pending"
   - rewardGiven: false
    ↓
3. Extend User A's subscription:
   subscriptions collection:
     - Find User A's active subscription
     - endDate: "2026-06-15" (extend by 30 days)
    ↓
4. Extend User B's subscription:
   subscriptions collection:
     - User B's subscription
     - endDate: "2026-06-15" (extend by 30 days)
    ↓
5. Mark referral as completed:
   referrals collection:
     - status: "completed"
     - rewardGiven: true
     - completedAt: "2026-04-11T10:05:00Z"
    ↓
6. Update User A's stats:
   users collection:
     - totalReferrals: 1
     - freeMonthsEarned: 1
    ↓
✅ Both users get 1 month FREE premium!
```

---

## 📊 **Complete Referral Lifecycle**

```
┌─────────────────────────────────────────────────────────┐
│ 1. USER A GETS CODE                                    │
│    "REFER" → Code: HANS2024ABC                          │
│    Stored in MongoDB                                      │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 2. USER A SHARES CODE                                    │
│    "Use HANS2024ABC for discount!"                       │
│    WhatsApp link or direct message                         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 3. USER B SENDS CODE                                    │
│    "My friend said HANS2024ABC"                          │
│    Auto-detected by system                                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 4. CODE APPLIED                                        │
│    User B linked to User A                               │
│    Status: "pending"                                     │
│    Bot confirms: "Referred by friend!"                  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 5. USER B SUBSCRIBES                                   │
│    Pays ₹199 for premium plan                            │
│    Subscription created (30 days)                         │
│    endDate: "2026-05-11"                                │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│ 6. REWARD PROCESSED (AUTOMATIC!)                       │
│    - User A: endDate → "2026-06-15" (+30 days)             │
│    - User B: endDate → "2026-06-15" (+30 days)             │
│    - Referral: status → "completed"                       │
│    - Stats: totalReferrals → 1, freeMonthsEarned → 1        │
└─────────────────────────────────────────────────────────┘
                          ↓
                      ✅ BOTH GET 1 MONTH FREE! ✅
```

---

## 🔗 **Database Updates (Referral System)**

### **users Collection - Referral Fields:**
```javascript
{
  userId: "+9197605210",
  
  // Referrer fields
  referralCode: "HANS2024ABC",           // This user's unique code
  totalReferrals: 5,                     // People referred
  freeMonthsEarned: 5,                  // Free months earned
  
  // Referred user fields
  referredBy: "+919999999999",           // Who referred this user
  referralCodeUsed: "HANS2024XYZ"         // Code used (if any)
}
```

### **referrals Collection - Tracking:**
```javascript
{
  _id: ObjectId,
  referrerId: "+9197605210",              // Who referred
  referredUserId: "+9199999999",         // Who was referred
  referralCode: "HANS2024ABC",          // Code used
  status: "pending" | "completed",      // pending = signed up, completed = subscribed
  rewardGiven: Boolean,                 // Whether reward was applied
  createdAt: ISODate("2026-04-11T10:00:00Z"),
  completedAt: ISODate("2026-04-11T11:00:00Z")
}
```

---

## 🎯 **Real Example:**

### **User A: +919760347653**
```
Day 1: 10:00 AM
User A: "REFER"
    ↓
Bot sends:
🎁 Share your Astrofriend!

Your referral code: HANS2024ABC

Share this with friends who need guidance.

📊 Your Stats:
Total referrals: 0
Free months earned: 0

Share link: [WhatsApp link]
    ↓
User A forwards code to 5 friends
```

### **User B: +919999999999**
```
Day 2: 03:00 PM
User B: "My friend said to use HANS2024ABC"
    ↓
System auto-detects code
    ↓
Bot: "Perfect! You've been referred by a friend 🌟

You'll get 1 month FREE premium when you subscribe!"

Day 2: 03:05 PM
User B: "PAY"
    ↓
Sees plans, taps "Buy Now - ₹199"
    ↓
Pays ₹199
    ↓
Subscription created: endDate = "2026-05-11"
    ↓
System automatically processes reward:
    - User A: endDate + 30 days = "2026-06-10"
    - User B: endDate + 30 days = "2026-06-10"
    ↓
Both users have premium till June!
```

---

## 💰 **Reward Calculation:**

### **Current Subscription:**
```
User B subscribes on: April 11, 2026
Plan: Monthly Premium (30 days)
End date: May 11, 2026
    ↓
Referral reward: +30 days
    ↓
New end date: June 10, 2026
```

### **If User A Already Has Subscription:**
```
User A's current end date: April 20, 2026
    ↓
Referral reward: +30 days
    ↓
If April 20 < today:
  New end date = April 20 + 30 days = May 20, 2026
    ↓
If April 20 > today (active):
  New end date = April 20 + 30 days = May 20, 2026
```

---

## ✅ **What Happens Automatically:**

### **1. Referral Code Generation**
- ✅ User types "REFER"
- ✅ System generates unique code
- ✅ Stored in MongoDB
- ✅ Sent via WhatsApp

### **2. Referral Code Detection**
- ✅ Auto-detects HANS2024ABC pattern
- ✅ Validates code exists
- ✅ Links referrer to referee
- ✅ Creates "pending" referral

### **3. Reward Processing**
- ✅ Triggered by payment webhook
- ✅ Checks if user was referred
- ✅ Extends both subscriptions by 30 days
- ✅ Marks referral as "completed"
- ✅ Updates referral stats

---

## 🚨 **Referral System Features:**

### **Security:**
- ✅ Cannot use own code (self-referral blocked)
- ✅ One code per user (unique codes)
- ✅ Code validation before applying

### **Tracking:**
- ✅ Referral status: "pending" → "completed"
- ✅ Reward tracking: rewardGiven flag
- ✅ Statistics: totalReferrals, freeMonthsEarned

### **Rewards:**
- ✅ 30 days (1 month) free premium
- ✅ Given to BOTH users
- ✅ Extends existing subscriptions
- ✅ OR creates new subscription

---

## 📱 **WhatsApp Commands:**

### **For Referrer (User A):**
```
REFER
REFERRAL
REFERRALS
SHARE
INVITE
```

All do the same thing: Show referral code and stats

### **For Referee (User B):**
```
HANS2024ABC
My friend said to use HANS2024ABC
Use code: HANS2024ABC
```

All of these are auto-detected by the system!

---

## 🎁 **Referral Reward Benefits:**

### **For Referrer (User A):**
- ✅ 1 month free premium per referral
- ✅ Unlimited referrals possible
- ✅ Stats tracking
- ✅ Free months keep accumulating

### **For Referred (User B):**
- ✅ 1 month free premium
- ✅ Instant benefit after subscription
- ✅ No extra cost

---

## 📊 **Referral Analytics:**

### **API Endpoint:**
```bash
GET /referrals/stats/{userId}
```

### **Returns:**
```json
{
  "totalReferrals": 5,
  "completedReferrals": 3,
  "pendingReferrals": 2,
  "freeMonthsEarned": 3,
  "referralCode": "HANS2024ABC"
}
```

---

## 🔗 **Integration with Payment Flow:**

```
User B subscribes
    ↓
Razorpay webhook: payment_link.paid
    ↓
_create_subscription_from_payment()
    ↓
Creates subscription (30 days)
    ↓
process_referral_reward()
    ↓
Checks: User B has "referredBy" field?
    ↓
Yes → Finds User A
    ↓
Extends User A's subscription (+30 days)
Extends User B's subscription (+30 days)
Updates referral stats
    ↓
✅ Both get 1 month free!
```

---

## 🎯 **Complete Example:**

### **Day 1: User A Gets Code**
```
User A (+919760347653): "REFER"
    ↓
Bot: "🎁 Share your Astrofriend!

Your referral code: HANS2024ABC

Share with friends who need guidance..."
```

### **Day 5: User B Uses Code**
```
User B (+919999999999): "My friend said HANS2024ABC"
    ↓
Bot: "Perfect! You've been referred by a friend 🌟

You'll get 1 month FREE premium when you subscribe!"

[Stored in DB: User B.referredBy = "+919760347653"]
```

### **Day 10: User B Subscribes**
```
User B: "PAY"
    ↓
Bot: Shows plans
    ↓
User B: Taps "Buy Now - ₹199"
    ↓
Pays ₹199
    ↓
Subscription created: endDate = May 10, 2026
    ↓
[WEBHOOK: payment_link.paid]
    ↓
process_referral_reward() called
    ↓
Finds: User B.referredBy = "+919760347653"
    ↓
Extends User A's subscription: +30 days
Extends User B's subscription: +30 days
    ↓
✅ Both have premium till June 9, 2026
```

---

## 📝 **Summary:**

**How Referral Works:**
1. User A types "REFER" → Gets code
2. User A shares code with User B
3. User B sends code → Auto-applied
4. User B subscribes → **BOTH get 1 month free automatically**

**What's Automatic:**
- ✅ Code generation
- ✅ Code detection
- ✅ Code validation
- ✅ Reward processing
- ✅ Subscription extension
- ✅ Stats updates

**What's Manual:**
- ❌ Nothing! All automatic! 🎉
