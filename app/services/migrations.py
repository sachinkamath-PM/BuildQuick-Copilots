from __future__ import annotations

SQLITE_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
            product TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS conversations_owner_idx ON conversations(workspace_id, owner_user_id, updated_at);
        CREATE TABLE IF NOT EXISTS context_snapshots (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL, created_by TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            payload TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS audit_conversation_idx ON audit_events(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS tyche_workspaces (
            workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, payload TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(workspace_id, owner_user_id)
        );
        CREATE TABLE IF NOT EXISTS plutus_workspaces (
            workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, payload TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(workspace_id, owner_user_id)
        );
        CREATE TABLE IF NOT EXISTS nous_workspaces (
            workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, payload TEXT NOT NULL,
            updated_at TEXT NOT NULL, PRIMARY KEY(workspace_id, owner_user_id)
        );
    """),
    (2, """
        CREATE TABLE IF NOT EXISTS guest_workspaces (
            workspace_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS guest_workspaces_expiry_idx ON guest_workspaces(expires_at);
    """),
)

POSTGRES_MIGRATIONS: tuple[tuple[int, str], ...] = (
    (1, """
        CREATE TABLE IF NOT EXISTS conversations (
            id UUID PRIMARY KEY, workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
            product TEXT NOT NULL, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX IF NOT EXISTS conversations_owner_idx ON conversations(workspace_id, owner_user_id, updated_at);
        CREATE TABLE IF NOT EXISTS context_snapshots (
            id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL, created_by TEXT NOT NULL, payload JSONB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            payload JSONB NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            id UUID PRIMARY KEY, conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            workspace_id TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, payload JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS audit_conversation_idx ON audit_events(conversation_id, created_at);
        CREATE TABLE IF NOT EXISTS tyche_workspaces (
            workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(workspace_id, owner_user_id)
        );
        CREATE TABLE IF NOT EXISTS plutus_workspaces (
            workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(workspace_id, owner_user_id)
        );
        CREATE TABLE IF NOT EXISTS nous_workspaces (
            workspace_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, payload JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(workspace_id, owner_user_id)
        );
    """),
    (2, """
        CREATE TABLE IF NOT EXISTS guest_workspaces (
            workspace_id TEXT PRIMARY KEY, expires_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX IF NOT EXISTS guest_workspaces_expiry_idx ON guest_workspaces(expires_at);
    """),
)

LATEST_SCHEMA_VERSION = 2
