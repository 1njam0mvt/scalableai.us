#!/usr/bin/env python3
"""
One-time migration: database/users/*.json + database/settings/*.json
                     -> Postgres (or whatever DATABASE_URL points at)

Run this ONCE, locally or in a Render shell, against the SAME disk that
still has your existing JSON files AND with DATABASE_URL pointed at your
new Render Postgres instance. After this runs successfully and you've
verified the row counts, the old database/users and database/settings
directories are no longer read by the app (auth_service.py and
settings_service.py are now Postgres-only) — you can leave them or
delete them.

Usage:
    python scripts/migrate_json_to_postgres.py
    python scripts/migrate_json_to_postgres.py --dry-run   # preview only, no writes

Safe to re-run: existing rows are updated in place (upsert), not duplicated.
"""

import argparse
import json
import sys
from pathlib import Path

# Make the project root importable when run as `python scripts/....py`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import USERS_DIR, SETTINGS_DIR, DATABASE_URL  # noqa: E402
from app.services.db import SessionLocal, UserRecord, SettingsRecord, init_db  # noqa: E402


def load_json_files(directory: Path) -> list[tuple[str, dict]]:
    """Returns [(key, data), ...] for every non-underscore-prefixed *.json
    file in the directory (underscore-prefixed files, like the old
    _sessions.json, are internal bookkeeping — not real records)."""
    results = []
    if not directory.exists():
        return results
    for path in sorted(directory.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = path.stem  # filename without .json — matches the old _path() scheme
            results.append((key, data))
        except Exception as e:
            print(f"  [SKIP] Could not read {path}: {e}")
    return results


def migrate_users(dry_run: bool) -> int:
    print(f"\n--- Migrating users from {USERS_DIR} ---")
    records = load_json_files(USERS_DIR)
    print(f"Found {len(records)} user file(s).")

    if dry_run:
        for key, data in records:
            print(f"  [DRY RUN] would upsert user: {data.get('username', key)}")
        return len(records)

    db = SessionLocal()
    count = 0
    try:
        for key, data in records:
            username = (data.get("username") or key).strip().lower()
            row = db.get(UserRecord, username)
            if row is None:
                row = UserRecord(username=username)
                db.add(row)
            row.email = (data.get("email") or "").strip()
            row.display_name = (data.get("display_name") or username)[:60]
            row.password_hash = data.get("password_hash")
            row.oauth = data.get("oauth") or {}
            row.created_at = data.get("created_at")
            count += 1
            print(f"  [OK] upserted user: {username}")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"  [ERROR] users migration failed, rolled back: {e}")
        raise
    finally:
        db.close()
    return count


def migrate_settings(dry_run: bool) -> int:
    print(f"\n--- Migrating settings from {SETTINGS_DIR} ---")
    records = load_json_files(SETTINGS_DIR)
    print(f"Found {len(records)} settings file(s).")

    if dry_run:
        for key, data in records:
            print(f"  [DRY RUN] would upsert settings for key: {key} (photo_url={'set' if data.get('photo_url') else 'empty'})")
        return len(records)

    db = SessionLocal()
    count = 0
    try:
        for key, data in records:
            safe_key = "".join(c for c in key if c.isalnum() or c in ("-", "_"))[:64] or "default"
            row = db.get(SettingsRecord, safe_key)
            if row is None:
                row = SettingsRecord(key=safe_key)
                db.add(row)
            row.display_name = data.get("display_name", "") or ""
            row.preferred_title = data.get("preferred_title", "") or ""
            row.language = data.get("language", "English") or "English"
            row.bio = data.get("bio", "") or ""
            row.theme = data.get("theme", "dark") or "dark"
            row.photo_url = data.get("photo_url", "") or ""
            row.improve_model_for_everyone = bool(data.get("improve_model_for_everyone", True))
            row.marketing_measurement = bool(data.get("marketing_measurement", True))
            row.personalized_marketing = bool(data.get("personalized_marketing", True))
            count += 1
            print(f"  [OK] upserted settings: {safe_key}")
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"  [ERROR] settings migration failed, rolled back: {e}")
        raise
    finally:
        db.close()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview what would be migrated without writing anything.")
    args = parser.parse_args()

    print(f"Target database: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        print("WARNING: DATABASE_URL is not set — this would migrate into a local SQLite file, "
              "not your Render Postgres instance. Set DATABASE_URL and re-run.")
        if not args.dry_run:
            confirm = input("Continue anyway? [y/N] ")
            if confirm.lower() != "y":
                print("Aborted.")
                return

    if not args.dry_run:
        print("\nCreating tables if they don't exist yet...")
        init_db()

    user_count = migrate_users(args.dry_run)
    settings_count = migrate_settings(args.dry_run)

    print(f"\n{'Would migrate' if args.dry_run else 'Migrated'}: "
          f"{user_count} user(s), {settings_count} settings record(s).")
    if args.dry_run:
        print("This was a dry run — nothing was written. Re-run without --dry-run to apply.")
    else:
        print("Done. Verify row counts in your Postgres dashboard, then you can retire "
              "the old database/users and database/settings JSON files.")


if __name__ == "__main__":
    main()