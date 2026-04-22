"""One-off: import 10 placeholder chats from public/InsightXpert into our app.db.

Schema mapping:
  fork.conversations(id, user_id, title, created_at DATETIME, updated_at, is_starred, org_id)
    -> ours(id, user_id, db_id, title, is_starred, created_at INTEGER, updated_at INTEGER)
  fork.messages(id, conversation_id, role, content, chunks_json,
                created_at DATETIME, feedback, feedback_comment,
                input_tokens, output_tokens, generation_time_ms)
    -> ours(id, conversation_id, role, content, chunks_json,
            tokens_in, tokens_out, created_at INTEGER)

Transforms: new UUIDs, datetime -> epoch seconds, map to our admin user,
pattern-match title -> bundled db_id (transactions | toxicology | california_schools).
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

FORK = Path(
    "/Users/nachiket/workspace/github.com/public/InsightXpert/backend/insightxpert.db"
)
OURS = Path(
    "/Users/nachiket/workspace/github.com/private/insightxpert.ai/apps/api/app.db"
)
TARGET_USER_EMAIL = "admin@insightxpert.ai"
N_CONVERSATIONS = 10


def to_epoch(dt_str: str) -> int:
    """Fork stores 'YYYY-MM-DD HH:MM:SS[.ffffff]' in UTC-naive."""
    # Some rows have microseconds, some don't — parse both.
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return int(
                datetime.strptime(dt_str, fmt).replace(tzinfo=timezone.utc).timestamp()
            )
        except ValueError:
            continue
    raise ValueError(f"unparsable datetime: {dt_str!r}")


def pick_db_id(title: str) -> str:
    """Heuristic mapping — fork is UPI-heavy so transactions is the common case."""
    t = title.lower()
    if any(k in t for k in ("molecule", "compound", "atom", "toxic")):
        return "toxicology"
    if any(k in t for k in ("school", "student", "district", "sat ", "enrollment")):
        return "california_schools"
    if any(k in t for k in ("player", "match", "football", "league", "goal")):
        return "european_football_2"
    if any(k in t for k in ("driver", "race", "grand prix", "constructor")):
        return "formula_1"
    if any(k in t for k in ("loan", "client", "account", "savings")):
        return "financial"
    if any(k in t for k in ("debit card", "gas", "consumption")):
        return "debit_card_specializing"
    return "transactions"


def main() -> None:
    fork = sqlite3.connect(f"file:{FORK}?mode=ro", uri=True)
    fork.row_factory = sqlite3.Row
    ours = sqlite3.connect(OURS)
    ours.row_factory = sqlite3.Row

    user_row = ours.execute(
        "SELECT id FROM users WHERE email = ?", (TARGET_USER_EMAIL,)
    ).fetchone()
    if not user_row:
        raise SystemExit(f"target user {TARGET_USER_EMAIL} not found")
    target_user_id = user_row["id"]

    # Pick 10 recent conversations that have ≥2 messages (one user + one assistant).
    candidates = fork.execute(
        """
        SELECT c.id, c.title, c.created_at, c.updated_at, c.is_starred,
               COUNT(m.id) AS msg_count
        FROM conversations c
        JOIN messages m ON m.conversation_id = c.id
        GROUP BY c.id
        HAVING msg_count >= 2
        ORDER BY c.created_at DESC
        LIMIT ?
        """,
        (N_CONVERSATIONS,),
    ).fetchall()

    imported = 0
    msg_total = 0
    for c in candidates:
        new_conv_id = str(uuid.uuid4())
        db_id = pick_db_id(c["title"])
        created_epoch = to_epoch(c["created_at"])
        updated_epoch = to_epoch(c["updated_at"])

        ours.execute(
            """
            INSERT INTO conversations (id, user_id, db_id, title, is_starred,
                                       created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_conv_id,
                target_user_id,
                db_id,
                c["title"][:255],
                int(c["is_starred"] or 0),
                created_epoch,
                updated_epoch,
            ),
        )

        messages = fork.execute(
            """
            SELECT id, role, content, chunks_json, created_at,
                   input_tokens, output_tokens
            FROM messages
            WHERE conversation_id = ?
            ORDER BY created_at ASC
            """,
            (c["id"],),
        ).fetchall()

        for m in messages:
            ours.execute(
                """
                INSERT INTO messages (id, conversation_id, role, content,
                                      chunks_json, tokens_in, tokens_out,
                                      created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    new_conv_id,
                    m["role"],
                    m["content"],
                    m["chunks_json"],
                    m["input_tokens"],
                    m["output_tokens"],
                    to_epoch(m["created_at"]),
                ),
            )
            msg_total += 1

        imported += 1
        print(
            f"  [{imported:2d}] db={db_id:25s} msgs={len(messages):2d}  {c['title'][:70]}"
        )

    ours.commit()
    ours.close()
    fork.close()

    print()
    print(f"imported {imported} conversations, {msg_total} messages into app.db")
    print(f"owner: {TARGET_USER_EMAIL} ({target_user_id})")


if __name__ == "__main__":
    main()
