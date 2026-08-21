"""Add the PostgreSQL expression index used by lexical retrieval.

SQLite remains supported for local tests; PostgreSQL gets a GIN index so the
full-text candidate query does not devolve into an unbounded chunk scan.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE INDEX ix_chunks_text_fts ON chunks USING gin (to_tsvector('simple', text))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_chunks_text_fts")
