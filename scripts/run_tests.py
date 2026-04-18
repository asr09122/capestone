"""
RetailFlow AI - Automated API Test Suite
Covers all 11 scenarios from TEST_SCENARIOS.md

Run:
    python scripts/seed_test_data.py   # fresh data first
    python scripts/run_tests.py

Prerequisites: API must be running on http://localhost:8000
"""
import sys
import sqlite3
import requests
import re as _re

# Force UTF-8 output so Windows cp1252 terminal doesn't crash on rupee/em-dash
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE   = "http://localhost:8000"
DB     = "data/retailflow.db"
PASSED = []
FAILED = []

# Colours (ANSI - work in most terminals)
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def ok(name, detail=""):
    PASSED.append(name)
    print(f"  {GREEN}[PASS]{RESET}  {name}" + (f"  - {detail}" if detail else ""))


def fail(name, detail=""):
    FAILED.append(name)
    print(f"  {RED}[FAIL]{RESET}  {name}" + (f"  - {detail}" if detail else ""))


def section(title):
    print(f"\n{BOLD}{YELLOW}{'-'*60}{RESET}")
    print(f"{BOLD}{YELLOW}  {title}{RESET}")
    print(f"{BOLD}{YELLOW}{'-'*60}{RESET}")


# ── Auth helpers ──────────────────────────────────────────────────────────────
def login(username, password):
    r = requests.post(f"{BASE}/auth/token",
                      data={"username": username, "password": password}, timeout=10)
    assert r.status_code == 200, f"Login failed for {username}: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def db(sql, params=()):
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Pre-flight ────────────────────────────────────────────────────────────────
section("0. Pre-flight checks")
try:
    r = requests.get(f"{BASE}/health", timeout=5)
    if r.status_code == 200:
        ok("API reachable", f"db={r.json().get('db_exists')} faiss={r.json().get('faiss_index_exists')}")
    else:
        fail("API reachable", f"status {r.status_code}")
        sys.exit(1)
except Exception as e:
    fail("API reachable", str(e))
    print(f"\n{RED}  Cannot reach API. Start it with: uv run uvicorn app.main:app --reload{RESET}")
    sys.exit(1)

# Login all accounts
try:
    H1 = login("seller1", "seller1123")   # Sharma Kirana — buyer
    H2 = login("seller2", "seller2123")   # Mehta Wholesale — main supplier
    H3 = login("seller3", "seller3123")   # Patel — partial supplier
    H5 = login("seller5", "seller5123")   # Rao Provision — partial supplier
    HA = login("admin",   "admin123")     # Admin
    ok("All accounts authenticated")
except AssertionError as e:
    fail("Account authentication", str(e))
    sys.exit(1)


# ── Scenario 1: Billing above threshold ──────────────────────────────────────
section("Scenario 1 — Billing above threshold (no demand)")
r = requests.post(f"{BASE}/billing",
                  json={"seller_id": 1, "product_id": 1, "quantity": 5, "price": 275.0},
                  headers=H1, timeout=60)
if r.status_code == 200:
    data = r.json()
    if not data.get("paused"):
        ok("S1: no interrupt triggered", f"result: {data.get('result','')[:60]}")
    else:
        fail("S1: should not pause", f"paused at {data.get('next_step')}")
else:
    fail("S1: billing request", f"HTTP {r.status_code} — {r.text[:120]}")

# Check DB
inv = db("SELECT stock_qty FROM inventory WHERE seller_id=1 AND product_id=1")
if inv and int(inv[0]["stock_qty"]) == 245:
    ok("S1: stock decremented to 245")
else:
    stock = inv[0]["stock_qty"] if inv else "no row"
    fail("S1: stock check", f"expected 245, got {stock}")


# ── Scenario 2: Billing below threshold → demand → single supplier ────────────
section("Scenario 2 — Billing triggers demand + single supplier")

# Step 1: trigger billing on low-stock product
r = requests.post(f"{BASE}/billing",
                  json={"seller_id": 1, "product_id": 5, "quantity": 3, "price": 160.0},
                  headers=H1, timeout=60)
if r.status_code == 200 and r.json().get("paused") and r.json().get("next_step") == "ask_price":
    data2 = r.json()
    ok("S2: paused at ask_price", f"stock={data2.get('stock')} threshold={data2.get('threshold')}")
else:
    fail("S2: should pause at ask_price", f"HTTP {r.status_code} paused={r.json().get('paused') if r.status_code==200 else 'N/A'}")
    data2 = None

# Step 2: set price
if data2:
    tid = data2["thread_id"]
    r2 = requests.post(f"{BASE}/billing/{tid}/set-price",
                       json={"qty": 20, "target_price": 155.0},
                       headers=H1, timeout=60)
    if r2.status_code == 200 and r2.json().get("paused") and r2.json().get("next_step") == "choose_seller":
        data2b = r2.json()
        candidates = (data2b.get("prompt") or {}).get("candidates", [])
        ok("S2: paused at choose_seller", f"{len(candidates)} candidates found")
    else:
        fail("S2: set-price", f"HTTP {r2.status_code} — {r2.text[:120]}")
        data2b = None
else:
    data2b = None

# Step 3: choose single supplier (Mehta = seller_id 2)
if data2b:
    tid = data2b["thread_id"]
    candidates = (data2b.get("prompt") or {}).get("candidates", [])
    mehta = next((c for c in candidates if c.get("seller_id") == 2), None)
    if mehta:
        r3 = requests.post(f"{BASE}/billing/{tid}/choose-seller",
                           json={"seller_id": 2, "offer_price": 155.0, "qty": 20},
                           headers=H1, timeout=60)
        if r3.status_code == 200 and not r3.json().get("paused"):
            d = r3.json()
            ok("S2: transfer created", f"transfer_id={d.get('transfer_id')} qty={d.get('transfer_qty')}")
            S2_TRANSFER_ID = d.get("transfer_id")
        else:
            fail("S2: choose-seller", f"HTTP {r3.status_code} — {r3.text[:120]}")
            S2_TRANSFER_ID = None
    else:
        fail("S2: Mehta not in candidates", f"candidates: {[c.get('seller_name') for c in candidates]}")
        S2_TRANSFER_ID = None
else:
    S2_TRANSFER_ID = None

# Step 4: supplier approves
if S2_TRANSFER_ID:
    stock_before = db("SELECT stock_qty FROM inventory WHERE seller_id=2 AND product_id=5")
    r4 = requests.post(f"{BASE}/respond-transfer/{S2_TRANSFER_ID}",
                       json={"approved": True}, headers=H2, timeout=30)
    if r4.status_code == 200:
        stock_after = db("SELECT stock_qty FROM inventory WHERE seller_id=2 AND product_id=5")
        buyer_inv   = db("SELECT stock_qty, cost_price FROM inventory WHERE seller_id=1 AND product_id=5")
        stock_delta = int(stock_before[0]["stock_qty"]) - int(stock_after[0]["stock_qty"])
        if stock_delta == 20:
            ok("S2: supplier approved → stock moved", f"Mehta −20, Sharma +20")
        else:
            fail("S2: stock delta wrong", f"delta={stock_delta}, expected 20")
        if "below_cost_warning" in r4.json():
            if not r4.json()["below_cost_warning"]:
                ok("S2: no below-cost warning (selling > cost as expected)")
            else:
                fail("S2: unexpected below-cost warning", r4.json().get("below_cost_message", "")[:60])
        else:
            fail("S2: below_cost_warning field missing from approval response")
    else:
        fail("S2: supplier approval", f"HTTP {r4.status_code} — {r4.text[:120]}")


# ── Scenario 3: Price anomaly ─────────────────────────────────────────────────
section("Scenario 3 — Price anomaly detection")
# Re-seed product5 stock so we can bill without going below threshold
# (just need enough stock — reseed inventory row)
conn = sqlite3.connect(DB)
conn.execute("UPDATE inventory SET stock_qty=50 WHERE seller_id=1 AND product_id=5")
conn.commit(); conn.close()

r = requests.post(f"{BASE}/billing",
                  json={"seller_id": 1, "product_id": 5, "quantity": 1, "price": 220.0},
                  headers=H1, timeout=120)
if r.status_code == 200:
    data = r.json()
    if data.get("anomaly_detected"):
        ok("S3: anomaly detected", f"explanation present={bool(data.get('anomaly_explanation'))}")
        # Verify selling_price NOT updated to 220
        inv = db("SELECT selling_price FROM inventory WHERE seller_id=1 AND product_id=5")
        sp = float(inv[0]["selling_price"]) if inv else -1
        if sp != 220.0:
            ok("S3: selling_price NOT updated to anomalous price", f"still ₹{sp:.2f}")
        else:
            fail("S3: selling_price was wrongly updated to anomalous ₹220")
    else:
        fail("S3: anomaly not detected", f"avg_price={data.get('market_avg_price')}")
else:
    fail("S3: billing request", f"HTTP {r.status_code}")


# ── Scenario 4: Split order ───────────────────────────────────────────────────
section("Scenario 4 — Split order (no single seller has enough)")
# Reset stock: seller1 product5 = 5 (low), sellers 2/3/5 have limited stock
conn = sqlite3.connect(DB)
conn.execute("UPDATE inventory SET stock_qty=5  WHERE seller_id=1 AND product_id=5")
conn.execute("UPDATE inventory SET stock_qty=40 WHERE seller_id=2 AND product_id=5")
conn.execute("UPDATE inventory SET stock_qty=35 WHERE seller_id=3 AND product_id=5")
conn.execute("UPDATE inventory SET stock_qty=30 WHERE seller_id=5 AND product_id=5")
conn.commit(); conn.close()

r = requests.post(f"{BASE}/billing",
                  json={"seller_id": 1, "product_id": 5, "quantity": 2, "price": 160.0},
                  headers=H1, timeout=60)
if r.status_code == 200 and r.json().get("paused") and r.json().get("next_step") == "ask_price":
    tid = r.json()["thread_id"]
    r2  = requests.post(f"{BASE}/billing/{tid}/set-price",
                        json={"qty": 100, "target_price": 156.0},
                        headers=H1, timeout=60)
    if r2.status_code == 200 and r2.json().get("paused"):
        prompt    = r2.json().get("prompt") or {}
        split     = prompt.get("split_plan")
        if split and split.get("picks"):
            ok("S4: split plan generated", f"{len(split['picks'])} suppliers, total={split['total_qty']}, avg=₹{split['avg_unit_price']}")
            # Confirm split
            r3 = requests.post(f"{BASE}/billing/{tid}/choose-seller",
                               json={"seller_id": 0, "offer_price": split["avg_unit_price"], "use_split": True},
                               headers=H1, timeout=60)
            if r3.status_code == 200:
                d = r3.json()
                tids = d.get("transfer_ids") or []
                ok("S4: split transfers created", f"{len(tids)} transfer IDs: {tids}")
            else:
                fail("S4: confirm split", f"HTTP {r3.status_code} — {r3.text[:120]}")
        else:
            fail("S4: no split plan in prompt", f"candidates={len(prompt.get('candidates',[]))}")
    else:
        fail("S4: set-price", f"HTTP {r2.status_code}")
else:
    fail("S4: billing should trigger ask_price", f"HTTP {r.status_code} paused={r.json().get('paused') if r.status_code==200 else 'N/A'}")


# ── Scenario 5: Manual demand ─────────────────────────────────────────────────
section("Scenario 5 — Manual demand (no billing)")
r = requests.post(f"{BASE}/demand",
                  json={"seller_id": 1, "product_id": 9, "quantity": 30},
                  headers=H1, timeout=60)
if r.status_code == 200 and r.json().get("paused") and r.json().get("next_step") == "ask_price":
    tid = r.json()["thread_id"]
    ok("S5: demand paused at ask_price")
    r2 = requests.post(f"{BASE}/demand/{tid}/set-price",
                       json={"qty": 30, "target_price": 37.0},
                       headers=H1, timeout=60)
    if r2.status_code == 200 and r2.json().get("paused") and r2.json().get("next_step") == "choose_seller":
        prompt = r2.json().get("prompt") or {}
        cands  = prompt.get("candidates", [])
        ok("S5: choose_seller prompt received", f"{len(cands)} candidates")
        # pick Rao (seller5)
        rao = next((c for c in cands if c.get("seller_id") == 5), cands[0] if cands else None)
        if rao:
            r3 = requests.post(f"{BASE}/demand/{tid}/choose-seller",
                               json={"seller_id": rao["seller_id"], "offer_price": 37.5, "qty": 25},
                               headers=H1, timeout=60)
            if r3.status_code == 200:
                ok("S5: demand transfer created", f"transfer_id={r3.json().get('transfer_id')}")
            else:
                fail("S5: choose-seller", f"HTTP {r3.status_code} — {r3.text[:120]}")
        else:
            fail("S5: no candidates found")
    else:
        fail("S5: set-price", f"HTTP {r2.status_code} paused={r2.json().get('paused') if r2.status_code==200 else 'N/A'}")
else:
    fail("S5: demand paused at ask_price", f"HTTP {r.status_code}")


# ── Scenario 6: Negotiation (counter-offer + buyer counter) ──────────────────
section("Scenario 6 — Negotiation (counter-offer flow)")
# Create a fresh transfer via demand
conn = sqlite3.connect(DB)
conn.execute("UPDATE inventory SET stock_qty=8 WHERE seller_id=1 AND product_id=9")
conn.execute("UPDATE inventory SET stock_qty=40 WHERE seller_id=2 AND product_id=9")
conn.commit(); conn.close()

r = requests.post(f"{BASE}/demand",
                  json={"seller_id": 1, "product_id": 9, "quantity": 10},
                  headers=H1, timeout=60)
NEG_TRANSFER_ID = None
if r.status_code == 200 and r.json().get("paused"):
    tid = r.json()["thread_id"]
    r2 = requests.post(f"{BASE}/demand/{tid}/set-price",
                       json={"qty": 10, "target_price": 36.0}, headers=H1, timeout=60)
    if r2.status_code == 200 and r2.json().get("paused"):
        prompt = r2.json().get("prompt") or {}
        cands  = prompt.get("candidates", [])
        mehta  = next((c for c in cands if c.get("seller_id") == 2), cands[0] if cands else None)
        if mehta:
            r3 = requests.post(f"{BASE}/demand/{tid}/choose-seller",
                               json={"seller_id": 2, "offer_price": 36.0, "qty": 10},
                               headers=H1, timeout=60)
            if r3.status_code == 200:
                NEG_TRANSFER_ID = r3.json().get("transfer_id")

if NEG_TRANSFER_ID:
    # Supplier sends counter
    r_ctr = requests.post(f"{BASE}/negotiate-transfer/{NEG_TRANSFER_ID}",
                          json={"counter_price": 38.0}, headers=H2, timeout=15)
    if r_ctr.status_code == 200 and r_ctr.json().get("status") == "countered":
        ok("S6: supplier counter sent", "status=countered")
    else:
        fail("S6: supplier counter", f"HTTP {r_ctr.status_code} status={r_ctr.json().get('status') if r_ctr.status_code==200 else 'N/A'}")

    # Buyer counters back
    r_bc = requests.post(f"{BASE}/buyer-counter/{NEG_TRANSFER_ID}",
                         json={"counter_price": 37.0}, headers=H1, timeout=15)
    if r_bc.status_code == 200 and r_bc.json().get("status") == "pending":
        ok("S6: buyer counter sent back", f"new price=₹{r_bc.json().get('transfer_price')}")
    else:
        fail("S6: buyer counter", f"HTTP {r_bc.status_code} status={r_bc.json().get('status') if r_bc.status_code==200 else 'N/A'}")

    # Supplier approves at ₹37
    r_app = requests.post(f"{BASE}/respond-transfer/{NEG_TRANSFER_ID}",
                          json={"approved": True}, headers=H2, timeout=15)
    if r_app.status_code == 200:
        ok("S6: supplier approved after negotiation", f"final price=₹{r_app.json().get('transfer_price')}")
    else:
        fail("S6: approval after negotiation", f"HTTP {r_app.status_code}")
else:
    fail("S6: could not create negotiation transfer")


# ── Scenario 7: Transfer rejection ───────────────────────────────────────────
section("Scenario 7 — Transfer rejection")
conn = sqlite3.connect(DB)
conn.execute("UPDATE inventory SET stock_qty=5 WHERE seller_id=1 AND product_id=9")
conn.execute("UPDATE inventory SET stock_qty=40 WHERE seller_id=2 AND product_id=9")
conn.commit(); conn.close()

r = requests.post(f"{BASE}/demand",
                  json={"seller_id": 1, "product_id": 9, "quantity": 10},
                  headers=H1, timeout=60)
REJ_TRANSFER_ID = None
REJ_SUPPLIER_HDR = None
if r.status_code == 200 and r.json().get("paused"):
    tid = r.json()["thread_id"]
    r2 = requests.post(f"{BASE}/demand/{tid}/set-price",
                       json={"qty": 10, "target_price": 36.0}, headers=H1, timeout=60)
    if r2.status_code == 200 and r2.json().get("paused"):
        cands = (r2.json().get("prompt") or {}).get("candidates", [])
        # Always choose seller2 (Mehta) to ensure we have the right header for rejection
        chosen = next((c for c in cands if c.get("seller_id") == 2), cands[0] if cands else None)
        if chosen:
            chosen_sid = chosen["seller_id"]
            # Map seller_id → auth header
            HDR_MAP = {1: H1, 2: H2, 3: H3, 5: H5}
            REJ_SUPPLIER_HDR = HDR_MAP.get(chosen_sid, H2)
            r3 = requests.post(f"{BASE}/demand/{tid}/choose-seller",
                               json={"seller_id": chosen_sid, "offer_price": 36.0, "qty": 10},
                               headers=H1, timeout=60)
            if r3.status_code == 200:
                REJ_TRANSFER_ID = r3.json().get("transfer_id")

if REJ_TRANSFER_ID:
    demand_id_before = db(f"SELECT demand_id FROM transfers WHERE transfer_id={REJ_TRANSFER_ID}")[0]["demand_id"]
    r_rej = requests.post(f"{BASE}/respond-transfer/{REJ_TRANSFER_ID}",
                          json={"approved": False}, headers=REJ_SUPPLIER_HDR, timeout=15)
    if r_rej.status_code == 200 and r_rej.json().get("status") == "rejected":
        ok("S7: transfer rejected")
        if demand_id_before:
            demand = db(f"SELECT status FROM demand_posts WHERE demand_id={demand_id_before}")
            if demand and demand[0]["status"] == "open":
                ok("S7: demand post stays open after rejection")
            else:
                status_val = demand[0]["status"] if demand else "not found"
                fail("S7: demand status", f"expected 'open', got '{status_val}'")
    else:
        fail("S7: rejection", f"HTTP {r_rej.status_code} - {r_rej.text[:100]}")
else:
    fail("S7: could not create rejection transfer")


# ── Scenario 8: Below-cost warning ───────────────────────────────────────────
section("Scenario 8 — Below-cost warning on approval")
conn = sqlite3.connect(DB)
conn.execute("UPDATE inventory SET stock_qty=5,  selling_price=36.0 WHERE seller_id=1 AND product_id=9")
conn.execute("UPDATE inventory SET stock_qty=40, cost_price=30.0  WHERE seller_id=2 AND product_id=9")
conn.commit(); conn.close()

r = requests.post(f"{BASE}/demand",
                  json={"seller_id": 1, "product_id": 9, "quantity": 10},
                  headers=H1, timeout=60)
if r.status_code == 200 and r.json().get("paused"):
    tid = r.json()["thread_id"]
    r2 = requests.post(f"{BASE}/demand/{tid}/set-price",
                       json={"qty": 10, "target_price": 45.0}, headers=H1, timeout=60)
    if r2.status_code == 200 and r2.json().get("paused"):
        cands = (r2.json().get("prompt") or {}).get("candidates", [])
        mehta = next((c for c in cands if c.get("seller_id") == 2), cands[0] if cands else None)
        if mehta:
            r3 = requests.post(f"{BASE}/demand/{tid}/choose-seller",
                               json={"seller_id": 2, "offer_price": 45.0, "qty": 10},
                               headers=H1, timeout=60)
            if r3.status_code == 200:
                tid2 = r3.json().get("transfer_id")
                r_app = requests.post(f"{BASE}/respond-transfer/{tid2}",
                                      json={"approved": True}, headers=H2, timeout=15)
                if r_app.status_code == 200:
                    d = r_app.json()
                    if d.get("below_cost_warning"):
                        ok("S8: below-cost warning shown", d.get("below_cost_message", "")[:80])
                    else:
                        fail("S8: expected below-cost warning", f"selling=₹36 cost=₹45 warning={d.get('below_cost_warning')}")
                else:
                    fail("S8: approval", f"HTTP {r_app.status_code}")
            else:
                fail("S8: choose-seller", f"HTTP {r3.status_code}")
        else:
            fail("S8: no candidates")
    else:
        fail("S8: set-price step")
else:
    fail("S8: demand start")


# ── Scenario 9: SQL analytics ─────────────────────────────────────────────────
section("Scenario 9 — SQL Analytics agent")
queries = [
    "Which seller has the most profit this month?",
    "Show total revenue for all sellers",
    "List sellers with stock below 20 units",
]
for q in queries:
    # SQL route is GET /sql?query=...  (not POST /sql/query)
    r = requests.get(f"{BASE}/sql", params={"query": q}, headers=HA, timeout=120)
    if r.status_code == 200:
        answer = r.json().get("result", "") or r.json().get("answer", "")
        ok(f"S9: SQL - '{q[:40]}...'", f"{len(str(answer))} chars returned")
    else:
        fail(f"S9: SQL - '{q[:40]}...'", f"HTTP {r.status_code} - {r.text[:80]}")


# ── Scenario 10: RAG explainability ──────────────────────────────────────────
section("Scenario 10 — RAG Explainability agent")
import re
rag_queries = [
    ("Why is my profit low for Sunflower Oil?", 1, 5),
    ("Explain the pricing rules for retail stores", 1, None),
]
for (q, sid, pid) in rag_queries:
    payload = {"query": q, "seller_id": sid}
    if pid:
        payload["product_id"] = pid
    r = requests.post(f"{BASE}/ask", json=payload, headers=H1, timeout=120)
    if r.status_code == 200:
        answer = r.json().get("answer", "")
        citations = re.findall(r"【[^】]*】", answer)
        if citations:
            fail(f"S10: RAG citation leak — '{q[:40]}'", f"found: {citations}")
        else:
            ok(f"S10: RAG clean — '{q[:40]}'", f"{len(answer)} chars, no citation markers")
    else:
        fail(f"S10: RAG — '{q[:40]}'", f"HTTP {r.status_code} — {r.text[:80]}")


# ── Scenario 11: No suppliers available ──────────────────────────────────────
section("Scenario 11 — No suppliers available")
conn = sqlite3.connect(DB)
conn.execute("UPDATE inventory SET stock_qty=0 WHERE product_id=2 AND seller_id!=1")
conn.execute("UPDATE inventory SET stock_qty=5 WHERE seller_id=1 AND product_id=2")
conn.commit(); conn.close()

r = requests.post(f"{BASE}/demand",
                  json={"seller_id": 1, "product_id": 2, "quantity": 20},
                  headers=H1, timeout=60)
if r.status_code == 200 and r.json().get("paused"):
    tid = r.json()["thread_id"]
    r2 = requests.post(f"{BASE}/demand/{tid}/set-price",
                       json={"qty": 20, "target_price": 350.0}, headers=H1, timeout=60)
    if r2.status_code == 200:
        d2 = r2.json()
        # Success = not paused AND (has a result message OR next_step signals done/no-suppliers)
        graceful = not d2.get("paused") and (
            d2.get("result") or d2.get("next_step") in ("done", None)
        )
        if graceful:
            msg = d2.get("result") or f"next_step={d2.get('next_step')}"
            ok("S11: no suppliers found - workflow ended gracefully", str(msg)[:80])
        else:
            fail("S11: expected graceful end", f"paused={d2.get('paused')} next={d2.get('next_step')}")
    else:
        fail("S11: set-price", f"HTTP {r2.status_code}")
else:
    fail("S11: demand start", f"HTTP {r.status_code}")


# ── Summary ───────────────────────────────────────────────────────────────────
section("RESULTS")
total = len(PASSED) + len(FAILED)
print(f"\n  {GREEN}{len(PASSED)}/{total} passed{RESET}   {RED}{len(FAILED)}/{total} failed{RESET}\n")
if FAILED:
    print(f"  {RED}Failed:{RESET}")
    for f in FAILED:
        print(f"    • {f}")
print()
sys.exit(0 if not FAILED else 1)
