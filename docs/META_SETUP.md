# Meta WhatsApp Business API Setup Guide

## Prerequisites

- Facebook Business Account
- Meta Business Suite access
- WhatsApp Business App

## Step 1: Create Meta Business Account

1. Go to [Meta Business Suite](https://business.facebook.com/)
2. Create a new business account
3. Complete business verification (optional but recommended)

## Step 2: Create WhatsApp Business Account

1. In Business Suite, go to "Asset Hub"
2. Click "WhatsApp" → "Get Started"
3. Create your WhatsApp Business Account
4. Add a phone number (special or regular)

## Step 3: Create App

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create a new app
3. Select "Business" type
4. Add "WhatsApp Cloud API" product

## Step 4: Get Credentials

1. Go to your app → WhatsApp → Configuration
2. Note down:
   - Phone Number ID
   - Business Account ID
   - Access Token (select "Never expire")

## Step 5: Configure Webhook

1. In WhatsApp API settings, find "Webhooks"
2. Add webhook URL: `https://your-domain.com/webhook/whatsapp`
3. Enter verify token (use same as WHATSAPP_VERIFY_TOKEN)
4. Subscribe to `messages` event

## Test Webhook

```bash
curl "https://your-domain.com/webhook/whatsapp?hub.mode=subscribe&hub.verify_token=YOUR_TOKEN&hub.challenge=test"
```

Should return: `test`
