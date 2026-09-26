import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = PROJECT_ROOT / "frontend" / "audio"

STARTER_PHRASES = [
    ("starter_1", "One second sir I am updating your request."),
    ("starter_2", "Sure sir i am searching that if i found then i get back on it."),
    ("starter_3", "Got it sir, could you hold for a sec."),
    ("starter_4", "On my way sir, wait i got it."),
    ("starter_5", "Alright Sir, give me a sec."),
    ("starter_6", "Right Sir, one moment."),
    ("starter_7", "Okay sir, hold on while i am finding your query."),
    ("starter_8", "One second please sir, i will back to you."),
    ("starter_9", "Give me a moment for checking that sir."),
    ("starter_10", "Just a moment sir I am checking that could you wait for a second please."),
]

PHRASES = STARTER_PHRASES
VOICE = "en-GB-RyanNeural"
RATE = "+15%"

# The thinking/starter clips are rendered with the same custom "ScalableAI"
# ElevenLabs voice used as the app's primary TTS voice, so the "okay, hold
# on" pre-answer fillers sound identical to the spoken reply that follows.
# ElevenLabs needs an API key and charges per character, so if the key is
# missing or a request fails we fall back to the original free edge-tts
# rendering — an audible clip beats no clip (or a broken startup) either day.
try:
    from config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID
except ImportError:
    ELEVENLABS_API_KEY = None
    ELEVENLABS_VOICE_ID = None

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def generate_one_elevenlabs(text: str) -> bytes:
    """Render `text` with the ElevenLabs ScalableAI voice, return raw MP3 bytes.

    Mirrors app.main._generate_elevenlabs_sync() but kept standalone so this
    script never has to import app.main (which pulls in the entire FastAPI
    app just to synthesize a handful of one-liners at startup).
    """
    import requests

    if not ELEVENLABS_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")

    resp = requests.post(
        ELEVENLABS_TTS_URL.format(voice_id=ELEVENLABS_VOICE_ID),
        headers={"xi-api-key": ELEVENLABS_API_KEY, "Content-Type": "application/json"},
        json={
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=30,
    )
    if not resp.ok:
        # raise_for_status() alone only gives "401 Client Error: Unauthorized
        # for url: ..." — it drops the response body, which is exactly where
        # ElevenLabs puts the actual reason (invalid key, quota exceeded,
        # voice_id not found under this account, etc). Surfacing resp.text
        # here is the difference between "it failed" and knowing why.
        raise RuntimeError(f"ElevenLabs API error {resp.status_code}: {resp.text[:500]}")
    return resp.content


async def generate_one(name: str, text: str) -> bool:

    path = AUDIO_DIR / f"{name}.mp3"

    # Primary path: the ElevenLabs ScalableAI voice (runs the blocking HTTP
    # call in a worker thread so the event loop stays responsive).
    try:
        content = await asyncio.to_thread(generate_one_elevenlabs, text)
        path.write_bytes(content)
        print(f"  [OK] {name}.mp3 (elevenlabs)")
        return True
    except Exception as e:
        print(f"   [WARN] {name}.mp3 elevenlabs failed: {e} — falling back to edge-tts")

    # Fallback path: free edge-tts rendering, as before.
    try:
        import edge_tts

    except ImportError:
        print(f"   [FAIL] {name}.mp3: edge-tts not installed")
        return False

    try:
        communicate = edge_tts.Communicate(text, VOICE, rate=RATE)
        await communicate.save(str(path))
        print(f"  [OK] {name}.mp3 (edge-tts)")
        return True

    except Exception as e:
        print(f"   [FAIL] {name}.mp3: {e}")
        return False

async def main():

    try:
        import edge_tts

    except ImportError:
        print("edge-tts not installed .Run: pip install edge-tts")
        return 1

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    # Print what's actually configured before making any calls — a wrong or
    # mismatched key/voice pair (e.g. a valid API key from a different
    # ElevenLabs account than the one the custom voice was cloned under)
    # fails every request the same way, so this is the fastest way to rule
    # that class of bug in or out before reading further output.
    masked_key = f"{ELEVENLABS_API_KEY[:4]}...{ELEVENLABS_API_KEY[-4:]}" if ELEVENLABS_API_KEY else "(not set)"
    print(f"ELEVENLABS_API_KEY: {masked_key}")
    print(f"ELEVENLABS_VOICE_ID: {ELEVENLABS_VOICE_ID or '(not set)'}")

    for f in AUDIO_DIR.glob("followup_*.mp3"):

        try:
            f.unlink()
            print(f"  [REMOVED] {f.name}")

        except OSError:
            pass

    print(f"Generating thinking audio in {AUDIO_DIR}...")
    success = 0

    for name, text in PHRASES:
        if await generate_one(name, text):
            success += 1

    print(f"Done: {success}/{len(PHRASES)} files.")
    return 0 if success == len(PHRASES) else 1

if __name__ == "__main__":

    try:
        exit_code = asyncio.run(main())

    except KeyboardInterrupt:
        exit_code = 130

    sys.exit(exit_code)
