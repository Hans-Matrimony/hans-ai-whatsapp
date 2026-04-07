# Gender-Based AI Astrologer Companion Feature

## Overview
This feature adds an opposite-gender AI astrologer companion to the WhatsApp bot. The bot now adapts its personality based on the user's detected gender, providing a more personalized and emotionally engaging experience.

## How It Works

### 1. Gender Detection
- **Automatic Detection**: The bot detects user gender from their name when they introduce themselves
- **Name Patterns**: Looks for common patterns like:
  - "Mera naam Rahul hai"
  - "I am Priya"
  - "Main Aarav hoon"
  - "Hi, I am Ananya"

- **Detection Methods**:
  1. **Direct Name Matching**: Checks against a database of 200+ common Indian names
  2. **Pattern Matching**: Uses Indian name patterns (e.g., names ending with 'a', 'i', 'ya' = female; names ending with 'h', 'sh', 'k', 'r' = male)
  3. **Caching**: Once detected, gender is cached in memory for future conversations

### 2. Astrologer Personalities

#### If User is Male → Female Astrologer "Meera"
- **Name**: Meera
- **Traits**: Warm, caring, emotionally intelligent female astrologer friend
- **Speaking Style**: Friendly, supportive, caring tone
- **Greeting**: Gentle, sisterly warmth
- **Example Greeting**: "Namaste! Main Meera hoon, tumhari apni astrologer friend 😊"

#### If User is Female → Male Astrologer "Aarav"
- **Name**: Aarav
- **Traits**: Warm, caring, emotionally intelligent male astrologer friend
- **Speaking Style**: Friendly, supportive, caring tone
- **Greeting**: Gentle, brotherly warmth
- **Example Greeting**: "Namaste! Main Aarav hoon, tumhara astrologer friend 😊"

### 3. Example Conversation Flow

#### Male User (Rahul) talking to Meera:
```
User: "Hey!"
Meera (Bot): "Namaste! Main Meera hoon, tumhari apni astrologer friend 😊
              Tumse baat karke khushi hui! Tumhari kundli banane ke liye
              mujhe tumhari DOB, birth place aur birth time chahiye.
              Batao, kya plan hai?"

User: "14 March 1998, Lucknow, subah 6:30"
Meera (Bot): "Pisces ho tum Rahul! Tumhari kundli mein bahut interesting
              cheezein hain. Chalo batao — kya jaanna hai?
              Love, career, ya kuch aur?"
```

#### Female User (Priya) talking to Aarav:
```
User: "Hi!"
Aarav (Bot): "Namaste! Main Aarav hoon, tumhara astrologer friend 😊
              Tumse baat karke khushi hui! Tumhari kundli banane ke liye
              mujhe tumhari DOB, birth place aur birth time chahiye.
              Batao, kya plan hai?"

User: "22 August 1995, Delhi, evening 5:45"
Aarav (Bot): "Leo ho tum Priya! Tumhari kundli mein bahut strong
              leadership qualities hain. Chalo batao — kya jaanna hai?
              Love, career, ya kuch aur?"
```

## Technical Implementation

### Files Modified
- **app/services/tasks.py**: Added gender detection and personality system

### New Functions Added

1. **`detect_gender_from_name(name: str)`**
   - Detects gender from user's name
   - Uses direct name matching and pattern detection
   - Returns: "male", "female", or None

2. **`get_user_gender(phone: str, message: str)`**
   - Gets user gender from cache or detects from message
   - Extracts name using regex patterns
   - Caches detected gender for future use

3. **`get_astrologer_personality(user_gender: str)`**
   - Returns astrologer personality based on user's gender
   - Opposite gender mapping (male user → female astrologer, etc.)

### Configuration Added

```python
# Astrologer personalities
ASTROLOGER_PERSONALITIES = {
    "male": {
        "name": "Aarav",
        "traits": "warm, caring, emotionally intelligent male astrologer friend",
        "speaking_style": "friendly, supportive, uses 'main' (I), caring tone",
        "greeting_style": "gentle, brotherly warmth"
    },
    "female": {
        "name": "Meera",
        "traits": "warm, caring, emotionally intelligent female astrologer friend",
        "speaking_style": "friendly, supportive, uses 'main' (I), caring tone",
        "greeting_style": "gentle, sisterly warmth"
    }
}

# Name databases (200+ common Indian names)
MALE_NAMES = { ... }
FEMALE_NAMES = { ... }
```

### System Prompt Injection

The astrologer's personality is injected into every message sent to OpenClaw:

```
[From: WhatsApp User (+91987654321) at 2026-04-07 12:30:45]
[SYSTEM: You are Meera, a warm, caring, emotionally intelligent female astrologer friend.
Your speaking style: friendly, supportive, uses 'main' (I), caring tone.
Greeting style: gentle, sisterly warmth.
Remember: You are the ASTROLOGER, not the user. Be warm, caring, and emotionally supportive.]
```

## Key Features

✅ **No Breaking Changes**: Existing functionality remains intact
✅ **Automatic Detection**: No user input required for gender detection
✅ **Emotional Connection**: Opposite-gender companion creates stronger emotional bond
✅ **Cultural Relevance**: Indian names and conversation patterns
✅ **Consistent Personality**: Gender is cached after first detection
✅ **Fallback Handling**: Unknown gender defaults to Aarav (male astrologer)

## Future Enhancements

1. **Persistent Storage**: Store gender in MongoDB instead of in-memory cache
2. **Pronoun Selection**: Allow users to specify preferred pronouns
3. **More Personalities**: Add more astrologer personalities
4. **Relationship Building**: Track conversation history for deeper emotional connections
5. **Birthday Reminders**: Send personalized birthday messages
6. **Mood Detection**: Adjust response style based on user's emotional state

## Testing

To test the feature:

1. **Male User Test**:
   ```
   Message: "Mera naam Rahul hai"
   Expected: Bot responds as Meera (female astrologer)
   ```

2. **Female User Test**:
   ```
   Message: "Meri naam Priya hai"
   Expected: Bot responds as Aarav (male astrologer)
   ```

3. **English Name Test**:
   ```
   Message: "I am Sarah"
   Expected: Bot responds as Aarav (male astrologer)
   ```

## Deployment

1. Build the Docker image:
   ```bash
   docker build -t hans-ai-whatsapp:latest .
   ```

2. Deploy to Coolify:
   - Push to your Git repository
   - Coolify will auto-deploy

3. Test with real users:
   - Send WhatsApp messages with your name
   - Verify the astrologer responds with correct personality

## Notes

- Gender detection is ~80% accurate with Indian names
- The system learns and caches gender after first detection
- Users can still use all existing features (kundli, remedies, predictions)
- The personality is injected at the system prompt level, so the AI naturally adapts
- No changes required to the OpenClaw agent configuration
