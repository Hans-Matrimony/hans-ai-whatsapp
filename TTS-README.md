# Edge TTS Integration for Test Number

## 🎯 Overview

This integration adds **Text-to-Speech (TTS)** functionality using **Edge TTS (100% FREE)**.

**Currently Enabled ONLY For:** Test number `8534823036`

---

## 🚀 Installation

### Step 1: Install Edge TTS
```bash
pip install edge-tts
```

Or add to your requirements:
```txt
edge-tts>=6.1.0
```

### Step 2: Deploy Changes
The TTS feature is already integrated in `app/services/tasks.py`.

---

## 📝 How It Works

### Flow:
```
User sends message → AI generates response → Check if test number → Generate audio → Send confirmation
```

### Test Number Filter:
- **Only works for:** `8534823036` (with or without +)
- **All other numbers:** Normal text response (no audio)

### Language Detection:
- Automatically detects Hindi/English from response
- Uses appropriate Edge TTS voice:
  - Hindi: `hi-IN-SwaraNeural` (Female voice)
  - English: `en-IN-NeerajNeural` (Indian English male voice)

---

## 📊 Current Status

**For Test Number (8534823036):**
- ✅ Audio generation enabled
- ✅ Language auto-detection
- ✅ Edge TTS integration
- ✅ Confirmation message sent

**For All Other Numbers:**
- ❌ Audio generation disabled
- ✅ Normal text response works

---

## 🎵 Audio Messages

The system generates audio using Edge TTS and saves it to a temporary file.
Currently, it sends a **confirmation message** with:
- Audio size in bytes
- Detected language
- File path

### Example Confirmation:
```
🎤 [TTS TEST] Audio generated (12345 bytes, language: hi)

File: /tmp/audio_8534823036_abc123_20250119_123456.mp3
```

---

## 🔧 Files Modified

1. **skills/audio-processor/text_to_speech_edge.py** (NEW)
   - Edge TTS implementation
   - Phone number filtering
   - Language detection
   - Audio generation

2. **skills/audio-processor/__init__.py** (UPDATED)
   - Exports Edge TTS functions

3. **skills/audio-processor/requirements.txt** (UPDATED)
   - Added edge-tts dependency

4. **app/services/tasks.py** (UPDATED)
   - Integrated TTS for test number
   - Added phone number check
   - Audio generation on response

---

## 🎯 Next Steps

### Option 1: Keep Test Only
Continue testing with test number only.

### Option 2: Enable for All Users
1. Remove phone number filter in `tasks.py`
2. Upload audio to cloud storage (S3/GCS)
3. Send audio via WhatsApp API
4. Add user preference (audio on/off)

### Option 3: Google WaveNet Upgrade
If Edge TTS quality is not good enough:
1. Use existing `text_to_speech.py` (Google WaveNet)
2. Cost: ~₹0.007 per message
3. Much more realistic voices

---

## 💰 Cost Comparison

| Service | Quality | Cost | Monthly (10K msgs) |
|---------|---------|------|-------------------|
| **Edge TTS** | ⭐⭐⭐ (Good) | FREE | ₹0 |
| **Google WaveNet** | ⭐⭐⭐⭐⭐ (Excellent) | ~₹0.007/msg | ₹70 |
| **OpenAI TTS** | ⭐⭐⭐⭐⭐ (Very Real) | ~₹0.025/msg | ₹250 |

---

## 🧪 Testing

### Test with Test Number:
```
Send any message to: +918534823036
Expected:
1. Normal AI text response
2. Audio generation confirmation
3. Audio file saved to /tmp/
```

### Test with Other Numbers:
```
Send message to any other number
Expected: Normal AI text response (no audio)
```

---

## 📝 Logs

Look for these logs in your system:
```
[TTS] Test number detected, generating audio response...
[TTS] Audio generated successfully: 12345 bytes
[TTS] Test number +918534823036: Audio generation confirmed
```

---

## 🎉 Ready to Test!

The TTS integration is **live and working** for test number `8534823036`!

Send a message to test it out! 🎤✨
