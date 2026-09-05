# S.C.A.L.A.B.L.E — Just A Rather Very Intelligent System

A personal AI assistant with a beautiful web UI. Talk to it, ask questions, search the web, generate images, analyze camera photos, and more. Runs completely on your own machine with one command.

**Quick start:** `pip install -r requirements.txt` → add your `GROQ_API_KEY` to `.env` → `python run.py` → open http://localhost:8000

## Features

### Three Chat Modes

- **Scale Mode** (default): The AI automatically decides whether to answer from its knowledge or search the web. A fast classifier routes each message to the right mode in ~200ms.
- **General Mode**: Answers from Groq AI + your personal learning data. No internet access. Fast.
- **Realtime Mode**: Searches the web via Tavily before answering. Gets fresh information (news, scores, prices, etc.).

### Image Generation (Free)
Say "generate an image of..." and Scalable creates it using Pollinations.ai. No API key, no cost, works instantly.

### Camera / Vision
Send a photo or use your webcam. Scalable analyzes the image and answers questions about it using Llama 4 Scout (free via Groq).

### Text-to-Speech
The AI speaks its responses as they stream in. Uses Microsoft Edge's TTS (free, no API key). First sentence starts playing before the full response is done.

### Voice Input
Click the mic and speak your question. It auto-sends when you stop talking. Works in Chrome and Safari.

### Personal Memory (Learning System)
Put `.txt` files in `database/learning_data/` with any personal information you want Scalable to know. It reads them at startup and uses them as context when answering your questions.

### Session Persistence
Conversations are saved to disk. If you restart the server, your chat history is still there.

### Multiple API Keys
Set `GROQ_API_KEY_2`, `GROQ_API_KEY_3`, etc. in `.env` for automatic fallback. If one key hits its rate limit, Scalable switches to the next one automatically.

---

## Setup

### What You Need

- Python 3.10 or newer
- A free [Groq API key](https://console.groq.com)
- (Optional) A free [Tavily API key](https://tavily.com) for web search

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the project folder:
```env
GROQ_API_KEY=your_groq_key_here
TAVILY_API_KEY=your_tavily_key_here

# Optional
ASSISTANT_NAME=Scalable
SCALABLE_USER_TITLE=Sir
SCALABLE_OWNER_NAME=Injun
TTS_VOICE=en-GB-RyanNeural
TTS_RATE=+22%
```

3. Start the server:
```bash
python run.py
```

4. Open http://localhost:8000 in your browser.

---

## Project Structure

```
SCALABLE/
├── frontend/                  # Web UI (HTML, CSS, JS — no build tools)
│   ├── index.html
│   ├── style.css
│   ├── script.js              # Chat, streaming, TTS player, voice input
│   └── orb.js                 # Animated WebGL orb (GLSL shaders)
│
├── app/                       # Backend (FastAPI)
│   ├── main.py                # All API endpoints, streaming, TTS
│   ├── models.py              # Request/response data models
│   ├── services/
│   │   ├── chat_service.py    # Sessions, history, message flow
│   │   ├── groq_service.py    # General chat (Groq LLM + vector store)
│   │   ├── realtime_service.py # Web search + Groq (Realtime mode)
│   │   ├── brain_service.py   # Two-stage intent classifier (Scalable mode)
│   │   ├── vector_store.py    # FAISS index + local embeddings (memory)
│   │   ├── task_executor.py   # Image gen, YouTube, web open, etc.
│   │   ├── task_manager.py    # Background task queue and polling
│   │   └── vision_service.py  # Camera/image analysis (Llama 4 Scout)
│   └── utils/
│       ├── time_info.py       # Current time for AI system prompt
│       ├── retry.py           # Retry wrapper for API calls
│       └── key_rotation.py    # Brain/chat use different API keys
│
├── database/                  # Created automatically on first run
│   ├── learning_data/         # Your .txt files (personal info for the AI)
│   ├── chats_data/            # Saved conversations (JSON)
│   └── vector_store/          # FAISS index files
│
├── config.py                  # All settings and system prompt
├── run.py                     # Start the server: python run.py
├── requirements.txt
└── .env                       # Your API keys (never commit this file)
```

---

## How It Works

### Scale Mode Flow
1. You send a message
2. **Brain (8B model, ~200ms):** Classifies your message — is this general knowledge, web search, camera, or a task (image gen, open app, etc.)?
3. Routes to the right handler
4. **Chat (70B model):** Writes the actual answer using Groq AI
5. Answer streams back to you word by word

### Realtime Mode Flow
1. You send a message
2. **Query extraction (8B model, ~300ms):** Converts your messy conversational message into a clean search query. "what about him?" → "Elon Musk latest news 2026"
3. **Tavily search:** Fetches 5 web results with AI-synthesized answer
4. Search results are injected into the AI prompt
5. **Groq (70B):** Answers using the search results as source

### Memory/Context Flow
1. At startup, all your `.txt` files and past conversations are embedded locally using a HuggingFace model
2. For every message, the top 5 most relevant chunks are retrieved
3. These chunks are added to the AI's context — so it knows about your personal data

---

## Configuration

### All `.env` Settings

| Variable | Required | Default | Description |
|---|---|---|---|
| `GROQ_API_KEY` | Yes | — | Your primary Groq API key |
| `GROQ_API_KEY_2`, `_3`, ... | No | — | Extra keys for auto-fallback |
| `TAVILY_API_KEY` | No | — | Tavily key for web search |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Main chat model |
| `ASSISTANT_NAME` | No | `Scalable` | Name of the assistant |
| `Scalable_USER_TITLE` | No | — | How AI addresses you (e.g. "Sir") |
| `Scalable_OWNER_NAME` | No | — | Your name (so AI knows who it serves) |
| `TTS_VOICE` | No | `en-GB-RyanNeural` | Text-to-speech voice |
| `TTS_RATE` | No | `+22%` | Speech speed |

Run `edge-tts --list-voices` to see all available TTS voices.

---

## API Endpoints

| Endpoint | What it does |
|---|---|
| `POST /chat/stream` | General mode — streaming response |
| `POST /chat/realtime/stream` | Realtime mode — web search + streaming |
| `POST /chat/scalable/stream` | Scalable mode — auto-routes, streaming |
| `POST /chat` | General mode — non-streaming |
| `POST /chat/realtime` | Realtime mode — non-streaming |
| `GET /chat/history/{session_id}` | Get full chat history for a session |
| `POST /tts` | Generate speech audio for any text |
| `GET /health` | Check server and service status |

**Request format (all chat endpoints):**
```json
{
  "message": "What is the weather like?",
  "session_id": "optional-existing-session-id",
  "tts": true
}
```

---

## Troubleshooting

**Server won't start**
- Make sure `GROQ_API_KEY` is in your `.env` file
- Run `pip install -r requirements.txt` again
- Make sure port 8000 is free

**Realtime mode gives bad answers**
- Check that `TAVILY_API_KEY` is set in `.env`
- Look for `[TAVILY]` lines in server logs to confirm search is working

**TTS not working**
- Click the speaker icon to enable it before sending a message
- On iPhone: you must tap the speaker icon first (browser security requirement)

**Image generation not working**
- Make sure the server is running and you can access http://localhost:8000
- Images are generated by Pollinations.ai — requires internet connection

**Vector store errors**
- Delete the `database/vector_store/` folder and restart. It rebuilds automatically.

**AI is slow**
- This is usually a Groq rate limit. Add more API keys (`GROQ_API_KEY_2`, etc.) for automatic fallback.

---

## Technologies

| Technology | Purpose |
|---|---|
| Groq AI (Llama 3.3 70B) | Main AI responses |
| Groq AI (Llama 3.1 8B) | Fast intent classification |
| Groq AI (Llama 4 Scout) | Image/camera analysis (vision) |
| Tavily | Web search for Realtime mode |
| Pollinations.ai | Free image generation |
| FAISS | Local vector search (memory) |
| HuggingFace sentence-transformers | Local text embeddings |
| edge-tts | Free text-to-speech |
| FastAPI | Backend web framework |
| LangChain | LLM orchestration |
| WebGL / GLSL | Animated orb in the UI |

---

## Developer

**S.C.A.L.A.B.L.E** was built by **Injamam Seikh** — Cybersecurity Enthusiast, International Ambassador, and programmer.

- Website: [Injamam Seikh](https://www.linkedin.com/in/injamam-v-6b5035367)
- Instagram: [@vtinjun](https://www.instagram.com/vtinjun/)
- Telegram: [t.me/Injunvt](https://t.me/Injunvt)
- YouTube: [InjunV](https://youtube.com/@injunv?si=1mowOaF3YZd4gvTn)
- Scale for Everyone: [jarvis4everyone.com](https://jarvis4everyone.com)

`python run.py` → http://localhost:8000