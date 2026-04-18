"""Seed the database with realistic FMCG B2B data for RetailFlow AI."""
import os
import random
import sqlite3
from datetime import datetime, timedelta
from passlib.context import CryptContext

DB_PATH = os.environ.get("DB_PATH", "data/retailflow.db")
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

random.seed(42)

# ── Products ─────────────────────────────────────────────────────────────────
PRODUCTS = [
    ("Basmati Rice 5kg",      "Grains",      "bag"),
    ("Wheat Flour 10kg",      "Grains",      "bag"),
    ("Sugar 1kg",             "Sweeteners",  "kg"),
    ("Salt 1kg",              "Condiments",  "kg"),
    ("Refined Sunflower Oil", "Oils",        "litre"),
    ("Mustard Oil 1L",        "Oils",        "litre"),
    ("Moong Dal 500g",        "Pulses",      "packet"),
    ("Chana Dal 500g",        "Pulses",      "packet"),
    ("Marie Biscuits 200g",   "Snacks",      "packet"),
    ("Tata Tea Premium 250g", "Beverages",   "packet"),
    ("Nescafe Classic 50g",   "Beverages",   "jar"),
    ("Lux Soap 100g",         "Personal Care","bar"),
    ("Head & Shoulders 180ml","Personal Care","bottle"),
    ("Colgate 200g",          "Personal Care","tube"),
    ("Surf Excel 1kg",        "Detergents",  "packet"),
    ("MDH Masala Mix 100g",   "Spices",      "packet"),
    ("Turmeric Powder 200g",  "Spices",      "packet"),
    ("Red Chilli Powder 200g","Spices",      "packet"),
    ("Coriander Powder 200g", "Spices",      "packet"),
    ("Aashirvaad Atta 5kg",   "Grains",      "bag"),
]

# ── Sellers ───────────────────────────────────────────────────────────────────
SELLERS = [
    ("Sharma Kirana",       "Delhi",     "retail"),
    ("Mehta Wholesale",     "Mumbai",    "wholesale"),
    ("Patel General Store", "Ahmedabad", "retail"),
    ("Singh Traders",       "Ludhiana",  "wholesale"),
    ("Rao Provision",       "Bangalore", "retail"),
    ("Gupta Mart",          "Kanpur",    "retail"),
    ("Khan Superstore",     "Hyderabad", "wholesale"),
    ("Joshi Grocers",       "Pune",      "retail"),
    ("Nair Provision",      "Kochi",     "retail"),
    ("Bose Brothers",       "Kolkata",   "wholesale"),
]

# Cost prices per product (approx)
BASE_COST = [
    220, 350, 42, 18, 130, 155, 55, 52, 32, 110,
    310, 28, 185, 72, 155, 38, 22, 28, 25, 275,
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def rand_date(days_back: int = 365) -> str:
    d = datetime.now() - timedelta(days=random.randint(0, days_back))
    return d.strftime("%Y-%m-%d %H:%M:%S")

def selling_price(cost: float) -> float:
    markup = random.uniform(0.10, 0.35)
    return round(cost * (1 + markup), 2)

def cost_variation(base: float) -> float:
    return round(base * random.uniform(0.90, 1.10), 2)


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ── 1. Products ───────────────────────────────────────────────────────────
    cur.executemany(
        "INSERT OR IGNORE INTO products (name, category, unit) VALUES (?, ?, ?)",
        PRODUCTS,
    )

    # ── 2. Sellers ────────────────────────────────────────────────────────────
    cur.executemany(
        "INSERT OR IGNORE INTO sellers (name, location, sector) VALUES (?, ?, ?)",
        SELLERS,
    )
    conn.commit()

    product_ids = [r[0] for r in cur.execute("SELECT product_id FROM products ORDER BY product_id").fetchall()]
    seller_ids  = [r[0] for r in cur.execute("SELECT seller_id  FROM sellers  ORDER BY seller_id" ).fetchall()]
    # Map product_id → BASE_COST index (safe regardless of autoincrement gaps)
    pid_to_cost_idx = {pid: i for i, pid in enumerate(product_ids)}

    # ── 2b. Users (only create default admin account) ──────────────────────────
    # Admin account with no store association (seller_id = NULL)
    admin_password = pwd_context.hash("admin123")
    cur.execute(
        "INSERT OR IGNORE INTO users (username, hashed_password, seller_id, role) "
        "VALUES (?, ?, ?, ?)",
        ("admin", admin_password, None, "admin")
    )
    for sid in seller_ids:
        cur.execute(
            "INSERT OR IGNORE INTO users (username, hashed_password, seller_id, role) "
            "VALUES (?, ?, ?, ?)",
            (f"seller{sid}", pwd_context.hash(f"seller{sid}123"), sid, "seller")
        )
    conn.commit()

    # ── 3. Inventory (15 items per seller) ────────────────────────────────────
    inventory_rows = []
    for sid in seller_ids:
        chosen = random.sample(product_ids, min(15, len(product_ids)))
        for pid in chosen:
            idx   = pid_to_cost_idx[pid]
            cost  = cost_variation(BASE_COST[idx])
            sprice = selling_price(cost)
            # Varied stock — some low (triggers demand), some high
            stock = random.choices(
                [random.randint(0, 15), random.randint(16, 100), random.randint(101, 500)],
                weights=[20, 50, 30],
            )[0]
            inventory_rows.append((sid, pid, stock, cost, sprice))

    cur.executemany(
        "INSERT OR IGNORE INTO inventory (seller_id, product_id, stock_qty, cost_price, selling_price) "
        "VALUES (?, ?, ?, ?, ?)",
        inventory_rows,
    )
    conn.commit()

    # ── 4. Transactions (150) ─────────────────────────────────────────────────
    REJECTION_REASONS = ["rejected:price_too_low", "rejected:stock_unavailable"]
    txn_rows = []
    for _ in range(150):
        sid = random.choice(seller_ids)
        pid = random.choice(product_ids)
        cost = BASE_COST[pid_to_cost_idx[pid]]
        qty  = random.randint(1, 50)
        # Agreed price: sometimes anomalous
        if random.random() < 0.10:   # 10% anomaly
            agreed = round(cost * random.uniform(1.50, 2.00), 2)
        else:
            agreed = round(cost * random.uniform(1.05, 1.40), 2)
        status = random.choices(
            ["completed", "completed", "completed", REJECTION_REASONS[0], REJECTION_REASONS[1]],
            weights=[60, 20, 10, 5, 5],
        )[0]
        neg_rounds = random.randint(1, 5)
        created = rand_date(90)
        txn_rows.append((None, sid, pid, qty, agreed, status, neg_rounds, created))

    cur.executemany(
        "INSERT INTO transactions (demand_id, seller_id, product_id, qty, agreed_price, status, negotiation_rounds, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        txn_rows,
    )
    conn.commit()

    # ── 5. Demand Posts (50) ──────────────────────────────────────────────────
    demand_rows = []
    for _ in range(50):
        sid    = random.choice(seller_ids)
        pid    = random.choice(product_ids)
        qty    = random.randint(10, 200)
        status = random.choice(["open", "open", "fulfilled", "cancelled"])
        created = rand_date(60)
        demand_rows.append((sid, pid, qty, status, created))

    cur.executemany(
        "INSERT INTO demand_posts (seller_id, product_id, qty_needed, status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        demand_rows,
    )
    conn.commit()

    # ── 6. Transfers (40) ────────────────────────────────────────────────────
    transfer_rows = []
    for _ in range(40):
        from_sid, to_sid = random.sample(seller_ids, 2)
        pid   = random.choice(product_ids)
        qty   = random.randint(5, 100)
        tprice = round(BASE_COST[pid_to_cost_idx[pid]] * random.uniform(1.05, 1.25), 2)
        status = random.choice(["pending", "completed", "completed", "rejected"])
        transfer_rows.append((from_sid, to_sid, pid, qty, tprice, status))

    cur.executemany(
        "INSERT INTO transfers (from_seller_id, to_seller_id, product_id, qty, transfer_price, status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        transfer_rows,
    )
    conn.commit()

    # ── 7. Profits (120 = 12 months × 10 sellers) ────────────────────────────
    profit_rows = []
    for sid in seller_ids:
        for month_offset in range(12):
            month_dt = datetime.now().replace(day=1) - timedelta(days=30 * month_offset)
            month    = month_dt.strftime("%Y-%m")
            revenue  = round(random.uniform(50_000, 300_000), 2)
            cost     = round(revenue * random.uniform(0.60, 0.80), 2)
            profit   = round(revenue - cost, 2)
            profit_rows.append((sid, month, revenue, cost, profit))

    cur.executemany(
        "INSERT OR IGNORE INTO profits (seller_id, month, revenue, cost, profit) "
        "VALUES (?, ?, ?, ?, ?)",
        profit_rows,
    )
    conn.commit()
    conn.close()

    print("Seed data inserted successfully:")
    print(f"  Products     : {len(PRODUCTS)}")
    print(f"  Sellers      : {len(SELLERS)}")
    print(f"  Users        : {1 + len(seller_ids)} (1 admin + seller accounts)")
    print(f"  Inventory    : {len(inventory_rows)}")
    print(f"  Transactions : {len(txn_rows)}")
    print(f"  Demand Posts : {len(demand_rows)}")
    print(f"  Transfers    : {len(transfer_rows)}")
    print(f"  Profits      : {len(profit_rows)}")


if __name__ == "__main__":
    main()
