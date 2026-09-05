import logging
import time
import re
import ast
import operator
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from config import TASK_EXECUTION_TIMEOUT, POLLINATIONS_API_KEY
from app.services.decision_types import (
    INTENT_OPEN, INTENT_PLAY, INTENT_CAMERA,
    INTENT_OPEN_WEBCAM, INTENT_CLOSE_WEBCAM,
    INTENT_GENERATE_IMAGE, INTENT_CONTENT,
    INTENT_GOOGLE_SEARCH, INTENT_YOUTUBE_SEARCH, INTENT_CHAT,
    INTENT_CALCULATE, INTENT_SITE_SEARCH, INTENT_REMINDER,
)

logger = logging.getLogger("SCALABLE")

@dataclass
class TaskResponse:
    text: str = ""
    wopens: List[str] = field(default_factory=list)
    plays: List[str] = field(default_factory=list)
    images: List[str] = field(default_factory=list)
    contents: List[str] = field(default_factory=list)
    googlesearches: List[str] = field(default_factory=list)
    youtubesearches: List[str] = field(default_factory=list)
    cam: Optional[dict] = None
    reminder: Optional[dict] = None

class TaskExecutor:

    def __init__(self, groq_service=None):
        self.groq_service = groq_service
        logger.info("[TASK] TaskExecutor initialized (Pollinations.ai for images)")

    def execute(
        self,
        intents: List[tuple],
        chat_history: Optional[List[tuple]] = None,
    ) -> TaskResponse:

        response = TaskResponse()

        tasks = []

        for intent_type, payload in intents:

            if intent_type == INTENT_OPEN:
                tasks.append(("wopen", self._do_open, payload))

            elif intent_type == INTENT_PLAY:
                tasks.append(("play", self._do_play, payload))

            elif intent_type == INTENT_GENERATE_IMAGE:
                tasks.append(("image", self._do_generate_image, payload))

            elif intent_type == INTENT_CONTENT:
                tasks.append(("content", lambda p: self._do_content(p, chat_history), payload))

            elif intent_type == INTENT_GOOGLE_SEARCH:
                tasks.append(("google", self._do_google_search, payload))

            elif intent_type == INTENT_YOUTUBE_SEARCH:
                tasks.append(("youtube", self._do_youtube_search, payload))

            elif intent_type == INTENT_CALCULATE:
                result = self._do_calculate(payload)
                response.text = result if result else "I couldn't work that out. Try rephrasing the expression."

            elif intent_type == INTENT_SITE_SEARCH:
                tasks.append(("google", self._do_site_search, payload))

            elif intent_type == INTENT_REMINDER:
                reminder = self._do_reminder(payload)

                if reminder:
                    response.reminder = reminder
                    response.text = f"Got it — I'll remind you to \"{reminder['message']}\" in {reminder['label']}."
                else:
                    response.text = "I couldn't figure out when to remind you. Try something like \"remind me to call mom in 10 minutes\"."

            elif intent_type == INTENT_OPEN_WEBCAM:
                response.cam = {"action": "open"}
                response.text = "Opening the webcam for you."

            elif intent_type == INTENT_CLOSE_WEBCAM:
                response.cam = {"action": "close"}
                response.text = "Webcam closed."

            elif intent_type == INTENT_CAMERA:
                response.cam = {"action": "open"}
                response.text = "Opening your webcam. Once it's on, send your message again and I'll describe what I see."

            elif intent_type == INTENT_CHAT:
                pass

        if not tasks:

            if not response.text and not response.cam:
                response.text = "I'm not sure what you'd like me to do. Could you clarify?"

            return response

        t0 = time.perf_counter()
        failed_tags = []

        try:

            with ThreadPoolExecutor(max_workers=min(6, len(tasks))) as executor:
                futures = {
                    executor.submit(fn, p): (tag, fn, p)
                    for tag, fn, p in tasks
                }

                for future in as_completed(futures, timeout=TASK_EXECUTION_TIMEOUT):
                    tag, fn, payload = futures[future]

                    try:
                        result = future.result()
                        if tag == "wopen" and result:
                            response.wopens.append(result)

                        elif tag == "play" and result:
                            response.plays.append(result)

                        elif tag == "image" and result:
                            # _do_generate_image returns (pollinations_url, image_bytes);
                            # response.images is List[str], so only the URL belongs here.
                            image_url = result[0] if isinstance(result, tuple) else result
                            response.images.append(image_url)

                        elif tag == "content" and result:
                            response.contents.append(result)

                        elif tag == "google" and result:
                            response.googlesearches.append(result)

                        elif tag == "youtube" and result:
                            response.youtubesearches.append(result)

                    except Exception as e:
                        failed_tags.append(tag)
                        err_msg = str(e)[:100]
                        logger.warning("[TASK] Task %s failed: %s", tag, e)

                        if "content_policy" in err_msg.lower() or "safety" in err_msg.lower():
                            if tag == "image":
                                response.text = "I couldn't generate that image - it may violate content guidelines."

                        elif not response.text:
                            response.text = f"Something went wrong with that task: {err_msg}"

        except FuturesTimeoutError:
            logger.warning("[TASK] Task execution timed out after %ds", TASK_EXECUTION_TIMEOUT)

            if not response.text:
                response.text = "Some tasks took too long. Please try again."

        elapsed = time.perf_counter() - t0
        logger.info("[TASK] Executed %d tasks in %.2fs (failed: %s)", len(tasks), elapsed, failed_tags or "none")

        if not response.text:
            parts = self._build_conversational_response(
                response.wopens, response.plays, response.images,
                response.contents, response.googlesearches, response.youtubesearches,
            )
            response.text = parts if parts else "All done."

        return response

    def _url_to_display_name(self, url: str) -> str:
        u = (url or "").lower()
        mapping = {
            "facebook.com": "Facebook", "instagram.com": "Instagram", "youtube.com": "YouTube",
            "google.com": "Google", "netflix.com": "Netflix", "twitter.com": "Twitter",
            "x.com": "X", "gmail.com": "Gmail", "whatsapp.com": "WhatsApp",
            "linkedin.com": "LinkedIn", "reddit.com": "Reddit", "discord.com": "Discord",
            "spotify.com": "Spotify", "tiktok.com": "TikTok", "amazon.com": "Amazon",
            "github.com": "GitHub", "wikipedia.org": "Wikipedia", "stackoverflow.com": "Stack Overflow",
            "medium.com": "Medium", "notion.so": "Notion", "figma.com": "Figma",
            "canva.com": "Canva", "zoom.us": "Zoom", "drive.google.com": "Google Drive",
            "scalableai.us": "Scale for Everyone", "graphy.com": "Graphy",
        }

        for key, name in mapping.items():
            if key in u:
                return name

        try:
            parsed = urlparse(url)
            domain = (parsed.netloc or parsed.path or "").replace("www.", "").split(".")[0]
            return domain.title() if domain else "the link"

        except Exception:
            return "the link"

    def _build_conversational_response(
        self,
        wopens: List[str],
        plays: List[str],
        images: List[str],
        contents: List[str],
        googlesearches: List[str],
        youtubesearches: List[str],
    ) -> str:

        parts = []

        if wopens:
            names = [self._url_to_display_name(u) for u in wopens]

            if len(names) == 1:
                parts.append(f"I've opened {names[0]} for you.")

            else:
                last = names[-1]
                rest = ", ".join(names[:-1])
                parts.append(f"I've opened {rest} and {last} for you.")

        if plays:
            parts.append("I've started playing that for you.")

        if images:
            count = len(images)
            parts.append(f"I've generated the image{'s' if count > 1 else ''} for you.")

        if contents:
            parts.append("I've written that for you.")

        if googlesearches or youtubesearches:
            parts.append("I've run the search for you.")

        return " ".join(parts) if parts else "Done."

    def _validate_url(self, url: str) -> Optional[str]:

        if not url or len(url) > 2048:
            return None
        u = url.strip()

        if not u.startswith("http"):
            u = "https://" + u

        try:
            parsed = urlparse(u)

            if parsed.scheme not in ("http", "https"):
                logger.warning("[TASK] Rejected non-http URL: %s", u[:50])
                return None
            return u

        except Exception:
            return None

    def _do_open(self, payload: dict) -> Optional[str]:
        url = payload.get("url", "").strip()

        if not url:
            return None
        return self._validate_url(url)

    def _do_play(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return "https://www.youtube.com"
        return f"https://www.youtube.com/results?search_query={quote(query, safe='')}"

    def _do_generate_image(self, payload: dict) -> Optional[tuple]:
        """Returns (pollinations_url, image_bytes) or None on failure."""
        prompt = (payload.get("prompt", payload.get("message", "")) or "").strip()

        if len(prompt) < 3:
            logger.warning("[TASK] Image prompt too short (< 3 chars)")
            return None

        prompt = prompt[:4000]
        t0 = time.perf_counter()

        result = self._generate_pollinations(prompt)

        if result:
            logger.info("[TASK] Pollinations image downloaded in %.2fs", time.perf_counter() - t0)
            return result

        logger.warning("[TASK] Image generation failed")
        return None

    # Tried in order until one returns a usable image. With a Pollinations
    # API key set (POLLINATIONS_API_KEY in .env), better models are
    # unlocked and tried first; without a key, this falls back to the
    # older free-tier chain.
    #
    # NOTE on "nanobanana": that model (Google's Gemini image model,
    # routed through Pollinations) has a known tendency to return a
    # multi-panel/contact-sheet grid of several small variations instead
    # of one clean image - especially for face/portrait/group prompts.
    # That's a quirk of the underlying model itself, not something request
    # parameters here can reliably suppress, so it's kept out of the
    # default chain and only tried as a last resort after the models that
    # behave predictably as single-image generators.
    IMAGE_MODEL_FALLBACK_CHAIN_AUTH = ["zimage", "gptimage", "flux", "nanobanana"]
    IMAGE_MODEL_FALLBACK_CHAIN_FREE = ["zimage", "flux", "turbo"]

    _GROUP_HINT_WORDS = (
        "group", "people", "friends", "team", "crowd", "family",
        "band", "squad", "everyone", "members", "couple",
    )

    def _enhance_image_prompt(self, prompt: str) -> str:
        """Add quality/composition hints that measurably reduce warped
        faces and limb artifacts on diffusion models, especially for
        multi-person scenes."""
        p = prompt.strip()
        lower = p.lower()
        boosters = ["highly detailed", "sharp focus", "professional photography", "correct anatomy"]

        if any(w in lower for w in self._GROUP_HINT_WORDS):
            boosters.append("individually distinct faces, consistent lighting, no duplicated or merged features")

        return f"{p}, {', '.join(boosters)}"

    def _generate_pollinations(self, prompt: str) -> Optional[tuple]:
        """Download the generated image and return (url, bytes), or None on failure.

        Tries each model in the active fallback chain in turn (a few
        attempts each) so a single model having a bad day, or being
        deprecated/gated, doesn't take image generation down entirely.
        If POLLINATIONS_API_KEY is set, it's sent as a Bearer token and
        the higher-quality authenticated model chain is used first.
        """
        import httpx
        enhanced_prompt = self._enhance_image_prompt(prompt)
        encoded_prompt = quote(enhanced_prompt, safe='')

        api_key = (POLLINATIONS_API_KEY or "").strip()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        model_chain = self.IMAGE_MODEL_FALLBACK_CHAIN_AUTH if api_key else self.IMAGE_MODEL_FALLBACK_CHAIN_FREE

        for model in model_chain:
            api_url = (
                f"https://image.pollinations.ai/prompt/{encoded_prompt}"
                f"?model={model}&width=1024&height=1024&nologo=true&private=true&enhance=true&safe=false"
            )
            logger.info("[TASK] Fetching Pollinations image (model=%s, auth=%s): %s", model, bool(api_key), api_url[:120])

            for attempt in range(2):
                try:
                    with httpx.Client(timeout=60, follow_redirects=True) as client:
                        resp = client.get(api_url, headers=headers)
                        if resp.status_code == 200 and resp.content:
                            content_type = resp.headers.get("content-type", "")
                            if "image" in content_type or len(resp.content) > 1000:
                                logger.info("[TASK] Pollinations image fetched via %s (%d bytes)", model, len(resp.content))
                                return (api_url, resp.content)
                        logger.warning("[TASK] Pollinations model=%s attempt %d: status=%d", model, attempt + 1, resp.status_code)
                except Exception as e:
                    logger.warning("[TASK] Pollinations model=%s attempt %d failed: %s", model, attempt + 1, e)
                time.sleep(2)

        logger.warning("[TASK] All Pollinations models failed for this prompt")
        return None

    def _do_content(self, payload: dict, chat_history: Optional[List[tuple]] = None) -> Optional[str]:
        prompt = (payload.get("prompt", payload.get("message", "")) or "").strip()

        if not prompt or not self.groq_service:
            return None
        content_question = f"Write the following. Be thorough and well-structured. Return only the requested content, no preamble.\n\n{prompt}"

        try:
            out = self.groq_service.get_response(
                question=content_question,
                chat_history=chat_history or [],
                key_start_index=0,
            )

            if not out or len(out.strip()) < 10:
                logger.warning("[TASK] Content generation returned empty or very short result")
                return None
            return out

        except Exception as e:
            logger.warning("[TASK] Content generation error: %s", e)
            return None

    def _do_google_search(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return None
        return f"https://www.google.com/search?q={quote(query, safe='')}"

    def _do_youtube_search(self, payload: dict) -> Optional[str]:
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]
        if not query:
            return "https://www.youtube.com"
        return f"https://www.youtube.com/results?search_query={quote(query, safe='')}"

    # ---- calculator ----

    # Only digits, arithmetic operators, parentheses, decimal points, and
    # whitespace are allowed through to the parser below.
    _CALC_SAFE_RE = re.compile(r"^[\d\s\.\+\-\*\/\(\)\%\^]+$")

    _CALC_OPS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Mod: operator.mod, ast.Pow: operator.pow,
        ast.USub: operator.neg, ast.UAdd: operator.pos,
    }

    def _safe_eval_node(self, node):
        """Evaluate a restricted arithmetic AST node. Only numeric literals and
        +, -, *, /, %, ** are supported - no names, calls, attributes, or
        subscripts are ever reachable, so this cannot execute arbitrary code."""

        if isinstance(node, ast.Expression):
            return self._safe_eval_node(node.body)

        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("non-numeric constant")

        if isinstance(node, ast.BinOp) and type(node.op) in self._CALC_OPS:
            left = self._safe_eval_node(node.left)
            right = self._safe_eval_node(node.right)
            return self._CALC_OPS[type(node.op)](left, right)

        if isinstance(node, ast.UnaryOp) and type(node.op) in self._CALC_OPS:
            return self._CALC_OPS[type(node.op)](self._safe_eval_node(node.operand))

        raise ValueError(f"disallowed expression node: {type(node).__name__}")

    def _safe_eval(self, expr: str):
        tree = ast.parse(expr, mode="eval")
        return self._safe_eval_node(tree)

    def _do_calculate(self, payload: dict) -> Optional[str]:
        expr = (payload.get("expression", payload.get("query", payload.get("message", ""))) or "").strip()

        if not expr:
            return None

        # Normalize common natural-language / calculator symbols to Python operators.
        normalized = expr.lower()
        normalized = re.sub(r"\b(calculate|what is|what's|equals?|=)\b", "", normalized)
        normalized = normalized.replace("x", "*").replace("×", "*").replace("÷", "/")
        normalized = normalized.replace("plus", "+").replace("minus", "-")
        normalized = normalized.replace("times", "*").replace("divided by", "/")
        normalized = normalized.replace("^", "**")

        if not self._CALC_SAFE_RE.match(normalized.replace("**", "^")):
            logger.warning("[TASK] Calculator rejected unsafe expression: %r", expr[:80])
            return None

        try:
            result = self._safe_eval(normalized)

            if isinstance(result, float) and result.is_integer():
                result = int(result)
            return f"{expr.strip()} = {result}"

        except ZeroDivisionError:
            return "That's a division by zero - undefined."

        except Exception as e:
            logger.warning("[TASK] Calculator error on %r: %s", expr[:80], e)
            return None

    # ---- site-specific search ----

    SITE_SEARCH_URLS = {
        "amazon": "https://www.amazon.com/s?k={q}",
        "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
        "maps": "https://www.google.com/maps/search/{q}",
        "google maps": "https://www.google.com/maps/search/{q}",
        "flipkart": "https://www.flipkart.com/search?q={q}",
        "ebay": "https://www.ebay.com/sch/i.html?_nkw={q}",
    }

    def _do_site_search(self, payload: dict) -> Optional[str]:
        site = (payload.get("site", "") or "").strip().lower()
        query = (payload.get("query", payload.get("message", "")) or "").strip()[:500]

        if not query:
            return None

        template = self.SITE_SEARCH_URLS.get(site)

        if not template:
            # Unknown site name - fall back to a Google search scoped to that site.
            return f"https://www.google.com/search?q={quote((site + ' ' + query).strip(), safe='')}"

        return template.format(q=quote(query, safe=''))

    # ---- reminders (client-delivered; see frontend script.js) ----

    _DURATION_RE = re.compile(
        r"(\d+)\s*(second|sec|minute|min|hour|hr|day)s?", re.IGNORECASE
    )
    _UNIT_SECONDS = {
        "second": 1, "sec": 1,
        "minute": 60, "min": 60,
        "hour": 3600, "hr": 3600,
        "day": 86400,
    }

    def _do_reminder(self, payload: dict) -> Optional[dict]:
        """Parse a reminder request into a delay + message. Delivery happens
        client-side via a JS timer + browser Notification (see script.js),
        since this app has no background job runner - the reminder only
        fires while the tab stays open."""

        raw = (payload.get("message", payload.get("raw", "")) or "").strip()

        if not raw:
            return None

        match = self._DURATION_RE.search(raw)

        if not match:
            return None

        amount = int(match.group(1))
        unit = match.group(2).lower()
        delay_seconds = amount * self._UNIT_SECONDS.get(unit, 60)

        if delay_seconds <= 0 or delay_seconds > 86400:  # cap at 24h - tab won't stay open longer reliably
            return None

        # Strip the duration phrase and command words to get the reminder text.
        message = self._DURATION_RE.sub("", raw)
        message = re.sub(
            r"\b(remind me to|remind me|set a reminder to|set a reminder|reminder to|in|after)\b",
            "", message, flags=re.IGNORECASE,
        ).strip(" .,!?")

        if not message:
            message = "your reminder"

        unit_label = "second" if unit.startswith("sec") else (
            "minute" if unit.startswith("min") else ("hour" if unit.startswith("h") else "day")
        )
        label = f"{amount} {unit_label}{'s' if amount != 1 else ''}"

        return {
            "message": message,
            "delay_seconds": delay_seconds,
            "label": label,
        }