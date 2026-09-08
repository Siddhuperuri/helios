"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Created: ${create_date}

Rolling-deployment note: during a deploy the previous release and the new one both talk to
this database. A migration must therefore be readable by the code that is still running.
Add nullable columns, backfill, ship the code that uses them, and only remove the old shape
in a later release. Do not drop or rename a column in the same migration that stops using
it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
