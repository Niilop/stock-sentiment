"""Add sentiment_analyses table.

Revision ID: 007_add_sentiment_analyses
Revises: 006_add_content_sentiment_to_stock_news
Create Date: 2026-04-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '007_add_sentiment_analyses'
down_revision = '006_add_content_sentiment'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sentiment_analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('ticker', sa.String(20), nullable=False),
        sa.Column('start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('articles_found', sa.Integer(), nullable=False),
        sa.Column('sentiment_breakdown', sa.JSON(), nullable=False),
        sa.Column('weekly_sentiment', sa.JSON(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sentiment_analyses_id', 'sentiment_analyses', ['id'])
    op.create_index('ix_sentiment_analyses_user_id', 'sentiment_analyses', ['user_id'])
    op.create_index('ix_sentiment_analyses_ticker', 'sentiment_analyses', ['ticker'])


def downgrade() -> None:
    op.drop_index('ix_sentiment_analyses_ticker', table_name='sentiment_analyses')
    op.drop_index('ix_sentiment_analyses_user_id', table_name='sentiment_analyses')
    op.drop_index('ix_sentiment_analyses_id', table_name='sentiment_analyses')
    op.drop_table('sentiment_analyses')
