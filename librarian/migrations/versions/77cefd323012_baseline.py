"""baseline

Revision ID: 77cefd323012
Revises: 
Create Date: 2024-05-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '77cefd323012'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Agents & Metrics ---
    op.create_table('agents',
        sa.Column('agent_id', sa.Text(), primary_key=True),
        sa.Column('hostname', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False),
        sa.Column('public_ip', sa.Text(), server_default=''),
        sa.Column('display_name', sa.Text(), server_default=''),
        sa.Column('os', sa.Text(), server_default=''),
        sa.Column('first_seen', sa.DateTime(), nullable=False),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.Column('enabled', sa.Integer(), server_default='1'),
        sa.Column('connection_address', sa.Text(), server_default=''),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('uptime_seconds', sa.Integer(), server_default='0'),
        sa.Column('tags', sa.Text(), server_default=''),
        sa.Column('auth_token_hash', sa.Text(), server_default=''),
        sa.Column('uptime_window', sa.Text(), server_default='monthly'),
        sa.Column('system_info', sa.Text(), server_default='')
    )

    op.create_table('agent_heartbeats',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('status', sa.Text(), server_default='online', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_heartbeats_agent_timestamp', 'agent_heartbeats', ['agent_id', sa.text('timestamp DESC')])
    op.create_index('idx_heartbeats_timestamp', 'agent_heartbeats', ['timestamp'])
    
    op.create_table('metrics',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('cpu_percent', sa.Float(), nullable=False),
        sa.Column('ram_percent', sa.Float(), nullable=False),
        sa.Column('net_up', sa.Float(), server_default='0.0'),
        sa.Column('net_down', sa.Float(), server_default='0.0'),
        sa.Column('disk_read', sa.Float(), server_default='0.0'),
        sa.Column('disk_write', sa.Float(), server_default='0.0'),
        sa.Column('ping', sa.Float(), server_default='0.0'),
        sa.Column('cpu_temp', sa.Float(), server_default='0.0'),
        sa.Column('load_avg', sa.Float(), server_default='0.0'),
        sa.Column('disk_json', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_agent_timestamp', 'metrics', ['agent_id', 'timestamp'])

    # --- 2. Logs & Templates ---
    op.create_table('log_occurrences',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('template_id', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('variables', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_template_id', 'log_occurrences', ['template_id'])
    op.create_index('idx_timestamp', 'log_occurrences', ['timestamp'])

    op.create_table('templates_metadata',
        sa.Column('template_id', sa.Text(), primary_key=True),
        sa.Column('template_text', sa.Text(), nullable=False),
        sa.Column('first_seen', sa.DateTime(), nullable=False),
        sa.Column('last_seen', sa.DateTime(), nullable=False),
        sa.Column('occurrence_count', sa.Integer(), server_default='1')
    )

    op.create_table('raw_logs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('severity', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('metadata', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_raw_logs_agent_timestamp', 'raw_logs', ['agent_id', sa.text('timestamp DESC')])
    op.create_index('idx_raw_logs_severity', 'raw_logs', ['agent_id', 'severity'])
    op.create_index('idx_raw_logs_source', 'raw_logs', ['agent_id', 'source'])
    op.create_index('idx_raw_logs_cleanup', 'raw_logs', ['agent_id', 'timestamp'])

    # --- 3. Alerts & Snapshots ---
    op.create_table('process_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=False),
        sa.Column('json_data', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_agent_snapshot_timestamp', 'process_snapshots', ['agent_id', 'timestamp'])

    op.create_table('alert_rules',
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), primary_key=True),
        sa.Column('monitor_uptime', sa.Integer(), server_default='1'),
        sa.Column('cpu_percent_threshold', sa.Float()),
        sa.Column('ram_percent_threshold', sa.Float()),
        sa.Column('disk_free_percent_threshold', sa.Float()),
        sa.Column('cpu_temp_threshold', sa.Float()),
        sa.Column('network_bandwidth_mbps_threshold', sa.Float()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    op.create_table('active_alerts',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), nullable=False),
        sa.Column('alert_type', sa.Text(), nullable=False),
        sa.Column('threshold_value', sa.Float()),
        sa.Column('current_value', sa.Float()),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('severity', sa.Text(), server_default='warning'),
        sa.Column('triggered_at', sa.DateTime(), nullable=False),
        sa.Column('resolved_at', sa.DateTime()),
        sa.Column('is_active', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_alert_agent_active', 'active_alerts', ['agent_id', 'is_active'])
    op.create_index('idx_alert_type_active', 'active_alerts', ['alert_type', 'is_active'])
    
    op.create_table('agent_log_settings',
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'), primary_key=True),
        sa.Column('logging_enabled', sa.Integer(), server_default='1'),
        sa.Column('log_level_threshold', sa.Text(), server_default='ERROR'),
        sa.Column('log_retention_days', sa.Integer(), server_default='7'),
        sa.Column('watch_docker_containers', sa.Integer(), server_default='0'),
        sa.Column('watch_system_logs', sa.Integer(), server_default='1'),
        sa.Column('watch_security_logs', sa.Integer(), server_default='1'),
        sa.Column('troubleshooting_mode', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    # --- 4. Settings & Tenants ---
    op.create_table('system_settings',
        sa.Column('key', sa.Text(), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    op.create_table('tenants',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False, unique=True),
        sa.Column('contact_email', sa.Text(), nullable=False),
        sa.Column('max_agents', sa.Integer(), server_default='10'),
        sa.Column('status', sa.Text(), server_default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    op.create_table('api_keys',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('api_key', sa.Text(), nullable=False),
        sa.Column('key_hash', sa.Text(), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('last_used_at', sa.DateTime()),
        sa.Column('is_active', sa.Integer(), server_default='1')
    )

    # --- 5. AI Module ---
    op.create_table('ai_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.CheckConstraint('id = 1', name='check_single_row'),
        sa.Column('provider', sa.Text(), server_default='local'),
        sa.Column('local_model_id', sa.Text(), server_default='gemma-2-2b'),
        sa.Column('openai_key', sa.Text(), server_default=''),
        sa.Column('feature_flags', sa.Text(), server_default='{"daily_briefing": true, "tips": true, "alert_analysis": true, "post_mortem": true}'),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('enabled', sa.Integer(), server_default='0'),
        sa.Column('briefing_time', sa.Text(), server_default='08:00'),
        sa.Column('report_style', sa.Text(), server_default='concise'),
        sa.Column('exec_summary_enabled', sa.Integer(), server_default='0'),
        sa.Column('exec_summary_schedule', sa.Text(), server_default='weekly'),
        sa.Column('exec_summary_day_of_week', sa.Text(), server_default='1'),
        sa.Column('exec_summary_day_of_month', sa.Integer(), server_default='1'),
        sa.Column('exec_summary_period_days', sa.Text(), server_default='30')
    )

    op.create_table('ai_reports',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('type', sa.Text(), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Integer(), server_default='0'),
        sa.Column('metadata', sa.Text(), server_default='{}'),
        sa.Column('agent_id', sa.Text(), sa.ForeignKey('agents.agent_id'))
    )
    op.create_index('idx_ai_reports_type', 'ai_reports', ['type'])
    op.create_index('idx_ai_reports_created', 'ai_reports', [sa.text('created_at DESC')])
    op.create_index('idx_ai_reports_unread', 'ai_reports', ['is_read', sa.text('created_at DESC')])

    op.create_table('ai_model_cache',
        sa.Column('model_id', sa.Text(), primary_key=True),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('file_hash', sa.Text(), server_default=''),
        sa.Column('file_size_mb', sa.Float(), server_default='0'),
        sa.Column('is_downloaded', sa.Integer(), server_default='0'),
        sa.Column('download_progress', sa.Float(), server_default='0'),
        sa.Column('downloaded_at', sa.DateTime()),
        sa.Column('last_used_at', sa.DateTime()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    op.create_table('ai_conversations',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('title', sa.Text(), server_default='New Chat', nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_ai_conversations_updated', 'ai_conversations', [sa.text('updated_at DESC')])

    op.create_table('ai_messages',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('conversation_id', sa.Text(), sa.ForeignKey('ai_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )
    op.create_index('idx_ai_messages_conversation', 'ai_messages', ['conversation_id', sa.text('created_at ASC')])

    # --- 6. Monitors & Reports ---
    op.create_table('monitor_groups',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('tenant_id', sa.Text(), server_default='default', nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('weight', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'))
    )

    op.create_table('bookmarks',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('tenant_id', sa.Text(), server_default='default', nullable=False),
        sa.Column('group_id', sa.Text(), sa.ForeignKey('monitor_groups.id', ondelete='SET NULL')),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('type', sa.Text(), nullable=False),
        sa.Column('target', sa.Text(), nullable=False),
        sa.Column('port', sa.Integer()),
        sa.Column('interval_seconds', sa.Integer(), server_default='60'),
        sa.Column('timeout_seconds', sa.Integer(), server_default='10'),
        sa.Column('active', sa.Integer(), server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('max_retries', sa.Integer(), server_default='1'),
        sa.Column('retry_interval', sa.Integer(), server_default='30'),
        sa.Column('resend_notification', sa.Integer(), server_default='0'),
        sa.Column('upside_down', sa.Integer(), server_default='0'),
        sa.Column('tags', sa.Text()),
        sa.Column('description', sa.Text())
    )

    op.create_table('bookmark_checks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bookmark_id', sa.Text(), sa.ForeignKey('bookmarks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('status', sa.Integer(), nullable=False),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('message', sa.Text())
    )
    op.create_index('idx_bookmark_checks_history', 'bookmark_checks', ['bookmark_id', sa.text('created_at DESC')])

    op.create_table('report_profiles',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('tenant_id', sa.Text(), server_default='default', nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('recipient_emails', sa.Text()),
        sa.Column('monitor_scope_tags', sa.Text()),
        sa.Column('monitor_scope_ids', sa.Text()),
        sa.Column('scribe_scope_tags', sa.Text()),
        sa.Column('scribe_scope_ids', sa.Text()),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('frequency', sa.Text(), server_default='MONTHLY'),
        sa.Column('sla_target', sa.Float(), server_default='99.9'),
        sa.Column('schedule_hour', sa.Integer(), server_default='7')
    )
    op.create_index('idx_report_profiles_tenant', 'report_profiles', ['tenant_id'])

    op.create_table('users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.Text(), unique=True, nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('is_admin', sa.Integer(), server_default='0'),
        sa.Column('is_setup_complete', sa.Integer(), server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('role', sa.Text(), server_default='user'),
        sa.Column('assigned_profile_id', sa.Text(), sa.ForeignKey('report_profiles.id', ondelete='SET NULL'))
    )


def downgrade() -> None:
    # Drop in reverse order of dependency
    op.drop_table('users')
    op.drop_index('idx_report_profiles_tenant', table_name='report_profiles')
    op.drop_table('report_profiles')
    op.drop_index('idx_bookmark_checks_history', table_name='bookmark_checks')
    op.drop_table('bookmark_checks')
    op.drop_table('bookmarks')
    op.drop_table('monitor_groups')
    
    op.drop_index('idx_ai_messages_conversation', table_name='ai_messages')
    op.drop_table('ai_messages')
    op.drop_index('idx_ai_conversations_updated', table_name='ai_conversations')
    op.drop_table('ai_conversations')
    op.drop_table('ai_model_cache')
    op.drop_index('idx_ai_reports_unread', table_name='ai_reports')
    op.drop_index('idx_ai_reports_created', table_name='ai_reports')
    op.drop_index('idx_ai_reports_type', table_name='ai_reports')
    op.drop_table('ai_reports')
    op.drop_table('ai_settings')
    
    op.drop_table('api_keys')
    op.drop_table('tenants')
    op.drop_table('system_settings')
    
    op.drop_table('agent_log_settings')
    op.drop_index('idx_alert_type_active', table_name='active_alerts')
    op.drop_index('idx_alert_agent_active', table_name='active_alerts')
    op.drop_table('active_alerts')
    op.drop_table('alert_rules')
    op.drop_index('idx_agent_snapshot_timestamp', table_name='process_snapshots')
    op.drop_table('process_snapshots')
    
    op.drop_index('idx_raw_logs_cleanup', table_name='raw_logs')
    op.drop_index('idx_raw_logs_source', table_name='raw_logs')
    op.drop_index('idx_raw_logs_severity', table_name='raw_logs')
    op.drop_index('idx_raw_logs_agent_timestamp', table_name='raw_logs')
    op.drop_table('raw_logs')
    
    op.drop_table('templates_metadata')
    op.drop_index('idx_timestamp', table_name='log_occurrences')
    op.drop_index('idx_template_id', table_name='log_occurrences')
    op.drop_table('log_occurrences')
    
    op.create_index('idx_agent_timestamp', 'metrics', ['agent_id', 'timestamp'])
    op.drop_table('metrics')
    
    op.drop_index('idx_heartbeats_timestamp', table_name='agent_heartbeats')
    op.drop_index('idx_heartbeats_agent_timestamp', table_name='agent_heartbeats')
    op.drop_table('agent_heartbeats')
    op.drop_table('agents')
