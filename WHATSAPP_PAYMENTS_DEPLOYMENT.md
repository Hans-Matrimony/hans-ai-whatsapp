# WhatsApp Payments (Flows API) - Production Deployment Guide

## Overview

This implementation enables **Razorpay Payments on WhatsApp** - users can now pay without leaving the WhatsApp app using the WhatsApp Flows API.

---

## Architecture

```
User sends "PAY" → Shows plan list
User selects plan → Sends WhatsApp Flow (in-app payment UI)
User taps "Pay Now" → Opens payment screen inside WhatsApp
User completes payment → Razorpay + Meta process payment
Meta sends webhook → Creates subscription → User gets access
```

---

## Prerequisites Checklist

Before deploying, ensure you have:

- [x] **WABA ID** - WhatsApp Business Account ID
- [x] **Payment Config Name** - Direct Pay Method name (e.g., "Astrofriend_Razorpay")
- [x] **Payment Gateway MID** - Razorpay Merchant ID
- [x] **WhatsApp Phone ID** - From WhatsApp Business API setup
- [x] **WhatsApp Access Token** - Long-term API token
- [x] **Flow ID** - From Meta Business Manager (Flows section)
- [x] **Razorpay Key ID & Secret** - Already configured in Coolify

---

## Step 1: Environment Variables Configuration

### Service: `hans-ai-whatsapp`

Add these environment variables in Coolify:

```bash
# WhatsApp Payments Configuration
WHATSAPP_WABA_ID=<your_waba_id>
WHATSAPP_PAYMENT_CONFIG_ID=Astrofriend_Razorpay
WHATSAPP_PAYMENT_MID=<your_razorpay_mid>
WHATSAPP_FLOW_ID=<your_flow_id_from_meta>

# Existing WhatsApp Config (should already be there)
WHATSAPP_PHONE_ID=<your_phone_id>
WHATSAPP_ACCESS_TOKEN=<your_long_term_access_token>
WHATSAPP_VERIFY_TOKEN=<your_verify_token>

# Subscription Service (should already be there)
SUBSCRIPTIONS_URL=<your_subscriptions_service_url>
```

### Service: `hans-ai-subscriptions`

Add this environment variable:

```bash
# WhatsApp Webhook Verification
WHATSAPP_WEBHOOK_VERIFY_TOKEN=<choose_a_secure_token>

# Existing Razorpay Config (should already be there)
RAZORPAY_KEY_ID=<your_key_id>
RAZORPAY_KEY_SECRET=<your_key_secret>
RAZORPAY_WEBHOOK_SECRET=<your_webhook_secret>
```

---

## Step 2: Meta Business Manager - Webhook Configuration

### 2.1 Configure WhatsApp Payment Webhook

1. Go to **Meta Business Suite** > **Settings** > **WhatsApp** > **Webhooks**
2. Add/Update webhook URL:
   ```
   URL: https://<your-domain>/payments/whatsapp-webhook
   ```
3. Set **Verify Token** to the value of `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
4. Subscribe to these webhook events:
   - ✅ **payments** (Payment status updates)
   - ✅ **messages** (Already configured for regular messages)

### 2.2 Verify Webhook

The webhook endpoint will automatically verify with Meta when they send the verification request.

---

## Step 3: Deploy to Coolify

### 3.1 Push Code Changes

```bash
# Commit and push the changes
git add .
git commit -m "feat: Add WhatsApp Payments (Flows API) integration"
git push origin main
```

### 3.2 Deploy Services

1. **hans-ai-whatsapp** - Auto-deploys on push (if configured)
2. **hans-ai-subscriptions** - Auto-deploys on push (if configured)

### 3.3 Verify Environment Variables

After deployment, check that all environment variables are loaded:

```bash
# Check WhatsApp service
curl https://<whatsapp-service-url>/health/whatsapp-payments

# Expected response:
{
  "status": "enabled",
  "configured": true,
  "enabled": true,
  "payment_mode": "in_app_flow",
  "missing_vars": [],
  "configured_vars": {
    "WHATSAPP_PHONE_ID": "123456789",
    "WHATSAPP_WABA_ID": "987654321",
    ...
  }
}

# Check Subscriptions service
curl https://<subscriptions-service-url>/health/whatsapp-payments

# Expected response:
{
  "status": "configured",
  "configured": true,
  "missing_vars": [],
  ...
}
```

---

## Step 4: Testing

### 4.1 Test Plan Selection Flow

```
1. Send a WhatsApp message to your bot: "PAY"
2. Bot should reply with plan options (1, 2, 3...)
3. Reply with a number: "1"
4. Bot should send a WhatsApp Flow (interactive payment UI)
```

### 4.2 Test Payment Flow

```
1. Tap "Pay Now" button in WhatsApp
2. Payment screen opens inside WhatsApp
3. Complete test payment (use small amount like ₹1)
4. Check database for subscription creation
5. Send another message to verify access
```

### 4.3 Monitor Logs

```bash
# Check WhatsApp service logs
# In Coolify: Services > hans-ai-whatsapp > Logs

# Look for:
[WhatsApp Flow] Payment flow sent successfully
[Subscription] Access check for +91XXXXXX: active
```

---

## Step 5: Monitoring

### Health Check Endpoints

Add these to your monitoring system (UptimeRobot, Pingdom, etc.):

| Endpoint | Purpose | Alert If |
|----------|---------|----------|
| `https://<whatsapp-url>/health` | Service health | Returns 500 |
| `https://<whatsapp-url>/health/whatsapp-payments` | Payment config | `status: "incomplete"` |
| `https://<subscriptions-url>/health` | Subscriptions service | Returns 500 |
| `https://<subscriptions-url>/health/whatsapp-payments` | Webhook config | `status: "incomplete"` |

### Key Metrics to Monitor

1. **Payment Flow Success Rate** - Should be >95%
2. **Webhook Response Time** - Should be <2 seconds
3. **Subscription Creation Rate** - Track successful payments
4. **Fallback Rate** - How often it falls back to payment links (should be 0%)

---

## Fallback Behavior

If WhatsApp Payments is not configured or fails:

1. **System automatically falls back** to Razorpay Payment Links
2. **User experience**: Opens browser instead of in-app payment
3. **No data loss**: Same payment processing flow
4. **Automatic recovery**: When Flow is fixed, system uses it again

---

## Troubleshooting

### Issue: Flow not sending

**Check:**
```bash
curl https://<whatsapp-url>/health/whatsapp-payments
```

**Solution:**
- Verify all environment variables are set
- Check `WHATSAPP_FLOW_ID` is correct
- Ensure Flow is published in Meta Business Manager

### Issue: Webhook not receiving updates

**Check:**
1. Webhook URL is correct in Meta Business Manager
2. Verify token matches `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
3. Check firewall allows incoming requests

**Solution:**
- Re-configure webhook in Meta Business Manager
- Verify token matches exactly
- Check server logs for webhook verification attempts

### Issue: Subscription not created after payment

**Check:**
```bash
# Check subscriptions service logs
# Look for: [WhatsApp Webhook] Payment successful
```

**Solution:**
- Verify webhook is receiving events from Meta
- Check Razorpay webhook is also configured
- Test webhook endpoint directly

---

## Rollback Plan

If you need to rollback to payment links:

1. **Remove these env vars** (or set to empty):
   - `WHATSAPP_FLOW_ID`
   - `WHATSAPP_PAYMENT_CONFIG_ID`
   - `WHATSAPP_WABA_ID`
   - `WHATSAPP_PAYMENT_MID`

2. **Restart services**

3. **System automatically falls back** to payment links

---

## Security Notes

1. **Never commit** environment variables to git
2. **Use secure tokens** for webhook verification
3. **Rotate access tokens** periodically (Meta recommends every 6 months)
4. **Monitor webhook logs** for suspicious activity
5. **Rate limit** payment attempts (already implemented)

---

## Performance Considerations

- **WhatsApp Flow API** has rate limits: ~1000 requests/minute
- **Webhook timeout**: Meta retries if >5 seconds
- **Database indexes**: Ensure `userId` and `subscriptionId` are indexed
- **Connection pooling**: MongoDB connections are pooled automatically

---

## Support & Debugging

### Enable Debug Logging

```bash
# In Coolify, add to environment variables:
LOG_LEVEL=DEBUG
```

### Check Flow Status in Meta

1. Go to Meta Business Manager
2. WhatsApp > Flows
3. Check Flow status (should be "Published")
4. View Flow analytics (opens, conversions)

### Test Webhook Locally

```bash
# Test webhook verification
curl "https://<your-url>/payments/whatsapp-webhook?hub.mode=subscribe&hub.challenge=test&hub.verify_token=<your_token>"

# Should return: test
```

---

## Future Enhancements

- [ ] Add payment retry logic
- [ ] Track payment analytics
- [ ] Add refund handling
- [ ] Support multiple payment gateways
- [ ] Add payment reminders

---

## Deployment Checklist

- [ ] All environment variables added to Coolify
- [ ] Code pushed to repository
- [ ] Services deployed successfully
- [ ] Health checks passing
- [ ] Webhook configured in Meta Business Manager
- [ ] Test payment completed successfully
- [ ] Monitoring endpoints configured
- [ ] Team notified of new payment flow

---

**Deployment Date**: ___________

**Deployed By**: ___________

**Verified By**: ___________
