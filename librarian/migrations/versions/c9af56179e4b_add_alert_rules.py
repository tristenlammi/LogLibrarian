"""add_alert_rules

Revision ID: c9af56179e4b
Revises: e1a2b3c4d5e6
Create Date: 2026-01-04 05:32:07.556195

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9af56179e4b'
down_revision: Union[str, Sequence[str], None] = 'e1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alert_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(), server_default='default', nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),  # 'global' or 'agent'
        sa.Column('target_id', sa.String(), nullable=False), # 'global' or agent_uuid
        sa.Column('metric', sa.String(), nullable=False), # 'cpu', 'ram', 'disk', 'status'
        sa.Column('operator', sa.String(), nullable=False), # 'gt', 'lt', 'eq'
        sa.Column('threshold', sa.Float(), nullable=False),
        sa.Column('channels', sa.String(), server_default='[]', nullable=False), # JSON list of channel IDs
        sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('alert_rules')
