from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from threading import RLock
from uuid import UUID

from typing import Protocol

from app.domain.models import (
    AuditEvent,
    ContextSnapshot,
    Conversation,
    NousWorkspace,
    PlutusWorkspace,
    Proposal,
    TycheWorkspace,
)


class Store(Protocol):
    def save_conversation(self, conversation: Conversation) -> None: ...
    def get_conversation(self, conversation_id: UUID) -> Conversation | None: ...
    def delete_conversation(self, conversation_id: UUID) -> bool: ...
    def save_context(self, conversation_id: UUID, context: ContextSnapshot) -> None: ...
    def save_proposal(self, conversation_id: UUID, proposal: Proposal) -> None: ...
    def get_proposal(self, proposal_id: UUID) -> tuple[UUID, Proposal] | None: ...
    def audit(self, event: AuditEvent) -> None: ...
    def get_audit_events(self, conversation_id: UUID) -> list[AuditEvent]: ...
    def save_tyche_workspace(self, workspace: TycheWorkspace) -> None: ...
    def get_tyche_workspace(self, workspace_id: str, owner_user_id: str) -> TycheWorkspace | None: ...
    def save_plutus_workspace(self, workspace: PlutusWorkspace) -> None: ...
    def get_plutus_workspace(self, workspace_id: str, owner_user_id: str) -> PlutusWorkspace | None: ...
    def save_nous_workspace(self, workspace: NousWorkspace) -> None: ...
    def get_nous_workspace(self, workspace_id: str, owner_user_id: str) -> NousWorkspace | None: ...


class SQLiteStore:
    """Durable repository with JSON domain payloads and indexed ownership columns."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(self.database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    product TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversations_owner_idx
                    ON conversations(workspace_id, owner_user_id, updated_at);

                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_conversation_idx
                    ON audit_events(conversation_id, created_at);

                CREATE TABLE IF NOT EXISTS tyche_workspaces (
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, owner_user_id)
                );
                CREATE TABLE IF NOT EXISTS plutus_workspaces (
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, owner_user_id)
                );
                CREATE TABLE IF NOT EXISTS nous_workspaces (
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(workspace_id, owner_user_id)
                );
                """
            )

    def save_conversation(self, conversation: Conversation) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO conversations(id, workspace_id, owner_user_id, product, payload, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    updated_at=excluded.updated_at
                """,
                (
                    str(conversation.id),
                    conversation.workspace_id,
                    conversation.owner_user_id,
                    conversation.product.value,
                    conversation.model_dump_json(),
                    conversation.updated_at.isoformat(),
                ),
            )

    def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        row = self._connection.execute(
            "SELECT payload FROM conversations WHERE id = ?", (str(conversation_id),)
        ).fetchone()
        return Conversation.model_validate_json(row["payload"]) if row else None

    def delete_conversation(self, conversation_id: UUID) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM conversations WHERE id = ?", (str(conversation_id),)
            )
        return cursor.rowcount > 0

    def save_context(self, conversation_id: UUID, context: ContextSnapshot) -> None:
        if not context.workspace_id or not context.created_by:
            raise ValueError("Context ownership must be assigned by the server")
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO context_snapshots(id, conversation_id, workspace_id, created_by, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                """,
                (
                    str(context.id),
                    str(conversation_id),
                    context.workspace_id,
                    context.created_by,
                    context.model_dump_json(),
                ),
            )

    def save_proposal(self, conversation_id: UUID, proposal: Proposal) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO proposals(id, conversation_id, payload) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                """,
                (str(proposal.id), str(conversation_id), proposal.model_dump_json()),
            )

    def get_proposal(self, proposal_id: UUID) -> tuple[UUID, Proposal] | None:
        row = self._connection.execute(
            "SELECT conversation_id, payload FROM proposals WHERE id = ?", (str(proposal_id),)
        ).fetchone()
        if not row:
            return None
        return UUID(row["conversation_id"]), Proposal.model_validate_json(row["payload"])

    def audit(self, event: AuditEvent) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO audit_events(id, conversation_id, workspace_id, created_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(event.id),
                    str(event.conversation_id),
                    event.workspace_id,
                    event.created_at.isoformat(),
                    event.model_dump_json(),
                ),
            )

    def get_audit_events(self, conversation_id: UUID) -> list[AuditEvent]:
        rows = self._connection.execute(
            "SELECT payload FROM audit_events WHERE conversation_id = ? ORDER BY created_at",
            (str(conversation_id),),
        ).fetchall()
        return [AuditEvent.model_validate_json(row["payload"]) for row in rows]

    def save_tyche_workspace(self, workspace: TycheWorkspace) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO tyche_workspaces(workspace_id, owner_user_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, owner_user_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    workspace.workspace_id,
                    workspace.owner_user_id,
                    workspace.model_dump_json(),
                    workspace.updated_at.isoformat(),
                ),
            )

    def get_tyche_workspace(
        self, workspace_id: str, owner_user_id: str
    ) -> TycheWorkspace | None:
        row = self._connection.execute(
            "SELECT payload FROM tyche_workspaces WHERE workspace_id = ? AND owner_user_id = ?",
            (workspace_id, owner_user_id),
        ).fetchone()
        return TycheWorkspace.model_validate_json(row["payload"]) if row else None

    def save_plutus_workspace(self, workspace: PlutusWorkspace) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO plutus_workspaces(workspace_id, owner_user_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, owner_user_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    workspace.workspace_id,
                    workspace.owner_user_id,
                    workspace.model_dump_json(),
                    workspace.updated_at.isoformat(),
                ),
            )

    def get_plutus_workspace(
        self, workspace_id: str, owner_user_id: str
    ) -> PlutusWorkspace | None:
        row = self._connection.execute(
            "SELECT payload FROM plutus_workspaces WHERE workspace_id = ? AND owner_user_id = ?",
            (workspace_id, owner_user_id),
        ).fetchone()
        return PlutusWorkspace.model_validate_json(row["payload"]) if row else None

    def save_nous_workspace(self, workspace: NousWorkspace) -> None:
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO nous_workspaces(workspace_id, owner_user_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(workspace_id, owner_user_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    workspace.workspace_id,
                    workspace.owner_user_id,
                    workspace.model_dump_json(),
                    workspace.updated_at.isoformat(),
                ),
            )

    def get_nous_workspace(
        self, workspace_id: str, owner_user_id: str
    ) -> NousWorkspace | None:
        row = self._connection.execute(
            "SELECT payload FROM nous_workspaces WHERE workspace_id = ? AND owner_user_id = ?",
            (workspace_id, owner_user_id),
        ).fetchone()
        return NousWorkspace.model_validate_json(row["payload"]) if row else None

    def close(self) -> None:
        self._connection.close()


class PostgresStore:
    """PostgreSQL repository selected with a postgresql:// DATABASE_URL."""

    def __init__(self, database_url: str) -> None:
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("Install the psycopg production dependency for PostgreSQL") from exc
        self._psycopg = psycopg
        self._connection = psycopg.connect(database_url)
        self._connection.autocommit = True
        self._migrate()

    def _migrate(self) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    id UUID PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    product TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                );
                CREATE INDEX IF NOT EXISTS conversations_owner_idx
                    ON conversations(workspace_id, owner_user_id, updated_at);
                CREATE TABLE IF NOT EXISTS context_snapshots (
                    id UUID PRIMARY KEY,
                    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS proposals (
                    id UUID PRIMARY KEY,
                    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    payload JSONB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id UUID PRIMARY KEY,
                    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    workspace_id TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    payload JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_conversation_idx
                    ON audit_events(conversation_id, created_at);
                CREATE TABLE IF NOT EXISTS tyche_workspaces (
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY(workspace_id, owner_user_id)
                );
                CREATE TABLE IF NOT EXISTS plutus_workspaces (
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY(workspace_id, owner_user_id)
                );
                CREATE TABLE IF NOT EXISTS nous_workspaces (
                    workspace_id TEXT NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY(workspace_id, owner_user_id)
                );
                """
            )

    def save_conversation(self, conversation: Conversation) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO conversations(id, workspace_id, owner_user_id, product, payload, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    conversation.id,
                    conversation.workspace_id,
                    conversation.owner_user_id,
                    conversation.product.value,
                    conversation.model_dump_json(),
                    conversation.updated_at,
                ),
            )

    def get_conversation(self, conversation_id: UUID) -> Conversation | None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT payload FROM conversations WHERE id = %s", (conversation_id,))
            row = cursor.fetchone()
        return Conversation.model_validate(row[0]) if row else None

    def delete_conversation(self, conversation_id: UUID) -> bool:
        with self._connection.cursor() as cursor:
            cursor.execute("DELETE FROM conversations WHERE id = %s", (conversation_id,))
            return cursor.rowcount > 0

    def save_context(self, conversation_id: UUID, context: ContextSnapshot) -> None:
        if not context.workspace_id or not context.created_by:
            raise ValueError("Context ownership must be assigned by the server")
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO context_snapshots(id, conversation_id, workspace_id, created_by, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                """,
                (context.id, conversation_id, context.workspace_id, context.created_by, context.model_dump_json()),
            )

    def save_proposal(self, conversation_id: UUID, proposal: Proposal) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO proposals(id, conversation_id, payload) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload
                """,
                (proposal.id, conversation_id, proposal.model_dump_json()),
            )

    def get_proposal(self, proposal_id: UUID) -> tuple[UUID, Proposal] | None:
        with self._connection.cursor() as cursor:
            cursor.execute("SELECT conversation_id, payload FROM proposals WHERE id = %s", (proposal_id,))
            row = cursor.fetchone()
        return (row[0], Proposal.model_validate(row[1])) if row else None

    def audit(self, event: AuditEvent) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO audit_events(id, conversation_id, workspace_id, created_at, payload)
                VALUES (%s, %s, %s, %s, %s::jsonb)
                """,
                (event.id, event.conversation_id, event.workspace_id, event.created_at, event.model_dump_json()),
            )

    def get_audit_events(self, conversation_id: UUID) -> list[AuditEvent]:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM audit_events WHERE conversation_id = %s ORDER BY created_at",
                (conversation_id,),
            )
            rows = cursor.fetchall()
        return [AuditEvent.model_validate(row[0]) for row in rows]

    def save_tyche_workspace(self, workspace: TycheWorkspace) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO tyche_workspaces(workspace_id, owner_user_id, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT(workspace_id, owner_user_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    workspace.workspace_id,
                    workspace.owner_user_id,
                    workspace.model_dump_json(),
                    workspace.updated_at,
                ),
            )

    def get_tyche_workspace(
        self, workspace_id: str, owner_user_id: str
    ) -> TycheWorkspace | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM tyche_workspaces WHERE workspace_id = %s AND owner_user_id = %s",
                (workspace_id, owner_user_id),
            )
            row = cursor.fetchone()
        return TycheWorkspace.model_validate(row[0]) if row else None

    def save_plutus_workspace(self, workspace: PlutusWorkspace) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO plutus_workspaces(workspace_id, owner_user_id, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT(workspace_id, owner_user_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    workspace.workspace_id,
                    workspace.owner_user_id,
                    workspace.model_dump_json(),
                    workspace.updated_at,
                ),
            )

    def get_plutus_workspace(
        self, workspace_id: str, owner_user_id: str
    ) -> PlutusWorkspace | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM plutus_workspaces WHERE workspace_id = %s AND owner_user_id = %s",
                (workspace_id, owner_user_id),
            )
            row = cursor.fetchone()
        return PlutusWorkspace.model_validate(row[0]) if row else None

    def save_nous_workspace(self, workspace: NousWorkspace) -> None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO nous_workspaces(workspace_id, owner_user_id, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, %s)
                ON CONFLICT(workspace_id, owner_user_id) DO UPDATE SET
                    payload=excluded.payload, updated_at=excluded.updated_at
                """,
                (
                    workspace.workspace_id,
                    workspace.owner_user_id,
                    workspace.model_dump_json(),
                    workspace.updated_at,
                ),
            )

    def get_nous_workspace(
        self, workspace_id: str, owner_user_id: str
    ) -> NousWorkspace | None:
        with self._connection.cursor() as cursor:
            cursor.execute(
                "SELECT payload FROM nous_workspaces WHERE workspace_id = %s AND owner_user_id = %s",
                (workspace_id, owner_user_id),
            )
            row = cursor.fetchone()
        return NousWorkspace.model_validate(row[0]) if row else None

    def close(self) -> None:
        self._connection.close()


def build_store() -> Store:
    database_url = os.getenv("DATABASE_URL", "")
    if database_url.startswith(("postgresql://", "postgres://")):
        return PostgresStore(database_url)
    if database_url.startswith("sqlite:///"):
        return SQLiteStore(database_url.removeprefix("sqlite:///"))
    if database_url:
        raise ValueError("DATABASE_URL must use postgresql:// or sqlite:///")
    return SQLiteStore(os.getenv("COPILOT_DB_PATH", "work/copilots.db"))


store = build_store()
