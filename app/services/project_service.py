import json
import logging
import re
import time
import uuid
import threading
from pathlib import Path
from typing import List, Optional

from config import (
    PROJECTS_DATA_DIR, PROJECT_FILES_DIR,
    PROJECT_MAX_FILE_BYTES, PROJECT_MAX_CONTEXT_CHARS_PER_FILE,
    PROJECT_MAX_TOTAL_CONTEXT_CHARS, PROJECT_MAX_FILES,
)
from app.models import Project, ProjectFile

logger = logging.getLogger("SCALABLE")


class ProjectError(Exception):
    """Raised for expected, user-facing project errors (not found, limits, bad file, etc.)."""
    pass


def _safe_id(raw: str) -> str:
    """Strip anything that isn't a safe filename character - defends against
    path traversal via a crafted project_id/username making it into a path."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)[:100]


class ProjectService:
    """File-backed project storage, matching the existing chat session pattern:
    one JSON file per project, one folder per project for uploaded files' raw
    bytes + extracted text. Everything is scoped under the owning username so
    one user can never see or touch another user's projects."""

    def __init__(self):
        self._save_lock = threading.Lock()
        logger.info("[PROJECT] ProjectService initialized")

    # ---- paths ----

    def _user_dir(self, username: str) -> Path:
        d = PROJECTS_DATA_DIR / _safe_id(username)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _project_path(self, username: str, project_id: str) -> Path:
        return self._user_dir(username) / f"{_safe_id(project_id)}.json"

    def _project_files_dir(self, username: str, project_id: str) -> Path:
        d = PROJECT_FILES_DIR / _safe_id(username) / _safe_id(project_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---- CRUD ----

    def create_project(self, username: str, title: str, description: str = "") -> Project:
        title = title.strip()

        if not title:
            raise ProjectError("Project title cannot be empty.")

        now = time.time()
        project = Project(
            project_id=str(uuid.uuid4()),
            title=title[:100],
            description=(description or "").strip()[:2000],
            instructions="",
            created_at=now,
            updated_at=now,
            pinned=False,
            archived=False,
            files=[],
            chat_count=0,
        )
        self._save(username, project)
        logger.info("[PROJECT] Created '%s' (%s) for user=%s", project.title, project.project_id, username)
        return project

    def list_projects(self, username: str, include_archived: bool = False) -> List[Project]:
        projects = []

        for path in self._user_dir(username).glob("*.json"):
            try:
                project = self._load_path(path)

                if project and (include_archived or not project.archived):
                    projects.append(project)

            except Exception as e:
                logger.warning("[PROJECT] Skipping unreadable project file %s: %s", path, e)

        # Pinned first, then most recently updated.
        projects.sort(key=lambda p: (not p.pinned, -p.updated_at))
        return projects

    def get_project(self, username: str, project_id: str) -> Project:
        path = self._project_path(username, project_id)
        project = self._load_path(path)

        if not project:
            raise ProjectError("Project not found.")
        return project

    def update_project(self, username: str, project_id: str, title: Optional[str] = None, description: Optional[str] = None) -> Project:
        project = self.get_project(username, project_id)

        if title is not None:
            title = title.strip()

            if not title:
                raise ProjectError("Project title cannot be empty.")
            project.title = title[:100]

        if description is not None:
            project.description = description.strip()[:2000]

        project.updated_at = time.time()
        self._save(username, project)
        return project

    def update_instructions(self, username: str, project_id: str, instructions: str) -> Project:
        project = self.get_project(username, project_id)
        project.instructions = (instructions or "").strip()[:10_000]
        project.updated_at = time.time()
        self._save(username, project)
        return project

    def set_pinned(self, username: str, project_id: str, pinned: bool) -> Project:
        project = self.get_project(username, project_id)
        project.pinned = pinned
        project.updated_at = time.time()
        self._save(username, project)
        return project

    def set_archived(self, username: str, project_id: str, archived: bool) -> Project:
        project = self.get_project(username, project_id)
        project.archived = archived
        project.updated_at = time.time()
        self._save(username, project)
        return project

    def delete_project(self, username: str, project_id: str) -> None:
        path = self._project_path(username, project_id)

        if not path.exists():
            raise ProjectError("Project not found.")

        try:
            path.unlink()
        except Exception as e:
            logger.error("[PROJECT] Failed to delete project file %s: %s", path, e)
            raise ProjectError("Could not delete the project. Please try again.")

        # Best-effort cleanup of uploaded files - a leftover folder isn't
        # harmful, so a failure here doesn't need to fail the whole delete.
        try:
            files_dir = self._project_files_dir(username, project_id)
            for f in files_dir.glob("*"):
                f.unlink(missing_ok=True)
            files_dir.rmdir()
        except Exception as e:
            logger.warning("[PROJECT] Non-fatal: could not clean up files for %s: %s", project_id, e)

        logger.info("[PROJECT] Deleted %s for user=%s", project_id, username)

    # ---- context assembly (used by chat) ----

    def build_context_prompt(self, username: str, project_id: str) -> str:
        """Assembles instructions + all uploaded files' extracted text into a
        single block to prepend to the AI's system prompt for this project."""

        project = self.get_project(username, project_id)
        parts = []

        if project.instructions:
            parts.append(f"=== PROJECT INSTRUCTIONS ===\n{project.instructions}")

        if project.files:
            files_dir = self._project_files_dir(username, project_id)
            remaining = PROJECT_MAX_TOTAL_CONTEXT_CHARS
            file_blocks = []

            for f in project.files:
                if remaining <= 0:
                    break
                text_path = files_dir / f"{f.file_id}.txt"

                if not text_path.exists():
                    continue

                try:
                    text = text_path.read_text(encoding="utf-8")
                except Exception:
                    continue

                text = text[:remaining]
                remaining -= len(text)
                file_blocks.append(f"--- {f.filename} ---\n{text}")

            if file_blocks:
                parts.append("=== PROJECT CONTEXT FILES ===\n" + "\n\n".join(file_blocks))

        return "\n\n".join(parts)

    # ---- internal load/save ----

    def _load_path(self, path: Path) -> Optional[Project]:
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Project(**data)

        except Exception as e:
            logger.warning("[PROJECT] Failed to load %s: %s", path, e)
            return None

    def _save(self, username: str, project: Project) -> None:
        path = self._project_path(username, project.project_id)

        with self._save_lock:
            try:
                tmp_path = path.with_suffix(".json.tmp")

                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(project.model_dump(), f, indent=2, ensure_ascii=False)
                tmp_path.replace(path)  # atomic on POSIX - avoids a half-written file on crash

            except Exception as e:
                logger.error("[PROJECT] Failed to save project %s: %s", project.project_id, e)
                raise ProjectError("Could not save the project. Please try again.")
            