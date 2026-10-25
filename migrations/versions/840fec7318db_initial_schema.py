from alembic import op
import sqlalchemy as sa


revision = '840fec7318db'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('locality_name', sa.String(length=120), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('category', sa.String(length=60), nullable=True),
    sa.Column('message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.create_index('ix_alerts_created', ['created_at'], unique=False)

    op.create_table('audit_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('target', sa.String(length=120), nullable=True),
    sa.Column('detail', sa.String(length=500), nullable=True),
    sa.Column('ip', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.create_index('ix_audit_created', ['created_at'], unique=False)

    op.create_table('community_posts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.String(length=80), nullable=False),
    sa.Column('author', sa.String(length=40), nullable=True),
    sa.Column('locality', sa.String(length=80), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('hidden', sa.Boolean(), nullable=False),
    sa.Column('report_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('community_posts', schema=None) as batch_op:
        batch_op.create_index('ix_posts_device_created', ['device_id', 'created_at'], unique=False)
        batch_op.create_index('ix_posts_visible_created', ['hidden', 'created_at'], unique=False)

    op.create_table('sos_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('locality_name', sa.String(length=120), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('issue_type', sa.String(length=60), nullable=False),
    sa.Column('urgency', sa.String(length=20), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('has_photo', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('sos_requests', schema=None) as batch_op:
        batch_op.create_index('ix_sos_created', ['created_at'], unique=False)
        batch_op.create_index('ix_sos_device_created', ['device_id', 'created_at'], unique=False)
        batch_op.create_index('ix_sos_locality_created', ['locality_name', 'created_at'], unique=False)

    op.create_table('trust_scores',
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('reports_filed', sa.Integer(), nullable=False),
    sa.Column('confirmed_accurate', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('device_id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('failed_logins', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('votes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('device_id', sa.String(length=64), nullable=False),
    sa.Column('locality_name', sa.String(length=120), nullable=False),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lon', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.create_index('ix_votes_locality_created', ['locality_name', 'created_at'], unique=False)

    op.create_table('post_reports',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('post_id', sa.Integer(), nullable=False),
    sa.Column('reporter', sa.String(length=120), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['post_id'], ['community_posts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('post_id', 'reporter', name='uq_post_reporter')
    )
    with op.batch_alter_table('post_reports', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_post_reports_post_id'), ['post_id'], unique=False)


def downgrade():
    with op.batch_alter_table('post_reports', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_post_reports_post_id'))

    op.drop_table('post_reports')
    with op.batch_alter_table('votes', schema=None) as batch_op:
        batch_op.drop_index('ix_votes_locality_created')

    op.drop_table('votes')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))

    op.drop_table('users')
    op.drop_table('trust_scores')
    with op.batch_alter_table('sos_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_sos_locality_created')
        batch_op.drop_index('ix_sos_device_created')
        batch_op.drop_index('ix_sos_created')

    op.drop_table('sos_requests')
    with op.batch_alter_table('community_posts', schema=None) as batch_op:
        batch_op.drop_index('ix_posts_visible_created')
        batch_op.drop_index('ix_posts_device_created')

    op.drop_table('community_posts')
    with op.batch_alter_table('audit_events', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_created')

    op.drop_table('audit_events')
    with op.batch_alter_table('alerts', schema=None) as batch_op:
        batch_op.drop_index('ix_alerts_created')

    op.drop_table('alerts')
