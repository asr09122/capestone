"""Add demand_id, counter_price, negotiation_rounds to transfers.

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-02 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # demand_id — which open demand this transfer fulfils (nullable)
    op.execute("ALTER TABLE transfers ADD COLUMN demand_id INTEGER")
    # counter_price — buyer's counter-offer per unit (nullable)
    op.execute("ALTER TABLE transfers ADD COLUMN counter_price REAL")
    # negotiation_rounds — number of rounds exchanged
    op.execute("ALTER TABLE transfers ADD COLUMN negotiation_rounds INTEGER NOT NULL DEFAULT 1")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN before 3.35.
    # Recreate the table without the new columns.
    op.execute("""
    CREATE TABLE transfers_backup AS
        SELECT transfer_id, from_seller_id, to_seller_id, product_id,
               qty, transfer_price, status
        FROM transfers
    """)
    op.execute("DROP TABLE transfers")
    op.execute("ALTER TABLE transfers_backup RENAME TO transfers")
