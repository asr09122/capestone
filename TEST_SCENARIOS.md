# RetailFlow AI — Manual Test Scenarios

## Setup
```bash
python scripts/seed_test_data.py   # wipes + re-seeds controlled data
uvicorn app.main:app --reload      # start API  (port 8000)
streamlit run streamlit_app.py     # start UI   (port 8501)
```

## Test Accounts
| Username | Password | Role | Store |
|---|---|---|---|
| admin | admin123 | admin | — |
| seller1 | seller1123 | seller | Sharma Kirana (buyer) |
| seller2 | seller2123 | seller | Mehta Wholesale (main supplier) |
| seller3 | seller3123 | seller | Patel General Store (partial supplier) |
| seller4 | seller4123 | seller | Singh Traders (no product 5) |
| seller5 | seller5123 | seller | Rao Provision (partial supplier) |

---

## Scenario 1 — Billing, stock stays above threshold ✅
**Goal:** Bill a product that still has plenty of stock; no demand triggered.

1. Login as **seller1**
2. Go to **Billing**
3. Select **Basmati Rice 5kg** (Product 1) — shows stock 250, price ₹275
4. Set qty = 5, price = ₹275 → click **Process Billing**
5. **Expected:** "Billing completed. Stock is still above the reorder threshold" — no popup, workflow ends immediately.
6. Stock should now show 245.

---

## Scenario 2 — Billing triggers demand + single supplier ✅
**Goal:** Bill enough of a low-stock product to go below threshold; pick one supplier.

1. Login as **seller1**
2. Go to **Billing**
3. Select **Refined Sunflower Oil** (Product 5) — stock 8, price ₹160
4. Set qty = 3, price = ₹160 → **Process Billing**
5. **Expected:** Paused at **Step 1 — Confirm qty & target price**
   - current stock ≈ 5, threshold ≈ 21 (7 × daily avg ≈ 3)
   - suggested qty ≈ 16+
6. Set qty = 20, target price = ₹155 → **Confirm**
7. **Expected:** Paused at **Step 2 — Pick a supplier**
   - Candidate table shows Mehta (₹155), Patel (₹158), Rao (₹157)
   - Best single match = Mehta (closest to ₹155)
8. Select **Mehta Wholesale**, offer ₹155, qty 20 → **Send request**
9. **Expected:** Transfer request created (PENDING). Demand post also created.

### Verify as seller2 (supplier):
10. Login as **seller2** → go to **Transfers**
11. See incoming request from Sharma Kirana for 20 units of Sunflower Oil @ ₹155
12. Click **Approve & Ship**
13. **Expected:** Mehta stock −20, Sharma stock +20, Sharma cost_price updated to weighted avg.
14. If Sharma's selling_price (₹160) > new cost (₹155) → no warning.

---

## Scenario 3 — Price anomaly detected ⚠️
**Goal:** Bill at a price >20% above 30-day average; see anomaly explanation.

1. Login as **seller1** → Billing
2. Select **Refined Sunflower Oil**, qty = 1, price = **₹220** (30-day avg ≈ ₹160 → +37%)
3. **Expected:** After submitting, anomaly box appears with RAG explanation.

---

## Scenario 4 — Billing triggers demand, split order (no single seller has enough) 🔀
**Goal:** Request 100 units when Mehta has 80, Patel has 35, Rao has 50 → split plan.

*(Re-seed first if previous tests consumed stock: `python scripts/seed_test_data.py`)*

1. Login as **seller1** → Billing
2. Select **Refined Sunflower Oil**, qty = 5, price = ₹160
3. After stock drops to 3 (below threshold):
   - Confirm qty = **100**, target price = ₹155
4. **Expected:** Step 2 shows **two tabs**: "Single Supplier" and "Split Plan (X/100 units ✅ fully covered)"
   - Split plan: Mehta 80 units @ ₹155, Rao/Patel make up remaining 20
   - Avg price shown
5. Click **Split Plan tab** → **Confirm split plan**
6. **Expected:** Multiple transfer IDs created. Result shows avg ₹/unit and "cost_price updated".

### After both suppliers approve:
7. Login as **seller2**, approve their transfer → Sharma cost_price updates
8. Login as **seller3** or **seller5**, approve theirs → Sharma cost_price blends to new weighted avg

---

## Scenario 5 — Manual demand (no billing trigger) 📋
**Goal:** Post a demand manually without selling anything first.

1. Login as **seller1** → go to **Demand**
2. Select **Marie Biscuits 200g** (Product 9), qty = 30
3. **Expected:** Paused at Step 1 — enter qty & target price
   - current stock = 5, threshold ≈ 14
4. Set qty = 30, target price = ₹37 → Confirm
5. **Expected:** Paused at Step 2 — candidate table shows sellers 2, 3, 4, 5
6. Pick **Rao Provision** (seller5), offer ₹37.50 → Send request

---

## Scenario 6 — Transfer negotiation (counter-offer) 💬
**Goal:** Supplier counters the buyer's offer; buyer accepts.

1. Complete Scenario 2 up to step 9 (transfer PENDING)
2. Login as **seller2** → Transfers → Incoming Requests
3. Instead of Approve, set counter price = ₹158 → **Send Counter-Offer**
4. **Expected:** Transfer status = "countered"

### Buyer counter-counters:
5. Login as **seller1** → Transfers → Supplier Counter-Offers
6. See counter at ₹158 — set your counter price = ₹156 → **Send My Counter**
7. **Expected:** transfer_price = ₹156, status back to **pending**. Message: "Your counter of ₹156.00/unit sent. Waiting for supplier."

### OR buyer accepts:
- Click **Accept Counter** → price = ₹158, status = pending (supplier executes)

### Supplier sees updated price and approves:
8. Login as **seller2** → Transfers → Incoming Requests (shows ₹156 now)
9. Click **Approve & Ship** → stock moves at ₹156

### Supplier executes the shipment:
8. Login as **seller2** → Transfers → Incoming Requests (transfer appears again at ₹158)
9. Click **Approve & Ship**
10. **Expected:** Stock moves, cost_price updates to weighted avg. No warning (₹160 > ₹158 ✅)

---

## Scenario 7 — Transfer rejection ❌
**Goal:** Supplier rejects; demand stays open.

1. Start a new billing/demand that creates a transfer
2. Login as **seller2** → Transfers → **Reject Request**
3. **Expected:** Transfer status = "rejected". Demand post remains "open".

---

## Scenario 8 — Below-cost warning 🔴
**Goal:** Buy stock at a price higher than your selling price → see warning.

1. Login as **seller1** → Demand
2. Select **Marie Biscuits 200g**, confirm qty = 10, target price = **₹45** (above selling ₹40)
3. Pick Mehta at ₹45 → Send request
4. Login as **seller2** → Approve
5. **Expected:** Approval response shows warning:
   > ⚠️ Your selling price ₹40.00 is now below your new cost price ₹45.00. Update your selling price to avoid losses.

---

## Scenario 9 — Analytics (SQL agent) 📊
**Goal:** Run business intelligence queries.

1. Login as **admin** → go to **Analytics / Chat**
2. Test queries:
   - "Which seller has the most profit this month?"
   - "Show total revenue for all sellers"
   - "Which product has the highest demand in the last 30 days?"
   - "List sellers with stock below 20 units"
   - "Show all completed transfers"

---

## Scenario 10 — RAG explainability 🤖
**Goal:** Get AI explanation for a decision.

1. Login as **seller1** → Chat
2. Ask: "Why is my profit low for Refined Sunflower Oil?"
3. Ask: "Explain the pricing rules for retail stores"
4. Ask: "Why was my transfer request sent to Mehta Wholesale?"

---

## Scenario 11 — No suppliers available 🚫
**Goal:** Request a product no one has stock for.

1. Ensure no seller except seller1 has **Wheat Flour 10kg** (product 2)
   - Run: `UPDATE inventory SET stock_qty=0 WHERE product_id=2 AND seller_id!=1`
2. Login as **seller1** → Demand → Wheat Flour, qty=20
3. Set price → Confirm
4. **Expected:** "No supplier currently has stock for this product." Demand post remains open.

---

## Quick DB checks after each scenario
```sql
-- Check seller1's inventory
SELECT * FROM inventory WHERE seller_id=1;

-- Check pending transfers
SELECT * FROM transfers WHERE status='pending';

-- Check demand posts
SELECT * FROM demand_posts ORDER BY demand_id DESC LIMIT 10;

-- Check profits
SELECT * FROM profits WHERE seller_id=1 ORDER BY month DESC;
```
