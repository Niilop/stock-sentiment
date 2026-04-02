"""Add content and sentiment columns to stock_news.

Revision ID: 006_add_content_sentiment
Revises: 005_add_stock_news
Create Date: 2026-04-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '006_add_content_sentiment'
down_revision = '005_add_stock_news'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('stock_news', sa.Column('content', sa.Text(), nullable=True))
    op.add_column('stock_news', sa.Column('sentiment', sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column('stock_news', 'sentiment')
    op.drop_column('stock_news', 'content')
