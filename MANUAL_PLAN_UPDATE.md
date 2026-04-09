# Manual Plan Update Instructions

Since the automatic script cannot connect to MongoDB, here are the manual steps to update your subscription plans.

---

## 🎯 Option 1: Using MongoDB Atlas Console (Easiest)

1. **Go to your MongoDB Atlas Dashboard**
   - Login to https://cloud.mongodb.com
   - Go to: Database → Browse Collections
   - Select database: `hans-ai-subscriptions`
   - Select collection: `plans`

2. **Deactivate Existing Plans**
   - Click "Filter" button
   - Add filter: `isActive = true`
   - This shows all active plans
   - For each plan, edit and set `isActive = false`

3. **Add New Plans**

   **Plan 1: Monthly (₹299)**
   - Click "Add Data" → "Insert Document"
   - Paste this JSON:
   ```json
   {
     "planId": "monthly_299",
     "name": "Monthly Basic",
     "description": "Unlimited messages for 1 month",
     "price": 29900,
     "currency": "INR",
     "durationDays": 30,
     "features": [
       "Unlimited messages",
       "Detailed kundli",
       "Personalized predictions",
       "Career guidance",
       "Relationship advice"
     ],
     "isActive": true,
     "createdAt": {"$date": "2026-04-07T00:00:00Z"}
   }
   ```

   **Plan 2: Yearly (₹199)**
   - Click "Add Data" → "Insert Document" again
   - Paste this JSON:
   ```json
   {
     "planId": "yearly_199",
     "name": "Yearly Premium",
     "description": "Unlimited messages for 1 year - BEST VALUE!",
     "price": 19900,
     "currency": "INR",
     "durationDays": 365,
     "features": [
       "Unlimited messages",
       "Detailed kundli",
       "Personalized predictions",
       "Career guidance",
       "Relationship advice",
       "Priority support",
       "Vastu consultation"
     ],
     "isActive": true,
     "createdAt": {"$date": "2026-04-07T00:00:00Z"}
   }
   ```

---

## 🎯 Option 2: Using mongosh (MongoDB Shell)

If you have MongoDB installed locally or can SSH into your server:

```bash
# Connect to your MongoDB (replace with your actual connection string)
mongosh "mongodb+srv://your-username:your-password@your-cluster.mongodb.net/hans-ai-subscriptions"

# Switch to database
use hans-ai-subscriptions

# Deactivate all existing plans
db.plans.updateMany(
  { isActive: true },
  { $set: { isActive: false } }
)

# Create monthly plan
db.plans.insertOne({
  planId: "monthly_299",
  name: "Monthly Basic",
  description: "Unlimited messages for 1 month",
  price: 29900,
  currency: "INR",
  durationDays: 30,
  features: [
    "Unlimited messages",
    "Detailed kundli",
    "Personalized predictions",
    "Career guidance",
    "Relationship advice"
  ],
  isActive: true,
  createdAt: new Date()
})

# Create yearly plan
db.plans.insertOne({
  planId: "yearly_199",
  name: "Yearly Premium",
  description: "Unlimited messages for 1 year - BEST VALUE!",
  price: 19900,
  currency: "INR",
  durationDays: 365,
  features: [
    "Unlimited messages",
    "Detailed kundli",
    "Personalized predictions",
    "Career guidance",
    "Relationship advice",
    "Priority support",
    "Vastu consultation"
  ],
  isActive: true,
  createdAt: new Date()
})

# Verify
db.plans.find({ isActive: true }).pretty()
```

---

## 🎯 Option 3: Via Coolify Database Interface

1. Go to Coolify → hans-ai-subscriptions service
2. Open database tab or use web shell
3. Run the commands from Option 2 above

---

## ✅ Verification

After updating, verify the plans are correct:

```bash
# In MongoDB shell or Atlas Console:
db.plans.find({ isActive: true }, { name: 1, price: 1, durationDays: 1 })
```

Expected output:
```javascript
[
  {
    "_id": ObjectId("..."),
    "name": "Monthly Basic",
    "price": 29900,
    "durationDays": 30
  },
  {
    "_id": ObjectId("..."),
    "name": "Yearly Premium",
    "price": 19900,
    "durationDays": 365
  }
]
```

---

## 📊 Price Confirmation:

- **Monthly:** ₹299 (29900 paise) for 30 days = ₹299/month ✅
- **Yearly:** ₹199 (19900 paise) for 365 days = ₹199/year ✅

**Savings:** ₹3,389 per year (96% discount!)

---

## 🚨 Note:

If you're having trouble with any of these methods, let me know:
1. What database service you're using (MongoDB Atlas, self-hosted, etc.)
2. How you normally access your database
3. I'll provide specific instructions for your setup!
