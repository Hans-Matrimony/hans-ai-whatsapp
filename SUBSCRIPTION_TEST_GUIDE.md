# WhatsApp-Native Subscription Flow (No Payment Page Needed!)

## ✨ NEW: Razorpay Payment Links - Direct from WhatsApp!

**NO custom payment page needed!** Users pay directly on Razorpay's hosted page.

---

## How It Works Now

```
📱 WhatsApp (Trial Expired)
    ↓
User: "PAY"
    ↓
Bot: Shows 3 plans
    ↓
User: "1"
    ↓
Bot: "Click: https://rzp.io/abc123" (Direct Razorpay link!)
    ↓
User clicks → Pays on Razorpay page → Auto webhook
    ↓
Subscription activated!
    ↓
User: "Hello" → Bot responds normally ✅
```

---

## Environment Variables

### hans-ai-whatsapp/.env
```bash
SUBSCRIPTIONS_URL=https://your-subscriptions-service.com
SUBSCRIPTION_TEST_NUMBER=9760347653
```

### hans-ai-subscriptions/.env
```bash
# Razorpay credentials
RAZORPAY_KEY_ID=rzp_live_xxxxx
RAZORPAY_KEY_SECRET=your_secret
RAZORPAY_WEBHOOK_SECRET=webhook_secret_from_razorpay_dashboard

# Your service URL (for callbacks)
BASE_URL=https://your-subscriptions-service.com
```

---

## Complete User Flow

### Step 1: Trial Expires
```
User: "Meri kundli banao"
```

```
Bot: Your 7-day free trial has ended. To continue using Hans AI Astrology services,
     please subscribe to a plan.

     Reply *PAY* to see subscription options.
```

### Step 2: User Requests Plans
```
User: "PAY"
```

```
Bot: *💫 Choose Your Subscription Plan:*

     *1. Monthly Basic*
     💰 ₹499/30 days
        ✓ Unlimited consultations
        ✓ Kundli generation
        ✓ Matchmaking

     *2. Quarterly Premium*
     💰 ₹999/90 days
        ✓ Everything in Monthly
        ✓ Priority support
        ✓ Vastu consultation

     *3. Yearly Pro*
     💰 ₹2999/365 days
        ✓ All features included
        ✓ Personalized remedies
        ✓ 24/7 support

     Reply with plan number (1, 2, 3...) to get payment link.
```

### Step 3: User Selects Plan
```
User: "1"
```

```
Bot: Great! You selected Plan 1.

     Click here to pay: https://rzp.io/abc123xyz

     After payment, come back and send me a message! 💫
```

### Step 4: User Pays (Razorpay Hosted Page)
1. User clicks link → Opens Razorpay payment page
2. User pays via UPI/Card/Wallet
3. Razorpay sends webhook to your server
4. Subscription automatically created
5. User redirected to success page

### Step 5: User Returns to WhatsApp
```
User: "Hello"
```

```
Bot: Namaste! How can I help you today?
     (Normal AI response - access granted!)
```

---

## API Changes

### New Endpoint: POST /payments/create-payment-link

**Request:**
```json
{
  "userId": "+919760347653",
  "planId": "monthly_basic",
  "currency": "INR"
}
```

**Response:**
```json
{
  "success": true,
  "payment_link": "https://rzp.io/abc123xyz",
  "payment_link_id": "plink_xyz123",
  "amount": 49900,
  "currency": "INR",
  "plan": {...}
}
```

### Updated Webhook: POST /payments/webhook

Now handles TWO events:

1. **`payment.captured`** - Standard checkout payments
2. **`payment_link.paid`** - Payment link payments (NEW!)

Both events:
- Verify signature
- Create subscription
- Record payment
- Activate user access

---

## Webhook Configuration (Razorpay Dashboard)

1. Go to: https://dashboard.razorpay.com/app/webhooks
2. Add webhook URL: `https://your-domain.com/payments/webhook`
3. Subscribe to events:
   - ✅ `payment.captured`
   - ✅ `payment_link.paid`
4. Copy webhook secret to `.env`:
   ```bash
   RAZORPAY_WEBHOOK_SECRET=your_secret_here
   ```

---

## Testing Checklist

### 1. Setup
```bash
# Add to hans-ai-whatsapp/.env
SUBSCRIPTIONS_URL=https://your-subscriptions-service.com
SUBSCRIPTION_TEST_NUMBER=9760347653

# Add to hans-ai-subscriptions/.env
RAZORPAY_KEY_ID=your_test_key_id
RAZORPAY_KEY_SECRET=your_test_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
BASE_URL=https://your-subscriptions-service.com
```

### 2. Test Payment Link Generation
```bash
# Expire trial
curl -X POST https://your-subscriptions.com/admin/expire-trial/+919760347653

# Send "PAY" from WhatsApp (9760347653)
# Should receive plan list

# Send "1" to select plan
# Should receive Razorpay payment link
```

### 3. Test Payment
1. Click the payment link
2. Pay with test card/UPI
3. Check webhook received
4. Verify subscription created in MongoDB
5. Send WhatsApp message - should work!

### 4. Test Webhook
```bash
# Check webhook logs
tail -f /var/log/hans-ai-subscriptions.log

# Should see:
# [PAYMENT_LINK_CALLBACK] Payment link ID: plink_xxx
# [Webhook] Created subscription for +919760347653
# [Webhook] Payment recorded: pay_xxx
```

---

## What Changed from Previous Version?

### ❌ OLD Way (Custom Page):
```
WhatsApp → Our Payment Page → Razorpay → Webhook
```
- Required custom HTML/JS page
- Needed PAYMENT_PAGE_URL config
- More maintenance

### ✅ NEW Way (Direct Razorpay):
```
WhatsApp → Razorpay Payment Link → User Pays → Webhook
```
- NO custom page needed!
- Razorpay handles everything
- Just 1 API call to generate link

---

## Files Modified

### hans-ai-whatsapp
- **tasks.py** - Updated `_generate_payment_link()` to call subscriptions service
- **.env.example** - Removed PAYMENT_PAGE_URL

### hans-ai-subscriptions
- **server.py** - Added `/payments/create-payment-link` endpoint
- **server.py** - Updated webhook to handle `payment_link.paid` events
- **server.py** - Added payment link callback handler
- **.env.example** - Added BASE_URL config

---

## Advantages of New Approach

✅ **No frontend code needed** - Razorpay hosts payment page
✅ **Mobile optimized** - Razorpay's mobile-friendly UI
✅ **All payment methods** - UPI, cards, wallets, Netbanking
✅ **Auto-retry** - Razorpay handles failed payments
✅ **Less maintenance** - No custom payment page to host
✅ **Faster setup** - Just configure webhook secret

---

## Production Readiness

To go live:

1. ✅ Switch from Test to Live credentials in Razorpay
2. ✅ Set BASE_URL to production domain
3. ✅ Configure webhook in Razorpay dashboard
4. ✅ Remove test number restriction from tasks.py
5. ✅ Test with real payment (₹1)

---

## Support

If payment link doesn't work:

1. Check SUBSCRIPTIONS_URL is reachable
2. Verify Razorpay credentials are correct
3. Check webhook is configured in Razorpay dashboard
4. Look at logs: `tail -f /var/log/hans-ai-subscriptions.log`

---

**That's it! No payment page needed - just WhatsApp + Razorpay! 🚀**
