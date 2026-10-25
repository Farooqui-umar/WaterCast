from alembic import op
import sqlalchemy as sa


revision = 'b7d41e2a9c10'
down_revision = '840fec7318db'
branch_labels = None
depends_on = None


def upgrade():
    op.create_index('ix_sos_lower_locality_created', 'sos_requests', [sa.text('lower(locality_name)'), 'created_at'])
    op.create_index('ix_votes_lower_locality_created', 'votes', [sa.text('lower(locality_name)'), 'created_at'])
    op.create_index('ix_votes_created', 'votes', ['created_at'])
    op.create_index('ix_votes_device_created', 'votes', ['device_id', 'created_at'])
    op.create_index('ix_alerts_lower_locality_created', 'alerts', [sa.text('lower(locality_name)'), 'created_at'])


def downgrade():
    op.drop_index('ix_alerts_lower_locality_created', table_name='alerts')
    op.drop_index('ix_votes_device_created', table_name='votes')
    op.drop_index('ix_votes_created', table_name='votes')
    op.drop_index('ix_votes_lower_locality_created', table_name='votes')
    op.drop_index('ix_sos_lower_locality_created', table_name='sos_requests')
