# Message-Based Paywall - Testing & Deployment Guide

## ✅ Implementation Complete!

All files have been created:
- ✅ `app/services/message_limiter.py` - Core paywall logic
- ✅ `app/services/tasks.py` - Updated with message counting
- ✅ `scripts/migrate_message_paywall.py` - Database migration script

---

## 🚀 Deployment Steps

### Step 1: Run Database Migration (5 minutes)

```bash
cd d:\HansMatrimonyOrg\hans-ai-whatsapp

# Run migration script
python scripts/migrate_message_paywall.py
```

**Expected Output:**
```
✅ Connected to MongoDB
📋 Step 1: Creating message_limits collection...
  ✅ Created index: userId_1_date_1
📋 Step 2: Updating users collection schema...
  📊 Total users in database: 10
  ✅ Updated 10 users with new fields
  ✅ Set isPaywallEnabled=false for 10 existing users
✅ MIGRATION COMPLETE!
```

**What this does:**
- Creates `message_limits` collection with indexes
- Adds new fields to all users (messageCount, paywallShown, etc.)
- Sets `isPaywallEnabled=false` for ALL existing users (they keep unlimited access)

---

### Step 2: Deploy to Coolify (5 minutes)

```bash
# Commit changes
git add .
git commit -m "Add message-based paywall for new users

- Added message_limiter.py with paywall logic
- Updated tasks.py to check message limits
- New users: 40 free messages, then 3-5/day
- Existing users: Unlimited (isPaywallEnabled=false)
- Database migration script included

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

# Push to GitHub
git push
```

Coolify will auto-deploy in 2-5 minutes.

---

### Step 3: Test with New User (10 minutes)

#### Test 1: New User Paywall Enabled

**Use a NEW phone number** (not in your database yet):

```
Phone: +919999999999
Message: "Hello"
```

**Expected Behavior:**
1. ✅ User created with `isPaywallEnabled=true`
2. ✅ Message allowed
3. ✅ AI responds normally
4. ✅ Message count = 1

**Check Logs:**
```
[Message Limiter] User: +919999999999, Allowed: True, Phase: new_user, Messages Remaining: 39
[Message Limiter] Incremented count for +919999999999: 1 total messages
```

**Check Database:**
```bash
mongosh mongodb://localhost:27017/hans-ai-subscriptions

db.users.findOne({userId: "+919999999999"})
```

**Expected:**
```json
{
  "userId": "+919999999999",
  "messageCount": 1,
  "isPaywallEnabled": true,  // ← Paywall ON for new users
  "tier": "free",
  "paywallShown": false
}
```

---

#### Test 2: Existing User Paywall Disabled

**Use YOUR phone number** (Vardhan):

```
Phone: +919760347653
Message: "Hello"
```

**Expected Behavior:**
1. ✅ Message allowed (no limit check)
2. ✅ AI responds normally
3. ✅ Message count NOT incremented (or stays at 0)

**Check Logs:**
```
[Message Limiter] User: +919760347653, Allowed: True, Phase: unlimited, Messages Remaining: -1
[Subscription] +919760347653 has access: trial
```

**Check Database:**
```bash
db.users.findOne({userId: "+919760347653"})
```

**Expected:**
```json
{
  "userId": "+919760347653",
  "messageCount": 0,  // or existing count
  "isPaywallEnabled": false,  // ← Paywall OFF for existing users
  "tier": "free"
}
```

---

#### Test 3: Soft Paywall (Message 40)

For the new user (+919999999999), manually set message count to 39:

```bash
db.users.updateOne(
  {userId: "+919999999999"},
  {$set: {messageCount: 39, paywallShown: false}}
)
```

**Send message:**
```
Phone: +919999999999
Message: "Hello"
```

**Expected Behavior:**
1. ✅ Soft paywall message sent FIRST
2. ✅ Then AI responds normally
3. ✅ Paywall marked as shown

**Expected WhatsApp Messages:**
```
[Message 1 - Paywall]
You've sent 40 messages! 🌟

Your kundli shows something interesting...

Want to unlock detailed predictions?

💫 Plans:
• Monthly - ₹499/month
• Quarterly - ₹999/quarter
• Yearly - ₹2999/year

Reply PAY to unlock unlimited access!

[Message 2 - AI Response]
(AI's normal response to "Hello")
```

**Check Logs:**
```
[Message Limiter] Soft paywall shown to user +919999999999, continuing message processing
[Message Limiter] Incremented count for +919999999999: 40 total messages
```

---

#### Test 4: Hard Paywall (Daily Limit)

For the new user (+919999999999), set up for hard paywall:

```bash
# Set up user as post-paywall with daily limit used
db.users.updateOne(
  {userId: "+919999999999"},
  {
    $set: {
      messageCount: 50,
      paywallShown: true,
      tier: "free"
    }
  }
)

# Use all 5 daily messages
db.message_limits.insertOne({
  userId: "+919999999999",
  date: "2024-04-07",
  messagesSent: 5,
  limit: 5,
  tier: "free"
})
```

**Send message:**
```
Phone: +919999999999
Message: "Hello"
```

**Expected Behavior:**
1. ✅ Message BLOCKED
2. ✅ Hard paywall message sent
3. ✅ NO AI response
4. ✅ Message count NOT incremented

**Expected WhatsApp Message:**
```
You've used your 5 free messages for today.

Come back tomorrow for more free messages,
or upgrade to UNLIMITED access:

💫 Plans:
• Monthly - ₹499/month
• Quarterly - ₹999/quarter
• Yearly - ₹2999/year

Reply PAY to continue now!
```

**Check Logs:**
```
[Message Limiter] User +919999999999 has hit daily limit, blocking message
[Message Limiter] User: +919999999999, Allowed: False, Phase: daily_limit_reached
```

---

#### Test 5: Premium User (Unlimited)

For the new user (+919999999999), upgrade to premium:

```bash
db.users.updateOne(
  {userId: "+919999999999"},
  {$set: {tier: "premium"}}
)
```

**Send message:**
```
Phone: +919999999999
Message: "Hello"
```

**Expected Behavior:**
1. ✅ Message allowed
2. ✅ NO daily limit check
3. ✅ AI responds normally
4. ✅ Unlimited access

**Check Logs:**
```
[Message Limiter] User +919999999999 is premium, unlimited access
[Message Limiter] User: +919999999999, Allowed: True, Phase: premium, Messages Remaining: -1
```

---

## 📊 Monitoring Commands

### Check All Users

```bash
mongosh mongodb://localhost:27017/hans-ai-subscriptions

# Total users
db.users.countDocuments()

# Users with paywall disabled (existing)
db.users.countDocuments({isPaywallEnabled: false})

# Users with paywall enabled (new)
db.users.countDocuments({isPaywallEnabled: true})

# Users at soft paywall (40 messages)
db.users.countDocuments({
  messageCount: 40,
  paywallShown: true
})

# Premium users
db.users.countDocuments({tier: "premium"})
```

### Check Specific User

```bash
db.users.findOne({userId: "+919999999999"}, {
  userId: 1,
  messageCount: 1,
  isPaywallEnabled: 1,
  paywallShown: 1,
  tier: 1
})
```

### Check Today's Message Usage

```bash
db.message_limits.aggregate([
  {$match: {date: "2024-04-07"}},
  {$count: "users_today"}
])
```

### Users Over Daily Limit

```bash
db.message_limits.find({
  date: "2024-04-07",
  messagesSent: {$gte: 5}
}).count()
```

---

## 🚨 Troubleshooting

### Issue: Migration Fails

**Error:** `Connection refused`

**Fix:** Check MongoDB is running:
```bash
# Check if MongoDB is accessible
mongosh mongodb://localhost:27017

# Or check environment variable
echo $MONGO_LOGGER_URL
```

---

### Issue: Paywall Not Working

**Symptom:** New user still has unlimited access

**Check:**
```bash
db.users.findOne({userId: "+919999999999"}, {isPaywallEnabled: 1})
```

**Expected:** `isPaywallEnabled: true`

**If false:**
```bash
db.users.updateOne(
  {userId: "+919999999999"},
  {$set: {isPaywallEnabled: true}}
)
```

---

### Issue: Message Count Not Incrementing

**Check Logs:**
```
grep "Message Limiter" /var/log/hans-ai-whatsapp.log
```

**If error:** Check MongoDB connection in tasks.py

---

### Issue: Existing Users Blocked

**Symptom:** You (Vardhan) getting blocked

**Fix:** Double-check your paywall status:
```bash
db.users.findOne({userId: "+919760347653"}, {isPaywallEnabled: 1})
```

**Should be:** `isPaywallEnabled: false`

**If true:**
```bash
db.users.updateOne(
  {userId: "+919760347653"},
  {$set: {isPaywallEnabled: false}}
)
```

---

## 📋 Rollback Plan

If something goes wrong:

### Option 1: Disable Paywall for All Users

```python
from app.services.message_limiter import MessageLimiter
from pymongo import MongoClient

client = MongoClient("mongodb://localhost:27017")
db = client["hans-ai-subscriptions"]

# Disable paywall for ALL users
db.users.updateMany(
  {},
  {$set: {isPaywallEnabled: false}}
)
```

### Option 2: Revert Code

```bash
# Revert to previous commit
git revert HEAD
git push
```

Coolify will redeploy previous version.

---

## ✅ Pre-Deployment Checklist

- [ ] Database migration run successfully
- [ ] No errors in migration logs
- [ ] Existing users have `isPaywallEnabled=false`
- [ ] Code committed to GitHub
- [ ] Code pushed to GitHub
- [ ] Coolify shows "Deploying..."
- [ ] Coolify shows "Deployed" successfully
- [ ] Tested with new phone number (+919999999999)
- [ ] Tested with your phone number (+919760347653)
- [ ] Checked logs for [Message Limiter] tags
- [ ] Verified database state

---

## 🎯 Post-Deployment Monitoring

### First Hour (After Deployment)

```bash
# Watch logs in real-time
tail -f /var/log/hans-ai-whatsapp.log | grep "Message Limiter"
```

**What to look for:**
- ✅ `[Message Limiter]` tags appearing
- ✅ New users getting `isPaywallEnabled: true`
- ✅ Existing users getting `paywallDisabled: True`
- ❌ No errors in message limiter code

### First Day

```bash
# Check how many new users signed up
db.users.countDocuments({
  isPaywallEnabled: true,
  createdAt: {$gte: ISODate("2024-04-07")}
})
```

### First Week

**Metrics to track:**
- How many users hit soft paywall (message 40)?
- How many users hit hard paywall (daily limit)?
- Paywall conversion rate (users who upgraded)
- Message count distribution across users

---

## 🚀 Ready to Deploy?

**All files created and ready!**

1. ✅ Run migration: `python scripts/migrate_message_paywall.py`
2. ✅ Deploy to production: `git push`
3. ✅ Test with new user
4. ✅ Monitor logs

**Any issues?** Check the troubleshooting section above!

**Need to enable paywall for existing users later?**
```python
from app.services.message_limiter import MessageLimiter
limiter = MessageLimiter(mongo_client)
limiter.enable_paywall_for_all_existing_users()
```

This can be done in 2-3 days as you planned!

---

**Good luck! 🚀**
