"""
RetailFlow AI — Interactive Streamlit Frontend
=============================================
Run: uv run streamlit run streamlit_app.py
"""

import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

# ── Config ────────────────────────────────────────────────────────────────────
# Read from environment so Docker / local both work:
#   Docker  → API_BASE_URL=http://api:8000   DB_PATH=/app/data/retailflow.db
#   Local   → defaults below
API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
DB_PATH  = os.environ.get("DB_PATH", "data/retailflow.db")

st.set_page_config(
    page_title="RetailFlow AI",
    page_icon="🏪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .main-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 1.5rem 2rem;
    border-radius: 12px;
    color: white;
    margin-bottom: 1.5rem;
  }
  .metric-card {
    background: #f8faff;
    border: 1px solid #e0e7ff;
    border-radius: 10px;
    padding: 1rem;
    text-align: center;
  }
  .status-badge-success {
    background: #d1fae5; color: #065f46;
    padding: 2px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
  }
  .status-badge-warning {
    background: #fef3c7; color: #92400e;
    padding: 2px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
  }
  .status-badge-danger {
    background: #fee2e2; color: #991b1b;
    padding: 2px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
  }
  .anomaly-box {
    background: #fff7ed; border-left: 4px solid #f97316;
    padding: 1rem; border-radius: 0 8px 8px 0; margin: 0.5rem 0;
  }
  .approval-box {
    background: #eff6ff; border-left: 4px solid #3b82f6;
    padding: 1rem; border-radius: 0 8px 8px 0; margin: 0.5rem 0;
  }
  .success-box {
    background: #f0fdf4; border-left: 4px solid #22c55e;
    padding: 1rem; border-radius: 0 8px 8px 0; margin: 0.5rem 0;
  }
  .stButton > button { border-radius: 8px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

if "token" not in st.session_state:
    st.session_state.token = None
if "username" not in st.session_state:
    st.session_state.username = ""
if "role" not in st.session_state:
    st.session_state.role = "seller"
if "seller_id" not in st.session_state:
    st.session_state.seller_id = None
if "pending_threads" not in st.session_state:
    st.session_state.pending_threads = []

# ── Session persistence (survives page reload via URL ?sid= param) ────────────
# Use st.cache_resource so the dict is a TRUE singleton — it is NOT reset when
# Streamlit re-executes the script on every page interaction / reload.
@st.cache_resource
def _get_sessions() -> dict:
    """Return the shared session store (persists for the lifetime of the server)."""
    return {}


def _save_session(token: str, username: str, role: str, seller_id):
    sessions = _get_sessions()
    sid = st.query_params.get("sid") or secrets.token_hex(8)
    sessions[sid] = {"token": token, "username": username,
                     "role": role, "seller_id": seller_id}
    st.query_params["sid"] = sid


def _restore_session():
    sessions = _get_sessions()
    sid = st.query_params.get("sid")
    if sid and sid in sessions:
        s = sessions[sid]
        st.session_state.token     = s["token"]
        st.session_state.username  = s["username"]
        st.session_state.role      = s["role"]
        st.session_state.seller_id = s["seller_id"]


def _clear_session():
    sessions = _get_sessions()
    sid = st.query_params.get("sid")
    if sid and sid in sessions:
        del sessions[sid]
    st.query_params.clear()
    st.session_state.token     = None
    st.session_state.username  = ""
    st.session_state.role      = "seller"
    st.session_state.seller_id = None


_restore_session()   # runs every page load — restores login from URL param

# ── Helper functions ──────────────────────────────────────────────────────────

def api(method: str, path: str, **kwargs):
    """Make an authenticated API call."""
    headers = kwargs.pop("headers", {})
    if st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        resp = requests.request(
            method, f"{API_BASE}{path}", headers=headers,
            timeout=kwargs.pop("timeout", 180), **kwargs
        )
        return resp
    except requests.exceptions.ConnectionError:
        st.error(f"❌ Cannot reach API at {API_BASE} — is it running?")
        return None


def db_query(sql: str, params=()):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_sellers():
    return db_query("SELECT seller_id, name, location, sector FROM sellers ORDER BY seller_id")


def get_products():
    return db_query("SELECT product_id, name, category, unit FROM products ORDER BY product_id")


def seller_map():
    return {s["seller_id"]: s["name"] for s in get_sellers()}


def product_map():
    return {p["product_id"]: p["name"] for p in get_products()}


def show_df(data: list, height: int = None, hide_index: bool = True):
    """Render a list-of-dicts as a Streamlit dataframe, or show an info message if empty."""
    if data:
        kwargs = {"use_container_width": True, "hide_index": hide_index}
        if height is not None:
            kwargs["height"] = height
        st.dataframe(pd.DataFrame(data), **kwargs)
    else:
        st.info("No data found.")


def bar_chart(df, x: str, y: str, title: str, *,
              color: str = None, color_scale: str = "Blues",
              height: int = 300, orientation: str = "v",
              color_map: dict = None, show_legend: bool = True):
    """Render a Plotly bar chart inside st.plotly_chart."""
    kwargs = dict(
        x=x, y=y, title=title, orientation=orientation,
        labels={x: x.replace("_", " ").title(), y: y.replace("_", " ").title()},
    )
    if color_map:
        kwargs["color"] = color or x
        kwargs["color_discrete_map"] = color_map
    elif color:
        kwargs["color"] = color
        kwargs["color_continuous_scale"] = color_scale
    else:
        kwargs["color"] = y
        kwargs["color_continuous_scale"] = color_scale
    fig = px.bar(df, **kwargs)
    fig.update_layout(height=height, margin=dict(t=40, b=10), showlegend=show_legend)
    st.plotly_chart(fig, use_container_width=True)


def line_chart(df, x: str, y: str, title: str, *,
               color: str = None, height: int = 320):
    """Render a Plotly line chart inside st.plotly_chart."""
    fig = px.line(df, x=x, y=y, title=title, color=color, markers=True,
                  labels={x: x.replace("_", " ").title(), y: y.replace("_", " ").title()})
    fig.update_layout(height=height, margin=dict(t=40, b=10))
    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# LOGIN PAGE
# ══════════════════════════════════════════════════════════════════════════════

def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("""
        <div class="main-header" style="text-align:center;">
          <h1>🏪 RetailFlow AI</h1>
          <p>B2B Smart Supply, Billing & Demand Intelligence</p>
        </div>
        """, unsafe_allow_html=True)

        tab1, tab2 = st.tabs(["🔑 Login", "📝 Sign Up"])
        
        with tab1:
            with st.form("login_form"):
                st.subheader("Sign In")
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("🔑 Login", use_container_width=True)

            if submitted:
                resp = requests.post(
                    f"{API_BASE}/auth/token",
                    data={"username": username, "password": password},
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state.token     = data["access_token"]
                    st.session_state.username  = username
                    st.session_state.role      = data.get("role", "seller")
                    st.session_state.seller_id = data.get("seller_id")
                    _save_session(data["access_token"], username,
                                  data.get("role", "seller"), data.get("seller_id"))
                    st.success("✅ Logged in successfully!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("❌ Invalid credentials. Please try again.")
            
            

        with tab2:
            with st.form("signup_form"):
                st.subheader("Create Account")
                new_username = st.text_input("Username", key="signup_username")
                new_password = st.text_input("Password", type="password", key="signup_password")
                confirm_password = st.text_input("Confirm Password", type="password")
                
                # Get sellers for dropdown
                sellers = get_sellers()
                seller_options = {f"{s['seller_id']} - {s['name']} ({s['location']})": s['seller_id'] 
                                 for s in sellers}
                selected_seller = st.selectbox("Select Your Store", options=list(seller_options.keys()))
                
                signup_submitted = st.form_submit_button("📝 Sign Up", use_container_width=True)

            if signup_submitted:
                if not new_username or not new_password:
                    st.error("❌ Username and password are required.")
                elif new_password != confirm_password:
                    st.error("❌ Passwords do not match.")
                elif len(new_password) < 6:
                    st.error("❌ Password must be at least 6 characters.")
                else:
                    seller_id = seller_options[selected_seller]
                    resp = requests.post(
                        f"{API_BASE}/auth/signup",
                        json={
                            "username": new_username,
                            "password": new_password,
                            "seller_id": seller_id,
                            "role": "seller"
                        },
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        st.success("✅ Account created successfully! Please login.")
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        try:
                            error_detail = resp.json().get("detail", "Signup failed")
                        except requests.exceptions.JSONDecodeError:
                            error_detail = f"Signup failed (Status: {resp.status_code}). Server may be down."
                        st.error(f"❌ {error_detail}")


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════

def sidebar():
    with st.sidebar:
        st.markdown("## 🏪 RetailFlow AI")
        role = st.session_state.get('role', 'seller')
        seller_id = st.session_state.get('seller_id')
        
        # Show user info
        st.markdown(f"👤 **{st.session_state.get('username', 'seller')}**")
        if role == "admin":
            st.markdown("🔑 *Admin Dashboard*")
        elif seller_id:
            # Get seller name
            sellers = get_sellers()
            seller = next((s for s in sellers if s['seller_id'] == seller_id), None)
            if seller:
                st.markdown(f"🏪 *{seller['name']}*")

        # Health check
        health = api("GET", "/health")
        if health and health.status_code == 200:
            h = health.json()
            col1, col2 = st.columns(2)
            col1.metric("DB", "✅" if h["db_exists"] else "❌")
            col2.metric("RAG", "✅" if h["faiss_index_exists"] else "❌")
        else:
            st.warning("⚠️ API offline")

        # Pending approvals badge
        if st.session_state.pending_threads:
            st.warning(f"⏳ {len(st.session_state.pending_threads)} pending approval(s)")

        st.divider()
        
        # Navigation based on role
        role = st.session_state.get('role', 'seller')
        if role == "admin":
            page = st.radio(
                "Navigation",
                ["📊 Dashboard", "💳 Billing", "🛒 Demand", "🤖 Ask Agent",
                 "📈 SQL Analytics", "📦 Inventory", "🔄 Transfers", "⏳ Approvals",
                 "⚙️ Admin Panel"],
            )
        else:
            page = st.radio(
                "Navigation",
                ["📊 Dashboard", "💳 Billing", "🛒 Demand", "🤖 Ask Agent",
                 "📈 SQL Analytics", "📦 Inventory", "🔄 Transfers", "⏳ Approvals"],
            )
        
        st.divider()
        if st.button("🚪 Logout", use_container_width=True):
            _clear_session()
            st.session_state.pending_threads = []
            st.rerun()
    return page


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def dashboard_page():
    is_admin = st.session_state.get("role") == "admin"
    my_sid   = st.session_state.get("seller_id")
    month    = datetime.now().strftime("%Y-%m")

    if is_admin:
        st.markdown('<div class="main-header"><h2>📊 Dashboard</h2><p>Real-time RetailFlow Network Overview</p></div>', unsafe_allow_html=True)
    else:
        sellers_list = get_sellers()
        my_name = next((s["name"] for s in sellers_list if s["seller_id"] == my_sid), "My Store")
        st.markdown(f'<div class="main-header"><h2>📊 My Dashboard</h2><p>{my_name} — Store Insights</p></div>', unsafe_allow_html=True)

    # ── KPI row ───────────────────────────────────────────────────────────────
    if is_admin:
        sellers_cnt  = db_query("SELECT COUNT(*) as c FROM sellers")[0]["c"]
        products_cnt = db_query("SELECT COUNT(*) as c FROM products")[0]["c"]
        open_demands = db_query("SELECT COUNT(*) as c FROM demand_posts WHERE status='open'")[0]["c"]
        pending_t    = db_query("SELECT COUNT(*) as c FROM transfers WHERE status='pending'")[0]["c"]
        total_profit = db_query("SELECT COALESCE(SUM(profit),0) as p FROM profits WHERE month=?", (month,))[0]["p"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🏪 Sellers",           sellers_cnt)
        c2.metric("📦 Products",           products_cnt)
        c3.metric("🛒 Open Demands",       open_demands)
        c4.metric("🔄 Pending Transfers",  pending_t)
        c5.metric("💰 Network Profit",     f"₹{total_profit:,.0f}")
    else:
        my_inv       = db_query("SELECT COUNT(*) as c FROM inventory WHERE seller_id=?", (my_sid,))[0]["c"]
        my_demands   = db_query("SELECT COUNT(*) as c FROM demand_posts WHERE seller_id=? AND status='open'", (my_sid,))[0]["c"]
        my_pending   = db_query("SELECT COUNT(*) as c FROM transfers WHERE (from_seller_id=? OR to_seller_id=?) AND status='pending'", (my_sid, my_sid))[0]["c"]
        my_profit    = db_query("SELECT COALESCE(SUM(profit),0) as p FROM profits WHERE seller_id=? AND month=?", (my_sid, month))[0]["p"]
        my_txns      = db_query("SELECT COUNT(*) as c FROM transactions WHERE seller_id=? AND status='completed'", (my_sid,))[0]["c"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("📦 SKUs in Stock",        my_inv)
        c2.metric("💰 My Profit This Month",  f"₹{my_profit:,.0f}")
        c3.metric("🛒 My Open Demands",       my_demands)
        c4.metric("🔄 My Pending Transfers",  my_pending)
        c5.metric("✅ Completed Txns",        my_txns)

    st.divider()
    col_l, col_r = st.columns(2)

    # ── Top-left chart ────────────────────────────────────────────────────────
    with col_l:
        if is_admin:
            st.subheader("📈 Monthly Profit Trend (All Sellers)")
            profits = db_query("SELECT month, SUM(profit) as total FROM profits GROUP BY month ORDER BY month DESC LIMIT 12")
            if profits:
                bar_chart(pd.DataFrame(profits).sort_values("month"), "month", "total",
                          "", color_scale="Viridis")
        else:
            st.subheader("📈 My Monthly Profit Trend")
            profits = db_query("SELECT month, profit FROM profits WHERE seller_id=? ORDER BY month DESC LIMIT 12", (my_sid,))
            if profits:
                bar_chart(pd.DataFrame(profits).sort_values("month"), "month", "profit",
                          "", color_scale="Viridis")
            else:
                st.info("No profit data yet.")

    # ── Top-right chart ───────────────────────────────────────────────────────
    with col_r:
        if is_admin:
            st.subheader("🏆 Top Sellers by Total Profit")
            top_sellers = db_query("""SELECT s.name, SUM(p.profit) as total_profit
               FROM profits p JOIN sellers s ON p.seller_id=s.seller_id
               GROUP BY s.name ORDER BY total_profit DESC LIMIT 8""")
            if top_sellers:
                df = pd.DataFrame(top_sellers)
                fig = px.bar(df, x="total_profit", y="name", orientation="h",
                             color="total_profit", color_continuous_scale="Blues",
                             labels={"total_profit": "Total Profit (₹)", "name": "Seller"})
                fig.update_layout(margin=dict(t=10, b=10), height=300, yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.subheader("📦 My Stock Levels (Bottom 10)")
            stock_data = db_query("""SELECT p.name as Product, i.stock_qty as Stock
                FROM inventory i JOIN products p ON i.product_id=p.product_id
                WHERE i.seller_id=? ORDER BY i.stock_qty ASC LIMIT 10""", (my_sid,))
            if stock_data:
                df = pd.DataFrame(stock_data)
                fig = px.bar(df, x="Stock", y="Product", orientation="h",
                             color="Stock", color_continuous_scale="RdYlGn",
                             labels={"Stock": "Stock (units)"})
                fig.update_layout(height=300, margin=dict(t=10, b=10), yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No inventory data.")

    col_l2, col_r2 = st.columns(2)

    # ── Bottom-left chart ─────────────────────────────────────────────────────
    with col_l2:
        if is_admin:
            st.subheader("📋 Transaction Status")
            txn_status = db_query("SELECT status, COUNT(*) as count FROM transactions GROUP BY status")
        else:
            st.subheader("📋 My Transaction Status")
            txn_status = db_query("SELECT status, COUNT(*) as count FROM transactions WHERE seller_id=? GROUP BY status", (my_sid,))
        if txn_status:
            df = pd.DataFrame(txn_status)
            df["status"] = df["status"].apply(
                lambda x: "rejected:price_low" if "price" in x else
                          "rejected:no_stock"  if "stock" in x else x
            )
            fig = px.pie(df, names="status", values="count",
                         color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(margin=dict(t=10, b=10), height=280)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No transactions yet.")

    # ── Bottom-right chart ────────────────────────────────────────────────────
    with col_r2:
        if is_admin:
            st.subheader("📦 Stock Level Distribution")
            stock_data = db_query("""SELECT
                CASE WHEN i.stock_qty = 0    THEN 'Out of Stock'
                     WHEN i.stock_qty <= 10  THEN 'Critical (<10)'
                     WHEN i.stock_qty <= 50  THEN 'Low (10-50)'
                     WHEN i.stock_qty <= 150 THEN 'Medium (50-150)'
                     ELSE 'High (>150)' END as level
               FROM inventory i""")
        else:
            st.subheader("🔄 My Transfer Activity")
            stock_data = None
            transfer_data = db_query("""SELECT status, COUNT(*) as count
                FROM transfers WHERE from_seller_id=? OR to_seller_id=?
                GROUP BY status""", (my_sid, my_sid))
            if transfer_data:
                df = pd.DataFrame(transfer_data)
                fig = px.pie(df, names="status", values="count",
                             color="status",
                             color_discrete_map={"completed": "#22c55e", "pending": "#f59e0b", "rejected": "#ef4444"})
                fig.update_layout(margin=dict(t=10, b=10), height=280)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No transfer activity yet.")
        if is_admin and stock_data:
            df = pd.DataFrame(stock_data)
            counts = df["level"].value_counts().reset_index()
            counts.columns = ["level", "count"]
            order = ["Out of Stock", "Critical (<10)", "Low (10-50)", "Medium (50-150)", "High (>150)"]
            counts["level"] = pd.Categorical(counts["level"], categories=order, ordered=True)
            counts = counts.sort_values("level")
            fig = px.bar(counts, x="level", y="count", color="level",
                         color_discrete_sequence=["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6"],
                         labels={"count": "# SKUs", "level": "Stock Level"})
            fig.update_layout(margin=dict(t=10, b=10), height=280, showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    # ── Profit Prediction Section ────────────────────────────────────────────
    st.divider()
    if is_admin:
        st.subheader("🔮 Profit Prediction")
        col_pred_input, col_pred_output = st.columns([1, 2])
        
        with col_pred_input:
            st.markdown("**Select a seller to predict next month's profit**")
            sellers_list = get_sellers()
            seller_options = {f"{s['seller_id']} - {s['name']} ({s['location']})": s['seller_id'] 
                            for s in sellers_list}
            selected_seller = st.selectbox("Select Seller", options=list(seller_options.keys()), key="admin_profit_pred")
            
            if st.button("🔮 Predict Profit", type="primary", key="admin_predict_btn"):
                seller_id_to_predict = seller_options[selected_seller]
                with st.spinner("🤖 ML Agent predicting..."):
                    resp = api("GET", f"/ml/predict-profit/{seller_id_to_predict}")
                
                if resp and resp.status_code == 200:
                    prediction = resp.json()
                    st.session_state['last_prediction_admin'] = prediction
                    st.session_state['last_seller_admin'] = selected_seller
                elif resp:
                    st.error(f"❌ {resp.json().get('detail', 'Prediction failed')}")
        
        with col_pred_output:
            if 'last_prediction_admin' in st.session_state and st.session_state.get('last_seller_admin'):
                pred = st.session_state['last_prediction_admin']
                st.markdown(f"**Prediction for: {st.session_state['last_seller_admin']}**")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("📊 Historical Data", f"{pred.get('historical_months_used', 0)} months")
                col2.metric("🎯 Linear Regression", f"₹{pred.get('predicted_next_month_profit_lr', 0):,.2f}")
                col3.metric("📈 Moving Average", f"₹{pred.get('predicted_next_month_profit_ma', 0):,.2f}")
                
                # Show historical profit chart
                _pred_label = st.session_state.get('last_seller_admin', '')
                seller_id_for_chart = seller_options.get(_pred_label)
                if seller_id_for_chart is None:
                    # label changed — skip chart silently
                    pass
                else:
                    hist_profits = db_query("SELECT month, profit FROM profits WHERE seller_id=? ORDER BY month ASC", (seller_id_for_chart,))
                    if hist_profits:
                        df_hist = pd.DataFrame(hist_profits)
                        fig = go.Figure()
                        fig.add_trace(go.Scatter(x=df_hist['month'], y=df_hist['profit'],
                                               mode='lines+markers', name='Historical',
                                               line=dict(color='#3b82f6', width=2)))
                        if len(df_hist) > 0:
                            next_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m")
                            last_m = df_hist['month'].iloc[-1]
                            last_p = df_hist['profit'].iloc[-1]
                            fig.add_trace(go.Scatter(x=[last_m, next_month],
                                                   y=[last_p, pred.get('predicted_next_month_profit_lr', 0)],
                                                   mode='lines+markers', name='LR Prediction',
                                                   line=dict(color='#10b981', width=2, dash='dash')))
                            fig.add_trace(go.Scatter(x=[last_m, next_month],
                                                   y=[last_p, pred.get('predicted_next_month_profit_ma', 0)],
                                                   mode='lines+markers', name='MA Prediction',
                                                   line=dict(color='#f59e0b', width=2, dash='dot')))
                        fig.update_layout(title="Profit Trend with Predictions",
                                        xaxis_title="Month", yaxis_title="Profit (₹)",
                                        height=250, margin=dict(t=40, b=10))
                        st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Select a seller and click 'Predict Profit' to see predictions.")
    
    else:
        # For regular users - show their own prediction
        st.subheader("🔮 My Profit Prediction")
        col_pred_btn, col_pred_display = st.columns([1, 2])
        
        with col_pred_btn:
            if st.button("🔮 Predict My Next Month Profit", type="primary", key="user_predict_btn"):
                with st.spinner("🤖 ML Agent predicting your profit..."):
                    resp = api("GET", f"/ml/predict-profit/{my_sid}")
                
                if resp and resp.status_code == 200:
                    prediction = resp.json()
                    st.session_state['last_prediction_user'] = prediction
                elif resp:
                    st.error(f"❌ {resp.json().get('detail', 'Prediction failed')}")
        
        with col_pred_display:
            if 'last_prediction_user' in st.session_state:
                pred = st.session_state['last_prediction_user']
                
                col1, col2, col3 = st.columns(3)
                col1.metric("📊 Historical Data", f"{pred.get('historical_months_used', 0)} months")
                col2.metric("🎯 Linear Regression", f"₹{pred.get('predicted_next_month_profit_lr', 0):,.2f}")
                col3.metric("📈 Moving Average", f"₹{pred.get('predicted_next_month_profit_ma', 0):,.2f}")
                
                # Show historical profit chart with predictions
                hist_profits = db_query("SELECT month, profit FROM profits WHERE seller_id=? ORDER BY month ASC", (my_sid,))
                if hist_profits:
                    df_hist = pd.DataFrame(hist_profits)
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(x=df_hist['month'], y=df_hist['profit'],
                                           mode='lines+markers', name='Historical',
                                           line=dict(color='#3b82f6', width=2)))
                    if len(df_hist) > 0:
                        next_month = (datetime.now() + timedelta(days=30)).strftime("%Y-%m")
                        last_m = df_hist['month'].iloc[-1]
                        last_p = df_hist['profit'].iloc[-1]
                        fig.add_trace(go.Scatter(x=[last_m, next_month],
                                               y=[last_p, pred.get('predicted_next_month_profit_lr', 0)],
                                               mode='lines+markers', name='LR Prediction',
                                               line=dict(color='#10b981', width=2, dash='dash')))
                        fig.add_trace(go.Scatter(x=[last_m, next_month],
                                               y=[last_p, pred.get('predicted_next_month_profit_ma', 0)],
                                               mode='lines+markers', name='MA Prediction',
                                               line=dict(color='#f59e0b', width=2, dash='dot')))
                    fig.update_layout(title="My Profit Trend with Predictions",
                                    xaxis_title="Month", yaxis_title="Profit (₹)",
                                    height=250, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Click 'Predict My Next Month Profit' to see your profit forecast.")

    # ── Recent activity ───────────────────────────────────────────────────────
    if is_admin:
        st.subheader("🕒 Recent Demand Posts")
        recent = db_query("""SELECT d.demand_id, s.name as seller, p.name as product,
                  d.qty_needed, d.status, d.created_at
           FROM demand_posts d
           JOIN sellers s ON d.seller_id=s.seller_id
           JOIN products p ON d.product_id=p.product_id
           ORDER BY d.created_at DESC LIMIT 10""")
    else:
        st.subheader("🕒 My Recent Demand Posts")
        recent = db_query("""SELECT d.demand_id, p.name as product,
                  d.qty_needed, d.status, d.created_at
           FROM demand_posts d
           JOIN products p ON d.product_id=p.product_id
           WHERE d.seller_id=?
           ORDER BY d.created_at DESC LIMIT 10""", (my_sid,))
    show_df(recent)


# ══════════════════════════════════════════════════════════════════════════════
# BILLING PAGE — multi-step HITL (ask_price → choose_seller → done)
# ══════════════════════════════════════════════════════════════════════════════

def _render_price_prompt(prompt: dict, thread_id: str, endpoint_prefix: str, key_prefix: str):
    """Inline form to resume the ask_price interrupt with user's qty + target price."""
    pmap = product_map()
    product_name = pmap.get(prompt.get("product_id"), f"Product #{prompt.get('product_id')}")

    st.markdown('<div class="approval-box">', unsafe_allow_html=True)
    st.info(f"""
**⏸️ Step 1 of 2 — Confirm qty & your target price**

{prompt.get("message", "")}

| | |
|--|--|
| Product | **{product_name}** |
| Current stock | {prompt.get("current_stock")} |
| 7-day threshold | {prompt.get("threshold")} |
| ML-suggested qty | **{prompt.get("suggested_qty")}** |
| Your selling price | ₹{prompt.get("your_selling_price", 0):.2f} |
| 30-day market avg | ₹{prompt.get("market_avg_price", 0):.2f} |
""")
    st.markdown("</div>", unsafe_allow_html=True)

    with st.form(f"{key_prefix}_price_form"):
        c1, c2 = st.columns(2)
        qty = c1.number_input(
            "Qty needed", min_value=1,
            value=int(prompt.get("suggested_qty") or 10), step=1,
        )
        target = c2.number_input(
            "Target price (₹/unit)", min_value=0.01,
            value=float(prompt.get("suggested_target_price") or 1.0), step=0.5,
            help="Agent will rank suppliers by how close their price is to this.",
        )
        submit = st.form_submit_button("➡️ Find suppliers", type="primary", use_container_width=True)
    if submit:
        with st.spinner("🔎 Finding suppliers..."):
            r = api("POST", f"{endpoint_prefix}/{thread_id}/set-price",
                    json={"qty": int(qty), "target_price": float(target)})
        if r and r.status_code == 200:
            st.session_state[f"{key_prefix}_response"] = r.json()
            st.rerun()
        elif r and r.status_code == 404:
            st.warning("⚠️ Session expired (server was restarted). Please start the workflow again.")
            st.session_state.pop(f"{key_prefix}_response", None)
            st.rerun()
        elif r:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            st.error(f"❌ {detail}")


def _render_seller_chooser(prompt: dict, thread_id: str, endpoint_prefix: str, key_prefix: str):
    """Inline form to resume the choose_seller interrupt with the user's pick."""
    candidates = prompt.get("candidates") or []
    target     = float(prompt.get("target_price") or 0.0)
    qty        = int(prompt.get("qty_needed") or 0)
    suggested  = prompt.get("suggested_supplier") or {}
    split_plan = prompt.get("split_plan")
    explanation = prompt.get("explanation")

    st.markdown('<div class="approval-box">', unsafe_allow_html=True)
    st.info(f"""
**⏸️ Step 2 of 2 — Pick a supplier**

{prompt.get("message", "")}

**🤖 Best single match:** **{suggested.get("seller_name")}** —
₹{suggested.get("selling_price", 0):.2f}/unit
({'+' if (suggested.get('price_delta') or 0) >= 0 else ''}₹{suggested.get("price_delta", 0):.2f} vs your target ₹{target:.2f}).
""")
    if explanation:
        st.caption(f"🤖 Agent: {explanation}")
    st.markdown("</div>", unsafe_allow_html=True)

    # Candidate table
    rows = []
    for c in candidates:
        pd_val = c.get("price_delta") or 0.0
        rows.append({
            "Seller":      c.get("seller_name"),
            "Location":    c.get("location"),
            "Stock":       c.get("stock_qty"),
            "Can fulfill": c.get("fulfillable_qty"),
            "Full cover":  "✅" if c.get("full_cover") else "partial",
            "Price ₹/unit": f"₹{float(c.get('selling_price', 0)):.2f}",
            "Δ vs target":  f"{'+' if pd_val >= 0 else ''}₹{pd_val:.2f}",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Decide tabs
    has_split = bool(split_plan and split_plan.get("picks"))
    tab_labels = ["Single Supplier"]
    if has_split:
        covered = split_plan["total_qty"]
        fully   = split_plan["fully_covered"]
        tab_labels.append(f"Split Plan ({covered}/{qty} units{'  ✅ fully covered' if fully else ' ⚠️ partial'})")

    tabs = st.tabs(tab_labels)

    # ── Tab 1: single supplier ──────────────────────────────────────────────────────────────────
    with tabs[0]:
        seller_options = {
            f"{c['seller_name']} — ₹{float(c['selling_price']):.2f}/unit (stock: {c['stock_qty']})": c
            for c in candidates
        }
        with st.form(f"{key_prefix}_choose_form"):
            pick_label  = st.selectbox("Select supplier", list(seller_options.keys()), index=0)
            pick        = seller_options[pick_label]
            c1, c2      = st.columns(2)
            offer_price = c1.number_input(
                "Offer price (₹/unit)", min_value=0.01,
                value=float(pick["selling_price"]), step=0.5,
                help="Supplier can accept, counter, or reject this.",
            )
            offer_qty = c2.number_input(
                "Qty to request", min_value=1,
                value=int(min(qty, pick["fulfillable_qty"])), step=1,
                max_value=int(pick["stock_qty"]),
            )
            cs, cc = st.columns(2)
            submit = cs.form_submit_button("📨 Send request", type="primary", use_container_width=True)
            cancel = cc.form_submit_button("❌ Cancel", use_container_width=True)

        if submit:
            with st.spinner("📨 Sending request to supplier..."):
                r = api("POST", f"{endpoint_prefix}/{thread_id}/choose-seller", json={
                    "seller_id":   int(pick["seller_id"]),
                    "offer_price": float(offer_price),
                    "qty":         int(offer_qty),
                })
            if r and r.status_code == 200:
                st.session_state[f"{key_prefix}_response"] = r.json()
                st.rerun()
            elif r and r.status_code == 404:
                st.warning("⚠️ Session expired (server was restarted). Please start the workflow again.")
                st.session_state.pop(f"{key_prefix}_response", None)
                st.rerun()
            elif r:
                try:
                    st.error(r.json().get("detail", r.text))
                except Exception:
                    st.error(r.text)
        if cancel:
            api("POST", f"{endpoint_prefix}/{thread_id}/cancel")
            st.session_state.pop(f"{key_prefix}_response", None)
            st.rerun()

    # ── Tab 2: split plan ───────────────────────────────────────────────────────────────────────────
    if has_split:
        with tabs[1]:
            picks = split_plan["picks"]
            avg   = split_plan["avg_unit_price"]
            total = split_plan["total_cost"]

            st.info(
                f"🔀 **Split across {len(picks)} suppliers** — "
                f"{split_plan['total_qty']} units total @ avg ₹{avg:.2f}/unit "
                f"(total ₹{total:,.2f}). "
                f"Your inventory **cost_price will be updated to ₹{avg:.2f}**."
            )

            split_rows = [{
                "Supplier":    p["seller_name"],
                "Qty":         p["qty"],
                "Price ₹/unit": f"₹{p['price']:.2f}",
                "Subtotal":    f"₹{p['subtotal']:,.2f}",
            } for p in picks]
            st.dataframe(pd.DataFrame(split_rows), use_container_width=True, hide_index=True)

            if not split_plan["fully_covered"]:
                st.warning(
                    f"⚠️ Only {split_plan['total_qty']} of {qty} units can be sourced right now. "
                    f"The remaining {qty - split_plan['total_qty']} units will stay as an open demand."
                )

            if st.button("🔀 Confirm split plan", type="primary",
                         key=f"{key_prefix}_split_confirm", use_container_width=True):
                with st.spinner("📨 Creating split requests..."):
                    r = api("POST", f"{endpoint_prefix}/{thread_id}/choose-seller",
                            json={"seller_id": 0, "offer_price": avg, "use_split": True})
                if r and r.status_code == 200:
                    st.session_state[f"{key_prefix}_response"] = r.json()
                    st.rerun()
                elif r:
                    try:
                        st.error(r.json().get("detail", r.text))
                    except Exception:
                        st.error(r.text)


def _render_final_result(data: dict, key_prefix: str):
    """After the graph ends — show anomaly (if any) then the billing outcome."""

    # ── Anomaly block (independent of stock outcome) ──────────────────────────
    if data.get("anomaly_detected"):
        st.markdown('<div class="anomaly-box">', unsafe_allow_html=True)
        st.warning("🚨 **Price Anomaly Detected**")
        st.write(data.get("anomaly_explanation") or "—")
        st.markdown("</div>", unsafe_allow_html=True)
        st.divider()

    # ── Billing outcome ───────────────────────────────────────────────────────
    if data.get("transfer_ids") and len(data["transfer_ids"]) > 1:
        st.markdown('<div class="success-box">', unsafe_allow_html=True)
        ids_str = ", ".join(f"#{i}" for i in data["transfer_ids"])
        st.success(
            f"🔀 **Split plan confirmed** — {len(data['transfer_ids'])} requests created ({ids_str}). "
            f"{data.get('transfer_qty')} units total @ avg ₹{data.get('chosen_price', 0):.2f}/unit. "
            f"Your inventory cost_price has been updated. Each supplier must approve on their Transfers page."
        )
        st.markdown("</div>", unsafe_allow_html=True)
    elif data.get("transfer_id"):
        # Full HITL flow completed — transfer sent to supplier
        st.markdown('<div class="success-box">', unsafe_allow_html=True)
        chosen_price = data.get("chosen_price") or 0.0
        st.success(
            f"📨 **Transfer #{data['transfer_id']} created** — "
            f"{data.get('transfer_qty')} units @ ₹{chosen_price:.2f}/unit. "
            f"Waiting for the supplier to approve, counter, or reject."
        )
        st.markdown("</div>", unsafe_allow_html=True)
    elif data.get("demand_created"):
        # Demand was created but no supplier found
        st.info(f"📋 Demand #{data.get('demand_id')} is open — no supplier has stock right now. You'll be notified when a match appears.")
    else:
        # Stock was fine — no demand needed
        if data.get("anomaly_detected"):
            st.success("✅ Billing recorded. Stock is above the reorder threshold — no demand was triggered. Review the anomaly above.")
        else:
            st.success("✅ Billing complete — stock is above threshold, no demand triggered.")

    st.divider()
    if st.button("🔄 New billing entry", key=f"{key_prefix}_reset", type="primary"):
        st.session_state.pop(f"{key_prefix}_response", None)
        st.rerun()


def billing_page():
    st.markdown('<div class="main-header"><h2>💳 Billing</h2><p>Sell stock — if it drops below threshold, the agent walks you through sourcing it back</p></div>', unsafe_allow_html=True)

    sellers  = get_sellers()
    products = get_products()
    smaps    = {s["name"]: s["seller_id"] for s in sellers}
    pmaps    = {p["name"]: p["product_id"] for p in products}

    my_sid        = st.session_state.get("seller_id")
    seller_names  = list(smaps.keys())
    seller_default = next((i for i, n in enumerate(seller_names) if smaps[n] == my_sid), 0)

    is_admin = st.session_state.get("role") == "admin"

    # ── If a workflow is in flight, show its current step ──────────────────────
    state = st.session_state.get("bill_response")
    if state:
        step = state.get("next_step")
        thread_id = state.get("thread_id")
        prompt    = state.get("prompt") or {}

        st.divider()
        if step == "ask_price" and state.get("paused"):
            # Show anomaly above the HITL prompt if one was detected
            if state.get("anomaly_detected"):
                st.markdown('<div class="anomaly-box">', unsafe_allow_html=True)
                st.warning("🚨 **Price Anomaly Detected** — billing was recorded, but review this before sourcing stock.")
                st.write(state.get("anomaly_explanation") or "—")
                st.markdown("</div>", unsafe_allow_html=True)
                st.divider()
            _render_price_prompt(prompt, thread_id, "/billing", "bill")
            return
        if step == "choose_seller" and state.get("paused"):
            _render_seller_chooser(prompt, thread_id, "/billing", "bill")
            return
        # Done / terminated
        _render_final_result(state, "bill")
        return

    # ── Form ───────────────────────────────────────────────────────────────────
    col_form, col_info = st.columns([1, 1])

    with col_form:
        st.subheader("📝 New Billing Entry")

        # Selectors OUTSIDE the form so changing them reruns immediately
        if is_admin:
            seller_name = st.selectbox("Seller", seller_names, index=seller_default, key="bill_seller")
        else:
            seller_name = seller_names[seller_default]
            st.info(f"🏪 Billing as: **{seller_name}**")
        product_name = st.selectbox("Product", list(pmaps.keys()), key="bill_product")

        sid = smaps[seller_name]
        pid = pmaps[product_name]
        inv = db_query(
            "SELECT stock_qty, selling_price, cost_price FROM inventory WHERE seller_id=? AND product_id=?",
            (sid, pid),
        )
        if inv:
            current_stock = int(inv[0]["stock_qty"])
            st.info(f"📦 Current stock: **{current_stock}** units | Selling price: ₹{inv[0]['selling_price']:.2f}")
            default_price = float(inv[0]["selling_price"])
        else:
            current_stock = 0
            st.warning("⚠️ No inventory record for this seller-product pair")
            default_price = 50.0

        with st.form("billing_form"):
            max_qty = max(1, current_stock)
            quantity = st.number_input(
                f"Quantity (max {current_stock})",
                min_value=1, max_value=max_qty,
                value=min(5, max_qty), step=1,
                help="Cannot bill more units than the current stock.",
            )
            price = st.number_input("Agreed Price (₹)", min_value=0.01,
                                    value=default_price, step=0.5,
                                    help="This price replaces the selling_price in inventory.")
            submitted = st.form_submit_button("⚡ Process Billing",
                                              use_container_width=True, type="primary")

    with col_info:
        st.subheader("ℹ️ How It Works")
        st.markdown("""
        **The HITL billing workflow:**
        1. 📉 Deducts qty from inventory (selling_price is also updated to this billed price)
        2. 📝 Records transaction + updates profits
        3. 🚨 Flags price anomalies (>20% deviation from 30-day avg)
        4. 🔍 Computes 7-day stock threshold
        5. ⏸️ **If low — asks you for qty + target price**
        6. 🔗 Shows all sellers with stock, ranked by price closeness
        7. ⏸️ **You pick the supplier** — request is sent, supplier approves/counters/rejects
        """)

    if submitted:
        with st.spinner("⚡ Processing billing..."):
            resp = api("POST", "/billing", json={
                "seller_id": sid, "product_id": pid,
                "quantity": int(quantity), "price": float(price),
            })
        if resp and resp.status_code == 200:
            st.session_state["bill_response"] = resp.json()
            st.rerun()
        elif resp:
            st.error(f"❌ {resp.json().get('detail', resp.text)}")


# ══════════════════════════════════════════════════════════════════════════════
# DEMAND PAGE
# ══════════════════════════════════════════════════════════════════════════════

def demand_page():
    st.markdown('<div class="main-header"><h2>🛒 Manual Demand</h2><p>Request stock from the seller network — HITL at every step</p></div>', unsafe_allow_html=True)

    sellers  = get_sellers()
    products = get_products()
    smaps    = {s["name"]: s["seller_id"] for s in sellers}
    pmaps    = {p["name"]: p["product_id"] for p in products}

    my_sid        = st.session_state.get("seller_id")
    is_admin      = st.session_state.get("role") == "admin"
    seller_names  = list(smaps.keys())
    seller_default = next((i for i, n in enumerate(seller_names) if smaps[n] == my_sid), 0)

    # ── If a demand workflow is in flight, show its current step ──────────────
    state = st.session_state.get("dem_response")
    if state:
        step = state.get("next_step")
        thread_id = state.get("thread_id")
        prompt    = state.get("prompt") or {}

        st.divider()
        if step == "ask_price" and state.get("paused"):
            _render_price_prompt(prompt, thread_id, "/demand", "dem")
            return
        if step == "choose_seller" and state.get("paused"):
            _render_seller_chooser(prompt, thread_id, "/demand", "dem")
            return
        _render_final_result(state, "dem")
        return

    col_form, col_history = st.columns([1, 1])

    with col_form:
        st.subheader("📋 Post a Demand")

        # Selectors OUTSIDE form so changing them reruns and shows live stock info
        if is_admin:
            seller_name = st.selectbox("Requesting Seller", seller_names, index=seller_default, key="dem_seller")
        else:
            seller_name = seller_names[seller_default]
            st.info(f"🏪 Posting as: **{seller_name}**")
        product_name = st.selectbox("Product Needed", list(pmaps.keys()), key="dem_product")

        dem_sid = smaps[seller_name]
        dem_pid = pmaps[product_name]
        dem_inv = db_query(
            "SELECT stock_qty, selling_price FROM inventory WHERE seller_id=? AND product_id=?",
            (dem_sid, dem_pid),
        )
        if dem_inv:
            st.info(f"📦 Current stock: **{dem_inv[0]['stock_qty']}** units | Selling price: ₹{dem_inv[0]['selling_price']:.2f}")
        else:
            st.warning("⚠️ No inventory record for this seller-product pair")

        with st.form("demand_form"):
            quantity = st.number_input("Quantity Required", min_value=1, value=20, step=5)
            st.caption("💡 Next you'll confirm the target price, then pick a supplier from all candidates.")
            submitted = st.form_submit_button("🛒 Start Demand Workflow", use_container_width=True, type="primary")

    with col_history:
        if is_admin:
            st.subheader("📜 Recent Demand Posts")
            recent_demands = db_query(
                """SELECT d.demand_id, s.name as seller, p.name as product,
                          d.qty_needed, d.status, d.created_at
                   FROM demand_posts d
                   JOIN sellers s ON d.seller_id=s.seller_id
                   JOIN products p ON d.product_id=p.product_id
                   ORDER BY d.demand_id DESC LIMIT 12"""
            )
        else:
            st.subheader("📜 My Demand Posts")
            recent_demands = db_query(
                """SELECT d.demand_id, p.name as product,
                          d.qty_needed, d.status, d.created_at
                   FROM demand_posts d
                   JOIN products p ON d.product_id=p.product_id
                   WHERE d.seller_id=?
                   ORDER BY d.demand_id DESC LIMIT 12""",
                (my_sid,),
            )
        show_df(recent_demands, height=280)

    if submitted:
        with st.spinner("🔎 Starting demand workflow..."):
            resp = api("POST", "/demand", json={
                "seller_id": dem_sid, "product_id": dem_pid, "quantity": int(quantity),
            })
        if resp and resp.status_code == 200:
            st.session_state["dem_response"] = resp.json()
            st.rerun()
        elif resp:
            st.error(f"❌ {resp.json().get('detail', resp.text)}")


# ══════════════════════════════════════════════════════════════════════════════
# ASK AGENT PAGE
# ══════════════════════════════════════════════════════════════════════════════

def ask_page():
    st.markdown('<div class="main-header"><h2>🤖 Ask Agent</h2><p>Natural language queries routed to RAG, SQL, or Demand agents</p></div>', unsafe_allow_html=True)

    sellers  = get_sellers()
    products = get_products()
    smaps    = {s["name"]: s["seller_id"] for s in sellers}
    pmaps    = {p["name"]: p["product_id"] for p in products}

    my_sid        = st.session_state.get("seller_id")
    seller_names  = list(smaps.keys())
    seller_default = next((i for i, n in enumerate(seller_names) if smaps[n] == my_sid), 0)

    is_admin = st.session_state.get("role") == "admin"

    col_q, col_meta = st.columns([2, 1])
    with col_q:
        query = st.text_area("💬 Your Question", height=100,
                             placeholder='e.g. "Why was the price flagged?" or "Show profit for this month"')
    with col_meta:
        if is_admin:
            seller_name = st.selectbox("Context: Seller", seller_names, index=seller_default)
        else:
            seller_name = seller_names[seller_default]
            st.info(f"🏪 Context: **{seller_name}**")
        product_name = st.selectbox("Context: Product (optional)", ["— None —"] + list(pmaps.keys()))

    # Example queries
    st.markdown("**Quick examples:**")
    ex_cols = st.columns(4)
    examples = [
        ("Why was price flagged?", "rag"),
        ("Show total profit by seller", "sql"),
        ("Check stock threshold", "demand"),
        ("Explain rejection pattern", "rag"),
    ]
    for i, (ex, agent) in enumerate(examples):
        badge = {"rag": "🔍 RAG", "sql": "📊 SQL", "demand": "📦 Demand"}[agent]
        if ex_cols[i].button(f"{badge}: {ex}", key=f"ex_{i}"):
            query = ex

    if st.button("🚀 Ask", type="primary", disabled=not query.strip()):
        sid = smaps[seller_name]
        pid = pmaps.get(product_name)

        with st.spinner("🤖 Agent thinking..."):
            resp = api("POST", "/ask", json={
                "query": query,
                "seller_id": sid,
                "product_id": pid,
            })

        if resp and resp.status_code == 200:
            data = resp.json()
            agent_labels = {
                "rag": ("🔍 RAG Agent", "#7c3aed"),
                "sql": ("📊 SQL Agent", "#0369a1"),
                "demand": ("📦 Demand Agent", "#065f46"),
            }
            label, color = agent_labels.get(data["agent_used"], ("🤖 Agent", "#374151"))
            st.markdown(f'<span style="background:{color};color:white;padding:3px 12px;border-radius:20px;font-size:0.8rem;">Routed to: {label}</span>', unsafe_allow_html=True)
            st.markdown("---")
            st.markdown("### 💡 Answer")
            st.markdown(data["answer"])
        elif resp and resp.status_code == 422:
            st.warning(f"⚠️ {resp.json().get('detail', 'Validation error')}")
        elif resp:
            st.error(f"❌ {resp.json().get('detail', resp.text)}")


# ══════════════════════════════════════════════════════════════════════════════
# SQL ANALYTICS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def sql_page():
    st.markdown('<div class="main-header"><h2>📈 SQL Analytics</h2><p>Ask anything — the SQL Agent translates natural language into database queries</p></div>', unsafe_allow_html=True)

    is_admin = st.session_state.get("role") == "admin"
    my_sid   = st.session_state.get("seller_id")
    scoped   = not is_admin and my_sid is not None

    # Preset queries
    st.subheader("📋 Preset Queries")
    month_label = datetime.now().strftime("%B %Y")
    if is_admin:
        presets = {
            "Top 5 sellers by profit this month":     f"Which sellers have the highest profit in {month_label}?",
            "Products with most transactions":         "Which products have the highest number of completed transactions?",
            "Low stock alert":                         "Which sellers have products with stock below 10 units?",
            "Rejection analysis":                      "Show all transactions with rejection status and count by reason",
            "Transfer summary":                        "Summarise all transfers by status with total quantity and value",
            "Monthly profit trend for all sellers":    "Show monthly profit trend for all sellers over the past 6 months",
        }
    else:
        sellers_list = get_sellers()
        my_name = next((s["name"] for s in sellers_list if s["seller_id"] == my_sid), "my store")
        presets = {
            f"My profit this month":                   f"What is the total profit for seller_id {my_sid} ({my_name}) in {month_label}?",
            f"My top-selling products":                f"Which products has seller_id {my_sid} ({my_name}) sold the most units of?",
            f"My low stock items":                     f"Which products does seller_id {my_sid} ({my_name}) have with stock below 10 units?",
            f"My transaction history":                 f"Show recent completed transactions for seller_id {my_sid} ({my_name})",
            f"My transfer activity":                   f"Show all transfers involving seller_id {my_sid} ({my_name}) with status and value",
            f"My monthly profit trend":                f"Show monthly profit trend for seller_id {my_sid} ({my_name}) over the past 6 months",
        }

    preset = st.selectbox("Choose a preset query", ["— Custom query —"] + list(presets.keys()))
    if preset != "— Custom query —":
        query_text = presets[preset]
    else:
        query_text = ""

    placeholder = "e.g. Show top sellers by revenue last month" if is_admin else f"e.g. Show my profit for this month (scoped to your store)"
    query = st.text_area("SQL / Natural Language Query", value=query_text, height=80, placeholder=placeholder)
    if not is_admin:
        st.caption(f"🏪 Queries are contextually scoped to your store (seller_id {my_sid}).")
        if query_text == "" and query.strip() and str(my_sid) not in query:
            query = query  # user typed custom query — allow but don't inject seller_id automatically

    if st.button("▶️ Run Query", type="primary", disabled=not query.strip()):
        # Guardrail check
        blocked = any(k in query.upper() for k in ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER"])
        if blocked:
            st.error("🚫 Query blocked: only SELECT operations are allowed.")
        else:
            with st.spinner("📊 SQL Agent working..."):
                resp = api("GET", f"/sql", params={"query": query})
            if resp and resp.status_code == 200:
                result = resp.json()["result"]
                st.markdown("### 📊 Result")
                st.markdown(result)
            elif resp and resp.status_code == 403:
                st.error(f"🚫 {resp.json().get('detail')}")
            elif resp:
                st.error(f"❌ {resp.json().get('detail', resp.text)}")

    st.divider()

    # Live profit chart
    months = db_query("SELECT DISTINCT month FROM profits ORDER BY month DESC LIMIT 6")
    sel_months = [m["month"] for m in months]
    if not sel_months:
        st.info("📉 No profit data yet — complete some transactions to see the trend chart.")
    elif scoped:
        st.subheader("📉 My Profit by Month")
        profit_data = db_query(
            f"""SELECT p.month, p.profit FROM profits p
                WHERE p.seller_id=? AND p.month IN ({','.join('?'*len(sel_months))})
                ORDER BY p.month""",
            (my_sid, *sel_months),
        )
        if profit_data:
            line_chart(pd.DataFrame(profit_data), "month", "profit", "My Monthly Profit", height=350)
        else:
            st.info("No profit data for your store yet.")
    else:
        st.subheader("📉 Seller Profit by Month")
        profit_data = db_query(
            f"""SELECT s.name, p.month, p.profit FROM profits p
                JOIN sellers s ON p.seller_id=s.seller_id
                WHERE p.month IN ({','.join('?'*len(sel_months))})
                ORDER BY p.month""",
            tuple(sel_months),
        )
        if profit_data:
            line_chart(pd.DataFrame(profit_data), "month", "profit", "Seller Profit Trends", color="name", height=350)
        else:
            st.info("No profit data yet.")


# ══════════════════════════════════════════════════════════════════════════════
# INVENTORY PAGE
# ══════════════════════════════════════════════════════════════════════════════

def inventory_page():
    st.markdown('<div class="main-header"><h2>📦 Inventory</h2><p>Real-time stock levels across all sellers</p></div>', unsafe_allow_html=True)

    sellers  = get_sellers()
    smaps    = {s["name"]: s["seller_id"] for s in sellers}
    is_admin = st.session_state.get("role") == "admin"
    my_sid   = st.session_state.get("seller_id")

    options = ["All Sellers"] + list(smaps.keys())
    if is_admin:
        default_idx = 0
    else:
        # Default to logged-in seller's name
        my_name = next((s["name"] for s in sellers if s["seller_id"] == my_sid), None)
        default_idx = options.index(my_name) if my_name in options else 0

    selected = st.selectbox("Filter by Seller", options, index=default_idx)

    if selected == "All Sellers":
        data = db_query(
            """SELECT s.name as Seller, p.name as Product, p.category as Category,
                      i.stock_qty as Stock, i.cost_price as Cost, i.selling_price as Price,
                      ROUND((i.selling_price - i.cost_price)/NULLIF(i.cost_price,0)*100,1) as Margin_pct
               FROM inventory i
               JOIN sellers s ON i.seller_id=s.seller_id
               JOIN products p ON i.product_id=p.product_id
               ORDER BY i.stock_qty ASC"""
        )
    else:
        sid = smaps[selected]
        data = db_query(
            """SELECT p.name as Product, p.category as Category,
                      i.stock_qty as Stock, i.cost_price as Cost, i.selling_price as Price,
                      ROUND((i.selling_price - i.cost_price)/NULLIF(i.cost_price,0)*100,1) as Margin_pct
               FROM inventory i
               JOIN products p ON i.product_id=p.product_id
               WHERE i.seller_id=?
               ORDER BY i.stock_qty ASC""",
            (sid,),
        )

    if not data:
        st.info("📦 No inventory records found. Run `python scripts/seed_test_data.py` to add sample data.")
    else:
        df = pd.DataFrame(data)

        # Color-code stock levels
        def stock_color(val):
            if val == 0: return "background-color:#fee2e2"
            if val <= 10: return "background-color:#ffedd5"
            if val <= 50: return "background-color:#fef9c3"
            return "background-color:#dcfce7"

        st.dataframe(
            df.style.map(stock_color, subset=["Stock"]),
            use_container_width=True,
            hide_index=True,
            height=420,
        )

        col_l, col_r = st.columns(2)
        with col_l:
            # Stock level bar chart — single seller
            if selected != "All Sellers":
                df_sorted = df.sort_values("Stock")
                fig = px.bar(df_sorted, x="Stock", y="Product", orientation="h",
                             color="Stock", color_continuous_scale="RdYlGn",
                             title=f"{selected} — Stock Levels",
                             labels={"Stock": "Stock (units)"})
                fig.update_layout(height=380, margin=dict(t=40, b=10), yaxis=dict(autorange="reversed"))
                st.plotly_chart(fig, use_container_width=True)
            else:
                # All sellers: stock distribution by category
                cat_stock = df.groupby("Category")["Stock"].sum().reset_index().sort_values("Stock", ascending=False)
                fig = px.bar(cat_stock, x="Category", y="Stock",
                             color="Stock", color_continuous_scale="Blues",
                             title="Total Stock by Category",
                             labels={"Stock": "Total Units"})
                fig.update_layout(height=380, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)

        with col_r:
            if selected == "All Sellers":
                # Seller-wise total stock
                seller_stock = df.groupby("Seller")["Stock"].sum().reset_index().sort_values("Stock", ascending=False)
                fig = px.bar(seller_stock, x="Seller", y="Stock",
                             color="Stock", color_continuous_scale="Greens",
                             title="Total Stock per Seller",
                             labels={"Stock": "Total Units"})
                fig.update_layout(height=380, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                # Margin distribution pie for single seller
                if "Margin_pct" in df.columns and df["Margin_pct"].notna().any():
                    fig = px.scatter(df, x="Cost", y="Price", size="Stock",
                                     hover_name="Product", color="Margin_pct",
                                     color_continuous_scale="RdYlGn",
                                     title="Cost vs Price (bubble = stock qty)",
                                     labels={"Cost": "Cost Price (₹)", "Price": "Selling Price (₹)"})
                    fig.update_layout(height=380, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TRANSFERS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def transfers_page():
    is_admin = st.session_state.get("role") == "admin"
    my_sid   = st.session_state.get("seller_id")

    if is_admin:
        st.markdown('<div class="main-header"><h2>🔄 Transfers</h2><p>Inter-seller stock transfer history</p></div>', unsafe_allow_html=True)
        stats = db_query("SELECT status, COUNT(*) as count, SUM(qty*transfer_price) as value FROM transfers GROUP BY status")
    else:
        st.markdown('<div class="main-header"><h2>🔄 My Transfers</h2><p>Your incoming and outgoing stock transfers</p></div>', unsafe_allow_html=True)
        stats = db_query("SELECT status, COUNT(*) as count, SUM(qty*transfer_price) as value FROM transfers WHERE from_seller_id=? OR to_seller_id=? GROUP BY status", (my_sid, my_sid))

    # ── Incoming supply requests (I am the SUPPLIER — my decision) ────────────
    if my_sid:
        pending_resp     = api("GET", "/pending-transfers")        # I'm supplier
        countered_resp   = api("GET", "/countered-transfers")      # I'm buyer, supplier countered
        outgoing_resp    = api("GET", "/my-outgoing-requests")     # I'm buyer, waiting on supplier

        incoming    = (pending_resp.json()   if pending_resp   and pending_resp.status_code   == 200 else [])
        my_counters = (countered_resp.json() if countered_resp and countered_resp.status_code == 200 else [])
        my_outgoing = (outgoing_resp.json()  if outgoing_resp  and outgoing_resp.status_code  == 200 else [])

        # ── 1) Incoming (I am the supplier — approve / counter / reject) ──────
        if incoming:
            st.subheader("📥 Incoming Requests — Your Decision as Supplier")
            pmap = product_map()
            smap = seller_map()
            for t in incoming:
                tid     = t["transfer_id"]
                buyer   = t.get("to_seller_name") or smap.get(t["to_seller_id"], f"Seller #{t['to_seller_id']}")
                product = t.get("product_name")   or pmap.get(t["product_id"],   f"Product #{t['product_id']}")
                rounds  = t.get("negotiation_rounds") or 1

                with st.expander(
                    f"Request #{tid} — {buyer} wants {t['qty']} × {product} @ ₹{t['transfer_price']:.2f}",
                    expanded=True,
                ):
                    col_info, col_act = st.columns([2, 1])
                    with col_info:
                        st.markdown(f"""
| | |
|--|--|
| Buyer | **{buyer}** |
| Product | {product} × {t['qty']} units |
| Buyer's Offer | **₹{t['transfer_price']:.2f}/unit** |
| Total Value | ₹{t['transfer_price'] * t['qty']:,.2f} |
| Negotiation Rounds | {rounds} |
                        """)

                    with col_act:
                        if st.button("✅ Approve & Ship", key=f"pt_app_{tid}", type="primary", use_container_width=True):
                            r = api("POST", f"/respond-transfer/{tid}", json={"approved": True})
                            if r and r.status_code == 200:
                                data = r.json()
                                st.success(data.get("message", "Approved."))
                                if data.get("below_cost_warning"):
                                    st.warning(data["below_cost_message"])
                                st.rerun()
                            elif r:
                                st.error(r.json().get("detail", r.text))

                        st.markdown("**— or counter —**")
                        counter_val = st.number_input(
                            "Your counter price (₹/unit)",
                            min_value=0.01,
                            value=round(float(t["transfer_price"]) * 1.05, 2),
                            step=0.50, key=f"ctr_val_{tid}",
                            help="Ask for a higher price — the buyer can accept or reject.",
                        )
                        if st.button("💬 Send Counter-Offer", key=f"pt_neg_{tid}", use_container_width=True):
                            r = api("POST", f"/negotiate-transfer/{tid}",
                                    json={"counter_price": counter_val})
                            if r and r.status_code == 200:
                                st.info(r.json()["message"])
                                st.rerun()
                            elif r:
                                st.error(r.json().get("detail", r.text))

                        if st.button("❌ Reject Request", key=f"pt_rej_{tid}", use_container_width=True):
                            r = api("POST", f"/respond-transfer/{tid}", json={"approved": False})
                            if r and r.status_code == 200:
                                st.info("Request rejected.")
                                st.rerun()
                            elif r:
                                st.error(r.json().get("detail", r.text))

        # ── 2) My outgoing requests waiting on supplier ───────────────────────
        if my_outgoing:
            st.subheader("📤 My Requests Waiting on Supplier")
            rows = []
            for t in my_outgoing:
                rows.append({
                    "ID":       t["transfer_id"],
                    "Supplier": t.get("from_seller_name"),
                    "Product":  t.get("product_name"),
                    "Qty":      t["qty"],
                    "My Offer": f"₹{t['transfer_price']:.2f}",
                    "Total":    f"₹{t['total_value']:,.2f}",
                    "Status":   "⏳ awaiting supplier",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # ── 3) Supplier sent me a counter (I'm buyer — accept/reject counter) ─
        if my_counters:
            st.subheader("🔁 Supplier Counter-Offers Awaiting Your Response")
            pmap = product_map()
            smap = seller_map()
            for t in my_counters:
                tid      = t["transfer_id"]
                supplier = t.get("from_seller_name") or smap.get(t["from_seller_id"], f"Seller #{t['from_seller_id']}")
                product  = t.get("product_name")    or pmap.get(t["product_id"],    f"Product #{t['product_id']}")

                with st.expander(
                    f"Request #{tid} — {supplier} countered: ₹{t.get('counter_price', 0):.2f} (you offered ₹{t['transfer_price']:.2f})",
                    expanded=True,
                ):
                    col_info, col_act = st.columns([2, 1])
                    with col_info:
                        delta = (t.get("counter_price", 0) - t["transfer_price"]) * t["qty"]
                        st.markdown(f"""
| | |
|--|--|
| Supplier | **{supplier}** |
| Product | {product} × {t['qty']} units |
| Your Offer | ₹{t['transfer_price']:.2f}/unit |
| Supplier's Counter | **₹{t.get('counter_price', 0):.2f}/unit** |
| Extra cost if accepted | ₹{delta:,.2f} total |
                        """)
                    with col_act:
                        if st.button("✅ Accept Counter", key=f"acc_ctr_{tid}", type="primary", use_container_width=True):
                            r = api("POST", f"/accept-counter/{tid}")
                            if r and r.status_code == 200:
                                st.success(r.json()["message"])
                                st.rerun()
                            elif r:
                                st.error(r.json().get("detail", r.text))

                        st.markdown("**— or negotiate —**")
                        my_counter = st.number_input(
                            "Your counter price (₹/unit)",
                            min_value=0.01,
                            value=round(float(t["transfer_price"]) * 1.02, 2),
                            step=0.50, key=f"buy_ctr_val_{tid}",
                            help="Send a new offer back to the supplier.",
                        )
                        if st.button("💬 Send My Counter", key=f"buy_ctr_{tid}", use_container_width=True):
                            r = api("POST", f"/buyer-counter/{tid}", json={"counter_price": my_counter})
                            if r and r.status_code == 200:
                                st.info(r.json()["message"])
                                st.rerun()
                            elif r:
                                st.error(r.json().get("detail", r.text))

                        if st.button("❌ Reject Counter", key=f"rej_ctr_{tid}", use_container_width=True):
                            r = api("POST", f"/reject-counter/{tid}")
                            if r and r.status_code == 200:
                                st.info("Counter rejected. Transfer closed.")
                                st.rerun()
                            elif r:
                                st.error(r.json().get("detail", r.text))

        if incoming or my_counters or my_outgoing:
            st.divider()

    cols = st.columns(len(stats) if stats else 1)
    for i, s in enumerate(stats):
        emoji = {"completed": "✅", "pending": "⏳", "rejected": "❌"}.get(s["status"], "📋")
        cols[i].metric(f"{emoji} {s['status'].title()}", s["count"],
                       delta=f"₹{(s['value'] or 0):,.0f} value")

    st.divider()

    # Table
    if is_admin:
        transfers = db_query(
            """SELECT t.transfer_id as ID,
                      sf.name as From_Seller, st2.name as To_Seller,
                      p.name as Product, t.qty as Qty,
                      t.transfer_price as Price,
                      ROUND(t.qty * t.transfer_price, 2) as Total_Value,
                      t.status as Status
               FROM transfers t
               JOIN sellers sf  ON t.from_seller_id = sf.seller_id
               JOIN sellers st2 ON t.to_seller_id   = st2.seller_id
               JOIN products p  ON t.product_id     = p.product_id
               ORDER BY t.transfer_id DESC"""
        )
    else:
        transfers = db_query(
            """SELECT t.transfer_id as ID,
                      sf.name as From_Seller, st2.name as To_Seller,
                      p.name as Product, t.qty as Qty,
                      t.transfer_price as Price,
                      ROUND(t.qty * t.transfer_price, 2) as Total_Value,
                      t.status as Status
               FROM transfers t
               JOIN sellers sf  ON t.from_seller_id = sf.seller_id
               JOIN sellers st2 ON t.to_seller_id   = st2.seller_id
               JOIN products p  ON t.product_id     = p.product_id
               WHERE t.from_seller_id=? OR t.to_seller_id=?
               ORDER BY t.transfer_id DESC""",
            (my_sid, my_sid)
        )

    if transfers:
        df = pd.DataFrame(transfers)

        all_statuses  = sorted(df["Status"].unique().tolist())
        status_filter = st.multiselect("Filter by status", all_statuses, default=all_statuses)
        df_filtered = df[df["Status"].isin(status_filter)]
        st.dataframe(df_filtered, use_container_width=True, hide_index=True)

        if len(df) > 0:
            col_l, col_r = st.columns(2)
            with col_l:
                fig = px.pie(df, names="Status", values="Total_Value",
                             title="Transfer Value by Status",
                             color_discrete_map={"completed": "#22c55e", "pending": "#f59e0b", "rejected": "#ef4444"})
                fig.update_layout(height=300, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)
            with col_r:
                fig = None
                if is_admin:
                    top_from = df.groupby("From_Seller")["Total_Value"].sum().reset_index().sort_values("Total_Value", ascending=False).head(5)
                    if not top_from.empty:
                        fig = px.bar(top_from, x="From_Seller", y="Total_Value",
                                     title="Top Supplying Sellers by Transfer Value",
                                     color="Total_Value", color_continuous_scale="Blues")
                else:
                    sellers_list = get_sellers()
                    my_name = next((s["name"] for s in sellers_list if s["seller_id"] == my_sid), "")
                    df["Direction"] = df.apply(
                        lambda r: "Outgoing" if r["From_Seller"] == my_name else "Incoming", axis=1
                    )
                    dir_df = df.groupby("Direction")["Total_Value"].sum().reset_index()
                    if not dir_df.empty:
                        fig = px.bar(dir_df, x="Direction", y="Total_Value",
                                     title="My Transfer Value: Incoming vs Outgoing",
                                     color="Direction",
                                     color_discrete_map={"Incoming": "#22c55e", "Outgoing": "#3b82f6"})
                if fig:
                    fig.update_layout(height=300, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No transfer records found.")


# ══════════════════════════════════════════════════════════════════════════════
# APPROVALS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def approvals_page():
    st.markdown('<div class="main-header"><h2>⏳ Approvals</h2><p>Everything that needs a human click right now</p></div>', unsafe_allow_html=True)

    my_sid = st.session_state.get("seller_id")
    if not my_sid:
        st.info("Log in as a seller to see your approvals.")
        return

    incoming_resp  = api("GET", "/pending-transfers")
    counters_resp  = api("GET", "/countered-transfers")
    outgoing_resp  = api("GET", "/my-outgoing-requests")

    incoming  = incoming_resp.json()  if incoming_resp  and incoming_resp.status_code  == 200 else []
    counters  = counters_resp.json()  if counters_resp  and counters_resp.status_code  == 200 else []
    outgoing  = outgoing_resp.json()  if outgoing_resp  and outgoing_resp.status_code  == 200 else []

    c1, c2, c3 = st.columns(3)
    c1.metric("📥 Incoming supply requests", len(incoming),
              help="Buyers are waiting on your decision.")
    c2.metric("🔁 Supplier counters to resolve", len(counters),
              help="Suppliers sent you a counter-offer — accept or reject.")
    c3.metric("📤 My outgoing requests", len(outgoing),
              help="Requests you've sent; waiting for suppliers.")

    if not (incoming or counters or outgoing):
        st.success("✅ Nothing needs your attention. Go to Billing or Manual Demand to create a new request.")
        st.subheader("📋 Recently Completed Transfers")
        recent = db_query(
            """SELECT t.transfer_id, sf.name as from_seller, st2.name as to_seller,
                      p.name as product, t.qty, t.transfer_price, t.status
               FROM transfers t
               JOIN sellers sf  ON t.from_seller_id=sf.seller_id
               JOIN sellers st2 ON t.to_seller_id=st2.seller_id
               JOIN products p  ON t.product_id=p.product_id
               WHERE t.from_seller_id=? OR t.to_seller_id=?
               ORDER BY t.transfer_id DESC LIMIT 10""",
            (my_sid, my_sid),
        )
        show_df(recent)
        return

    st.info("👉 Use the **Transfers** page to take action on incoming requests and counter-offers.")


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN PANEL
# ══════════════════════════════════════════════════════════════════════════════

def admin_page():
    st.markdown('<div class="main-header"><h2>⚙️ Admin Panel</h2><p>System Management & Configuration</p></div>', unsafe_allow_html=True)
    
    # Check if user is admin
    if st.session_state.get('role') != 'admin':
        st.error("🚫 Access Denied: Admin privileges required")
        return
    
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["📊 Stats", "👥 Users", "🏪 Stores", "📦 Products", "📦 Inventory", "🗑️ Data Management"])

    # ── TAB 1: System Statistics ─────────────────────────────────────────────
    with tab1:
        st.subheader("System Statistics")
        resp = api("GET", "/admin/stats")
        if resp and resp.status_code == 200:
            stats = resp.json()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("👥 Total Users",      stats["total_users"])
            col2.metric("🏪 Total Stores",     stats["total_sellers"])
            col3.metric("📦 Total Products",   stats["total_products"])
            col4.metric("📊 Inventory Items",  stats["total_inventory_items"])

            col5, col6, col7, col8 = st.columns(4)
            col5.metric("💳 Transactions",  stats["total_transactions"])
            col6.metric("🛒 Demand Posts",  stats["total_demand_posts"])
            col7.metric("🔄 Transfers",     stats["total_transfers"])
            col8.metric("🔑 Admins",        stats["admin_users"])
        else:
            st.error("Failed to load statistics")

        st.divider()
        st.subheader("📈 Network Analytics")
        col_a, col_b = st.columns(2)

        with col_a:
            # Seller profit comparison
            profit_data = db_query(
                """SELECT s.name as Seller, SUM(p.profit) as Profit
                   FROM profits p JOIN sellers s ON p.seller_id=s.seller_id
                   GROUP BY s.name ORDER BY Profit DESC"""
            )
            if profit_data:
                fig = px.bar(pd.DataFrame(profit_data), x="Seller", y="Profit",
                             color="Profit", color_continuous_scale="Viridis",
                             title="Total Profit per Seller",
                             labels={"Profit": "Profit (₹)"})
                fig.update_layout(height=300, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No profit data yet.")

        with col_b:
            # Transfer status overview
            t_stats = db_query("SELECT status, COUNT(*) as count FROM transfers GROUP BY status")
            if t_stats:
                fig = px.pie(pd.DataFrame(t_stats), names="status", values="count",
                             title="Transfer Status Distribution",
                             color="status",
                             color_discrete_map={"completed": "#22c55e", "pending": "#f59e0b",
                                                 "rejected": "#ef4444", "countered": "#8b5cf6"})
                fig.update_layout(height=300, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No transfer data yet.")

        col_c, col_d = st.columns(2)
        with col_c:
            # Monthly profit trend
            monthly = db_query(
                """SELECT month, SUM(profit) as total FROM profits
                   GROUP BY month ORDER BY month ASC LIMIT 12"""
            )
            if monthly:
                fig = px.line(pd.DataFrame(monthly), x="month", y="total", markers=True,
                              title="Network Monthly Profit Trend",
                              labels={"month": "Month", "total": "Total Profit (₹)"})
                fig.update_layout(height=280, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)

        with col_d:
            # Demand post status
            dem_stats = db_query("SELECT status, COUNT(*) as count FROM demand_posts GROUP BY status")
            if dem_stats:
                fig = px.pie(pd.DataFrame(dem_stats), names="status", values="count",
                             title="Demand Post Status",
                             color="status",
                             color_discrete_map={"open": "#f59e0b", "fulfilled": "#22c55e",
                                                 "cancelled": "#ef4444"})
                fig.update_layout(height=280, margin=dict(t=40, b=10))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No demand data yet.")
    
    # ── TAB 2: User Management ────────────────────────────────────────────────
    with tab2:
        st.subheader("User Management")
        
        # Fetch users
        resp = api("GET", "/admin/users")
        if resp and resp.status_code == 200:
            users = resp.json()
            
            show_df(users)

            if users:
                st.markdown("---")

                # User actions
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("### Update User")
                    user_ids = [u["user_id"] for u in users]
                    selected_user_id = st.selectbox("Select User", user_ids, format_func=lambda x: f"ID: {x} - {next((u['username'] for u in users if u['user_id'] == x), 'Unknown')}")

                    new_role = st.selectbox("New Role", ["seller", "admin"])
                    new_seller = st.number_input("New Seller ID (0 for admin)", min_value=0, value=0)
                    new_password = st.text_input("New Password (leave empty to keep current)", type="password")

                    if st.button("Update User", type="primary"):
                        update_data = {"role": new_role}
                        if new_seller > 0:
                            update_data["seller_id"] = new_seller
                        else:
                            update_data["seller_id"] = None
                        if new_password:
                            update_data["password"] = new_password

                        resp = api("PUT", f"/admin/users/{selected_user_id}", json=update_data)
                        if resp and resp.status_code == 200:
                            st.success("User updated successfully!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")

                with col2:
                    st.markdown("### Delete User")
                    delete_user_id = st.selectbox(
                        "Select User to Delete",
                        user_ids,
                        format_func=lambda x: f"ID: {x} - {next((u['username'] for u in users if u['user_id'] == x), 'Unknown')}",
                        key="delete_user"
                    )

                    if st.button("🗑️ Delete User", type="secondary"):
                        resp = api("DELETE", f"/admin/users/{delete_user_id}")
                        if resp and resp.status_code == 200:
                            st.success("User deleted!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")
        else:
            st.error("Failed to load users")
    
    # ── TAB 3: Store Management ───────────────────────────────────────────────
    with tab3:
        st.subheader("Store Management")
        
        # Create new store
        with st.expander("➕ Create New Store"):
            with st.form("create_store"):
                store_name = st.text_input("Store Name")
                store_location = st.text_input("Location")
                store_sector = st.selectbox("Sector", ["retail", "wholesale"])
                
                if st.form_submit_button("Create Store"):
                    resp = api("POST", "/admin/sellers", json={
                        "name": store_name,
                        "location": store_location,
                        "sector": store_sector
                    })
                    if resp and resp.status_code == 200:
                        st.success("Store created successfully!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")
        
        # Display stores
        sellers = get_sellers()
        show_df(sellers)
        
        st.markdown("---")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Update Store")
            seller_ids = [s["seller_id"] for s in sellers]
            selected_seller = st.selectbox(
                "Select Store", 
                seller_ids, 
                format_func=lambda x: f"ID: {x} - {next((s['name'] for s in sellers if s['seller_id'] == x), 'Unknown')}"
            )
            
            current_seller = next((s for s in sellers if s["seller_id"] == selected_seller), None)
            if current_seller:
                upd_name = st.text_input("Name", value=current_seller["name"])
                upd_location = st.text_input("Location", value=current_seller["location"])
                upd_sector = st.selectbox("Sector", ["retail", "wholesale"], index=0 if current_seller["sector"] == "retail" else 1)
                
                if st.button("Update Store", type="primary"):
                    resp = api("PUT", f"/admin/sellers/{selected_seller}", json={
                        "name": upd_name,
                        "location": upd_location,
                        "sector": upd_sector
                    })
                    if resp and resp.status_code == 200:
                        st.success("Store updated!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")
        
        with col2:
            st.markdown("### Delete Store")
            del_seller = st.selectbox(
                "Select Store to Delete", 
                seller_ids, 
                format_func=lambda x: f"ID: {x} - {next((s['name'] for s in sellers if s['seller_id'] == x), 'Unknown')}",
                key="delete_seller"
            )
            st.warning("⚠️ This will delete all associated data (inventory, transactions, users, etc.)")
            
            if st.button("🗑️ Delete Store", type="secondary"):
                resp = api("DELETE", f"/admin/sellers/{del_seller}")
                if resp and resp.status_code == 200:
                    st.success("Store and all associated data deleted!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")
    
    # ── TAB 4: Product Management ─────────────────────────────────────────────
    with tab4:
        st.subheader("Product Management")
        
        # Create new product
        with st.expander("➕ Create New Product"):
            with st.form("create_product"):
                prod_name = st.text_input("Product Name")
                prod_category = st.text_input("Category")
                prod_unit = st.selectbox("Unit", ["kg", "litre", "packet", "bag", "bar", "bottle", "tube", "jar", "piece"])
                
                if st.form_submit_button("Create Product"):
                    resp = api("POST", "/admin/products", json={
                        "name": prod_name,
                        "category": prod_category,
                        "unit": prod_unit
                    })
                    if resp and resp.status_code == 200:
                        st.success("Product created successfully!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")
        
        # Display products
        products = get_products()
        show_df(products)

        st.markdown("---")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Update Product")
            product_ids = [p["product_id"] for p in products]
            selected_product = st.selectbox(
                "Select Product",
                product_ids,
                format_func=lambda x: f"ID: {x} - {next((p['name'] for p in products if p['product_id'] == x), 'Unknown')}"
            )

            current_prod = next((p for p in products if p["product_id"] == selected_product), None)
            if current_prod:
                upd_prod_name = st.text_input("Name", value=current_prod["name"], key="upd_prod_name")
                upd_prod_cat = st.text_input("Category", value=current_prod["category"], key="upd_prod_cat")
                upd_prod_unit = st.text_input("Unit", value=current_prod["unit"], key="upd_prod_unit")

                if st.button("Update Product", type="primary"):
                    resp = api("PUT", f"/admin/products/{selected_product}", json={
                        "name": upd_prod_name,
                        "category": upd_prod_cat,
                        "unit": upd_prod_unit
                    })
                    if resp and resp.status_code == 200:
                        st.success("Product updated!")
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")

        with col2:
            st.markdown("### Delete Product")
            del_product = st.selectbox(
                "Select Product to Delete",
                product_ids,
                format_func=lambda x: f"ID: {x} - {next((p['name'] for p in products if p['product_id'] == x), 'Unknown')}",
                key="delete_product"
            )
            st.warning("⚠️ This will delete all associated inventory and transaction data")

            if st.button("🗑️ Delete Product", type="secondary"):
                resp = api("DELETE", f"/admin/products/{del_product}")
                if resp and resp.status_code == 200:
                    st.success("Product and all associated data deleted!")
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error(f"Failed: {resp.json().get('detail') if resp else 'Connection error'}")
    
    # ── TAB 5: Inventory Overview ─────────────────────────────────────────────
    with tab5:
        st.subheader("📦 Network Inventory Overview")

        inv_data = db_query(
            """SELECT s.name as Seller, p.name as Product, p.category as Category,
                      i.stock_qty as Stock, i.cost_price as Cost, i.selling_price as Price,
                      ROUND((i.selling_price - i.cost_price)/NULLIF(i.cost_price,0)*100,1) as Margin_pct
               FROM inventory i
               JOIN sellers s ON i.seller_id=s.seller_id
               JOIN products p ON i.product_id=p.product_id
               ORDER BY i.stock_qty ASC"""
        )
        if not inv_data:
            st.info("No inventory records found.")
        else:
            df_inv = pd.DataFrame(inv_data)

            # Summary metrics
            ci1, ci2, ci3, ci4 = st.columns(4)
            ci1.metric("Total SKUs", len(df_inv))
            ci2.metric("Total Units", f"{df_inv['Stock'].sum():,}")
            ci3.metric("Out of Stock", int((df_inv['Stock'] == 0).sum()))
            ci4.metric("Low Stock (<10)", int((df_inv['Stock'] < 10).sum()))

            st.dataframe(df_inv, use_container_width=True, hide_index=True, height=320)

            col_i1, col_i2 = st.columns(2)
            with col_i1:
                # Heatmap: Seller × Product stock
                pivot_data = db_query(
                    """SELECT s.name as Seller, p.name as Product, i.stock_qty as Stock
                       FROM inventory i
                       JOIN sellers s ON i.seller_id=s.seller_id
                       JOIN products p ON i.product_id=p.product_id"""
                )
                if pivot_data:
                    df_piv = pd.DataFrame(pivot_data).pivot_table(
                        index="Seller", columns="Product", values="Stock", fill_value=0
                    )
                    fig = px.imshow(df_piv, text_auto=True, aspect="auto",
                                    color_continuous_scale="RdYlGn",
                                    title="Stock Heatmap: Seller × Product")
                    fig.update_layout(height=360, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)

            with col_i2:
                # Low stock sellers
                low = df_inv[df_inv['Stock'] < 20].groupby("Seller").size().reset_index(name="Low_Stock_SKUs")
                if not low.empty:
                    fig = px.bar(low.sort_values("Low_Stock_SKUs", ascending=False),
                                 x="Seller", y="Low_Stock_SKUs",
                                 color="Low_Stock_SKUs", color_continuous_scale="Reds",
                                 title="Sellers with Most Low-Stock SKUs (<20 units)")
                    fig.update_layout(height=360, margin=dict(t=40, b=10))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.success("✅ All sellers have healthy stock levels (≥20 units on all SKUs).")

        # Inline inventory edit
        st.divider()
        st.subheader("✏️ Update Inventory Record")
        inv_sellers = get_sellers()
        inv_products = get_products()
        ce1, ce2, ce3, ce4, ce5 = st.columns(5)
        edit_seller  = ce1.selectbox("Seller",  [f"{s['seller_id']} - {s['name']}" for s in inv_sellers], key="inv_edit_seller")
        edit_product = ce2.selectbox("Product", [f"{p['product_id']} - {p['name']}" for p in inv_products], key="inv_edit_prod")
        edit_sid = int(edit_seller.split(" - ")[0])
        edit_pid = int(edit_product.split(" - ")[0])
        cur_inv = db_query("SELECT stock_qty, cost_price, selling_price FROM inventory WHERE seller_id=? AND product_id=?", (edit_sid, edit_pid))
        default_stock = int(cur_inv[0]["stock_qty"])   if cur_inv else 0
        default_cost  = float(cur_inv[0]["cost_price"])  if cur_inv else 0.0
        default_price = float(cur_inv[0]["selling_price"]) if cur_inv else 0.0
        new_stock = ce3.number_input("Stock Qty", min_value=0, value=default_stock, step=1, key="inv_edit_stock")
        new_cost  = ce4.number_input("Cost Price ₹", min_value=0.0, value=default_cost, step=0.5, key="inv_edit_cost")
        new_price = ce5.number_input("Sell Price ₹", min_value=0.0, value=default_price, step=0.5, key="inv_edit_price")
        if st.button("💾 Save Inventory Changes", type="primary", key="inv_edit_save"):
            try:
                import sqlite3 as _s
                _c = _s.connect(DB_PATH)
                if cur_inv:
                    _c.execute("UPDATE inventory SET stock_qty=?, cost_price=?, selling_price=? WHERE seller_id=? AND product_id=?",
                               (new_stock, new_cost, new_price, edit_sid, edit_pid))
                else:
                    _c.execute("INSERT INTO inventory (seller_id, product_id, stock_qty, cost_price, selling_price) VALUES (?,?,?,?,?)",
                               (edit_sid, edit_pid, new_stock, new_cost, new_price))
                _c.commit(); _c.close()
                st.success("✅ Inventory updated!")
                time.sleep(0.3)
                st.rerun()
            except Exception as e:
                st.error(f"Failed: {e}")

    # ── TAB 6: Data Management ────────────────────────────────────────────────
    with tab6:
        st.subheader("Data Management")
        st.warning("⚠️ These actions are **irreversible**. Use with caution!")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Clear Transactional Data")
            
            if st.button("🗑️ Clear All Transactions"):
                resp = api("DELETE", "/admin/data/transactions")
                if resp and resp.status_code == 200:
                    st.success(resp.json()["message"])
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Failed to clear transactions")
            
            if st.button("🗑️ Clear All Demand Posts"):
                resp = api("DELETE", "/admin/data/demand-posts")
                if resp and resp.status_code == 200:
                    st.success(resp.json()["message"])
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Failed to clear demand posts")
            
            if st.button("🗑️ Clear All Transfers"):
                resp = api("DELETE", "/admin/data/transfers")
                if resp and resp.status_code == 200:
                    st.success(resp.json()["message"])
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Failed to clear transfers")
        
        with col2:
            st.markdown("### Inventory Operations")
            
            if st.button("🔄 Reset All Inventory to Zero"):
                resp = api("POST", "/admin/data/reset-inventory")
                if resp and resp.status_code == 200:
                    st.success(resp.json()["message"])
                    time.sleep(0.5)
                    st.rerun()
                else:
                    st.error("Failed to reset inventory")



# ══════════════════════════════════════════════════════════════════════════════
# MAIN ROUTER
# ══════════════════════════════════════════════════════════════════════════════

def main():
    if not st.session_state.token:
        login_page()
        return

    page = sidebar()

    if page == "📊 Dashboard":
        dashboard_page()
    elif page == "💳 Billing":
        billing_page()
    elif page == "🛒 Demand":
        demand_page()
    elif page == "🤖 Ask Agent":
        ask_page()
    elif page == "📈 SQL Analytics":
        sql_page()
    elif page == "📦 Inventory":
        inventory_page()
    elif page == "🔄 Transfers":
        transfers_page()
    elif page == "⏳ Approvals":
        approvals_page()
    elif page == "⚙️ Admin Panel":
        admin_page()


if __name__ == "__main__":
    main()
