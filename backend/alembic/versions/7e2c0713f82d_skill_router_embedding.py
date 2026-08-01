"""skill_router_embedding

Revision ID: 7e2c0713f82d
Revises: d8381ce6d30d
Create Date: 2026-07-30 22:51:38.742117

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7e2c0713f82d'
down_revision: Union[str, Sequence[str], None] = '4dfd3378d565'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # tags: 存量行无值，用空 JSONB 数组作 server_default 再收紧
    op.add_column(
        'skills',
        sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb"))
    )
    op.add_column('skills', sa.Column('embedding', pgvector.sqlalchemy.Vector(1024), nullable=True))
    op.add_column('skills', sa.Column('embedding_source_hash', sa.String(length=64), nullable=True))
    op.execute(
        "CREATE INDEX ix_skills_embedding ON skills "
        "USING hnsw (embedding vector_cosine_ops) "
        "WHERE embedding IS NOT NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_skills_embedding")
    op.drop_column('skills', 'embedding_source_hash')
    op.drop_column('skills', 'embedding')
    op.drop_column('skills', 'tags')
