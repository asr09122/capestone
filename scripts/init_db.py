"""Initialize the SQLite database schema."""
import os
import sqlite3


DB_PATH = os.environ.get("DB_PATH", "data/kirananet.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    seller_id       INTEGER,
    role            TEXT NOT NULL DEFAULT 'seller',
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id)
);

CREATE TABLE IF NOT EXISTS products (
    product_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,
    unit         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sellers (
    seller_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    location     TEXT NOT NULL,
    sector       TEXT NOT NULL
);

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
);

CREATE TABLE IF NOT EXISTS demand_posts (
    demand_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id    INTEGER NOT NULL,
    product_id   INTEGER NOT NULL,
    qty_needed   INTEGER NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'open',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (seller_id)  REFERENCES sellers(seller_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

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
);

CREATE TABLE IF NOT EXISTS transfers (
    transfer_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    from_seller_id     INTEGER NOT NULL,
    to_seller_id       INTEGER NOT NULL,
    product_id         INTEGER NOT NULL,
    qty                INTEGER NOT NULL,
    transfer_price     REAL    NOT NULL,
    status             TEXT    NOT NULL DEFAULT 'pending',
    demand_id          INTEGER,
    counter_price      REAL,
    negotiation_rounds INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (from_seller_id) REFERENCES sellers(seller_id),
    FOREIGN KEY (to_seller_id)   REFERENCES sellers(seller_id),
    FOREIGN KEY (product_id)     REFERENCES products(product_id)
);

CREATE TABLE IF NOT EXISTS profits (
    profit_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id  INTEGER NOT NULL,
    month      TEXT    NOT NULL,
    revenue    REAL    NOT NULL,
    cost       REAL    NOT NULL,
    profit     REAL    NOT NULL,
    FOREIGN KEY (seller_id) REFERENCES sellers(seller_id),
    UNIQUE (seller_id, month)
);
"""


def main():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"Database initialised at {DB_PATH}")


if __name__ == "__main__":
    main()
