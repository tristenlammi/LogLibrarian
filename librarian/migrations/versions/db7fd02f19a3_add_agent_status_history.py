"""add_agent_status_history

Revision ID: db7fd02f19a3
Revises: 77cefd323012
Create Date: 2024-05-23 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db7fd02f19a3'
down_revision: Union[str, None] = '77cefd323012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('agent_status_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('status', sa.Text(), nullable=False), # 'online', 'offline'
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    
    # Indexes for efficient querying by agent and time
    op.create_index(
        'idx_agent_status_agent_time', 
        'agent_status_history', 
        ['agent_id', sa.text('started_at DESC')]
    )
    # Filtered index for finding the currently open event (where ended_at IS NULL)
    # Note: SQLite partial indexes supported in recent versions, standard index ok too
    op.create_index(
        'idx_agent_status_current',
        'agent_status_history',
        ['agent_id', 'ended_at']
    )


def downgrade() -> None:
    op.drop_index('idx_agent_status_current', table_name='agent_status_history')
    op.drop_index('idx_agent_status_agent_time', table_name='agent_status_history')
    op.drop_table('agent_status_history')
