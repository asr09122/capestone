"""
RetailFlow AI — Comprehensive Test Suite
========================================
Tests every layer of the system:
  1. Unit tests  — tools, validators, routing
  2. Integration — FastAPI endpoints via TestClient
  3. Workflow    — full LangGraph billing + demand + approval flows

Run:
    uv run pytest tests/test_kirananet.py -v
    uv run pytest tests/test_kirananet.py -v -k "unit"          # unit only
    uv run pytest tests/test_kirananet.py -v -k "integration"   # API only
    uv run pytest tests/test_kirananet.py -v -k "workflow"      # graph only
"""

import json
import os
import sqlite3
import uuid

import pytest
from fastapi.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient (no live server needed)."""
    from app.main import app

    return TestClient(app)


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


@pytest.fixture(scope="session")
def auth_token(client):
    """Obtain a JWT token once for the entire session."""
    resp = client.post(
        "/auth/token",
        data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
    )
    assert resp.status_code == 200, f"Auth failed: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture(scope="session")
def auth_headers(auth_token):
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture(scope="session")
def test_pair():
    """Find a seller/product pair where stock is below the 30-day threshold."""
    import sqlite3
    from datetime import datetime, timedelta

    conn = sqlite3.connect("data/retailflow.db")
    conn.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")

    row = conn.execute(
        """
        SELECT t.seller_id, t.product_id, i.stock_qty,
               ROUND(SUM(t.qty)/30.0*7,1) AS threshold
        FROM transactions t
        JOIN inventory i ON i.seller_id=t.seller_id AND i.product_id=t.product_id
        WHERE t.status='completed' AND t.created_at >= ?
        GROUP BY t.seller_id, t.product_id
        HAVING i.stock_qty < threshold AND i.stock_qty > 0
        ORDER BY (threshold - i.stock_qty) DESC
        LIMIT 1
        """,
        (cutoff,),
    ).fetchone()
    conn.close()

    if row:
        return {
            "seller_id": int(row["seller_id"]),
            "product_id": int(row["product_id"]),
        }
    # Fallback: seller 3 / product 17 (known low-stock pair from seeded data)
    return {"seller_id": 3, "product_id": 17}


# ══════════════════════════════════════════════════════════════════════════════
# 1. UNIT TESTS — Tools & Validators
# ══════════════════════════════════════════════════════════════════════════════


class TestInventoryTools:
    """Unit tests for app/tools/inventory_tools.py"""

    def test_get_inventory_exists(self):
        from app.tools.inventory_tools import get_inventory_raw

        result = get_inventory_raw(1, 1)
        # seller 1 may or may not have product 1; just verify return type
        assert result is None or isinstance(result, dict)

    def test_get_inventory_returns_correct_fields(self):
        from app.tools.inventory_tools import get_inventory_raw
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        row = conn.execute(
            "SELECT seller_id, product_id FROM inventory LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            result = get_inventory_raw(row[0], row[1])
            assert result is not None
            assert "stock_qty" in result
            assert "cost_price" in result
            assert "selling_price" in result

    def test_get_inventory_nonexistent_returns_none(self):
        from app.tools.inventory_tools import get_inventory_raw

        result = get_inventory_raw(9999, 9999)
        assert result is None

    def test_update_inventory_invalid_raises(self):
        from app.tools.inventory_tools import update_inventory_raw

        with pytest.raises(ValueError, match="No inventory record"):
            update_inventory_raw(9999, 9999, -5)

    def test_update_inventory_negative_stock_raises(self):
        """Deducting more than available stock should raise ValueError."""
        from app.tools.inventory_tools import get_inventory_raw, update_inventory_raw
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        row = conn.execute(
            "SELECT seller_id, product_id, stock_qty FROM inventory WHERE stock_qty > 0 LIMIT 1"
        ).fetchone()
        conn.close()
        if row:
            with pytest.raises(ValueError, match="Insufficient stock"):
                update_inventory_raw(row[0], row[1], -(row[2] + 9999))


class TestDemandTools:
    """Unit tests for app/tools/demand_tools.py"""

    def test_get_recent_sales_returns_dict(self):
        from app.tools.demand_tools import get_recent_sales_raw

        result = get_recent_sales_raw(1, 1, days=30)
        assert isinstance(result, dict)
        assert "total_qty" in result
        assert "daily_avg" in result
        assert "threshold" in result

    def test_threshold_formula(self):
        """threshold == daily_avg * 7"""
        from app.tools.demand_tools import get_recent_sales_raw

        result = get_recent_sales_raw(1, 1, days=30)
        expected = round(result["daily_avg"] * 7, 2)
        assert abs(result["threshold"] - expected) < 0.01

    def test_create_demand_post_success(self):
        from app.tools.demand_tools import create_demand_post_raw

        result = create_demand_post_raw(1, 1, 25)
        assert "demand_id" in result
        assert result["demand_id"] is not None
        assert result["status"] == "open"
        assert result["qty_needed"] == 25

    def test_create_demand_post_zero_qty_raises(self):
        from app.tools.demand_tools import create_demand_post_raw

        with pytest.raises(Exception):
            create_demand_post_raw(1, 1, 0)


class TestTransferTools:
    """Unit tests for app/tools/transfer_tools.py"""

    def test_find_sellers_with_stock_returns_list(self):
        from app.tools.transfer_tools import find_sellers_with_stock_raw

        results = find_sellers_with_stock_raw(1, 1, exclude_seller_id=0)
        assert isinstance(results, list)

    def test_find_sellers_with_stock_excludes_seller(self):
        from app.tools.transfer_tools import find_sellers_with_stock_raw

        results = find_sellers_with_stock_raw(1, 5, exclude_seller_id=1)
        seller_ids = [r["seller_id"] for r in results]
        assert 1 not in seller_ids

    def test_find_sellers_sorted_by_price(self):
        from app.tools.transfer_tools import find_sellers_with_stock_raw

        results = find_sellers_with_stock_raw(1, 1)
        prices = [r["selling_price"] for r in results]
        assert prices == sorted(prices)

    def test_create_transfer_success(self):
        from app.tools.transfer_tools import create_transfer_raw

        result = create_transfer_raw(
            from_seller_id=2, to_seller_id=5, product_id=1, qty=5, transfer_price=100.0
        )
        assert "transfer_id" in result
        assert result["status"] == "pending"

    def test_create_transfer_same_seller_raises(self):
        from app.tools.transfer_tools import create_transfer_raw

        with pytest.raises(ValueError, match="must differ"):
            create_transfer_raw(1, 1, 1, 5, 100.0)

    def test_reject_transfer_only_touches_pending(self):
        """reject_transfer must NOT overwrite a 'countered' status."""
        import sqlite3
        from app.tools.transfer_tools import create_transfer_raw, reject_transfer

        t = create_transfer_raw(
            from_seller_id=2, to_seller_id=3, product_id=2, qty=5, transfer_price=75.0
        )
        tid = t["transfer_id"]
        # Manually move it to 'countered'
        conn = sqlite3.connect("data/retailflow.db")
        conn.execute(
            "UPDATE transfers SET status='countered', counter_price=70 WHERE transfer_id=?",
            (tid,),
        )
        conn.commit()
        conn.close()

        # reject_transfer should be a no-op on countered
        reject_transfer(tid)

        conn = sqlite3.connect("data/retailflow.db")
        status = conn.execute(
            "SELECT status FROM transfers WHERE transfer_id=?", (tid,)
        ).fetchone()[0]
        conn.close()
        assert status == "countered", "reject_transfer clobbered a countered transfer"

    def test_create_transfer_zero_qty_raises(self):
        from app.tools.transfer_tools import create_transfer_raw

        with pytest.raises(ValueError, match="qty must be positive"):
            create_transfer_raw(1, 2, 1, 0, 100.0)


class TestRagTools:
    """Unit tests for app/tools/rag_tools.py"""

    def test_get_transaction_history_returns_list(self):
        from app.tools.rag_tools import get_transaction_history

        result = get_transaction_history.invoke(
            {"seller_id": 1, "product_id": 1, "limit": 5}
        )
        assert isinstance(result, list)

    def test_get_avg_price_returns_float(self):
        from app.tools.rag_tools import get_avg_transaction_price

        result = get_avg_transaction_price(1, 1, days=30)
        assert isinstance(result, float)
        assert result >= 0


class TestValidators:
    """Unit tests for app/guardrails/validators.py"""

    def test_validate_billing_input_valid(self):
        from app.guardrails.validators import validate_billing_input

        validate_billing_input(1, 1, 10, 50.0)  # should not raise

    def test_validate_billing_zero_qty_raises(self):
        from app.guardrails.validators import validate_billing_input

        with pytest.raises(ValueError, match="quantity"):
            validate_billing_input(1, 1, 0, 50.0)

    def test_validate_billing_negative_price_raises(self):
        from app.guardrails.validators import validate_billing_input

        with pytest.raises(ValueError, match="price"):
            validate_billing_input(1, 1, 5, -10.0)

    def test_validate_billing_invalid_seller_raises(self):
        from app.guardrails.validators import validate_billing_input

        with pytest.raises(ValueError, match="seller_id"):
            validate_billing_input(0, 1, 5, 50.0)

    def test_sql_select_passes(self):
        from app.guardrails.validators import validate_sql_query

        validate_sql_query("SELECT * FROM products")  # no raise

    def test_sql_drop_blocked(self):
        from app.guardrails.validators import validate_sql_query

        with pytest.raises(ValueError, match="Only SELECT"):
            validate_sql_query("DROP TABLE products")

    def test_sql_update_blocked(self):
        from app.guardrails.validators import validate_sql_query

        with pytest.raises(ValueError):
            validate_sql_query("UPDATE inventory SET stock_qty = 0")

    def test_sql_delete_blocked(self):
        from app.guardrails.validators import validate_sql_query

        with pytest.raises(ValueError):
            validate_sql_query("DELETE FROM transactions")

    def test_sql_insert_blocked(self):
        from app.guardrails.validators import validate_sql_query

        with pytest.raises(ValueError):
            validate_sql_query("INSERT INTO sellers VALUES (11,'X','Y','Z')")

    def test_sql_case_insensitive_block(self):
        from app.guardrails.validators import validate_sql_query

        with pytest.raises(ValueError):
            validate_sql_query("drop table products")

    def test_pricing_anomaly_detected(self):
        from app.guardrails.validators import validate_pricing

        assert validate_pricing(150.0, 100.0, threshold=0.20) is True

    def test_pricing_no_anomaly(self):
        from app.guardrails.validators import validate_pricing

        assert validate_pricing(105.0, 100.0, threshold=0.20) is False

    def test_pricing_zero_avg_no_anomaly(self):
        from app.guardrails.validators import validate_pricing

        assert validate_pricing(100.0, 0.0) is False

    def test_price_floor_violation(self):
        from app.guardrails.validators import validate_price_floor

        with pytest.raises(ValueError, match="floor"):
            validate_price_floor(price=100.0, cost_price=100.0)  # 100 < 103 (floor)

    def test_price_floor_passes(self):
        from app.guardrails.validators import validate_price_floor

        validate_price_floor(price=110.0, cost_price=100.0)  # 110 >= 103


class TestGraphRouting:
    """Unit tests for query routing in app/agents/graph.py"""

    def test_why_routes_to_rag(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("why was the price flagged?") == "rag"

    def test_explain_routes_to_rag(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("explain this anomaly") == "rag"

    def test_how_routes_to_rag(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("how does the threshold work?") == "rag"

    def test_profit_routes_to_sql(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("show profit for seller 1") == "sql"

    def test_revenue_routes_to_sql(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("what is the total revenue this month?") == "sql"

    def test_analytics_routes_to_sql(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("give me analytics report") == "sql"

    def test_stock_routes_to_demand(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("check my stock levels") == "demand"

    def test_unknown_routes_to_demand(self):
        from app.agents.graph import route_query_to_agent

        assert route_query_to_agent("hello there") == "demand"

    def test_threshold_router(self):
        from app.agents.graph import route_after_threshold

        # stock < threshold → demand
        state = {"stock": 5, "threshold": 20.0}
        assert route_after_threshold(state) == "demand"

    def test_threshold_router_sufficient_stock(self):
        from app.agents.graph import route_after_threshold
        from langgraph.graph import END

        state = {"stock": 50, "threshold": 20.0}
        assert route_after_threshold(state) == END

    def test_start_routing_billing(self):
        from app.agents.graph import route_start

        assert route_start({"trigger": "billing"}) == "billing"

    def test_start_routing_demand(self):
        from app.agents.graph import route_start
        # Manual demand trigger → goes straight to demand_node
        assert route_start({"trigger": "demand"}) == "demand"


# ══════════════════════════════════════════════════════════════════════════════
# 2. INTEGRATION TESTS — FastAPI Endpoints
# ══════════════════════════════════════════════════════════════════════════════


class TestAuthEndpoints:
    """Integration tests for /auth/token"""

    def test_login_success(self, client):
        resp = client.post(
            "/auth/token",
            data={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert len(data["access_token"]) > 20

    def test_login_wrong_password(self, client):
        resp = client.post(
            "/auth/token",
            data={"username": ADMIN_USERNAME, "password": "wrongpassword"},
        )
        assert resp.status_code == 401

    def test_login_unknown_user(self, client):
        resp = client.post(
            "/auth/token",
            data={"username": "ghost", "password": "abc"},
        )
        assert resp.status_code == 401

    def test_signup_then_login(self, client):
        """Register a brand-new user through /auth/signup, then log in."""
        import uuid
        username = f"testuser_{uuid.uuid4().hex[:8]}"
        # Signup
        signup = client.post(
            "/auth/signup",
            json={"username": username, "password": "secret123", "role": "user"},
        )
        assert signup.status_code == 200, f"Signup failed: {signup.text}"

        # Login
        login = client.post(
            "/auth/token",
            data={"username": username, "password": "secret123"},
        )
        assert login.status_code == 200
        assert login.json()["role"] == "user"


class TestHealthAndRoot:
    """Integration tests for /health and /"""

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "db_exists" in data
        assert "faiss_index_exists" in data

    def test_health_db_exists(self, client):
        resp = client.get("/health")
        assert resp.json()["db_exists"] is True

    def test_root_returns_project_info(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project"] == "RetailFlow AI"

    def test_protected_endpoint_without_token(self, client):
        resp = client.post(
            "/billing",
            json={"seller_id": 1, "product_id": 1, "quantity": 1, "price": 50.0},
        )
        assert resp.status_code == 401

    def test_protected_endpoint_bad_token(self, client):
        resp = client.post(
            "/billing",
            json={"seller_id": 1, "product_id": 1, "quantity": 1, "price": 50.0},
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


class TestBillingEndpoints:
    """Integration tests for POST /billing"""

    def test_billing_invalid_qty_zero(self, client, auth_headers):
        resp = client.post(
            "/billing",
            json={"seller_id": 1, "product_id": 1, "quantity": 0, "price": 50.0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_billing_invalid_price_negative(self, client, auth_headers):
        resp = client.post(
            "/billing",
            json={"seller_id": 1, "product_id": 1, "quantity": 1, "price": -5.0},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_billing_no_inventory_returns_500(self, client, auth_headers):
        """Seller 9999 has no inventory — should return 500."""
        resp = client.post(
            "/billing",
            json={"seller_id": 9999, "product_id": 9999, "quantity": 1, "price": 50.0},
            headers=auth_headers,
        )
        assert resp.status_code in (422, 500)

    def test_billing_success_returns_thread_id(self, client, auth_headers, test_pair):
        """A valid billing on a pair with stock should return a thread_id."""
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        row = conn.execute(
            "SELECT seller_id, product_id, selling_price FROM inventory WHERE stock_qty >= 2 LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No inventory with stock >= 2")

        resp = client.post(
            "/billing",
            json={
                "seller_id": row[0],
                "product_id": row[1],
                "quantity": 1,
                "price": float(row[2]),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "thread_id" in data
        assert "new_stock" in data
        assert "anomaly_detected" in data
        assert isinstance(data["demand_created"], bool)
        assert isinstance(data["transfer_suggested"], bool)
        assert isinstance(data["pending_approval"], bool)

    def test_billing_response_structure(self, client, auth_headers):
        """Validate all expected keys are present in billing response."""
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        row = conn.execute(
            "SELECT seller_id, product_id, selling_price FROM inventory WHERE stock_qty >= 1 LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No inventory available")

        resp = client.post(
            "/billing",
            json={
                "seller_id": row[0],
                "product_id": row[1],
                "quantity": 1,
                "price": float(row[2]),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        required_keys = [
            "thread_id",
            "seller_id",
            "product_id",
            "new_stock",
            "anomaly_detected",
            "demand_created",
            "transfer_suggested",
            "pending_approval",
        ]
        for key in required_keys:
            assert key in data, f"Missing key: {key}"

    def test_billing_anomaly_detected_on_high_price(self, client, auth_headers):
        """Bill at 3× the normal price — anomaly should be detected."""
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            """SELECT t.seller_id, t.product_id, AVG(t.agreed_price) as avg_price, i.stock_qty
               FROM transactions t
               JOIN inventory i ON i.seller_id=t.seller_id AND i.product_id=t.product_id
               WHERE t.status='completed' AND t.created_at >= ? AND i.stock_qty >= 1
               GROUP BY t.seller_id, t.product_id
               HAVING COUNT(*) >= 2
               LIMIT 1""",
            (cutoff,),
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No suitable pair for anomaly test")

        anomalous_price = round(float(row[2]) * 3.0, 2)
        resp = client.post(
            "/billing",
            json={
                "seller_id": int(row[0]),
                "product_id": int(row[1]),
                "quantity": 1,
                "price": anomalous_price,
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["anomaly_detected"] is True
        assert data["anomaly_explanation"] is not None
        assert len(data["anomaly_explanation"]) > 10

    def test_billing_approve_invalid_thread_returns_404(self, client, auth_headers):
        resp = client.post(
            "/billing/approve/nonexistent-thread-id",
            json={"approved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_billing_response_exposes_supplier_name_and_alternatives(
        self, client, auth_headers
    ):
        """When a transfer is suggested the API must expose the auto-picked
        supplier's name and a list of alternatives the AI considered."""
        import sqlite3
        from datetime import datetime, timedelta

        conn = sqlite3.connect("data/retailflow.db")
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            """SELECT t.seller_id, t.product_id, i.stock_qty, i.selling_price
               FROM transactions t
               JOIN inventory i ON i.seller_id=t.seller_id AND i.product_id=t.product_id
               WHERE t.status='completed' AND t.created_at >= ? AND i.stock_qty >= 1
               GROUP BY t.seller_id, t.product_id
               HAVING i.stock_qty < ROUND(SUM(t.qty)/30.0*7, 1)
               LIMIT 1""",
            (cutoff,),
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No low-stock pair available for this test")

        resp = client.post(
            "/billing",
            json={
                "seller_id": int(row[0]),
                "product_id": int(row[1]),
                "quantity": 1,
                "price": float(row[3]),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        if not data.get("pending_approval"):
            pytest.skip("No suitable supplier — transfer not suggested")

        ar = data.get("approval_required") or {}
        assert "from_seller_name" in ar
        assert "alternatives" in ar
        assert "selection_reason" in ar
        assert "negotiate_url" in ar
        # Alternatives list must be sorted by cheapest price first (or empty)
        prices = [a["selling_price"] for a in ar["alternatives"] if "selling_price" in a]
        assert prices == sorted(prices)


class TestNegotiationFlow:
    """Integration tests for /negotiate-transfer, /accept-counter, /reject-counter."""

    def test_negotiate_requires_pending_status(self, client, auth_headers):
        """Negotiating a non-pending transfer returns 400."""
        import sqlite3
        from app.tools.transfer_tools import create_transfer_raw

        # Create a transfer as admin (no seller_id) — negotiating should fail on
        # auth (admin has no seller_id), so just verify the endpoint wiring works.
        t = create_transfer_raw(
            from_seller_id=2, to_seller_id=3, product_id=4, qty=3, transfer_price=60.0
        )
        resp = client.post(
            f"/negotiate-transfer/{t['transfer_id']}",
            json={"counter_price": 50.0},
            headers=auth_headers,
        )
        # Admin has no seller_id → 403
        assert resp.status_code in (400, 403)

    def test_negotiate_nonexistent_transfer_returns_404(self, client):
        """Logged-in seller negotiating a missing transfer → 404."""
        # Fetch a token for a seller user
        import sqlite3
        from app.core.security import create_user
        import uuid
        uname = f"testseller_{uuid.uuid4().hex[:6]}"
        conn = sqlite3.connect("data/retailflow.db")
        sid = conn.execute("SELECT seller_id FROM sellers LIMIT 1").fetchone()[0]
        conn.close()
        try:
            create_user(uname, "testpw", seller_id=int(sid), role="user")
        except Exception:
            pass
        tok = client.post(
            "/auth/token", data={"username": uname, "password": "testpw"}
        ).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}

        resp = client.post(
            "/negotiate-transfer/999999",
            json={"counter_price": 10.0},
            headers=h,
        )
        assert resp.status_code == 404


class TestDemandEndpoints:
    """Integration tests for POST /demand"""

    def test_demand_invalid_qty(self, client, auth_headers):
        resp = client.post(
            "/demand",
            json={"seller_id": 1, "product_id": 1, "quantity": -5},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_demand_invalid_seller(self, client, auth_headers):
        resp = client.post(
            "/demand",
            json={"seller_id": 0, "product_id": 1, "quantity": 10},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_demand_success_returns_thread_id(self, client, auth_headers):
        """Manual demand on any valid seller/product returns a thread_id."""
        resp = client.post(
            "/demand",
            json={"seller_id": 1, "product_id": 2, "quantity": 20},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "thread_id" in data
        assert "demand_id" in data
        assert data["demand_created"] is True

    def test_demand_response_structure(self, client, auth_headers):
        resp = client.post(
            "/demand",
            json={"seller_id": 2, "product_id": 5, "quantity": 15},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        for key in [
            "thread_id",
            "seller_id",
            "product_id",
            "demand_id",
            "demand_created",
            "pending_approval",
        ]:
            assert key in data, f"Missing key: {key}"

    def test_demand_approve_invalid_thread(self, client, auth_headers):
        resp = client.post(
            "/demand/approve/fake-thread-xyz",
            json={"approved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 404


class TestAskEndpoints:
    """Integration tests for POST /ask (routing only — no LLM call)"""

    def test_ask_empty_query_rejected(self, client, auth_headers):
        resp = client.post(
            "/ask",
            json={"query": "  ", "seller_id": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_ask_demand_query_missing_product_id(self, client, auth_headers):
        resp = client.post(
            "/ask",
            json={"query": "check stock levels", "seller_id": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    def test_ask_routes_why_to_rag(self, client, auth_headers):
        """Verify routing meta — agent_used field should be 'rag' for why queries.
        Actual LLM call is made; mark as slow."""
        pytest.importorskip("langchain_nvidia_ai_endpoints")
        resp = client.post(
            "/ask",
            json={
                "query": "why is this price flagged?",
                "seller_id": 1,
                "product_id": 1,
            },
            headers=auth_headers,
            timeout=120,
        )
        if resp.status_code == 200:
            assert resp.json()["agent_used"] == "rag"

    def test_ask_routes_profit_to_sql(self, client, auth_headers):
        """SQL analytics via ask endpoint."""
        resp = client.post(
            "/ask",
            json={"query": "show total profit for all sellers", "seller_id": 1},
            headers=auth_headers,
            timeout=120,
        )
        if resp.status_code == 200:
            assert resp.json()["agent_used"] == "sql"


class TestSQLEndpoints:
    """Integration tests for GET /sql"""

    def test_sql_missing_query(self, client, auth_headers):
        resp = client.get("/sql", headers=auth_headers)
        assert resp.status_code == 422

    def test_sql_drop_blocked(self, client, auth_headers):
        resp = client.get("/sql?query=DROP+TABLE+products", headers=auth_headers)
        assert resp.status_code == 403

    def test_sql_update_blocked(self, client, auth_headers):
        resp = client.get(
            "/sql?query=UPDATE+inventory+SET+stock_qty%3D0", headers=auth_headers
        )
        assert resp.status_code == 403

    def test_sql_delete_blocked(self, client, auth_headers):
        resp = client.get("/sql?query=DELETE+FROM+transactions", headers=auth_headers)
        assert resp.status_code == 403

    def test_sql_insert_blocked(self, client, auth_headers):
        resp = client.get(
            "/sql?query=INSERT+INTO+sellers+VALUES+(11,'X','Y','Z')",
            headers=auth_headers,
        )
        assert resp.status_code == 403

    def test_sql_select_query_runs(self, client, auth_headers):
        """Natural-language profit query — makes actual LLM call."""
        resp = client.get(
            "/sql?query=Show+total+profit+for+each+seller",
            headers=auth_headers,
            timeout=120,
        )
        if resp.status_code == 200:
            data = resp.json()
            assert "result" in data
            assert len(data["result"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 3. WORKFLOW TESTS — Full LangGraph State Machine
# ══════════════════════════════════════════════════════════════════════════════


class TestBillingWorkflow:
    """End-to-end workflow: billing → threshold → demand → seller match → approval."""

    def test_workflow_billing_trigger_completes(self, client, auth_headers):
        """Billing on a pair with sufficient stock completes without demand."""
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        row = conn.execute(
            "SELECT seller_id, product_id, selling_price, stock_qty FROM inventory WHERE stock_qty > 50 LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No high-stock inventory")

        resp = client.post(
            "/billing",
            json={
                "seller_id": int(row[0]),
                "product_id": int(row[1]),
                "quantity": 1,
                "price": float(row[2]),
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["new_stock"] == row[3] - 1

    def test_workflow_full_approve_cycle(self, client, auth_headers, test_pair):
        """
        Full workflow:
        1. POST /billing with a low-stock pair → demand + transfer suggestion
        2. POST /billing/approve/{thread_id} with approved=True → transfer executes
        """
        import sqlite3
        from datetime import datetime, timedelta

        conn = sqlite3.connect("data/retailflow.db")
        cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        row = conn.execute(
            """SELECT t.seller_id, t.product_id, i.stock_qty, i.selling_price
               FROM transactions t
               JOIN inventory i ON i.seller_id=t.seller_id AND i.product_id=t.product_id
               WHERE t.status='completed' AND t.created_at >= ? AND i.stock_qty >= 1
               GROUP BY t.seller_id, t.product_id
               HAVING i.stock_qty < ROUND(SUM(t.qty)/30.0*7, 1)
               LIMIT 1""",
            (cutoff,),
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip(
                "No low-stock pair with recent sales — re-run seed_db or adjust"
            )

        sid, pid, stock, price = int(row[0]), int(row[1]), int(row[2]), float(row[3])

        # Step 1: trigger billing
        bill_resp = client.post(
            "/billing",
            json={"seller_id": sid, "product_id": pid, "quantity": 1, "price": price},
            headers=auth_headers,
        )
        assert bill_resp.status_code == 200
        bill_data = bill_resp.json()
        assert bill_data["demand_created"] is True, "Demand was not created"
        assert bill_data["transfer_suggested"] is True, "Transfer was not suggested"
        assert bill_data["pending_approval"] is True, "Graph should be paused"
        thread_id = bill_data["thread_id"]

        # Step 2: approve transfer
        approve_resp = client.post(
            f"/billing/approve/{thread_id}",
            json={"approved": True},
            headers=auth_headers,
        )
        assert approve_resp.status_code == 200
        approve_data = approve_resp.json()
        assert approve_data["approved"] is True
        assert approve_data["result"] is not None
        assert "Transfer" in approve_data["result"]
        assert "completed" in approve_data["result"]

    def test_workflow_full_reject_cycle(self, client, auth_headers):
        """Manual demand → find transfer → reject → demand stays open."""
        resp = client.post(
            "/demand",
            json={"seller_id": 1, "product_id": 3, "quantity": 30},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["demand_created"] is True
        thread_id = data["thread_id"]

        if not data.get("pending_approval"):
            pytest.skip("No transfer was suggested (no sellers with stock)")

        reject_resp = client.post(
            f"/demand/approve/{thread_id}",
            json={"approved": False, "reason": "Price too high"},
            headers=auth_headers,
        )
        assert reject_resp.status_code == 200
        rdata = reject_resp.json()
        assert rdata["approved"] is False
        assert "rejected" in rdata["result"].lower()

    def test_double_approval_returns_404(self, client, auth_headers):
        """Approving an already-completed thread returns 404."""
        # Use a fresh demand that likely has no match (very high qty)
        resp = client.post(
            "/demand",
            json={"seller_id": 5, "product_id": 7, "quantity": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        thread_id = resp.json()["thread_id"]

        # First approve (even if not pending, will 404)
        approve1 = client.post(
            f"/demand/approve/{thread_id}",
            json={"approved": True},
            headers=auth_headers,
        )
        # Second approve on same thread must 404
        approve2 = client.post(
            f"/demand/approve/{thread_id}",
            json={"approved": True},
            headers=auth_headers,
        )
        assert approve2.status_code == 404


class TestDatabaseIntegrity:
    """Verify DB state after workflow operations."""

    def test_transaction_inserted_after_billing(self, client, auth_headers):
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        row = conn.execute(
            "SELECT seller_id, product_id, selling_price FROM inventory WHERE stock_qty >= 1 LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No inventory available")

        client.post(
            "/billing",
            json={
                "seller_id": int(row[0]),
                "product_id": int(row[1]),
                "quantity": 1,
                "price": float(row[2]),
            },
            headers=auth_headers,
        )

        conn = sqlite3.connect("data/retailflow.db")
        after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        conn.close()
        assert after == before + 1

    def test_profit_updated_after_billing(self, client, auth_headers):
        from datetime import datetime
        import sqlite3

        month = datetime.now().strftime("%Y-%m")
        conn = sqlite3.connect("data/retailflow.db")
        row = conn.execute(
            "SELECT seller_id, product_id, selling_price FROM inventory WHERE stock_qty >= 1 LIMIT 1"
        ).fetchone()
        conn.close()
        if row is None:
            pytest.skip("No inventory available")

        client.post(
            "/billing",
            json={
                "seller_id": int(row[0]),
                "product_id": int(row[1]),
                "quantity": 1,
                "price": float(row[2]),
            },
            headers=auth_headers,
        )

        conn = sqlite3.connect("data/retailflow.db")
        profit_row = conn.execute(
            "SELECT profit_id FROM profits WHERE seller_id=? AND month=?",
            (int(row[0]), month),
        ).fetchone()
        conn.close()
        assert profit_row is not None, "Profit record not created/updated"

    def test_demand_post_created_in_db(self, client, auth_headers):
        import sqlite3

        conn = sqlite3.connect("data/retailflow.db")
        before = conn.execute("SELECT COUNT(*) FROM demand_posts").fetchone()[0]
        conn.close()

        resp = client.post(
            "/demand",
            json={"seller_id": 3, "product_id": 8, "quantity": 20},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        demand_id = resp.json().get("demand_id")

        conn = sqlite3.connect("data/retailflow.db")
        after = conn.execute("SELECT COUNT(*) FROM demand_posts").fetchone()[0]
        row = conn.execute(
            "SELECT status FROM demand_posts WHERE demand_id=?", (demand_id,)
        ).fetchone()
        conn.close()

        assert after == before + 1
        assert row is not None
        assert row[0] == "open"
