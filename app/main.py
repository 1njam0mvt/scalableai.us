from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse, RedirectResponse, Response, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from contextlib import asynccontextmanager
import uvicorn
import logging
import json
import time
import re
import os
import base64
import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import edge_tts
from typing import Optional
from pydantic import BaseModel, Field
import secrets
from collections import defaultdict
from app.models import (
    ChatRequest, ChatResponse, TTSRequest, SignupRequest, LoginRequest, AuthResponse,
    BugReportRequest, ChangePasswordRequest, DeleteAccountRequest,
    Project, ProjectFile, CreateProjectRequest, UpdateProjectRequest,
    UpdateProjectInstructionsRequest, AddProjectTextContentRequest,
    Personalization,
)

RATE_LIMIT_MESSAGE = (
    "You've reached your daily API limit for this assistant. "
    "Your credits will reset in a few hours, or you can upgrade your plan for more. "
    "Please try again later."
)

def _is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in str(exc) or "rate limit" in msg or "tokens per day" in msg

from app.services.vector_store import VectorStoreService
from app.services.groq_service import GroqService, AllGroqApisFailedError
from app.services.realtime_service import RealtimeGroqService
from app.services.chat_service import ChatService
from app.services.brain_service import BrainService
from app.services.task_executor import TaskExecutor
from app.services.vision_service import VisionService
from app.services.task_manager import TaskManager
from app.services.finance_service import FinanceService
from app.services.auth_service import AuthService, AuthError
from app.services.project_service import ProjectService, ProjectError
from app.services.file_parser import extract_text as extract_file_text

from config import (
    VECTOR_STORE_DIR, GROQ_API_KEYS, GROQ_MODEL, TAVILY_API_KEY,
    EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, MAX_CHAT_HISTORY_TURNS,
    ASSISTANT_NAME, TTS_VOICE, TTS_RATE, BUG_REPORTS_DIR,
    PROJECT_MAX_FILE_BYTES, PROJECT_MAX_FILES, PROJECT_MAX_CONTEXT_CHARS_PER_FILE,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("SCALABLE")
vector_store_service: VectorStoreService = None
groq_service: GroqService = None
realtime_service: RealtimeGroqService = None
brain_service: BrainService = None
task_executor: TaskExecutor = None
task_manager: TaskManager = None
vision_service: VisionService = None
chat_service: ChatService = None
finance_service: FinanceService = None
auth_service: AuthService = None
project_service: ProjectService = None

def print_title():

    title = """

   ╔══════════════════════════════════════════════════════════════════╗
   ║                                                                  ║
   ║  ███████╗ ██████╗ █████╗ ██╗      █████╗ ██████╗ ██╗     ███████╗║
   ║  ██╔════╝██╔════╝██╔══██╗██║     ██╔══██╗██╔══██╗██║     ██╔════╝║
   ║  ███████╗██║     ███████║██║     ███████║██████╔╝██║     █████╗  ║
   ║  ╚════██║██║     ██╔══██║██║     ██╔══██║██╔══██╗██║     ██╔══╝  ║
   ║  ███████║╚██████╗██║  ██║███████╗██║  ██║██████╔╝███████╗███████╗║
   ║  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═════╝ ╚══════╝╚══════╝║
   ║                                                                  ║
   ║          Just A Rather Very Intelligent System                   ║
   ║                                                                  ║
   ╚══════════════════════════════════════════════════════════════════╝

    """
    print(title)

@asynccontextmanager

async def lifespan(app: FastAPI):

    global vector_store_service, groq_service, realtime_service, brain_service
    global task_executor, task_manager, vision_service, chat_service, finance_service, auth_service, project_service
    print_title()
    logger.info("=" * 60)
    logger.info("SCALABLE - Starting Up...")
    logger.info("=" * 60)
    logger.info("[CONFIG] Assistant name: %s", ASSISTANT_NAME)
    logger.info("[CONFIG] Groq model: %s", GROQ_MODEL)
    logger.info("[CONFIG] Groq API keys loaded: %d", len(GROQ_API_KEYS))
    logger.info("[CONFIG] Tavily API key: %s", "configured" if TAVILY_API_KEY else "NOT SET")
    logger.info("[CONFIG] Image generation: Pollinations.ai (free, no API key)")
    logger.info("[CONFIG] Embedding model: %s", EMBEDDING_MODEL)
    logger.info("[CONFIG] Chunk size: %d | Overlap: %d | Max history turns: %d",
                CHUNK_SIZE, CHUNK_OVERLAP, MAX_CHAT_HISTORY_TURNS)

    try:

        logger.info("Initializing vector store service...")
        t0 = time.perf_counter()

        try:
            vector_store_service = VectorStoreService()
            vector_store_service.create_vector_store()
            logger.info("[TIMING] startup_vector_store: %.3fs", time.perf_counter() - t0)

        except Exception as vs_err:
            logger.error(
                "Vector store initialization failed (%.3fs): %s. "
                "Continuing WITHOUT memory/learning-data retrieval — chat, vision, tasks, "
                "and auth are unaffected. Common cause: no internet access to huggingface.co "
                "to download the embedding model on first run.",
                time.perf_counter() - t0, vs_err, exc_info=True,
            )
            vector_store_service = None

        logger.info("Initializing Groq service (general queries)...")
        groq_service = GroqService(vector_store_service)
        logger.info("Groq service initialized successfully")
        logger.info("Initializing Realtime Groq service (with Tavily search)...")
        realtime_service = RealtimeGroqService(vector_store_service)
        logger.info("Realtime Groq service initialized successfully")
        logger.info("Initializing Brain service (Groq query classification)...")
        brain_service = BrainService(groq_service=groq_service)
        logger.info("Brain service initialized successfully")
        logger.info("Initializing Task executor...")
        task_executor = TaskExecutor(groq_service=groq_service)
        logger.info("Task executor initialized successfully")
        logger.info("Initializing Background task manager...")
        task_manager = TaskManager(task_executor=task_executor)
        logger.info("Background task manager initialized successfully")
        logger.info("Initializing Vision service (Groq)...")
        vision_service = VisionService()
        logger.info("Vision service initialized successfully")
        logger.info("Initializing Finance service (FMP)...")
        finance_service = FinanceService()
        logger.info("Finance service initialized successfully")
        logger.info("Initializing Auth service...")
        auth_service = AuthService()
        logger.info("Auth service initialized successfully")
        logger.info("Initializing Project service...")
        project_service = ProjectService()
        logger.info("Project service initialized successfully")
        logger.info("Initializing chat service...")

        chat_service = ChatService(
            groq_service, realtime_service, brain_service,
            task_executor=task_executor,
            vision_service=vision_service,
            task_manager=task_manager,
            project_service=project_service,
        )

        logger.info("Chat service initialized successfully")
        logger.info("=" * 60)
        logger.info("Service Status:")
        logger.info("  - Vector Store: %s", "Ready" if vector_store_service else "UNAVAILABLE (memory/learning-data disabled)")
        logger.info("  - Groq AI (General): Ready")
        logger.info("  - Groq AI (Realtime): Ready")
        logger.info("  - Brain (Unified Decision): Ready")
        logger.info("  - Task Executor: Ready")
        logger.info("  - Background Task Manager: Ready")
        logger.info("  - Vision (Groq): Ready")
        logger.info("  - Chat Service: Ready")
        logger.info("=" * 60)
        logger.info("SCALABLE is online and ready!")
        logger.info("API: http://localhost:8000")
        logger.info("Frontend: http://localhost:8000/app/ (open in browser)")
        logger.info("=" * 60)

        yield

        logger.info("\nShutting down SCALABLE...")
        _tts_pool.shutdown(wait=True)

        if task_manager:
            task_manager.shutdown()

        if chat_service:
            for session_id in list(chat_service.sessions.keys()):
                chat_service.save_chat_session(session_id)

        logger.info("All sessions saved. Goodbye!")

    except Exception as e:
        logger.error(f"Fatal error during startup: {e}", exc_info=True)
        raise

app = FastAPI(
    title="SCALABLE API",
    description="Just A Rather Very Intelligent System",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - t0
        path = request.url.path
        logger.info("[REQUEST] %s %s -> %s (%.3fs)", request.method, path, response.status_code, elapsed)
        return response

app.add_middleware(TimingMiddleware)

@app.get("/api")

async def api_info():
    return {
        "message": "SCALABLE API",
        "endpoints": {
            "/chat": "General chat (non-streaming)",
            "/chat/stream": "General chat (streaming chunks)",
            "/chat/realtime": "Realtime chat (non-streaming)",
            "/chat/realtime/stream": "Realtime chat (streaming chunks)",
            "/chat/scalable/stream": "Scalable unified route (two-stage brain: classify -> route -> execute/stream)",
            "/chat/history/{session_id}": "Get chat history",
            "/tasks/{task_id}": "Get background task status and result",
            "/health": "System health check",
            "/tts": "Text-to-speech (POST text, returns streamed MP3)"
        }
    }

@app.get("/health")

async def health():
    try:
        return {
            "status": "healthy",
            "vector_store": vector_store_service is not None,
            "groq_service": groq_service is not None,
            "realtime_service": realtime_service is not None,
            "brain_service": brain_service is not None,
            "task_executor": task_executor is not None,
            "task_manager": task_manager is not None,
            "vision_service": vision_service is not None,
            "chat_service": chat_service is not None,
            "finance_service": finance_service is not None
        }

    except Exception as e:
        logger.warning("[API /health] Error: %s", e)
        return {"status": "degraded", "error": str(e)}

_discover_pool = ThreadPoolExecutor(max_workers=4)

DISCOVER_TOPIC_QUERIES = {
    "discover": ["trending news today"],
    "finance": ["stock market news today", "global economy news today"],
    "academic": ["latest scientific research breakthroughs", "new academic research findings"],
    "health": ["latest health news today", "new medical research findings"],
}

def get_bearer_token(authorization: Optional[str] = Header(default=None)) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()

def require_auth(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: returns the authenticated username, or raises 401."""
    token = get_bearer_token(authorization)

    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    username = auth_service.get_username_for_token(token)

    if not username:
        raise HTTPException(status_code=401, detail="Not authenticated")

    return username

# ---- Guest chat access (unauthenticated visitors on the homepage) ----
# Deliberately narrow: this does NOT touch require_auth or any of its other
# call sites, does NOT create a real user record in auth_service/the user
# database, and only grants access to the one chat-streaming endpoint below.
# Everything else (settings, projects, artifacts, account deletion, chat
# history listing) still requires a genuine account via require_auth exactly
# as before.
import hmac
import hashlib

GUEST_TOKEN_PREFIX = "guest_"
GUEST_USERNAME_PREFIX = "__guest_"
GUEST_MAX_MESSAGES = 5
_guest_message_counts: dict = defaultdict(int)  # keyed by guest_id -> message count this process lifetime

def _guest_secret() -> bytes:
    # Falls back to the auth service's own secret if it exposes one, else a
    # process-local secret is fine here: guest tokens are short-lived, low
    # value (chat-only, capped, no persisted data tied to them), and don't
    # need to survive a server restart.
    return (os.getenv("GUEST_TOKEN_SECRET") or "scalable-guest-preview").encode("utf-8")

def _sign_guest_id(guest_id: str) -> str:
    sig = hmac.new(_guest_secret(), guest_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    return f"{GUEST_TOKEN_PREFIX}{guest_id}.{sig}"

def _verify_guest_token(token: str) -> Optional[str]:
    if not token.startswith(GUEST_TOKEN_PREFIX):
        return None
    body = token[len(GUEST_TOKEN_PREFIX):]
    if "." not in body:
        return None
    guest_id, _, sig = body.rpartition(".")
    if not guest_id or not sig:
        return None
    expected = hmac.new(_guest_secret(), guest_id.encode("utf-8"), hashlib.sha256).hexdigest()[:24]
    if not hmac.compare_digest(sig, expected):
        return None
    return guest_id

@app.post("/auth/guest")
async def create_guest_token():
    """Issues a signed, throwaway guest identity for the homepage chat
    preview. No account is created, no password, nothing written to the
    user database - just a token the client can use to call the real chat
    endpoint a handful of times before being asked to sign in for real."""
    guest_id = secrets.token_hex(12)
    return {"token": _sign_guest_id(guest_id), "max_messages": GUEST_MAX_MESSAGES}

def require_auth_or_guest(authorization: Optional[str] = Header(default=None)) -> str:
    """Like require_auth, but also accepts a signed guest token (capped,
    chat-only). Returns either the real username, or a synthetic
    '__guest_<id>' username for guests - which chat_service/task_executor
    treat as just another username, but which can never collide with or be
    mistaken for a real account (real usernames can't contain this prefix
    per auth_service's USERNAME_RE)."""
    token = get_bearer_token(authorization)

    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    if token:
        username = auth_service.get_username_for_token(token)
        if username:
            return username

        guest_id = _verify_guest_token(token)
        if guest_id:
            if _guest_message_counts[guest_id] >= GUEST_MAX_MESSAGES:
                raise HTTPException(status_code=403, detail="Free preview limit reached. Sign in to keep chatting.")
            _guest_message_counts[guest_id] += 1
            return f"{GUEST_USERNAME_PREFIX}{guest_id}"

    raise HTTPException(status_code=401, detail="Not authenticated")

@app.get("/discover/{topic}")

async def discover_topic(topic: str, username: str = Depends(require_auth)):
    topic_key = topic.strip().lower()

    if topic_key not in DISCOVER_TOPIC_QUERIES:
        raise HTTPException(status_code=404, detail=f"Unknown discover topic: {topic}")

    if not realtime_service:
        raise HTTPException(status_code=503, detail="Realtime service not initialized")

    queries = DISCOVER_TOPIC_QUERIES[topic_key]
    loop = asyncio.get_event_loop()

    try:
        results_lists = await asyncio.gather(*[
            loop.run_in_executor(_discover_pool, realtime_service.search_tavily, q, 6)
            for q in queries
        ])

        cards = []
        seen_urls = set()

        for _formatted, payload in results_lists:

            if not payload or not isinstance(payload, dict):
                continue

            for r in payload.get("results", []):
                url = r.get("url", "")

                if not url or url in seen_urls:
                    continue

                seen_urls.add(url)
                cards.append({
                    "title": r.get("title", "Untitled"),
                    "summary": r.get("content", "")[:220],
                    "url": url,
                })

        cards.sort(key=lambda c: len(c["summary"]), reverse=True)
        logger.info("[API /discover/%s] Returning %d cards", topic_key, len(cards))
        return {"topic": topic_key, "cards": cards[:12]}

    except Exception as e:
        logger.error("[API /discover/%s] Error: %s", topic_key, e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not load {topic} feed: {str(e)}")

@app.post("/auth/signup", response_model=AuthResponse)

async def signup(request: SignupRequest):
    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    try:
        token = auth_service.signup(request.username, request.password, request.email, request.display_name)
        actual_username = auth_service.get_username_for_token(token)
        profile = auth_service.get_profile(actual_username)
        return AuthResponse(
            token=token, username=profile["username"], email=profile["email"],
            display_name=profile["display_name"], created_at=profile.get("created_at"),
        )

    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error("[API /auth/signup] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create account")

@app.post("/auth/login", response_model=AuthResponse)

async def login(request: LoginRequest):
    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    try:
        token = auth_service.login(request.username, request.password)
        # request.username may be an email; resolve the real username from the
        # session we just created instead of assuming request.username is it.
        actual_username = auth_service.get_username_for_token(token)
        profile = auth_service.get_profile(actual_username)
        return AuthResponse(
            token=token, username=profile["username"], email=profile["email"],
            display_name=profile["display_name"], created_at=profile.get("created_at"),
        )

    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))

    except Exception as e:
        logger.error("[API /auth/login] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not log in")

@app.post("/auth/logout")

async def logout(authorization: Optional[str] = Header(default=None)):
    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    token = get_bearer_token(authorization)
    auth_service.logout(token)
    return {"ok": True}

@app.get("/auth/me")

async def me(username: str = Depends(require_auth)):
    profile = auth_service.get_profile(username)

    if not profile:
        raise HTTPException(status_code=404, detail="User not found")

    return profile

@app.post("/feedback/bug")

async def report_bug(request: BugReportRequest, username: str = Depends(require_auth)):
    try:
        report = {
            "username": username,
            "description": request.description,
            "page_url": request.page_url,
            "user_agent": request.user_agent,
            "reported_at": time.time(),
        }
        filename = f"{int(time.time() * 1000)}_{username}.json"
        filepath = BUG_REPORTS_DIR / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        logger.info("[API /feedback/bug] Bug report saved from %s: %s", username, filepath.name)
        return {"ok": True}

    except Exception as e:
        logger.error("[API /feedback/bug] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not save bug report")

@app.post("/auth/change-password")

async def change_password(request: ChangePasswordRequest, username: str = Depends(require_auth)):
    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    try:
        auth_service.change_password(username, request.current_password, request.new_password)
        return {"ok": True}

    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error("[API /auth/change-password] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not change password")

@app.post("/auth/delete-account")

async def delete_account(request: DeleteAccountRequest, authorization: Optional[str] = Header(default=None), username: str = Depends(require_auth)):
    if not auth_service:
        raise HTTPException(status_code=503, detail="Auth service not initialized")

    try:
        auth_service.delete_account(username, request.password)
        token = get_bearer_token(authorization)
        auth_service.revoke_session(token)
        return {"ok": True}

    except AuthError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error("[API /auth/delete-account] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete account")

_finance_pool = ThreadPoolExecutor(max_workers=2)

@app.get("/finance/dashboard")

async def finance_dashboard(username: str = Depends(require_auth)):
    if not finance_service:
        raise HTTPException(status_code=503, detail="Finance service not initialized")

    loop = asyncio.get_event_loop()

    try:
        data = await loop.run_in_executor(_finance_pool, finance_service.get_dashboard)

        if not data.get("available"):
            raise HTTPException(
                status_code=503,
                detail="Finance dashboard isn't configured yet. Add FMP_API_KEY to your .env.",
            )

        total_cards = len(data.get("indices", [])) + len(data.get("gainers", [])) + \
            len(data.get("losers", [])) + len(data.get("actives", []))
        logger.info("[API /finance/dashboard] Returning %d symbols", total_cards)
        return data

    except HTTPException:
        raise

    except Exception as e:
        logger.error("[API /finance/dashboard] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Could not load finance dashboard: {str(e)}")

# ==================== PROJECTS ====================

_project_pool = ThreadPoolExecutor(max_workers=4)

def _require_project_service():
    if not project_service:
        raise HTTPException(status_code=503, detail="Project service not initialized")
    return project_service

@app.get("/projects", response_model=list)
async def list_projects(include_archived: bool = False, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        projects = svc.list_projects(username, include_archived=include_archived)
        return [p.model_dump() for p in projects]

    except Exception as e:
        logger.error("[API /projects] Error listing for user=%s: %s", username, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load projects")

@app.post("/projects", response_model=Project)
async def create_project(request: CreateProjectRequest, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        project = svc.create_project(username, request.title, request.description or "")
        logger.info("[API /projects] Created %s for user=%s", project.project_id, username)
        return project

    except ProjectError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        logger.error("[API /projects] Error creating for user=%s: %s", username, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not create project")

@app.get("/projects/{project_id}", response_model=Project)
async def get_project(project_id: str, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        return svc.get_project(username, project_id)

    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s] Error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load project")

@app.patch("/projects/{project_id}", response_model=Project)
async def update_project(project_id: str, request: UpdateProjectRequest, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        return svc.update_project(username, project_id, title=request.title, description=request.description)

    except ProjectError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s] Update error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not update project")

@app.put("/projects/{project_id}/instructions", response_model=Project)
async def set_project_instructions(project_id: str, request: UpdateProjectInstructionsRequest, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        return svc.update_instructions(username, project_id, request.instructions)

    except ProjectError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s/instructions] Error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not save instructions")

@app.post("/projects/{project_id}/pin", response_model=Project)
async def pin_project(project_id: str, pinned: bool = True, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        return svc.set_pinned(username, project_id, pinned)

    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.post("/projects/{project_id}/archive", response_model=Project)
async def archive_project(project_id: str, archived: bool = True, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        return svc.set_archived(username, project_id, archived)

    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

@app.delete("/projects/{project_id}")
async def delete_project(project_id: str, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        svc.delete_project(username, project_id)
        return {"ok": True}

    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s] Delete error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete project")

def _parse_and_save_project_file_sync(svc: ProjectService, username: str, project_id: str, filename: str, raw_bytes: bytes) -> ProjectFile:
    """Runs off the event loop: parses the file and writes both the raw bytes
    and extracted text to disk, then appends a ProjectFile record and saves
    the project. Kept as one function so it can run in the thread pool."""

    import uuid as _uuid

    project = svc.get_project(username, project_id)

    if len(project.files) >= PROJECT_MAX_FILES:
        raise ProjectError(f"This project already has the maximum of {PROJECT_MAX_FILES} files.")

    file_id = str(_uuid.uuid4())
    files_dir = svc._project_files_dir(username, project_id)

    raw_path = files_dir / f"{file_id}_{filename}"
    raw_path.write_bytes(raw_bytes)

    text, error = extract_file_text(filename, raw_bytes)
    text = text[:PROJECT_MAX_CONTEXT_CHARS_PER_FILE]

    if text:
        text_path = files_dir / f"{file_id}.txt"
        text_path.write_text(text, encoding="utf-8")

    record = ProjectFile(
        file_id=file_id,
        filename=filename,
        size_bytes=len(raw_bytes),
        uploaded_at=time.time(),
        extracted_chars=len(text),
        extraction_error=error or None,
    )
    project.files.append(record)
    project.updated_at = time.time()
    svc._save(username, project)
    return record

@app.post("/projects/{project_id}/files", response_model=ProjectFile)
async def upload_project_file(project_id: str, file: UploadFile = File(...), username: str = Depends(require_auth)):
    svc = _require_project_service()

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    raw_bytes = await file.read()

    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    if len(raw_bytes) > PROJECT_MAX_FILE_BYTES:
        max_mb = PROJECT_MAX_FILE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"File is too large. Maximum size is {max_mb}MB.")

    loop = asyncio.get_event_loop()

    try:
        record = await loop.run_in_executor(
            _project_pool, _parse_and_save_project_file_sync,
            svc, username, project_id, file.filename, raw_bytes,
        )
        logger.info("[API /projects/%s/files] Uploaded %s (%d bytes, %d extracted chars) for user=%s",
                     project_id, file.filename, len(raw_bytes), record.extracted_chars, username)
        return record

    except ProjectError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s/files] Upload error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not process the uploaded file.")

@app.post("/projects/{project_id}/text-content", response_model=ProjectFile)
async def add_project_text_content(project_id: str, request: AddProjectTextContentRequest, username: str = Depends(require_auth)):
    """Lets the user paste text directly instead of uploading a file (matches
    the 'Add text content' option in the Context upload menu)."""
    svc = _require_project_service()

    raw_bytes = request.content.encode("utf-8")
    filename = request.title.strip()[:150] or "Untitled note"

    if not filename.lower().endswith(".txt"):
        filename += ".txt"

    loop = asyncio.get_event_loop()

    try:
        record = await loop.run_in_executor(
            _project_pool, _parse_and_save_project_file_sync,
            svc, username, project_id, filename, raw_bytes,
        )
        return record

    except ProjectError as e:
        status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=status, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s/text-content] Error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not save text content.")

@app.delete("/projects/{project_id}/files/{file_id}")
async def delete_project_file(project_id: str, file_id: str, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        project = svc.get_project(username, project_id)
        match = next((f for f in project.files if f.file_id == file_id), None)

        if not match:
            raise HTTPException(status_code=404, detail="File not found in this project.")

        files_dir = svc._project_files_dir(username, project_id)

        for p in files_dir.glob(f"{file_id}*"):
            p.unlink(missing_ok=True)

        project.files = [f for f in project.files if f.file_id != file_id]
        project.updated_at = time.time()
        svc._save(username, project)
        return {"ok": True}

    except HTTPException:
        raise

    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        logger.error("[API /projects/%s/files/%s] Delete error: %s", project_id, file_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not delete file.")

@app.post("/chat", response_model=ChatResponse)

async def chat(request: ChatRequest, username: str = Depends(require_auth)):

    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")


    logger.info("[API /chat] Incoming | session_id=%s | message_len=%d | message=%.100s",
                request.session_id or "new", len(request.message), request.message)

    try:
        session_id = chat_service.get_or_create_session(request.session_id)
        response_text = chat_service.process_message(session_id, request.message)
        chat_service.save_chat_session(session_id)
        logger.info("[API /chat] Done | session_id=%s | response_len=%d", session_id[:12], len(response_text))
        return ChatResponse(response=response_text, session_id=session_id)

    except ValueError as e:
        logger.warning("[API /chat] Invalid session_id: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        logger.error("[API /chat] All Groq APIs failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:

        if _is_rate_limit_error(e):
            logger.warning("[API /chat] Rate limit hit: %s", e)
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")


_SPLIT_RE = re.compile(r"(?<=[.!?,;:])\s+")
_MIN_WORDS_FIRST = 1
_MIN_WORDS = 1
_MERGE_IF_WORDS = 2
_TTS_BUFFER_TIMEOUT = 2.0
_TTS_BUFFER_MIN_WORDS = 4
_ABBREV_HOLD_RE = re.compile(r"^(?:Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|Vs|Etc)\.$", re.IGNORECASE)

def _should_hold_sentence_for_continuation(sent: str) -> bool:

    t = sent.strip()

    if not t.endswith("."):
        return False

    words = t.split()

    if len(words) != 1:
        return False

    return bool(_ABBREV_HOLD_RE.match(words[0]))

def _split_sentences(buf: str):
    parts = _SPLIT_RE.split(buf)

    if len(parts) <= 1:
        return [], buf

    raw = [p.strip() for p in parts[:-1] if p.strip()]
    sentences, pending = [], ""

    for s in raw:

        if pending:
            s = (pending + " " + s).strip()
            pending = ""

        min_req = _MIN_WORDS_FIRST if not sentences else _MIN_WORDS

        if len(s.split()) < min_req:
            pending = s
            continue
        sentences.append(s)

    remaining = (pending + " " + parts[-1].strip()).strip() if pending else parts[-1].strip()
    return sentences, remaining

def _merge_short(sentences):

    if not sentences:
        return []

    merged, i = [], 0

    while i < len(sentences):
        cur = sentences[i]
        j = i + 1

        while j < len(sentences) and len(sentences[j].split()) <= _MERGE_IF_WORDS:
            cur = (cur + " " + sentences[j]).strip()
            j += 1

        merged.append(cur)
        i = j

    return merged

def _generate_tts_sync(text: str, voice: str, rate: str) -> bytes:

    async def _inner():
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
        parts = []

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                parts.append(chunk["data"])

        return b"".join(parts)

    return asyncio.run(_inner())

_tts_pool = ThreadPoolExecutor(max_workers=4)

VALID_TTS_VOICES = {
    "en-GB-RyanNeural", "en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-GB-ThomasNeural",
    "en-US-JennyNeural", "en-US-GuyNeural", "en-US-AriaNeural", "en-US-EricNeural",
    "en-US-MichelleNeural", "en-US-RogerNeural", "en-AU-NatashaNeural", "en-AU-WilliamNeural",
    "en-IN-NeerjaNeural", "en-IN-PrabhatNeural",
}

def _stream_generator(session_id: str, chunk_iter, is_realtime: bool, tts_enabled: bool = False, tts_voice: Optional[str] = None):
    yield f"data: {json.dumps({'session_id': session_id, 'chunk': '', 'done': False})}\n\n"
    buffer = ""
    held = None
    is_first = True
    audio_queue = []
    last_submit_time = time.perf_counter()
    effective_voice = tts_voice if tts_voice in VALID_TTS_VOICES else TTS_VOICE

    def _submit(text):
        nonlocal last_submit_time

        if not text or not text.strip():
            return

        audio_queue.append((_tts_pool.submit(_generate_tts_sync, text, effective_voice, TTS_RATE), text))
        last_submit_time = time.perf_counter()

    def _drain_ready():
        events = []

        while audio_queue and audio_queue[0][0].done():
            fut, sent = audio_queue.pop(0)

            try:
                audio = fut.result()
                b64 = base64.b64encode(audio).decode("ascii")
                events.append(f"data: {json.dumps({'audio': b64, 'sentence': sent})}\n\n")

            except Exception as exc:
                logger.warning("[TTS-INLINE] Failed for '%s': %s", sent[:40], exc)
        return events

    def _yield_completed_audio():

        if not tts_enabled:
            return

        for ev in _drain_ready():
            yield ev

    try:

        for chunk in chunk_iter:

            if isinstance(chunk, dict) and "_activity" in chunk:
                yield f"data: {json.dumps({'activity': chunk['_activity']})}\n\n"
                yield from _yield_completed_audio()
                continue

            if isinstance(chunk, dict) and "_search_results" in chunk:
                yield f"data: {json.dumps({'search_results': chunk['_search_results']})}\n\n"
                yield from _yield_completed_audio()
                continue

            if isinstance(chunk, dict) and "_actions" in chunk:
                yield f"data: {json.dumps({'actions': chunk['_actions']})}\n\n"
                yield from _yield_completed_audio()
                continue

            if isinstance(chunk, dict) and "_background_tasks" in chunk:
                yield f"data: {json.dumps({'background_tasks': chunk['_background_tasks']})}\n\n"
                yield from _yield_completed_audio()
                continue

            if not chunk:
                yield from _yield_completed_audio()
                continue

            yield f"data: {json.dumps({'chunk': chunk, 'done': False})}\n\n"

            if not tts_enabled:
                continue

            yield from _yield_completed_audio()

            buffer += chunk
            sentences, buffer = _split_sentences(buffer)
            sentences = _merge_short(sentences)

            if held and sentences and len(sentences[0].split()) <= _MERGE_IF_WORDS:
                held = (held + " " + sentences[0]).strip()
                sentences = sentences[1:]

            for i, sent in enumerate(sentences):
                min_w = _MIN_WORDS_FIRST if is_first else _MIN_WORDS
                if len(sent.split()) < min_w:
                    continue

                is_last = (i == len(sentences) - 1)

                if held:
                    _submit(held)
                    held = None
                    is_first = False

                if is_last and _should_hold_sentence_for_continuation(sent):
                    held = sent

                else:
                    _submit(sent)
                    is_first = False

            if buffer and len(buffer.split()) >= _TTS_BUFFER_MIN_WORDS:
                if time.perf_counter() - last_submit_time > _TTS_BUFFER_TIMEOUT:

                    if held:
                        _submit(held)
                        held = None
                        is_first = False

                    _submit(buffer.strip())
                    buffer = ""
                    is_first = False

        yield from _yield_completed_audio()

    except Exception as e:

        for fut, _ in audio_queue:
            fut.cancel()

        yield f"data: {json.dumps({'chunk': '', 'done': True, 'error': str(e)})}\n\n"
        return

    if tts_enabled:
        remaining = buffer.strip()

        if held:

            if remaining and len(remaining.split()) <= _MERGE_IF_WORDS:
                _submit((held + " " + remaining).strip())

            else:
                _submit(held)
                if remaining:
                    _submit(remaining)

        elif remaining:
            _submit(remaining)

        for fut, sent in audio_queue:

            try:
                audio = fut.result(timeout=15)
                b64 = base64.b64encode(audio).decode("ascii")
                yield f"data: {json.dumps({'audio': b64, 'sentence': sent})}\n\n"

            except FuturesTimeoutError:
                logger.warning("[TTS-INLINE] Timeout for '%s' (15s)", (sent or "")[:40])

            except Exception as exc:
                logger.warning("[TTS-INLINE] Failed for '%s': %s", (sent or "")[:40], exc)

    yield f"data: {json.dumps({'chunk': '', 'done': True, 'session_id': session_id})}\n\n"

@app.post("/chat/stream")

async def chat_stream(request: ChatRequest, username: str = Depends(require_auth)):

    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    logger.info("[API /chat/stream] Incoming | session_id=%s | message_len=%d | message=%.100s",
                request.session_id or "new", len(request.message), request.message)

    try:
        session_id = chat_service.get_or_create_session(request.session_id)

        chunk_iter = chat_service.process_message_stream(session_id, request.message)
        return StreamingResponse(
            _stream_generator(session_id, chunk_iter, is_realtime=False, tts_enabled=request.tts, tts_voice=(request.personalization.voice if request.personalization else None)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/stream] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/realtime", response_model=ChatResponse)

async def chat_realtime(request: ChatRequest, username: str = Depends(require_auth)):

    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    if not realtime_service:
        raise HTTPException(status_code=503, detail="Realtime service not initialized")

    logger.info("[API /chat/realtime] Incoming | session_id=%s | message_len=%d | message=%.100s",
                request.session_id or "new", len(request.message), request.message)

    try:
        session_id = chat_service.get_or_create_session(request.session_id)
        response_text = chat_service.process_realtime_message(session_id, request.message)
        chat_service.save_chat_session(session_id)
        logger.info("[API /chat/realtime] Done | session_id=%s | response_len=%d", session_id[:12], len(response_text))
        return ChatResponse(response=response_text, session_id=session_id)

    except ValueError as e:
        logger.warning("[API /chat/realtime] Invalid session_id: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        logger.error("[API /chat/realtime] All Groq APIs failed: %s", e)
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:

        if _is_rate_limit_error(e):
            logger.warning("[API /chat/realtime] Rate limit hit: %s", e)
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/realtime] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing chat: {str(e)}")

@app.post("/chat/realtime/stream")

async def chat_realtime_stream(request: ChatRequest, username: str = Depends(require_auth)):

    if not chat_service or not realtime_service:
        raise HTTPException(status_code=503, detail="Service not initialized")

    logger.info("[API /chat/realtime/stream] Incoming | session_id=%s | message_len=%d | message=%.100s",
                request.session_id or "new", len(request.message), request.message)

    try:
        session_id = chat_service.get_or_create_session(request.session_id)
        chunk_iter = chat_service.process_realtime_message_stream(session_id, request.message)
        return StreamingResponse(
            _stream_generator(session_id, chunk_iter, is_realtime=True, tts_enabled=request.tts, tts_voice=(request.personalization.voice if request.personalization else None)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/realtime/stream] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chat/sessions")
async def list_chat_sessions(username: str = Depends(require_auth)):
    """Every saved chat session owned by the current user, across all
    projects, most recently updated first. Powers the sidebar's recent
    chats list so history is tied to the account instead of the browser."""
    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    try:
        return chat_service.list_user_sessions(username)

    except Exception as e:
        logger.error("[API /chat/sessions] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load chat history")

@app.get("/projects/{project_id}/chats")
async def list_project_chats(project_id: str, username: str = Depends(require_auth)):
    svc = _require_project_service()

    try:
        svc.get_project(username, project_id)  # 404s if not found/not owned by this user

    except ProjectError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    try:
        return chat_service.list_project_sessions(project_id, username)

    except Exception as e:
        logger.error("[API /projects/%s/chats] Error: %s", project_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Could not load project chats")

@app.post("/chat/scalable/stream")

async def chat_scalable_stream(request: ChatRequest, username: str = Depends(require_auth_or_guest)):
    if not chat_service:
        raise HTTPException(status_code=503, detail="Service not initialized")

    logger.info("[API /chat/scalable/stream] Incoming | session_id=%s | message_len=%d | img=%s | message=%.100s",
                request.session_id or "new", len(request.message), "yes" if request.imgbase64 else "no", request.message)

    try:
        # Default the assistant's nickname to the signed-in user's own
        # display_name, so each user is addressed by their name (not a
        # global env value). The user's own nickname setting wins if set.
        personalization = request.personalization
        if username and not username.startswith(GUEST_USERNAME_PREFIX):
            has_nickname = bool(personalization and (personalization.nickname or "").strip())
            if not has_nickname:
                profile = auth_service.get_profile(username)
                display_name = ((profile or {}).get("display_name") or username).strip()
                if display_name:
                    personalization = personalization or Personalization()
                    personalization.nickname = display_name

        session_id = chat_service.get_or_create_session(request.session_id)
        chunk_iter = chat_service.process_scalable_message_stream(
            session_id, request.message, imgbase64=request.imgbase64, personalization=personalization,
            username=username, project_id=request.project_id,
        )

        return StreamingResponse(
            _stream_generator(session_id, chunk_iter, is_realtime=True, tts_enabled=request.tts, tts_voice=(request.personalization.voice if request.personalization else None)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except AllGroqApisFailedError as e:
        raise HTTPException(status_code=503, detail=str(e))

    except Exception as e:
        if _is_rate_limit_error(e):
            raise HTTPException(status_code=429, detail=RATE_LIMIT_MESSAGE)

        logger.error("[API /chat/scalable/stream] Error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tasks/{task_id}")

async def get_task_status(task_id: str, username: str = Depends(require_auth)):
    if not task_manager:
        raise HTTPException(status_code=503, detail="Task manager not initialized")

    if not task_id or len(task_id) > 32:
        raise HTTPException(status_code=400, detail="Invalid task_id")
    data = task_manager.get_serializable(task_id)

    if not data:
        raise HTTPException(status_code=404, detail="Task not found")

    return data

@app.get("/tasks/{task_id}/image")

async def get_task_image(task_id: str, username: str = Depends(require_auth)):
    if not task_manager:
        raise HTTPException(status_code=503, detail="Task manager not initialized")

    if not task_id or len(task_id) > 32:
        raise HTTPException(status_code=400, detail="Invalid task_id")

    entry = task_manager.get(task_id)

    if not entry:
        raise HTTPException(status_code=404, detail="Task not found")

    if entry.status != "completed" or not entry.image_bytes:
        raise HTTPException(status_code=404, detail="Image not ready")

    return Response(content=entry.image_bytes, media_type="image/png")

@app.get("/artifacts")

async def list_artifacts(username: str = Depends(require_auth)):
    if not task_manager:
        raise HTTPException(status_code=503, detail="Task manager not initialized")

    artifacts = task_manager.list_artifacts(username)
    return {"artifacts": artifacts}

@app.get("/artifacts/{task_id}/image")

async def get_artifact_image(task_id: str, username: str = Depends(require_auth)):
    if not task_manager:
        raise HTTPException(status_code=503, detail="Task manager not initialized")

    if not task_id or len(task_id) > 32:
        raise HTTPException(status_code=400, detail="Invalid task_id")

    image_bytes = task_manager.get_artifact_image(username, task_id)

    if not image_bytes:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return Response(content=image_bytes, media_type="image/png")

@app.get("/chat/history/{session_id}")

async def get_chat_history(session_id: str, username: str = Depends(require_auth)):
    if not chat_service:
        raise HTTPException(status_code=503, detail="Chat service not initialized")

    if not chat_service.validate_session_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    try:
        messages = chat_service.get_chat_history(session_id)
        return {
            "session_id": session_id,
            "messages": [{"role": msg.role, "content": msg.content} for msg in messages]
        }

    except Exception as e:
        logger.error(f"Error retrieving history: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error retrieving history: {str(e)}")

@app.post("/tts")

async def text_to_speech(request: TTSRequest, username: str = Depends(require_auth)):
    text = request.text.strip()

    if not text:
        raise HTTPException(status_code=400, detail="Text is required")

    async def generate():
        try:
            communicate = edge_tts.Communicate(text=text, voice=TTS_VOICE, rate=TTS_RATE)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            logger.error("[TTS] Error generating speech: %s", e)

    return StreamingResponse(
        generate(),
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )

_public_dir = Path(__file__).resolve().parent.parent / "public"

def _public_page(filename: str) -> FileResponse:
    return FileResponse(
        _public_dir / filename,
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )

@app.get("/terms")
async def terms_redirect():
    return _public_page("terms.html")

@app.get("/terms.html", include_in_schema=False)
async def terms_page():
    return _public_page("terms.html")

@app.get("/privacy")
async def privacy_redirect():
    return _public_page("privacy.html")

@app.get("/privacy.html", include_in_schema=False)
async def privacy_page():
    return _public_page("privacy.html")

@app.get("/features")
async def features_redirect():
    return _public_page("features.html")

@app.get("/features.html", include_in_schema=False)
async def features_page():
    return _public_page("features.html")

@app.get("/faq")
async def faq_redirect():
    return _public_page("faq.html")

@app.get("/faq.html", include_in_schema=False)
async def faq_page():
    return _public_page("faq.html")

@app.get("/cookie-consent.js", include_in_schema=False)
async def cookie_consent_script():
    return FileResponse(
        _public_dir / "cookie-consent.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )

@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml(request: Request):
    host = (request.url.hostname or "").lower()
    if host.endswith("onrender.com"):
        # No sitemap for the render.com preview URL.
        return Response(
            content="<!-- sitemap not served on this host -->",
            media_type="application/xml",
            headers={"Cache-Control": "no-cache, must-revalidate", "X-Robots-Tag": "noindex"},
        )
    return FileResponse(
        _public_dir / "sitemap.xml",
        media_type="application/xml",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt(request: Request):
    # The *.onrender.com deployment URL must stay out of search indexes —
    # only the real domain (scalableai.us) is crawlable.
    host = (request.url.hostname or "").lower()
    if host.endswith("onrender.com"):
        return Response(
            content="User-agent: *\nDisallow: /\n",
            media_type="text/plain",
            headers={"Cache-Control": "no-cache, must-revalidate", "X-Robots-Tag": "noindex"},
        )
    return FileResponse(
        _public_dir / "robots.txt",
        media_type="text/plain",
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )

# Public-only assets referenced by the marketing pages (not present in frontend/).
@app.get("/style-marketing.css", include_in_schema=False)
async def marketing_css():
    return FileResponse(
        _public_dir / "style-marketing.css",
        media_type="text/css",
        headers={"Cache-Control": "public, max-age=3600"},
    )

@app.get("/og-banner.png", include_in_schema=False)
async def og_banner():
    return FileResponse(
        _public_dir / "og-banner.png",
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400"},
    )

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
_i18n_assets_dir = Path(__file__).resolve().parent.parent / "i18n-assets"

# ---- UI language subpaths (/es/, /fr/, /ja/, /de/, /pt/, /ko/, /it/) ----
# frontend/index.html is itself the public-facing app (no separate marketing
# homepage), so each language prefix serves the SAME index.html. Visible text
# is swapped client-side by /i18n/i18n.js based on the URL prefix — this is
# independent of the "Response language" setting, which only controls what
# language the AI replies in.
# Must be registered BEFORE the catch-all StaticFiles mount at "/".
_UI_LANGS = ["es", "fr", "ja", "de", "pt", "ko", "it"]

def _make_localized_index():
    async def _localized_index():
        index_path = _frontend_dir / "index.html"
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return _localized_index

for _lang in _UI_LANGS:
    app.add_api_route(
        f"/{_lang}/",
        _make_localized_index(),
        methods=["GET"],
        include_in_schema=False,
        name=f"localized_index_{_lang}",
    )
    app.add_api_route(
        f"/app/{_lang}/",
        _make_localized_index(),
        methods=["GET"],
        include_in_schema=False,
        name=f"localized_index_app_{_lang}",
    )

if _i18n_assets_dir.exists():
    app.mount("/i18n", StaticFiles(directory=str(_i18n_assets_dir)), name="i18n_assets")
else:
    logger.warning("i18n assets dir not found at %s — language switcher will not load", _i18n_assets_dir)

if _frontend_dir.exists():
    app.mount("/app", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend_root")


def run():
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    run()