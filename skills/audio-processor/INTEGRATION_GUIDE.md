# 🎧 Audio-to-Audio Integration for WhatsApp Bot

## ✅ Files Created:

```
skills/audio-processor/
├── __init__.py
├── transcribe.py         # Groq audio transcription (FREE)
├── text_to_speech.py     # Google Cloud TTS (FREE tier)
├── audio_handler.py       # Main coordinator
└── requirements.txt
```

---

## 🔧 Step 1: Install Dependencies

```bash
cd skills/audio-processor
pip install -r requirements.txt
pip install google-cloud-texttospeech
```

---

## 🔑 Step 2: Set Environment Variables

Add to your `.env` file or Coolify environment:

```bash
# For Groq Transcription (FREE)
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# For Google Cloud TTS (FREE tier)
# Download service account JSON from Google Cloud Console
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

### Get Groq API Key (FREE):
1. Go to: https://console.groq.com
2. Sign up/login (free)
3. Go to: API Keys
4. Create new API key
5. Copy key

### Get Google Cloud Service Account:
1. Go to: https://console.cloud.google.com
2. Create new project (or use existing)
3. Go to: Text-to-Speech API
4. Enable API
5. Go to: IAM & Admin → Service Accounts
6. Create service account
7. Download JSON key
8. Save to project (not git!)
9. Set path in GOOGLE_APPLICATION_CREDENTIALS

---

## 📝 Step 3: Update tasks.py

Add audio handling in `app/services/tasks.py`:

```python
# Add after imports
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '../../skills'))
from audio_processor import transcribe_audio, is_audio_message, audio_handler
```

### Then add audio message handling:

```python
# In _process_message_async function

# Check if message is audio
if message_type in ["audio", "voice"]:
    logger.info(f"[Audio] Received audio message from {phone}")

    # Check if user wants audio response
    # For now, transcribe and give text response
    # If you want audio response, use: process_audio_message

    if not media_info or not media_info.get("base64_data"):
        logger.error("[Audio] No audio data found")
        return {"error": "No audio data"}

    # Transcribe audio
    transcribed = await transcribe_audio(
        media_info["base64_data"],
        media_info.get("mime_type", "audio/ogg")
    )

    if transcribed:
        logger.info(f"[Audio] Transcribed: {transcribed}")
        # Replace original message with transcription
        message = transcribed
    else:
        logger.warning("[Audio] Transcription failed, using as-is")
        # Continue with empty message if transcription fails
        message = ""
```

---

## 🎵 Step 4: For Complete Audio-to-Audio Response

If you want to send AUDIO replies (not just transcribe):

```python
# After getting OpenClaw text response
if should_send_audio_response(phone, user_id):
    # Check if we should send audio (based on user preference)
    # For now, let's say: if user sent audio, send audio back

    logger.info("[Audio] Generating audio response...")

    # Convert AI response to audio
    audio_result = await audio_handler.process_audio_message(
        phone=phone,
        audio_bytes=media_info["base64_data"],
        mime_type=media_info.get("mime_type", "audio/ogg"),
        openclaw_response_text=final_response
    )

    if audio_result["success"]:
        # Upload audio and send via WhatsApp
        audio_url = await upload_audio_to_storage(audio_result["audio_file"])
        await send_whatsapp_audio(phone, audio_url)

        return {
            "status": "audio_sent",
            "audio_url": audio_url
        }
```

---

## 🧪 Testing

### Test 1: Transcription Only
```python
from audio_processor import transcribe_audio

# Load audio file
with open("test_audio.ogg", "rb") as f:
    audio_bytes = f.read()

# Transcribe
text = await transcribe_audio(audio_bytes, "audio/ogg")
print(f"Transcribed: {text}")
```

### Test 2: TTS Only
```python
from audio_processor import text_to_speech

audio_bytes = text_to_speech("Namaste, kaise hain aap?", "hi")

# Save to file
with open("output.mp3", "wb") as f:
    f.write(audio_bytes)

print("Audio saved!")
```

### Test 3: Complete Flow
```python
from audio_handler import process_audio_message

# Load audio
with open("test.ogg", "rb") as f:
    audio_bytes = f.read()

# Process
result = await process_audio_message(
    phone="+919876543210",
    audio_bytes=audio_bytes,
    mime_type="audio/ogg",
    openclaw_response_text="Aapka kundli bahut achha hai."
)
```

---

## 📊 Flow Summary

### Input Flow:
```
User sends voice note on WhatsApp
    ↓
WhatsApp webhook receives
    ↓
Download audio data
    ↓
Transcribe using Groq (FREE)
    ↓
Process with OpenClaw AI
    ↓
Convert response to audio using Google TTS (FREE)
    ↓
Upload audio to public URL
    ↓
Send via WhatsApp
    ↓
User receives audio reply! 🎧
```

---

## 🎯 Configuration Options

### Option 1: Audio Input Always, Text Output
- User sends audio → Transcribe → Text response
- User sends text → Text response
- **Simplest to implement**

### Option 2: Audio Input, Text Output (Current)
- User sends audio → Transcribe → Text response
- No audio reply (just text)

### Option 3: Audio Input, Audio Output (Full)
- User sends audio → Transcribe → AI → Audio response
- User sends text → Text response
- **Best user experience**

### Option 4: User Preference
- First time: ask preference
- Remember for future messages
- Can change anytime

---

## 💡 Next Steps

1. ✅ Files created
2. ⏳ Install dependencies
3. ⏳ Set API keys
4. ⏳ Integrate into tasks.py
5. ⏳ Test with audio messages
6. ⏳ Deploy

**Ready for integration!** 🎧✨
