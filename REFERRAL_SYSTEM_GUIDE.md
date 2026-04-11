# Referral System - Testing & Usage Guide

## 🎁 How the Referral System Works

### User Flow:

**Step 1: User A (Existing) gets referral code**
```
User A: "REFER"
Bot: 🎁 Share your Astrofriend!

Your referral code: HANS2024ABC

Share this with friends who need guidance. When they subscribe:
✓ You get 1 month FREE premium
✓ They also get 1 month FREE premium

📊 Your Stats:
Total referrals: 0
Free months earned: 0

Share link: [WhatsApp link]
```

**Step 2: User A shares with User B (New)**
- User A sends referral code: "HANS2024ABC"
- Or shares WhatsApp link

**Step 3: User B applies referral code**
```
User B: "HANS2024ABC"
Bot: Perfect! You've been referred by a friend 🌟

You'll get 1 month FREE premium when you subscribe!
```

**Step 4: User B subscribes**
- User B pays for any plan (Basic, Premium, etc.)
- System automatically processes referral reward

**Step 5: Both users get 1 month free premium**
```
✓ User A (referrer) gets 1 month added to existing subscription
✓ User B (referred) gets 1 month added to new subscription
✓ Both notified automatically
```

---

## 🧪 Testing the Referral System

### Test 1: Generate Referral Code

**Via WhatsApp:**
```
User: "REFER"
Expected: Bot sends referral code and share link
```

**Via API:**
```bash
curl -X POST https://hans-ai-subscriptions.onrender.com/referrals/generate-code \
  -H "Content-Type: application/json" \
  -d '{"userId": "+919760347653"}'

Expected:
{
  "success": true,
  "referralCode": "HANS2024ABC"
}
```

### Test 2: Get Referral Link

**Via API:**
```bash
curl https://hans-ai-subscriptions.onrender.com/referrals/my-link/+919760347653

Expected:
{
  "referralCode": "HANS2024ABC",
  "referralLink": "https://wa.me/?text=...",
  "totalReferrals": 0,
  "freeMonthsEarned": 0,
  "shareMessage": "🎁 Share your Astrofriend!..."
}
```

### Test 3: Apply Referral Code

**Via WhatsApp:**
```
User B: "My friend told me to use code HANS2024ABC"
Expected: Code automatically detected and applied
```

**Via API:**
```bash
curl -X POST https://hans-ai-subscriptions.onrender.com/referrals/apply \
  -H "Content-Type: application/json" \
  -d '{"userId": "+919999999999", "referralCode": "HANS2024ABC"}'

Expected:
{
  "success": true,
  "referrerId": "+919760347653",
  "referrerName": "Friend",
  "message": "Perfect! You've been referred..."
}
```

### Test 4: Process Referral Reward

**After User B subscribes:**

```bash
curl -X POST https://hans-ai-subscriptions.onrender.com/referrals/process-reward \
  -H "Content-Type: application/json" \
  -d '{"userId": "+919999999999"}'

Expected:
{
  "success": true,
  "message": "Reward given! Both users get 1 month free premium",
  "referrerId": "+919760347653",
  "referredUserId": "+919999999999",
  "premiumDurationDays": 30
}
```

### Test 5: Check Referral Stats

```bash
curl https://hans-ai-subscriptions.onrender.com/referrals/stats/+919760347653

Expected:
{
  "totalReferrals": 1,
  "completedReferrals": 1,
  "pendingReferrals": 0,
  "freeMonthsEarned": 1,
  "referralCode": "HANS2024ABC"
}
```

---

## 📊 Database Collections

### referrals Collection
```javascript
{
  _id: ObjectId,
  referrerId: "+919760347653",        // Who referred
  referredUserId: "+919999999999",    // Who was referred
  referralCode: "HANS2024ABC",        // Unique code
  status: "pending" | "completed",    // pending = signup, completed = subscription
  rewardGiven: Boolean,               // Whether reward was given
  createdAt: ISODate,
  completedAt: ISODate                // When referred user subscribed
}
```

### users Collection (new fields)
```javascript
{
  userId: "+919760347653",
  // ... existing fields ...
  referralCode: "HANS2024ABC",        // User's unique referral code
  referredBy: "+919999999999",        // Who referred this user (if any)
  referralCodeUsed: "HANS2024XYZ",     // Code used (if any)
  totalReferrals: Number,             // Count of successful referrals
  freeMonthsEarned: Number            // Free premium months from referrals
}
```

---

## 🔄 Automatic Detection

The system automatically detects referral codes in messages:

**Supported formats:**
- `HANS2024ABC` (code alone)
- `My code is HANS2024ABC` (in sentence)
- `Use referral code: HANS2024ABC` (with prefix)
- Case-insensitive: `hans2024abc` → `HANS2024ABC`

**Pattern:**
- Starts with: `HANS`
- Followed by: 4 digits
- Ends with: 3 uppercase letters

---

## 🎯 Referral Commands

### WhatsApp Commands:
- `REFER` - Get referral code & link
- `REFERRAL` - Same as REFER
- `REFERRALS` - Same as REFER
- `SHARE` - Same as REFER
- `INVITE` - Same as REFER

### API Endpoints:
- `POST /referrals/generate-code` - Generate code
- `GET /referrals/my-link/{userId}` - Get link & stats
- `POST /referrals/apply` - Apply code
- `POST /referrals/process-reward` - Process reward
- `GET /referrals/stats/{userId}` - Get stats

---

## 💰 Reward Details

**Reward:** 1 month FREE premium for BOTH users

**When:** Immediately after referred user subscribes

**How:**
- Referrer's existing subscription extended by 30 days
- Referred user's new subscription extended by 30 days
- Both users automatically get the extra time

**Tracking:**
- `totalReferrals` - Total people referred
- `freeMonthsEarned` - Total free months earned
- `completedReferrals` - Successfully converted referrals
- `pendingReferrals` - Signed up but not subscribed yet

---

## 🚨 Important Notes

1. **Cannot refer yourself** - System blocks self-referrals
2. **One referral per user** - Can only use one code when signing up
3. **Reward given once** - Each referral can only be rewarded once
4. **Valid codes only** - System validates all codes before applying
5. **Automatic processing** - Reward processed automatically on subscription

---

## 📱 WhatsApp Message Flow

**For Referrer (User A):**
```
User A: "REFER"

Bot: 🎁 Share your Astrofriend!

Your referral code: HANS2024ABC

Share this with friends who need guidance. When they subscribe:
✓ You get 1 month FREE premium
✓ They also get 1 month FREE premium

📊 Your Stats:
Total referrals: 0
Free months earned: 0

Share link: https://wa.me/?text=...
```

**For Referred User (User B):**
```
User B: "HANS2024ABC"

Bot: Perfect! You've been referred by a friend 🌟

You'll get 1 month FREE premium when you subscribe!
```

**After Subscription (Both):**
```
Bot: 🎁 Congratulations! Your referral reward has been applied!

You now have 1 extra month of premium access!
Enjoy your extended subscription! ✨
```

---

## ✅ Deployment Checklist

- [x] Referral handler created
- [x] Referral routes created
- [x] Server updated with referral router
- [x] REFER command added to WhatsApp
- [x] Auto-detection of referral codes
- [x] Reward processing on subscription
- [x] Committed to GitHub
- [ ] Deployed to Coolify
- [ ] Tested with real users
- [ ] Monitoring referral stats

---

## 🔧 Troubleshooting

**Error: "Invalid referral code"**
- Check code format: `HANS` + 4 digits + 3 letters
- Verify code exists in database
- Ensure referrer user exists

**Error: "Already used a referral code"**
- User can only use one code
- Check if user already has `referredBy` field

**Error: "Cannot use your own referral code"**
- User trying to refer themselves
- System blocks this automatically

**Reward not applied:**
- Check if referral status is "completed"
- Verify user has active subscription
- Check logs for processing errors
