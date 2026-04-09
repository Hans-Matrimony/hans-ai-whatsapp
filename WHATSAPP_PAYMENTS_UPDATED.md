# WhatsApp Payments Implementation - UPDATED ARCHITECTURE

## ✅ Changes Made

The implementation has been updated to use the **existing webhook** instead of creating a separate payment webhook.

---

## 🔄 New Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Meta Business Manager                                      │
│  Webhook URL: https://<your-domain>/webhook/whatsapp        │
│  Verify Token: WHATSAPP_VERIFY_TOKEN (existing)             │
│                                                             │
│  All events come here:                                      │
│  - User messages                                            │
│  - Message status updates                                   │
│  - Payment events (NEW!)                                    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  hans-ai-whatsapp (Webhook Handler)                         │
│  /webhook/whatsapp                                          │
│                                                             │
│  Detect event type:                                         │
│  ├─ Message → Process as usual (existing logic)             │
│  └─ Payment → Forward to subscriptions service             │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓ (for payments only)
┌─────────────────────────────────────────────────────────────┐
│  hans-ai-subscriptions                                     │
│  /payments/internal/process-whatsapp-payment                │
│                                                             │
│  Process payment and create subscription                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 📝 What Changed

### Before (Old Implementation):
- ❌ Separate payment webhook: `/payments/whatsapp-webhook`
- ❌ Required: `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
- ❌ Two webhooks in Meta Manager (not supported)

### After (New Implementation):
- ✅ Single webhook: `/webhook/whatsapp` (existing)
- ✅ No new verify token needed
- ✅ Internal forwarding of payment events
- ✅ Works with Meta's single webhook limitation

---

## 🎯 Environment Variables Needed

### hans-ai-whatsapp (Webhook + Worker services)
```bash
# NEW - Add these 4 variables:
WHATSAPP_WABA_ID=<your_waba_id>
WHATSAPP_PAYMENT_CONFIG_ID=Astrofriend_Razorpay
WHATSAPP_PAYMENT_MID=<your_payment_gateway_mid>
WHATSAPP_FLOW_ID=<your_flow_id>

# EXISTING - Already have these (no changes needed):
WHATSAPP_VERIFY_TOKEN=<existing_token>
WHATSAPP_PHONE_ID=<existing_phone_id>
WHATSAPP_ACCESS_TOKEN=<existing_access_token>
```

### hans-ai-subscriptions
```bash
# NO NEW VARIABLES NEEDED!

# EXISTING - Already have these:
RAZORPAY_KEY_ID=<existing>
RAZORPAY_KEY_SECRET=<existing>
RAZORPAY_WEBHOOK_SECRET=<existing>
```

---

## ✅ Summary of Changes

### Files Modified:

1. **hans-ai-whatsapp/whatsapp_webhook.py**
   - ✅ Added payment event detection in existing webhook
   - ✅ Added `_forward_payment_event()` function
   - ✅ Payment events forwarded internally to subscriptions service

2. **hans-ai-subscriptions/server.py**
   - ✅ Added `/payments/internal/process-whatsapp-payment` endpoint
   - ✅ Removed separate payment webhook endpoints
   - ✅ Updated health check endpoint

### What Was Removed:
- ❌ Separate payment webhook verification endpoint
- ❌ Need for `WHATSAPP_WEBHOOK_VERIFY_TOKEN`

### What Stayed the Same:
- ✅ All existing message processing logic
- ✅ All existing webhook verification
- ✅ Razorpay webhook handling
- ✅ All environment variables (except the new WhatsApp Payments ones)

---

## 🚀 Deployment Steps

### Step 1: Add Environment Variables to Coolify

**Service: hans-ai-whatsapp** (Both Webhook AND Worker)
```bash
WHATSAPP_WABA_ID=<your_waba_id>
WHATSAPP_PAYMENT_CONFIG_ID=Astrofriend_Razorpay
WHATSAPP_PAYMENT_MID=<your_payment_gateway_mid>
WHATSAPP_FLOW_ID=<your_flow_id>
```

**Service: hans-ai-subscriptions**
```bash
# NO NEW VARIABLES NEEDED!
```

### Step 2: Push Code to Repository
```bash
git add .
git commit -m "feat: WhatsApp Payments integration using existing webhook"
git push origin main
```

### Step 3: Deploy in Coolify
1. Deploy `hans-ai-whatsapp` (Webhook service)
2. Deploy `hans-ai-whatsapp` (Worker service)
3. Deploy `hans-ai-subscriptions` (if needed)

### Step 4: Test with Test Number
```
1. Send "PAY" to your WhatsApp bot (test number)
2. Should receive plan options
3. Send "1" (or any plan number)
4. Should receive WhatsApp Flow with "Pay Now" button
5. Tap button to pay
6. After payment, subscription should be created
```

---

## 🔧 How to Test

### Manual Test with Test Number:
```
Phone: +919760347653 (or your test number)

1. Send: PAY
2. Bot: [Shows plans]
3. Send: 1
4. Bot: [Sends WhatsApp Flow]
5. You: [Tap Pay Now → Complete payment]
6. Send: [Any message]
7. Bot: [Should respond - access granted!]
```

### Health Check:
```bash
curl https://<whatsapp-service>/health/whatsapp-payments
```

Expected response:
```json
{
  "status": "enabled",
  "payment_mode": "in_app_flow",
  "configured": true
}
```

---

## ✅ Advantages of New Architecture

1. **Simpler** - Only one webhook to manage
2. **No new tokens** - Uses existing WHATSAPP_VERIFY_TOKEN
3. **Cleaner** - Internal service communication
4. **Works with Meta** - Respects Meta's single webhook limitation
5. **No breaking changes** - Existing functionality untouched

---

## 🎯 Total Variables to Add

**Across all services:** **4 environment variables**

| Repository | Service | Variables to ADD |
|-----------|---------|-----------------|
| `hans-ai-whatsapp` | Webhook Handler | 4 (WhatsApp Payments vars) |
| `hans-ai-whatsapp` | Celery Worker | 4 (same WhatsApp Payments vars) |
| `hans-ai-subscriptions` | Main service | 0 (none!) |

---

## ✅ You're Ready!

All code changes are complete. No new verify token needed. Just add the 4 environment variables and test!

**Ready to deploy? 🚀**
