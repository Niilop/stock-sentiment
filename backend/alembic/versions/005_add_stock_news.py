"""Add stock_news table for Alpaca news storage.

Revision ID: 005_add_stock_news
Revises: 004_add_background_jobs
Create Date: 2026-04-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '005_add_stock_news'
down_revision = '004_add_background_jobs'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stock_news',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('alpaca_id', sa.String(50), nullable=False),
        sa.Column('ticker', sa.String(20), nullable=False),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('url', sa.String(1000), nullable=False),
        sa.Column('source', sa.String(100), nullable=False),
        sa.Column('author', sa.String(255), nullable=True),
        sa.Column('symbols', sa.JSON(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_stock_news_id', 'stock_news', ['id'])
    op.create_index('ix_stock_news_alpaca_id', 'stock_news', ['alpaca_id'], unique=True)
    op.create_index('ix_stock_news_ticker', 'stock_news', ['ticker'])
    op.create_index('ix_stock_news_published_at', 'stock_news', ['published_at'])


def downgrade() -> None:
    op.drop_index('ix_stock_news_published_at', table_name='stock_news')
    op.drop_index('ix_stock_news_ticker', table_name='stock_news')
    op.drop_index('ix_stock_news_alpaca_id', table_name='stock_news')
    op.drop_index('ix_stock_news_id', table_name='stock_news')
    op.drop_table('stock_news')
