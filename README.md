# hans-ai-whatsapp

WhatsApp Webhook Handler for Hans AI Dashboard. Integrates Meta WhatsApp Cloud API with OpenClaw Gateway.

## Features

- Meta WhatsApp Cloud API integration
- Real-time message processing
- Media handling (images, audio, video, documents)
- Message queuing for reliability
- Rate limiting
- Webhook verification
- Health monitoring

## Quick Start

```bash
# Clone repository
git clone https://github.com/your-username/hans-ai-whatsapp.git
cd hans-ai-whatsapp

# Copy environment file
cp .env.example .env

# Edit .env with your Meta credentials
# - WHATSAPP_VERIFY_TOKEN
# - WHATSAPP_PHONE_ID
# - WHATSAPP_ACCESS_TOKEN
# - OPENCLAW_URL

# Run with Docker
docker-compose up -d

# Or run directly
pip install -r requirements.txt
uvicorn whatsapp_webhook:app --host 0.0.0.0 --port 8003
```

## Meta Business Setup

1. Go to [Meta Business Suite](https://business.facebook.com/wa-management)
2. Create WhatsApp Business Account
3. Create App with WhatsApp product
4. Get Phone ID and Access Token
5. Configure webhook

## Webhook Configuration

**Webhook URL:** `https://your-domain.com/webhook/whatsapp`

**Verify Token:** Use the value from `WHATSAPP_VERIFY_TOKEN`

**Subscribe to events:**
- `messages`

## API Endpoints

### Health Check
```
GET /health
```

### Verify Webhook (Meta calls this)
```
GET /webhook/whatsapp?hub.mode=subscribe&hub.verify_token=TOKEN&hub.challenge=CHALLENGE
```

### Receive Messages (Meta sends this)
```
POST /webhook/whatsapp
```

### Send Message
```
POST /send
Content-Type: application/json

{
  "to": "919999999999",
  "message": "Hello from Hans AI!"
}
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `WHATSAPP_VERIFY_TOKEN` | Yes | Token for webhook verification |
| `WHATSAPP_PHONE_ID` | Yes | Phone ID from Meta |
| `WHATSAPP_ACCESS_TOKEN` | Yes | Permanent access token |
| `OPENCLAW_URL` | Yes | OpenClaw Gateway URL |
| `MESSAGE_TIMEOUT` | No | Request timeout in seconds (default: 30) |
| `RATE_LIMIT_PER_MINUTE` | No | Rate limit (default: 60) |

## License

MIT License
