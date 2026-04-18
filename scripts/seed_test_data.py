"""
Seed controlled test data for manual QA of all RetailFlow features.

Run:  python scripts/seed_test_data.py
Then: python scripts/run_tests.py   (optional automated checks)

Accounts created
----------------
admin / admin123          — full access
seller1 / seller1123      — Sharma Kirana        (buyer in most scenarios)
seller2 / seller2123      — Mehta Wholesale       (supplier with large stock)
seller3 / seller3123      — Patel General Store   (supplier with partial stock)
seller4 / seller4123      — Singh Traders         (no stock → tests no-supplier path)
seller5 / seller5123      — Rao Provision         (for split scenario)

Test products used
------------------
product_id 1  — Basmati Rice 5kg     (cost ₹220, sell ₹275)
product_id 5  — Refined Sunflower Oil(cost ₹130, sell ₹160)
product_id 9  — Marie Biscuits 200g  (cost ₹32,  sell ₹40)
"""

import os
import sqlite3
from passlib.context import CryptContext

DB_PATH = os.environ.get("DB_PATH", "data/retailflow.db")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def reset_and_seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ── Wipe tables (order respects FK) ──────────────────────────────────────
    for tbl in ["profits", "transfers", "transactions", "demand_posts",
                "inventory", "users", "sellers", "products"]:
        cur.execute(f"DELETE FROM {tbl}")
    conn.commit()

    # ── Products ─────────────────────────────────────────────────────────────
    products = [
        (1, "Basmati Rice 5kg",       "Grains",       "bag"),
        (2, "Wheat Flour 10kg",       "Grains",       "bag"),
        (3, "Sugar 1kg",              "Sweeteners",   "kg"),
        (4, "Salt 1kg",               "Condiments",   "kg"),
        (5, "Refined Sunflower Oil",  "Oils",         "litre"),
        (6, "Mustard Oil 1L",         "Oils",         "litre"),
        (7, "Moong Dal 500g",         "Pulses",       "packet"),
        (8, "Chana Dal 500g",         "Pulses",       "packet"),
        (9, "Marie Biscuits 200g",    "Snacks",       "packet"),
        (10,"Tata Tea Premium 250g",  "Beverages",    "packet"),
    ]
    cur.executemany(
        "INSERT INTO products (product_id, name, category, unit) VALUES (?,?,?,?)",
        products,
    )

    # ── Sellers ───────────────────────────────────────────────────────────────
    sellers = [
        (1, "Sharma Kirana",       "Delhi",     "retail"),
        (2, "Mehta Wholesale",     "Delhi",     "wholesale"),   # same city → location_match bonus
        (3, "Patel General Store", "Ahmedabad", "retail"),
        (4, "Singh Traders",       "Ludhiana",  "wholesale"),
        (5, "Rao Provision",       "Delhi",     "retail"),
    ]
    cur.executemany(
        "INSERT INTO sellers (seller_id, name, location, sector) VALUES (?,?,?,?)",
        sellers,
    )

    # ── Users ─────────────────────────────────────────────────────────────────
    users = [
        ("admin",   pwd_context.hash("admin123"),   None, "admin"),
        ("seller1", pwd_context.hash("seller1123"), 1,    "seller"),
        ("seller2", pwd_context.hash("seller2123"), 2,    "seller"),
        ("seller3", pwd_context.hash("seller3123"), 3,    "seller"),
        ("seller4", pwd_context.hash("seller4123"), 4,    "seller"),
        ("seller5", pwd_context.hash("seller5123"), 5,    "seller"),
    ]
    cur.executemany(
        "INSERT INTO users (username, hashed_password, seller_id, role) VALUES (?,?,?,?)",
        users,
    )

    # ── Inventory ─────────────────────────────────────────────────────────────
    # Full inventory: all 5 sellers x all 10 products
    # seller_id, product_id, stock_qty, cost_price, selling_price
    inventory = [
        # ── Sharma Kirana (seller 1) — buyer in tests ──────────────────────
        (1,  1,  250, 220.00, 275.00),   # Basmati Rice    — high stock
        (1,  2,   45, 340.00, 420.00),   # Wheat Flour
        (1,  3,  120,  44.00,  55.00),   # Sugar
        (1,  4,  200,  18.00,  24.00),   # Salt
        (1,  5,    8, 130.00, 160.00),   # Sunflower Oil   — LOW (triggers demand)
        (1,  6,   30,  95.00, 120.00),   # Mustard Oil
        (1,  7,   55,  55.00,  70.00),   # Moong Dal
        (1,  8,   40,  50.00,  65.00),   # Chana Dal
        (1,  9,    5,  32.00,  40.00),   # Marie Biscuits  — LOW (triggers demand)
        (1, 10,   18, 110.00, 140.00),   # Tata Tea

        # ── Mehta Wholesale (seller 2) — main supplier ──────────────────────
        (2,  1,  200, 215.00, 260.00),
        (2,  2,  150, 330.00, 400.00),
        (2,  3,  300,  42.00,  52.00),
        (2,  4,  500,  16.00,  22.00),
        (2,  5,   80, 125.00, 155.00),
        (2,  6,   60,  90.00, 115.00),
        (2,  7,  120,  52.00,  66.00),
        (2,  8,  100,  48.00,  62.00),
        (2,  9,   40,  30.00,  38.00),
        (2, 10,   75, 105.00, 135.00),

        # ── Patel General Store (seller 3) — partial supplier ───────────────
        (3,  1,   80, 217.00, 265.00),
        (3,  2,   60, 335.00, 410.00),
        (3,  3,  150,  43.00,  53.00),
        (3,  4,  250,  17.00,  23.00),
        (3,  5,   35, 128.00, 158.00),
        (3,  6,   25,  92.00, 118.00),
        (3,  7,   70,  53.00,  68.00),
        (3,  8,   55,  49.00,  63.00),
        (3,  9,   20,  31.00,  39.00),
        (3, 10,   45, 108.00, 138.00),

        # ── Singh Traders (seller 4) — no product-5 stock ──────────────────
        (4,  1,  100, 218.00, 268.00),
        (4,  2,   90, 338.00, 415.00),
        (4,  3,  200,  43.50,  54.00),
        (4,  4,  300,  17.50,  23.50),
        (4,  5,    0, 130.00, 160.00),   # out-of-stock → tests no-supplier path
        (4,  6,   40,  93.00, 119.00),
        (4,  7,   85,  54.00,  69.00),
        (4,  8,   65,  50.00,  64.00),
        (4,  9,   15,  31.50,  39.50),
        (4, 10,   50, 107.00, 136.00),

        # ── Rao Provision (seller 5) — split test supplier ──────────────────
        (5,  1,  120, 216.00, 262.00),
        (5,  2,   70, 332.00, 405.00),
        (5,  3,  180,  42.50,  52.50),
        (5,  4,  350,  16.50,  22.50),
        (5,  5,   50, 127.00, 157.00),
        (5,  6,   35,  91.00, 116.00),
        (5,  7,   90,  53.50,  67.50),
        (5,  8,   70,  49.50,  63.50),
        (5,  9,   25,  29.50,  37.50),
        (5, 10,   55, 106.00, 134.00),
    ]
    cur.executemany(
        "INSERT INTO inventory (seller_id, product_id, stock_qty, cost_price, selling_price) "
        "VALUES (?,?,?,?,?)",
        inventory,
    )

    # ── Transactions (30-day history so threshold/analytics work) ────────────
    # Seller 1 sells ~3 units of product 5 per day → daily_avg≈3 → threshold≈21
    import random
    from datetime import datetime, timedelta
    random.seed(99)

    # product prices for transaction seeding
    product_prices = {
        1: 275.00, 2: 420.00, 3: 55.00, 4: 24.00, 5: 160.00,
        6: 120.00, 7: 70.00,  8: 65.00, 9: 40.00, 10: 140.00,
    }
    # daily sales volumes per product per seller
    daily_sales = {
        (1, 1): (1, 5),  (1, 5): (2, 4),  (1, 9): (1, 2),
        (1, 2): (0, 2),  (1, 3): (2, 6),  (1, 4): (3, 8),
        (2, 1): (1, 3),  (2, 5): (1, 3),  (2, 9): (1, 2),
        (3, 1): (0, 2),  (3, 5): (1, 2),
        (5, 5): (1, 2),  (5, 9): (0, 2),
    }

    txns = []
    base = datetime.now()
    for day in range(30):
        dt = (base - timedelta(days=day)).strftime("%Y-%m-%d %H:%M:%S")
        for (sid, pid), (lo, hi) in daily_sales.items():
            n_sales = random.randint(lo, hi)
            for _ in range(n_sales):
                txns.append((sid, pid, random.randint(1, 3),
                              product_prices.get(pid, 50.0), "completed", 1, dt))

    cur.executemany(
        "INSERT INTO transactions (seller_id, product_id, qty, agreed_price, status, negotiation_rounds, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        txns,
    )

    # ── Profits (last 6 months — enough for trend charts) ────────────────────
    profits = []
    for sid in range(1, 6):
        for mo in range(6):
            month = (datetime.now().replace(day=1) - timedelta(days=30*mo)).strftime("%Y-%m")
            # Each seller grows differently — realistic variation
            base = 40000 + sid * 8000
            seasonal_bump = (3 - abs(mo - 2)) * 2000   # peaks around 2 months ago
            rev  = round(base + seasonal_bump + random.randint(-2000, 2000), 2)
            cost = round(rev * (0.65 + sid * 0.01), 2)  # margin varies by seller
            profits.append((sid, month, rev, cost, round(rev - cost, 2)))
    cur.executemany(
        "INSERT OR IGNORE INTO profits (seller_id, month, revenue, cost, profit) VALUES (?,?,?,?,?)",
        profits,
    )

    conn.commit()
    conn.close()
    print("[OK] Test data seeded. See TEST_SCENARIOS.md for step-by-step test guide.")


if __name__ == "__main__":
    reset_and_seed()
