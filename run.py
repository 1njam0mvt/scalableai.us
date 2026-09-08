import os
import subprocess
import sys
from pathlib import Path
import uvicorn

def _ensure_thinking_audio():

    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.generate_thinking_audio"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path(__file__).parent),
        )

        if result.returncode != 0 and result.stderr:
            print(f"[startup] Thinking audio: {result.stderr.strip()}")

    except Exception as e:
        print(f"[startup] Thinking audio skipped: {e}")

def _validate_startup():

    # Returns True so callers can distinguish "validated OK" from "warned".
    ok = True

    from config import GROQ_API_KEY, CHATS_DATA_DIR, LEARNING_DATA_DIR
    if not GROQ_API_KEY or len(GROQ_API_KEY.strip()) < 10:
        print("[WARN] GROQ_API_KEY is missing or invalid. Chat will not work.")
        ok = False

    for name, d in (("CHATS_DATA_DIR", CHATS_DATA_DIR), ("LEARNING_DATA_DIR", LEARNING_DATA_DIR)):
        if not d.exists() or not d.is_dir():
            print(f"[WARN] {name} does not exist or is not writable.")
            ok = False

    return ok

if __name__ == "__main__":
    _validated_ok = _validate_startup()
    _ensure_thinking_audio()

    port = int(os.environ.get("PORT", 8000))
    is_production = os.environ.get("RENDER") == "true" or os.environ.get("ENV") == "production"

    # Defensive: PORT must be a sane integer, and must not be privileged
    # (binding low ports needs admin/root and will fail on Render/Windows).
    if not (1 <= port <= 65535):
        print(f"[ERROR] PORT={port} is out of range (1-65535). Falling back to 8000.")
        port = 8000
    elif port < 1024 and not is_production:
        print(f"[WARN] PORT={port} is a privileged port; may fail without admin rights.")

    try:
        # reload must be False in production (Render), and reload requires
        # import-string form "app.main:app" (not the app object) to work.
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=port,
            reload=not is_production,
        )
    except OSError as e:
        msg = str(e).lower()
        if "address already in use" in msg or "10048" in msg or "10013" in msg:
            print(f"[ERROR] Port {port} is already in use. Try another port or stop the other process.")
        else:
            print(f"[ERROR] Server failed to start: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Server stopped by user.")
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        sys.exit(1)