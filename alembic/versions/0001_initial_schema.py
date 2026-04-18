"""Initial schema — all RetailFlow tables.

Revision ID: 0001
Revises: 
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
        username        TEXT    NOT NULL UNIQUE,
        hashed_password TEXT    NOT NULL,
        seller_id       INTEGER,
        role            TEXT    NOT NULL DEFAULT 'user',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        category    TEXT NOT NULL,
        unit        TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS sellers (
        seller_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL,
        location    TEXT NOT NULL,
        sector      TEXT NOT NULL
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        inventory_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id     INTEGER NOT NULL,
        product_id    INTEGER NOT NULL,
        stock_qty     INTEGER NOT NULL DEFAULT 0,
        cost_price    REAL    NOT NULL,
        selling_price REAL    NOT NULL,
        FOREIGN KEY (seller_id)  REFERENCES sellers(seller_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id),
        UNIQUE (seller_id, product_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS demand_posts (
        demand_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id   INTEGER NOT NULL,
        product_id  INTEGER NOT NULL,
        qty_needed  INTEGER NOT NULL,
        status      TEXT    NOT NULL DEFAULT 'open',
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (seller_id)  REFERENCES sellers(seller_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        txn_id             INTEGER PRIMARY KEY AUTOINCREMENT,
        demand_id          INTEGER,
        seller_id          INTEGER NOT NULL,
        product_id         INTEGER NOT NULL,
        qty                INTEGER NOT NULL,
        agreed_price       REAL    NOT NULL,
        status             TEXT    NOT NULL DEFAULT 'completed',
        negotiation_rounds INTEGER NOT NULL DEFAULT 1,
        created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
        FOREIGN KEY (seller_id)  REFERENCES sellers(seller_id),
        FOREIGN KEY (product_id) REFERENCES products(product_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS transfers (
        transfer_id     INTEGER PRIMARY KEY AUTOINCREMENT,
        from_seller_id  INTEGER NOT NULL,
        to_seller_id    INTEGER NOT NULL,
        product_id      INTEGER NOT NULL,
        qty             INTEGER NOT NULL,
        transfer_price  REAL    NOT NULL,
        status          TEXT    NOT NULL DEFAULT 'pending',
        FOREIGN KEY (from_seller_id) REFERENCES sellers(seller_id),
        FOREIGN KEY (to_seller_id)   REFERENCES sellers(seller_id),
        FOREIGN KEY (product_id)     REFERENCES products(product_id)
    )
    """)
    op.execute("""
    CREATE TABLE IF NOT EXISTS profits (
        profit_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id  INTEGER NOT NULL,
        month      TEXT    NOT NULL,
        revenue    REAL    NOT NULL,
        cost       REAL    NOT NULL,
        profit     REAL    NOT NULL,
        FOREIGN KEY (seller_id) REFERENCES sellers(seller_id),
        UNIQUE (seller_id, month)
    )
    """)


def downgrade() -> None:
    for table in ["profits", "transfers", "transactions", "demand_posts",
                  "inventory", "users", "sellers", "products"]:
        op.execute(f"DROP TABLE IF EXISTS {table}")
