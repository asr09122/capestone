"""Normalize roles and add compatibility indexes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-17 14:00:00.000000
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role='seller' WHERE role IS NULL OR role != 'admin'")
    op.execute("UPDATE transactions SET status='rejected' WHERE status LIKE 'rejected:%'")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_role ON users(role)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_seller_id ON users(seller_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_inventory_seller_product ON inventory(seller_id, product_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_inventory_product_stock ON inventory(product_id, stock_qty)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_demand_seller_product_status ON demand_posts(seller_id, product_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_demand_status_created ON demand_posts(status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transactions_seller_product_created ON transactions(seller_id, product_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transactions_status_created ON transactions(status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transfers_from_status ON transfers(from_seller_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transfers_to_status ON transfers(to_seller_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transfers_product_status ON transfers(product_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_transfers_demand_id ON transfers(demand_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_profits_seller_month ON profits(seller_id, month)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_profits_seller_month")
    op.execute("DROP INDEX IF EXISTS ix_transfers_demand_id")
    op.execute("DROP INDEX IF EXISTS ix_transfers_product_status")
    op.execute("DROP INDEX IF EXISTS ix_transfers_to_status")
    op.execute("DROP INDEX IF EXISTS ix_transfers_from_status")
    op.execute("DROP INDEX IF EXISTS ix_transactions_status_created")
    op.execute("DROP INDEX IF EXISTS ix_transactions_seller_product_created")
    op.execute("DROP INDEX IF EXISTS ix_demand_status_created")
    op.execute("DROP INDEX IF EXISTS ix_demand_seller_product_status")
    op.execute("DROP INDEX IF EXISTS ix_inventory_product_stock")
    op.execute("DROP INDEX IF EXISTS ix_inventory_seller_product")
    op.execute("DROP INDEX IF EXISTS ix_users_seller_id")
    op.execute("DROP INDEX IF EXISTS ix_users_role")
