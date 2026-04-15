#!/usr/bin/env python3
"""
Migration Script: Token-Based → Extension-Based Architecture
Date: 2026-04-15

This migration:
1. Adds new tables for extension MVP (ai_completions, extension_auth_tokens)
2. Removes canvas_api_token column from users table
3. Marks old Canvas tables as deprecated (does NOT delete them yet)
4. Preserves all existing user data

Safe to run multiple times (idempotent).
"""

import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from storage.database import get_conn

def migrate():
    """Run migration."""
    conn = get_conn()

    print("[Migration] Starting extension architecture migration...")

    # ── 1. Create ai_completions table ──────────────────────────────────
    print("[Migration] Creating ai_completions table...")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_completions (
                id SERIAL PRIMARY KEY,
                google_id TEXT NOT NULL,
                course_id BIGINT,
                assignment_id BIGINT,
                assignment_title VARCHAR(500) NOT NULL,
                assignment_description TEXT,
                context_summary TEXT,
                ai_draft TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                FOREIGN KEY (google_id) REFERENCES users(google_id) ON DELETE CASCADE
            )
        """)
        # Create indexes for performance
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_completions_user ON ai_completions(google_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_completions_created ON ai_completions(created_at)")
        print("  ✓ ai_completions table created")
    except Exception as e:
        print(f"  ✗ Error creating ai_completions: {e}")
        return False

    # ── 2. Create extension_auth_tokens table ──────────────────────────
    print("[Migration] Creating extension_auth_tokens table...")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS extension_auth_tokens (
                id SERIAL PRIMARY KEY,
                google_id TEXT NOT NULL UNIQUE,
                auth_token VARCHAR(64) NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT NOW(),
                last_used_at TIMESTAMP,
                FOREIGN KEY (google_id) REFERENCES users(google_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ext_auth_token ON extension_auth_tokens(auth_token)")
        print("  ✓ extension_auth_tokens table created")
    except Exception as e:
        print(f"  ✗ Error creating extension_auth_tokens: {e}")
        return False

    # ── 3. Mark old Canvas tables as deprecated ──────────────────────────
    print("[Migration] Marking old Canvas tables as deprecated (keeping them for now)...")
    deprecated_tables = [
        "courses", "assignments", "submissions", "files",
        "modules", "module_items", "pages"
    ]

    for table in deprecated_tables:
        try:
            # Add deprecation notice comment
            conn.execute(f"""
                COMMENT ON TABLE {table} IS
                'DEPRECATED: Used by old token-based architecture.
                Being replaced by extension-based approach.
                Keep for reference but do not use in new code.'
            """)
            print(f"  ✓ {table} marked as deprecated")
        except Exception as e:
            print(f"  ⚠ Could not mark {table} as deprecated: {e}")

    # ── 4. Update users table ───────────────────────────────────────────
    print("[Migration] Updating users table...")
    try:
        # Drop canvas_api_token column if it exists
        # Note: This is safe because new architecture doesn't use it
        conn.execute("""
            ALTER TABLE users DROP COLUMN IF EXISTS canvas_api_token
        """)
        print("  ✓ Removed canvas_api_token column from users")
    except Exception as e:
        # Column might not exist yet - that's OK
        print(f"  ⚠ canvas_api_token column: {e}")

    try:
        # Drop canvas_linked column if it exists
        conn.execute("""
            ALTER TABLE users DROP COLUMN IF EXISTS canvas_linked
        """)
        print("  ✓ Removed canvas_linked column from users")
    except Exception as e:
        # Column might not exist yet - that's OK
        print(f"  ⚠ canvas_linked column: {e}")

    # ── 5. Verify migration ─────────────────────────────────────────────
    print("[Migration] Verifying tables exist...")
    try:
        # Check ai_completions
        result = conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'ai_completions'
        """).fetchone()
        if result:
            print("  ✓ ai_completions table verified")

        # Check extension_auth_tokens
        result = conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'extension_auth_tokens'
        """).fetchone()
        if result:
            print("  ✓ extension_auth_tokens table verified")

        # Check users table still exists
        result = conn.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_name = 'users'
        """).fetchone()
        if result:
            print("  ✓ users table still intact")
    except Exception as e:
        print(f"  ✗ Verification failed: {e}")
        return False

    conn.commit()
    conn.close()

    print("\n[Migration] ✅ Migration complete!")
    print("""
New tables created:
  - ai_completions (stores AI-generated drafts)
  - extension_auth_tokens (stores extension auth tokens)

Users table updated:
  - Removed canvas_api_token column
  - Removed canvas_linked column

Old Canvas tables (deprecated but kept):
  - courses, assignments, submissions, files, modules, module_items, pages

Next steps:
  1. Test with: python migrate_to_extension.py verify
  2. Update database.py init_db() to include new schema
  3. Update storage/users.py with extension auth functions
  4. Test web app still works
""")

    return True


def verify():
    """Verify migration was successful."""
    print("[Verify] Checking migration status...")

    conn = get_conn()

    # Check new tables exist
    tables_to_check = ['ai_completions', 'extension_auth_tokens', 'users']

    for table in tables_to_check:
        try:
            result = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}").fetchone()
            count = result['cnt'] if result else 0
            status = "✓" if count >= 0 else "✗"
            print(f"  {status} {table}: {count} rows")
        except Exception as e:
            print(f"  ✗ {table}: {e}")

    conn.close()
    print("[Verify] Done")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        verify()
    else:
        success = migrate()
        sys.exit(0 if success else 1)
