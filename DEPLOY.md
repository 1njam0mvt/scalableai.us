# Deploying ScalableAI (Render + Cloudflare)

This app is a FastAPI + PyTorch/FAISS Python service, so it runs as a normal
web service on **Render** — not on Cloudflare Workers, which is a JS/edge
runtime that can't run this stack. Cloudflare's role here is DNS + CDN/proxy
in front of Render, plus SSL.

```
  scalableai.us (Cloudflare DNS, proxied)
          │
          ▼
   Render web service (Docker, persistent disk at /app/database)
```

## 1. Push this repo to GitHub

Render deploys from a Git repository. If you haven't already:

```bash
cd ScalableAI
git init
git add .
git commit -m "Initial commit"
```

**Before you push anywhere public**, make sure `.env` and `database/` are
git-ignored — they contain secrets and user data. Check `.gitignore`
includes:

```
.env
database/
__pycache__/
.venv/
```

Then create a repo on GitHub and push:

```bash
git remote add origin https://github.com/<you>/scalableai.git
git push -u origin main
```

## 2. Create the Render service

1. Go to [render.com](https://render.com) → **New** → **Blueprint**.
2. Connect your GitHub repo. Render will detect `render.yaml` in this
   project and read the service definition (Docker runtime, persistent
   disk, env var slots) automatically.
3. Click through to create the service. It will build the Dockerfile —
   the first build takes a while (torch + sentence-transformers are
   large downloads).

If you'd rather set it up manually instead of via `render.yaml`:
- **New** → **Web Service** → connect the repo
- Runtime: **Docker**
- Add a **Disk**: mount path `/app/database`, size 5GB (grow later if needed)
- Health check path: `/`

## 3. Set your environment variables

`render.yaml` declares the env var *names* but not their values (`sync: false`
means "set this manually, don't commit it"). In the Render dashboard, go to
your service → **Environment**, and add each one from your local `.env`:

```
GROQ_API_KEY=...
TAVILY_API_KEY=...
GROQ_MODEL=...
GROQ_BRAIN_MODEL=...
INTENT_CLASSIFY_MODEL=...
GROQ_VISION_MODEL=...
FMP_API_KEY=...
POLLINATIONS_API_KEY=...
TASK_EXECUTION_TIMEOUT=...
VISION_MAX_IMAGE_BYTES=...
TTS_VOICE=...
TTS_RATE=...
ASSISTANT_NAME=...
SCALABLE_USER_TITLE=...
SCALABLE_OWNER_NAME=...
```

Copy the values straight from your local `.env` file — never paste them
into a chat, issue tracker, or commit them to Git. Render encrypts
environment variables at rest and only exposes them to your running service.

`RENDER=true` is already set in `render.yaml`, which tells `run.py` to bind
to Render's `$PORT` and disable dev-mode auto-reload.

## 4. First deploy

Once env vars are set, trigger a deploy (it happens automatically on push
if `autoDeploy: true`, or manually via **Manual Deploy** → **Deploy latest
commit**). Watch the build logs — a healthy first boot looks like:

```
[startup] Thinking audio: ...
INFO:     Uvicorn running on http://0.0.0.0:10000
```

Render gives you a `https://scalableai.onrender.com`-style URL immediately —
confirm the app loads there before moving to the custom domain.

## 5. Point your domain (scalableai.us) at Render, via Cloudflare

Since you've bought `scalableai.us` and want Cloudflare in front:

1. **Add the domain to Cloudflare** (if not already): Cloudflare dashboard →
   **Add a site** → enter `scalableai.us` → follow the nameserver-change
   instructions at your domain registrar (point your registrar's nameservers
   to the two Cloudflare ones it gives you).
2. **In Render**: service → **Settings** → **Custom Domain** → add
   `scalableai.us` (and `www.scalableai.us` if you want both). Render shows
   you a CNAME target, e.g. `scalableai.onrender.com`.
3. **In Cloudflare DNS**, add:
   - Type `CNAME`, Name `@` (root), Target `scalableai.onrender.com`,
     Proxy status: **Proxied** (orange cloud)
   - Type `CNAME`, Name `www`, Target `scalableai.onrender.com`, Proxied
   
   (Some registrars don't allow a CNAME at the root/`@` — Cloudflare handles
   this fine via "CNAME flattening," so this works even though it wouldn't
   with a traditional DNS host.)
4. **SSL/TLS mode** in Cloudflare: set to **Full** (not "Flexible") under
   SSL/TLS → Overview, since Render already terminates HTTPS on its end —
   Flexible would cause redirect loops.
5. Wait for DNS propagation (usually minutes with Cloudflare, occasionally
   up to ~24h), then visit `https://scalableai.us`.

## 6. Where Cloudflare Workers could fit later (optional)

Workers can't run this app, but they're genuinely useful *in front of* it
for small edge tasks if you want them later — e.g., serving `robots.txt`/
`sitemap.xml` from the edge, redirect rules, or A/B testing headers. Not
needed for launch; Cloudflare's plain DNS+proxy (steps above) is enough to
get `scalableai.us` live.

## 7. Ongoing: updating the deployed app

Push to your `main` branch (or whichever branch Render is watching) and it
auto-deploys. The persistent disk means `database/` survives every deploy —
only the code changes.

## Notes on the current setup

- User data (chats, accounts, projects, uploaded files, vector store) lives
  on Render's persistent disk, not a managed database. This is fine at
  small-to-moderate scale, but it means backups are your responsibility —
  Render's disks aren't automatically backed up. Consider periodically
  downloading a copy of `/app/database` (Render's shell access lets you
  `tar` it up) until/unless you migrate to a managed DB.
- The Docker image installs `torch` and `sentence-transformers`, which are
  large — expect multi-minute build times and a meaningful RAM footprint at
  runtime. If the service crashes with an out-of-memory error, upgrade the
  Render plan.