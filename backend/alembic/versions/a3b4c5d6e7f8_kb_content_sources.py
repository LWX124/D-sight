"""kb_content_sources

Revision ID: a3b4c5d6e7f8
Revises: 7e2c0713f82d
Create Date: 2026-08-02 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, Sequence[str], None] = '7e2c0713f82d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'kb_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('kb_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('source_ref_id', sa.String(length=128), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['kb_id'], ['kb.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('kb_id', 'source_type', 'source_ref_id', name='uq_kb_source'),
    )
    op.create_index(op.f('ix_kb_sources_kb_id'), 'kb_sources', ['kb_id'])
    op.create_index(op.f('ix_kb_sources_source_ref_id'), 'kb_sources', ['source_ref_id'])

    # --- kb_documents 扩展 ---
    op.add_column('kb_documents', sa.Column('title', sa.String(length=512), nullable=True))
    op.add_column('kb_documents', sa.Column('text', sa.Text(), nullable=True))
    op.add_column('kb_documents', sa.Column(
        'source_type', sa.String(length=32), nullable=False, server_default='upload'))
    op.add_column('kb_documents', sa.Column('source_ref_id', sa.String(length=128), nullable=True))
    op.add_column('kb_documents', sa.Column('source_url', sa.String(length=1024), nullable=True))
    op.add_column('kb_documents', sa.Column(
        'published_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('kb_documents', sa.Column(
        'kb_source_id', postgresql.UUID(as_uuid=True), nullable=True))
    # 存量行：title 回填为 filename，然后置 NOT NULL；filename 放宽为可空
    op.execute('UPDATE kb_documents SET title = filename WHERE title IS NULL')
    op.alter_column('kb_documents', 'title', nullable=False)
    op.alter_column('kb_documents', 'filename', existing_type=sa.String(length=255), nullable=True)
    op.create_foreign_key('fk_kb_documents_kb_source', 'kb_documents', 'kb_sources',
                          ['kb_source_id'], ['id'], ondelete='SET NULL')
    op.create_index(op.f('ix_kb_documents_source_type'), 'kb_documents', ['source_type'])
    op.create_index(op.f('ix_kb_documents_published_at'), 'kb_documents', ['published_at'])
    op.create_index(op.f('ix_kb_documents_kb_source_id'), 'kb_documents', ['kb_source_id'])
    op.create_unique_constraint('uq_kb_doc_source', 'kb_documents',
                               ['kb_id', 'source_type', 'source_ref_id'])

    # --- kb_chunks 扩展（向量复用键）---
    op.add_column('kb_chunks', sa.Column('content_hash', sa.String(length=64), nullable=True))
    op.add_column('kb_chunks', sa.Column('embedding_model', sa.String(length=128), nullable=True))
    # 存量行：hash 由 content 现算（pgcrypto 不一定装，用 sha256 内置函数）；
    # 模型名填 'legacy'——存量向量的真实模型无从考证，标记为 legacy 使其永不被复用，
    # 比错填当前模型名安全（错填会让旧模型向量污染新索引）。
    op.execute("UPDATE kb_chunks SET content_hash = encode(sha256(content::bytea), 'hex') "
               "WHERE content_hash IS NULL")
    op.execute("UPDATE kb_chunks SET embedding_model = 'legacy' WHERE embedding_model IS NULL")
    op.alter_column('kb_chunks', 'content_hash',
                    existing_type=sa.String(length=64), nullable=False)
    op.alter_column('kb_chunks', 'embedding_model',
                    existing_type=sa.String(length=128), nullable=False)
    op.create_index(op.f('ix_kb_chunks_content_hash'), 'kb_chunks', ['content_hash'])
    op.create_index(op.f('ix_kb_chunks_embedding_model'), 'kb_chunks', ['embedding_model'])

    # --- threads.ref_id ---
    op.add_column('threads', sa.Column('ref_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_threads_ref_id'), 'threads', ['ref_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_threads_ref_id'), table_name='threads')
    op.drop_column('threads', 'ref_id')

    op.drop_index(op.f('ix_kb_chunks_embedding_model'), table_name='kb_chunks')
    op.drop_index(op.f('ix_kb_chunks_content_hash'), table_name='kb_chunks')
    op.drop_column('kb_chunks', 'embedding_model')
    op.drop_column('kb_chunks', 'content_hash')

    op.drop_constraint('uq_kb_doc_source', 'kb_documents', type_='unique')
    op.drop_index(op.f('ix_kb_documents_kb_source_id'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_published_at'), table_name='kb_documents')
    op.drop_index(op.f('ix_kb_documents_source_type'), table_name='kb_documents')
    op.drop_constraint('fk_kb_documents_kb_source', 'kb_documents', type_='foreignkey')
    op.execute('UPDATE kb_documents SET filename = title WHERE filename IS NULL')
    op.alter_column('kb_documents', 'filename', existing_type=sa.String(length=255), nullable=False)
    for col in ('kb_source_id', 'published_at', 'source_url',
                'source_ref_id', 'source_type', 'text', 'title'):
        op.drop_column('kb_documents', col)

    op.drop_index(op.f('ix_kb_sources_source_ref_id'), table_name='kb_sources')
    op.drop_index(op.f('ix_kb_sources_kb_id'), table_name='kb_sources')
    op.drop_table('kb_sources')
