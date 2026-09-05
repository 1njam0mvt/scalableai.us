import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor
from app.services.decision_types import INTENT_GENERATE_IMAGE, INTENT_CONTENT
from config import ARTIFACTS_DIR

logger = logging.getLogger("SCALABLE")
TASK_TTL = 3600

@dataclass

class TaskEntry:
    task_id: str
    status: str = "running"
    task_type: str = ""
    label: str = ""
    prompt: str = ""
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: float = 0.0
    image_bytes: Optional[bytes] = None
    username: Optional[str] = None

class TaskManager:

    def __init__(self, task_executor):
        self.task_executor = task_executor
        self._tasks: Dict[str, TaskEntry] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg-task")
        logger.info("[TASK-MGR] Background task manager initialized (4 workers)")

    def submit(
        self,
        intent_type: str,
        payload: dict,
        chat_history: Optional[List[tuple]] = None,
        username: Optional[str] = None,
    ) -> str:

        task_id = uuid.uuid4().hex[:8]
        prompt = payload.get("prompt", payload.get("message", ""))[:200]

        if intent_type == INTENT_GENERATE_IMAGE:
            label = "Generating image"

        elif intent_type == INTENT_CONTENT:
            label = "Writing content"

        else:
            label = "Processing task"

        entry = TaskEntry(
            task_id=task_id,
            status="running",
            task_type=intent_type,
            label=label,
            prompt=prompt,
            created_at=time.time(),
            username=username,
        )

        with self._lock:
            self._tasks[task_id] = entry

        self._pool.submit(self._run, task_id, intent_type, payload, chat_history)
        logger.info("[TASK-MGR] Submitted %s task %s for %s: %.80s", intent_type, task_id, username or "unknown", prompt)
        return task_id

    def get(self, task_id: str) -> Optional[TaskEntry]:
        with self._lock:
            return self._tasks.get(task_id)

    def get_serializable(self, task_id: str) -> Optional[dict]:
        entry = self.get(task_id)
        if not entry:
            return None
        return {
            "task_id": entry.task_id,
            "status": entry.status,
            "task_type": entry.task_type,
            "label": entry.label,
            "prompt": entry.prompt,
            "result": entry.result,
            "error": entry.error,
        }

    def _persist_artifact(self, task_id: str, image_bytes: bytes, prompt: str, username: Optional[str]) -> None:
        if not username:
            return

        try:
            safe_username = "".join(c for c in username if c.isalnum() or c in "_.-") or "unknown"
            user_dir = ARTIFACTS_DIR / safe_username
            user_dir.mkdir(parents=True, exist_ok=True)

            image_path = user_dir / f"{task_id}.png"
            with open(image_path, "wb") as f:
                f.write(image_bytes)

            meta_path = user_dir / f"{task_id}.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump({
                    "task_id": task_id,
                    "prompt": prompt,
                    "created_at": time.time(),
                }, f, indent=2)

            logger.info("[TASK-MGR] Persisted artifact %s for %s", task_id, username)

        except Exception as e:
            logger.warning("[TASK-MGR] Could not persist artifact %s for %s: %s", task_id, username, e)

    def list_artifacts(self, username: str, limit: int = 60) -> List[dict]:
        safe_username = "".join(c for c in (username or "") if c.isalnum() or c in "_.-") or "unknown"
        user_dir = ARTIFACTS_DIR / safe_username

        if not user_dir.exists():
            return []

        artifacts = []

        for meta_path in user_dir.glob("*.json"):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

                task_id = meta.get("task_id", meta_path.stem)
                image_path = user_dir / f"{task_id}.png"

                if not image_path.exists():
                    continue

                artifacts.append({
                    "task_id": task_id,
                    "prompt": meta.get("prompt", ""),
                    "created_at": meta.get("created_at", 0),
                    "url": f"/artifacts/{task_id}/image",
                })

            except Exception as e:
                logger.warning("[TASK-MGR] Could not read artifact metadata %s: %s", meta_path, e)

        artifacts.sort(key=lambda a: a["created_at"], reverse=True)
        return artifacts[:limit]

    def get_artifact_image(self, username: str, task_id: str) -> Optional[bytes]:
        safe_username = "".join(c for c in (username or "") if c.isalnum() or c in "_.-") or "unknown"
        safe_task_id = "".join(c for c in (task_id or "") if c.isalnum())
        image_path = ARTIFACTS_DIR / safe_username / f"{safe_task_id}.png"

        if not image_path.exists():
            return None

        try:
            with open(image_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning("[TASK-MGR] Could not read artifact image %s: %s", image_path, e)
            return None

    def _run(self, task_id: str, intent_type: str, payload: dict, chat_history):
        t0 = time.perf_counter()

        try:
            if intent_type == INTENT_GENERATE_IMAGE:
                img_result = self.task_executor._do_generate_image(payload)

                if img_result:
                    pollinations_url, image_bytes = img_result
                    result = {
                        "type": "image",
                        "url": f"/tasks/{task_id}/image",
                        "prompt": payload.get("prompt", payload.get("message", "")),
                    }
                    with self._lock:
                        self._tasks[task_id].image_bytes = image_bytes
                        entry_username = self._tasks[task_id].username

                    self._persist_artifact(task_id, image_bytes, result["prompt"], entry_username)

                else:
                    raise RuntimeError("Image generation returned no result. Check API key or content policy.")

            elif intent_type == INTENT_CONTENT:
                text = self.task_executor._do_content(payload, chat_history)

                if text:
                    result = {
                        "type": "content",
                        "text": text,
                        "prompt": payload.get("prompt", payload.get("message", "")),
                    }

                else:
                    raise RuntimeError("Content generation returned no result.")

            else:
                raise ValueError(f"Unsupported background task type: {intent_type}")

            with self._lock:
                self._tasks[task_id].status = "completed"
                self._tasks[task_id].result = result

            elapsed = time.perf_counter() - t0
            logger.info("[TASK-MGR] Task %s completed in %.2fs", task_id, elapsed)

        except Exception as e:
            with self._lock:
                self._tasks[task_id].status = "failed"
                self._tasks[task_id].error = str(e)[:500]
            logger.warning("[TASK-MGR] Task %s failed: %s", task_id, e)

    def cleanup_old(self):
        cutoff = time.time() - TASK_TTL

        with self._lock:
            to_remove = [tid for tid, e in self._tasks.items() if e.created_at < cutoff]
            for tid in to_remove:
                del self._tasks[tid]

        if to_remove:
            logger.info("[TASK-MGR] Cleaned up %d expired tasks", len(to_remove))

    def shutdown(self):
        self._pool.shutdown(wait=False)
        logger.info("[TASK-MGR] Shutdown complete")