"""7C-1 additive authentication state; intentionally not a startup helper.

Prerequisite: validated AUTH-03/04 helper-created tables and push_tokens.
This revision never executes those helpers (they include expiry cleanup).
Missing prerequisites or partially applied/conflicting new objects fail closed.
Company PostgreSQL validation and separate execution authorization are pending.
"""
from alembic import op
import sqlalchemy as sa

revision = "auth05_security_foundation"
down_revision = "fc07_schema_compat"
branch_labels = None
depends_on = None

PREREQUISITES = {
    "users": {"id"},
    "auth_otps": {"email_hash", "purpose", "code_digest", "attempts", "expires_at", "resend_available_at", "created_at"},
    "auth_sessions": {"id", "user_id", "expires_at", "revoked_at"},
    "auth_user_token_epochs": {"user_id", "tokens_valid_after"},
    "auth_refresh_consumptions": {"token_id", "user_id", "expires_at", "consumed_at"},
    "auth_password_resets": {"email_hash", "code_digest", "attempts", "expires_at"},
    "push_tokens": {"user_id", "token"},
}
NEW_TABLES = (
    "auth_phone_security", "auth_installations",
    "auth_phone_change_operations", "auth_sos_credentials",
)
ADDITIONS = {
    "auth_otps": ("proof_user_id", "proof_session_id", "proof_circle_id", "proof_target_id", "proof_verified_at"),
    "auth_sessions": ("auth_installation_id",),
    "push_tokens": ("auth_installation_id",),
    "auth_two_factor_settings": ("totp_state", "totp_ciphertext", "totp_key_id", "totp_enrolled_at", "totp_verified_at", "totp_last_step", "totp_disabled_at"),
}


def preflight(inspector):
    """Metadata only. Do not silently adopt an unknown partial deployment."""
    for table, columns in PREREQUISITES.items():
        if not inspector.has_table(table, schema="public"):
            raise RuntimeError(f"AUTH-05 prerequisite missing: {table}; validate AUTH-03/04/push schema first")
        actual = {c["name"] for c in inspector.get_columns(table, schema="public")}
        if not columns <= actual:
            raise RuntimeError(f"AUTH-05 prerequisite columns missing: {table}")
    for table in NEW_TABLES:
        if inspector.has_table(table, schema="public"):
            raise RuntimeError(f"AUTH-05 object already exists: {table}; review partial migration, do not replace")
    for table, columns in ADDITIONS.items():
        if inspector.has_table(table, schema="public"):
            actual = {c["name"] for c in inspector.get_columns(table, schema="public")}
            if actual.intersection(columns):
                raise RuntimeError(f"AUTH-05 extension already exists: {table}; explicit schema review required")
    if inspector.has_table("auth_two_factor_settings", schema="public"):
        actual = {c["name"] for c in inspector.get_columns("auth_two_factor_settings", schema="public")}
        if not {"user_id", "sms_enabled", "phone_hash", "enabled_at", "updated_at"} <= actual:
            raise RuntimeError("AUTH-05 incompatible SMS settings prerequisite")


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    preflight(inspector)
    # All legacy rows remain untouched; nullable extensions preserve old callers.
    op.create_table("auth_phone_security",
        sa.Column("phone_digest", sa.String(64), primary_key=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("phone_digest ~ '^[0-9a-f]{64}$'", name="ck_auth_phone_digest"),
        sa.CheckConstraint("failure_count BETWEEN 0 AND 5", name="ck_auth_phone_failures"),
        sa.CheckConstraint("(failure_count = 5) = (locked_until IS NOT NULL)", name="ck_auth_phone_lock_state"),
        schema="public")
    op.create_table("auth_installations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("identity_digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("notice_state", sa.String(16), nullable=False),
        sa.Column("notice_delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "identity_digest", name="uq_auth_installation_identity"),
        sa.UniqueConstraint("user_id", "id", name="uq_auth_installation_owner"),
        sa.CheckConstraint("identity_digest ~ '^[0-9a-f]{64}$'", name="ck_auth_installation_digest"),
        sa.CheckConstraint("notice_state IN ('not_required','pending','delivered')", name="ck_auth_installation_notice"),
        schema="public")
    for table in ("auth_sessions", "push_tokens"):
        op.add_column(table, sa.Column("auth_installation_id", sa.Uuid()), schema="public")
        op.create_foreign_key(f"fk_{table}_installation", table, "auth_installations",
            ["auth_installation_id"], ["id"], source_schema="public", referent_schema="public", ondelete="SET NULL")
        op.create_index(f"ix_{table}_installation", table, ["user_id", "auth_installation_id"], schema="public")
    # Ownership is also checked on each association/read; legacy push upserts can
    # transfer user_id without violating a composite FK or leaking the old owner.
    for name in ADDITIONS["auth_otps"]:
        op.add_column("auth_otps", sa.Column(name, sa.DateTime(timezone=True) if name == "proof_verified_at" else sa.Uuid()), schema="public")
    op.create_foreign_key("fk_auth_proof_user", "auth_otps", "users", ["proof_user_id"], ["id"], source_schema="public", referent_schema="public", ondelete="CASCADE")
    op.create_foreign_key("fk_auth_proof_session", "auth_otps", "auth_sessions", ["proof_session_id"], ["id"], source_schema="public", referent_schema="public", ondelete="CASCADE")
    op.create_check_constraint("ck_auth_proof_binding", "auth_otps", """
        (proof_user_id IS NULL AND proof_session_id IS NULL AND proof_circle_id IS NULL
         AND proof_target_id IS NULL AND proof_verified_at IS NULL)
        OR (proof_user_id IS NOT NULL AND proof_session_id IS NOT NULL AND proof_verified_at IS NOT NULL
         AND purpose IN ('stepup:ownership_transfer','stepup:circle_delete','stepup:member_remove',
                         'stepup:plan_cancel','stepup:phone_change','stepup:minor_add')
         AND (purpose = 'stepup:phone_change' OR proof_circle_id IS NOT NULL)
         AND (purpose IN ('stepup:circle_delete','stepup:plan_cancel') OR proof_target_id IS NOT NULL)
         AND expires_at > proof_verified_at AND expires_at <= proof_verified_at + INTERVAL '300 seconds')
    """, schema="public")
    op.create_table("auth_phone_change_operations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("public.users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("old_phone_digest", sa.String(64), nullable=False),
        sa.Column("new_phone_digest", sa.String(64), nullable=False),
        sa.Column("recovery", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("old_verified_at", sa.DateTime(timezone=True)),
        sa.Column("new_verified_at", sa.DateTime(timezone=True)),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("eligible_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("owner_notice_state", sa.String(16), nullable=False),
        sa.Column("owner_notified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("old_phone_digest ~ '^[0-9a-f]{64}$' AND new_phone_digest ~ '^[0-9a-f]{64}$' AND old_phone_digest <> new_phone_digest", name="ck_auth_phone_change_digest"),
        sa.CheckConstraint("status IN ('pending','completed','cancelled')", name="ck_auth_phone_change_status"),
        sa.CheckConstraint("(status = 'completed') = (completed_at IS NOT NULL) AND (status = 'cancelled') = (cancelled_at IS NOT NULL)", name="ck_auth_phone_change_terminal"),
        sa.CheckConstraint("eligible_after >= requested_at AND (NOT recovery OR eligible_after >= requested_at + INTERVAL '24 hours')", name="ck_auth_phone_change_delay"),
        sa.CheckConstraint("owner_notice_state IN ('not_required','pending','delivered')", name="ck_auth_phone_change_notice"),
        schema="public")
    op.create_index("uq_auth_phone_change_pending", "auth_phone_change_operations", ["user_id"], unique=True, postgresql_where=sa.text("status = 'pending'"), schema="public")
    op.create_table("auth_sos_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Uuid(), nullable=False),
        sa.Column("credential_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id", "installation_id"], ["public.auth_installations.user_id", "public.auth_installations.id"], ondelete="CASCADE"),
        sa.CheckConstraint("scope = 'emergency:raise'", name="ck_auth_sos_scope"),
        sa.CheckConstraint("credential_digest ~ '^[0-9a-f]{64}$'", name="ck_auth_sos_digest"),
        sa.CheckConstraint("expires_at > issued_at", name="ck_auth_sos_expiry"),
        schema="public")
    op.create_index("ix_auth_sos_installation", "auth_sos_credentials", ["user_id", "installation_id"], schema="public")
    if not inspector.has_table("auth_two_factor_settings", schema="public"):
        # Same lazy SMS table shape, now available before future TOTP enrollment.
        op.create_table("auth_two_factor_settings",
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("public.users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("sms_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("phone_hash", sa.String(64)),
            sa.Column("enabled_at", sa.DateTime(timezone=True)),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")), schema="public")
    for column in (
        sa.Column("totp_state", sa.String(16), nullable=False, server_default="disabled"),
        sa.Column("totp_ciphertext", sa.LargeBinary()), sa.Column("totp_key_id", sa.String(160)),
        sa.Column("totp_enrolled_at", sa.DateTime(timezone=True)),
        sa.Column("totp_verified_at", sa.DateTime(timezone=True)),
        sa.Column("totp_last_step", sa.BigInteger()), sa.Column("totp_disabled_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("auth_two_factor_settings", column, schema="public")
    op.create_check_constraint("ck_auth_totp_state", "auth_two_factor_settings", """
        totp_state IN ('disabled','pending','enabled')
        AND (totp_state = 'disabled' OR (totp_ciphertext IS NOT NULL AND totp_key_id IS NOT NULL AND totp_enrolled_at IS NOT NULL))
        AND (totp_state <> 'enabled' OR (totp_verified_at IS NOT NULL AND totp_last_step IS NOT NULL))
        AND (totp_last_step IS NULL OR totp_last_step >= 0)
    """, schema="public")


def downgrade():
    raise RuntimeError("AUTH-05 is additive security state; destructive downgrade is not supported")
