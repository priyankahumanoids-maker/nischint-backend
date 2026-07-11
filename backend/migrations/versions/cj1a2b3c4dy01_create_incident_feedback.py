"""NISCH-009 — Guardian feedback loop on safety incidents.

`incident_feedback` rows store one verdict per (incident, guardian).
Latest verdict wins via UPSERT semantics; the forensic trail in
`safety_incident_events` keeps the audit history.

Verdicts:
  * 'mark_safe'      — guardian asserts no real risk
  * 'confirm_risk'   — guardian asserts the alert is real
  * 'report_anomaly' — guardian flags something unusual but won't commit
                       to safe/risk; goes to human review queue.

Privacy/integrity constraints:
  * UNIQUE(incident_id, guardian_id) — one verdict per pair (UPSERT).
  * ON DELETE CASCADE on incident_id  — deleting an incident wipes its
    feedback. TODO(GDPR): revisit when erasure sprint lands.
  * ON DELETE CASCADE on guardian_id  — deleting a user wipes their
    verdicts (do not orphan).
  * `note` capped at 200 chars at the API layer (column allows NULL).
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "cj1a2b3c4dy01"
down_revision = "bi1a2b3c4dx01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incident_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True),
                  primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("incident_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("safety_incidents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("guardian_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("verdict", sa.String(20), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )

    # UPSERT contract: one verdict per (incident, guardian).
    op.create_unique_constraint(
        "uq_incident_feedback_incident_guardian",
        "incident_feedback", ["incident_id", "guardian_id"],
    )

    # Aggregation hot-path index: aggregator counts per incident.
    op.create_index(
        "idx_incident_feedback_incident",
        "incident_feedback", ["incident_id"],
    )

    # Audit hot-path: per-guardian recent verdicts (e.g. for anti-spam).
    op.create_index(
        "idx_incident_feedback_guardian_created",
        "incident_feedback", ["guardian_id", "created_at"],
    )

    # Verdict CHECK — defends against rogue inserts even if app layer
    # forgets to validate.
    op.create_check_constraint(
        "ck_incident_feedback_verdict",
        "incident_feedback",
        "verdict IN ('mark_safe', 'confirm_risk', 'report_anomaly')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_incident_feedback_verdict",
                       "incident_feedback", type_="check")
    op.drop_index("idx_incident_feedback_guardian_created",
                  table_name="incident_feedback")
    op.drop_index("idx_incident_feedback_incident",
                  table_name="incident_feedback")
    op.drop_constraint("uq_incident_feedback_incident_guardian",
                       "incident_feedback", type_="unique")
    op.drop_table("incident_feedback")
