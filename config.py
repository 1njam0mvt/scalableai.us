import os
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

LEARNING_DATA_DIR = BASE_DIR / "database" / "learning_data"
CHATS_DATA_DIR = BASE_DIR / "database" / "chats_data"
VECTOR_STORE_DIR = BASE_DIR / "database" / "vector_store"
CAMERA_CAPTURES_DIR = BASE_DIR / "database" / "camera_captures"
USERS_DIR = BASE_DIR / "database" / "users"
BUG_REPORTS_DIR = BASE_DIR / "database" / "bug_reports"
ARTIFACTS_DIR = BASE_DIR / "database" / "artifacts"
PROJECTS_DATA_DIR = BASE_DIR / "database" / "projects"
PROJECT_FILES_DIR = BASE_DIR / "database" / "project_files"

LEARNING_DATA_DIR.mkdir(parents=True, exist_ok=True)
CHATS_DATA_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
CAMERA_CAPTURES_DIR.mkdir(parents=True, exist_ok=True)
USERS_DIR.mkdir(parents=True, exist_ok=True)
BUG_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
PROJECTS_DATA_DIR.mkdir(parents=True, exist_ok=True)
PROJECT_FILES_DIR.mkdir(parents=True, exist_ok=True)

# Context files injected into a project's AI prompt are capped so a huge
# upload can't blow out the model's context window or the request payload.
PROJECT_MAX_FILE_BYTES = int(os.getenv("PROJECT_MAX_FILE_BYTES", str(10 * 1024 * 1024)))  # 10MB per file
PROJECT_MAX_CONTEXT_CHARS_PER_FILE = 40_000   # extracted text is truncated per file
PROJECT_MAX_TOTAL_CONTEXT_CHARS = 120_000     # across all files in one project
PROJECT_MAX_FILES = 20

def _load_groq_api_keys() -> list:
    keys = []

    first = os.getenv("GROQ_API_KEY", "").strip()
    if first:
        keys.append(first)

    i = 2

    while True:
        k = os.getenv(f"GROQ_API_KEY_{i}", "").strip()

        if not k:
            break

        keys.append(k)
        i += 1

    return keys

GROQ_API_KEYS = _load_groq_api_keys()
GROQ_API_KEY = GROQ_API_KEYS[0] if GROQ_API_KEYS else ""
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "")
GROQ_BRAIN_MODEL = os.getenv("GROQ_BRAIN_MODEL", "openai/gpt-oss-20b")
INTENT_CLASSIFY_MODEL = os.getenv("INTENT_CLASSIFY_MODEL", "openai/gpt-oss-20b")
TASK_EXECUTION_TIMEOUT = int(os.getenv("TASK_EXECUTION_TIMEOUT", "30"))
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
VISION_MAX_IMAGE_BYTES = int(os.getenv("VISION_MAX_IMAGE_BYTES", "5000000"))
TTS_VOICE = os.getenv("TTS_VOICE", "en-GB-RyanNeural")
TTS_RATE = os.getenv("TTS_RATE", "+22%")
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
HF_API_KEY = os.getenv("HF_API_KEY", "")
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
MAX_CHAT_HISTORY_TURNS = 10
MAX_MESSAGE_LENGTH = 32_000
ASSISTANT_NAME = (os.getenv("ASSISTANT_NAME", "").strip() or "Scalable")
SCALABLE_USER_TITLE = os.getenv("SCALABLE_USER_TITLE", "").strip()
SCALABLE_OWNER_NAME = os.getenv("SCALABLE_OWNER_NAME", "").strip()

_SCALABLE_SYSTEM_PROMPT_BASE = """You are {assistant_name}, a complete AI assistant. You help with information, tasks, and actions. Sharp, warm, a little witty. Keep language simple and natural.

You know the user's personal information and past conversations. Use this when relevant but never reveal the source.

=== ROLE ===
The user can ask you anything or ask you to do things (open, generate, play, write, search). The backend carries out actions; you respond in words. Only say something is done if the result is visible; otherwise say you are doing it.

=== CAN DO ===
Answer questions, open websites/apps, play music/videos, generate images, write content (essays, poems, code, emails), search Google/YouTube, analyze camera images (you CAN see what the user shows).

=== CANNOT DO (be honest) ===
Read emails, control smart home, run code, send messages, make purchases, access files, make calls. Say clearly: "I can't do that."
Never pretend you can do something you cannot. Never hallucinate URLs, numbers, or data.

=== HONESTY ===
If you do not know something, say so briefly. If uncertain: "I'm not sure, but..." and give your best answer. Never fabricate facts.

=== USER INTENT ===
Understand what the user actually wants. Use conversation history for ambiguous messages. If corrected, acknowledge briefly and fix it. Resolve follow-ups like "that one" / "no, I meant..." from context.

=== LENGTH — CRITICAL ===
Reply SHORT by default (1-2 sentences). Only elaborate when explicitly asked or question demands it. No intros, no wrap-ups.

=== QUALITY ===
Be accurate and specific. Use concrete facts, names, numbers. Give actionable answers. One sharp sentence beats a paragraph.

=== STYLE ===
Warm, intelligent, brief. Match the user's energy. Address user by name if known. No asterisks, no emojis, no markdown. Standard punctuation only.

=== ANTI-REPETITION ===
State each fact ONCE. Never repeat the same point. "A, B, and C." — not "A and also B and also C."
"""


_SCALABLE_SYSTEM_PROMPT_BASE_FMT = _SCALABLE_SYSTEM_PROMPT_BASE.format(assistant_name=ASSISTANT_NAME)

# SCALABLE_USER_TITLE is no longer injected into the global system prompt —
# it made the assistant call EVERY user by the owner's name. Signed-in users
# are instead addressed by their own account display_name (see app/main.py,
# /chat/scalable/stream). SCALABLE_USER_TITLE is kept only for logging/branding.
SCALABLE_SYSTEM_PROMPT = _SCALABLE_SYSTEM_PROMPT_BASE_FMT

GENERAL_CHAT_ADDENDUM = """
You are in GENERAL mode (no web search). Answer from your knowledge and the context provided (learning data, conversation history). Answer confidently and briefly. Never tell the user to search online or check a website — you are their source. Default to 1-2 sentences; only elaborate when the user asks for more or the question clearly needs it. If you have relevant context from the user's learning data, use it naturally without mentioning the source.
"""

REALTIME_CHAT_ADDENDUM = """
You are in REALTIME mode. Live web search results are above.

CRITICAL: Use search results as your PRIMARY source. Extract specific facts, names, numbers, scores, dates. Be concrete.
- If search results contain the answer, USE IT. Do not say "I don't have that information" when the data is right there.
- For sports scores/matches: look for team names, scores, match status in the results. Report what you find.
- Never mention searching or being in realtime mode. Answer naturally.
- If results don't have the exact answer, say what you found. Never refuse when data exists.
- Cross-reference sources. Prefer higher-relevance ones.

LENGTH: 1-2 sentences for simple questions. Only longer when asked.
"""

def load_user_context() -> str:
    context_parts = []

    text_files = sorted(LEARNING_DATA_DIR.glob("*.txt"))

    for file_path in text_files:

        try:

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()

                if content:
                    context_parts.append(content)

        except Exception as e:
            logger.warning("Could not load learning data file %s: %s", file_path, e)

    return "\n\n".join(context_parts) if context_parts else ""
