# WhatsApp Payments - Environment Variables Quick Reference

## hans-ai-whatsapp Service

| Variable | Example | Required? | Description |
|----------|---------|-----------|-------------|
| `WHATSAPP_PHONE_ID` | `123456789012345` | ✅ Yes | Phone ID from Meta |
| `WHATSAPP_ACCESS_TOKEN` | `EAAxxxxxxxxxx` | ✅ Yes | Long-term API token |
| `WHATSAPP_WABA_ID` | `987654321098765` | ✅ Yes | WABA ID |
| `WHATSAPP_PAYMENT_CONFIG_ID` | `Astrofriend_Razorpay` | ✅ Yes | Direct Pay Method name |
| `WHATSAPP_PAYMENT_MID` | `rzp_live_xxxxx` | ✅ Yes | Razorpay Merchant ID |
| `WHATSAPP_FLOW_ID` | `1234567890123456` | ✅ Yes | Flow ID from Meta |
| `WHATSAPP_VERIFY_TOKEN` | `my_secret_token_123` | ✅ Yes | Webhook verify token |
| `SUBSCRIPTIONS_URL` | `https://...` | ✅ Yes | Subscriptions service URL |

## hans-ai-subscriptions Service

| Variable | Example | Required? | Description |
|----------|---------|-----------|-------------|
| `RAZORPAY_KEY_ID` | `rzp_live_xxxxx` | ✅ Yes | Razorpay Key ID |
| `RAZORPAY_KEY_SECRET` | `rzp_live_xxxxx` | ✅ Yes | Razorpay Key Secret |
| `RAZORPAY_WEBHOOK_SECRET` | `webhook_secret_xxx` | ✅ Yes | Razorpay webhook secret |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | `my_secret_token_123` | ✅ Yes | Webhook verify token |
| `MONGO_URL` | `mongodb://...` | ✅ Yes | MongoDB connection string |

---

## How to Get These Values

### From Meta Business Manager

1. **WHATSAPP_PHONE_ID**
   - Business Manager > WhatsApp > Phone Numbers
   - Click on your number > Phone ID

2. **WHATSAPP_ACCESS_TOKEN**
   - Business Manager > WhatsApp > Phone Numbers
   - Click on your number > Temporary Access Token
   - Set expiration to "Never" for production

3. **WHATSAPP_WABA_ID**
   - Business Manager > WhatsApp > Account Overview
   - WABA ID shown at the top

4. **WHATSAPP_PAYMENT_CONFIG_ID**
   - Business Manager > Payments > Payment Configurations
   - This is the name you created: "Astrofriend_Razorpay"

5. **WHATSAPP_FLOW_ID**
   - Business Manager > WhatsApp > Flows
   - Create Flow > Publish > Flow ID shown

### From Razorpay Dashboard

6. **RAZORPAY_KEY_ID**
   - Razorpay Dashboard > Settings > API Keys
   - Key ID (starts with `rzp_live_` or `rzp_test_`)

7. **RAZORPAY_KEY_SECRET**
   - Razorpay Dashboard > Settings > API Keys
   - Key Secret (click to reveal)

8. **RAZORPAY_WEBHOOK_SECRET**
   - Razorpay Dashboard > Settings > Webhooks
   - Create webhook > Webhook Secret

9. **WHATSAPP_PAYMENT_MID**
   - Razorpay Dashboard > Settings
   - Merchant ID (MID)

---

## Testing vs Production

### For Testing (Sandbox Mode)

Use test values:
```bash
RAZORPAY_KEY_ID=rzp_test_xxxxx
RAZORPAY_KEY_SECRET=test_secret_xxxxx
```

### For Production (Live Mode)

Use live values:
```bash
RAZORPAY_KEY_ID=rzp_live_xxxxx
RAZORPAY_KEY_SECRET=live_secret_xxxxx
```

⚠️ **Important**: Never use test keys in production!

---

## Coolify Configuration Steps

### 1. Open Coolify Dashboard

### 2. Select Service: hans-ai-whatsapp

### 3. Go to: Settings > Environment Variables

### 4. Add Variables (one per line):

```bash
WHATSAPP_PHONE_ID=123456789012345
WHATSAPP_ACCESS_TOKEN=EAAxxxxxxxxxx
WHATSAPP_WABA_ID=987654321098765
WHATSAPP_PAYMENT_CONFIG_ID=Astrofriend_Razorpay
WHATSAPP_PAYMENT_MID=rzp_live_xxxxx
WHATSAPP_FLOW_ID=1234567890123456
```

### 5. Save & Restart Service

### 6. Repeat for hans-ai-subscriptions service

---

## Verification

After adding variables, verify with:

```bash
# Check WhatsApp service
curl https://<your-whatsapp-service>/health/whatsapp-payments

# Check Subscriptions service
curl https://<your-subscriptions-service>/health/whatsapp-payments
```

Expected: `"status": "enabled"` or `"status": "configured"`
