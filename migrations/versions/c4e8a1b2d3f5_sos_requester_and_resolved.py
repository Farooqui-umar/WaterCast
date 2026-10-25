from alembic import op
import sqlalchemy as sa


revision = 'c4e8a1b2d3f5'
down_revision = 'b7d41e2a9c10'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('sos_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('requester_ip_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('resolved_at', sa.DateTime(), nullable=True))
        batch_op.create_index('ix_sos_requester_ip', ['requester_ip_hash'], unique=False)
        batch_op.create_index('ix_sos_status_created', ['status', 'created_at'], unique=False)


def downgrade():
    with op.batch_alter_table('sos_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_sos_status_created')
        batch_op.drop_index('ix_sos_requester_ip')
        batch_op.drop_column('resolved_at')
        batch_op.drop_column('requester_ip_hash')
