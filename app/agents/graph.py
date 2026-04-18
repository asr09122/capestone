"""RetailFlow AI — LangGraph workflow. Every node calls @tool functions directly."""
from typing import Literal, Optional, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agents.rag_agent import run_rag_agent
from app.guardrails.validators import validate_pricing
from app.tools.demand_tools import predict_reorder_qty
from app.tools.inventory_tools import (
    create_demand,
    create_transfer,
    find_suppliers,
    get_avg_price,
    get_inventory,
    get_sales_stats,
    record_transaction,
    update_cost_price,
    update_selling_price,
    update_stock,
    upsert_profit,
)


# ── State ─────────────────────────────────────────────────────────────────────

class KiranaState(TypedDict):
    seller_id: int
    product_id: int
    quantity: int
    price: float
    trigger: Literal["billing", "demand"]
    stock: Optional[int]
    threshold: Optional[float]
    daily_avg: Optional[float]
    suggested_qty: Optional[int]
    market_avg_price: Optional[float]
    user_qty_needed: Optional[int]
    user_target_price: Optional[float]
    demand_id: Optional[int]
    demand_created: bool
    candidates: Optional[list]
    split_plan: Optional[dict]
    chosen_seller_id: Optional[int]
    chosen_price: Optional[float]
    split_confirmed: Optional[list]
    transfer_id: Optional[int]
    transfer_ids: Optional[list]
    transfer_qty: Optional[int]
    transfer_suggested: bool
    anomaly_detected: bool
    anomaly_explanation: Optional[str]
    next_step: Optional[str]
    result: Optional[str]
    error: Optional[str]


# ── Nodes ─────────────────────────────────────────────────────────────────────

def billing_node(state):
    sid, pid, qty, price = state["seller_id"], state["product_id"], state["quantity"], state["price"]

    # check stock and price floor
    inv = get_inventory.invoke({"seller_id": sid, "product_id": pid})
    if not inv:
        raise ValueError(f"No inventory for seller={sid} product={pid}")
    if qty > int(inv["stock_qty"]):
        raise ValueError(f"Cannot bill {qty} — only {inv['stock_qty']} in stock")
    cost_price = float(inv["cost_price"])
    if price < cost_price * 1.03:
        raise ValueError(f"Price ₹{price:.2f} is below cost floor ₹{cost_price * 1.03:.2f}")

    # deduct stock, record sale, update profits
    result = update_stock.invoke({"seller_id": sid, "product_id": pid, "qty_change": -qty})
    record_transaction.invoke({"seller_id": sid, "product_id": pid, "qty": qty, "price": price})
    upsert_profit.invoke({"seller_id": sid, "revenue": round(price * qty, 2), "cost": round(cost_price * qty, 2)})

    # anomaly check — only sync selling_price if price is normal
    avg_price = get_avg_price.invoke({"seller_id": sid, "product_id": pid, "days": 30})
    anomaly = avg_price > 0 and validate_pricing(price, avg_price)

    if not anomaly:
        update_selling_price.invoke({"seller_id": sid, "product_id": pid, "price": price})

    explanation = None
    if anomaly:
        try:
            explanation = run_rag_agent(
                f"Price anomaly: billed ₹{price:.2f} vs 30-day avg ₹{avg_price:.2f}. Explain and suggest action.",
                seller_id=sid, product_id=pid,
            )
        except Exception:
            explanation = f"Price ₹{price:.2f} is {abs(price - avg_price) / avg_price * 100:.0f}% from 30-day avg ₹{avg_price:.2f}."

    return {
        **state,
        "stock": result["new_stock_qty"],
        "market_avg_price": avg_price,
        "anomaly_detected": anomaly,
        "anomaly_explanation": explanation,
    }


def threshold_check_node(state):
    sid, pid = state["seller_id"], state["product_id"]

    stock = state.get("stock")
    if stock is None:
        inv = get_inventory.invoke({"seller_id": sid, "product_id": pid})
        stock = int(inv.get("stock_qty", 0))

    stats = get_sales_stats.invoke({"seller_id": sid, "product_id": pid, "days": 30})
    avg_price = state.get("market_avg_price") or get_avg_price.invoke({"seller_id": sid, "product_id": pid})
    reorder = predict_reorder_qty(sid, pid)

    return {
        **state,
        "stock": stock,
        "threshold": stats["threshold"],
        "daily_avg": stats["daily_avg"],
        "suggested_qty": max(1, int(state.get("suggested_qty") or reorder["suggested_qty"] or 10)),
        "market_avg_price": avg_price,
    }


def stock_ok_node(state):
    return {**state, "next_step": "done", "result": "Billing done. Stock is above threshold — no demand needed."}


def ask_price_node(state):
    sid, pid = state["seller_id"], state["product_id"]
    inv = get_inventory.invoke({"seller_id": sid, "product_id": pid})

    stock = int(state.get("stock") or inv.get("stock_qty") or 0)
    threshold = float(state.get("threshold") or 0.0)
    suggested_qty = int(state.get("suggested_qty") or 10)
    market_avg = float(state.get("market_avg_price") or 0.0)
    selling_price = float(inv.get("selling_price") or 0.0)
    fallback_price = market_avg or selling_price or float(state.get("price") or 1.0)

    user_input = interrupt({
        "step": "ask_price",
        "message": "Low stock detected. Confirm how many units you want and your target buying price.",
        "seller_id": sid,
        "product_id": pid,
        "current_stock": stock,
        "threshold": threshold,
        "suggested_qty": suggested_qty,
        "market_avg_price": round(market_avg, 2),
        "your_selling_price": round(selling_price, 2),
        "suggested_target_price": round(fallback_price, 2),
    })

    user_input = user_input or {}
    return {
        **state,
        "user_qty_needed": max(1, int(user_input.get("qty") or suggested_qty)),
        "user_target_price": max(0.01, float(user_input.get("target_price") or fallback_price)),
        "next_step": "choose_seller",
    }


def demand_node(state):
    qty = int(state.get("user_qty_needed") or state.get("suggested_qty") or 10)
    result = create_demand.invoke({"seller_id": state["seller_id"], "product_id": state["product_id"], "qty_needed": qty})
    return {**state, "demand_id": result["demand_id"], "demand_created": True}


def match_sellers_node(state):
    sid, pid = state["seller_id"], state["product_id"]
    qty = int(state.get("user_qty_needed") or state.get("suggested_qty") or 10)
    target = float(state.get("user_target_price") or 0.0)

    candidates = find_suppliers.invoke({
        "product_id": pid,
        "exclude_seller_id": sid,
        "qty_needed": qty,
        "target_price": target,
    })

    # build greedy split plan when no single seller covers the full qty
    split_plan = None
    if candidates and not any(c["full_cover"] for c in candidates):
        remaining, picks, total_cost = qty, [], 0.0
        for c in sorted(candidates, key=lambda c: abs(float(c["selling_price"]) - target)):
            if remaining <= 0:
                break
            take = min(int(c["stock_qty"]), remaining)
            picks.append({"seller_id": c["seller_id"], "seller_name": c["seller_name"],
                          "qty": take, "price": float(c["selling_price"]),
                          "subtotal": round(float(c["selling_price"]) * take, 2)})
            total_cost += float(c["selling_price"]) * take
            remaining -= take
        covered = qty - remaining
        if covered > 0:
            split_plan = {
                "picks": picks, "total_qty": covered, "fully_covered": remaining == 0,
                "avg_unit_price": round(total_cost / covered, 2), "total_cost": round(total_cost, 2),
            }

    return {
        **state,
        "candidates": candidates,
        "split_plan": split_plan,
        "transfer_suggested": bool(candidates),
        "next_step": "choose_seller" if candidates else "done",
    }


def choose_seller_node(state):
    candidates = state.get("candidates") or []
    if not candidates:
        return {**state, "next_step": "done",
                "result": f"Demand #{state.get('demand_id')} is open — no supplier has stock right now."}

    best = candidates[0]
    choice = interrupt({
        "step": "choose_seller",
        "message": "Pick a single supplier or use the split plan to source from multiple sellers.",
        "product_id": state["product_id"],
        "qty_needed": state.get("user_qty_needed"),
        "target_price": state.get("user_target_price"),
        "suggested_supplier": {
            "seller_id": best["seller_id"], "seller_name": best["seller_name"],
            "selling_price": best["selling_price"], "stock_qty": best["stock_qty"],
            "price_delta": best["price_delta"],
        },
        "candidates": candidates,
        "split_plan": state.get("split_plan"),
    }) or {}

    if choice.get("use_split"):
        split = state.get("split_plan") or {}
        return {
            **state,
            "split_confirmed": split.get("picks", []),
            "chosen_seller_id": None,
            "chosen_price": split.get("avg_unit_price"),
            "transfer_qty": split.get("total_qty"),
            "split_confirmed": split.get("picks", []),
        }

    chosen_id = int(choice.get("seller_id") or best["seller_id"])
    selected = next((c for c in candidates if int(c["seller_id"]) == chosen_id), best)
    chosen_qty = max(1, min(
        int(choice.get("qty") or state.get("user_qty_needed") or selected["fulfillable_qty"]),
        int(selected["stock_qty"]),
    ))
    return {
        **state,
        "chosen_seller_id": selected["seller_id"],
        "chosen_price": round(float(choice.get("offer_price") or selected["selling_price"]), 2),
        "transfer_qty": chosen_qty,
        "split_confirmed": None,
    }


def create_transfer_node(state):
    to_sid = int(state["seller_id"])
    pid = int(state["product_id"])
    demand_id = state.get("demand_id")

    # split plan — create one transfer per supplier, update buyer's cost_price to weighted avg
    if state.get("split_confirmed"):
        picks = state["split_confirmed"]
        ids, total_units, total_cost = [], 0, 0.0
        for p in picks:
            t = create_transfer.invoke({
                "from_seller_id": int(p["seller_id"]), "to_seller_id": to_sid,
                "product_id": pid, "qty": int(p["qty"]),
                "transfer_price": float(p["price"]), "demand_id": demand_id,
            })
            ids.append(t["transfer_id"])
            total_units += int(p["qty"])
            total_cost += float(p["price"]) * int(p["qty"])

        avg = round(total_cost / total_units, 2) if total_units else 0
        update_cost_price.invoke({"seller_id": to_sid, "product_id": pid, "cost": avg})

        return {
            **state,
            "transfer_id": ids[0] if ids else None,
            "transfer_ids": ids,
            "transfer_qty": total_units,
            "chosen_price": avg,
            "next_step": "done",
            "result": (
                f"{len(ids)} split requests sent to {', '.join(p['seller_name'] for p in picks)}. "
                f"{total_units} units @ avg ₹{avg:.2f}/unit. Cost price updated to ₹{avg:.2f}."
            ),
        }

    # single supplier
    t = create_transfer.invoke({
        "from_seller_id": int(state["chosen_seller_id"]), "to_seller_id": to_sid,
        "product_id": pid, "qty": int(state["transfer_qty"]),
        "transfer_price": float(state["chosen_price"]), "demand_id": demand_id,
    })
    return {
        **state,
        "transfer_id": t["transfer_id"],
        "transfer_ids": None,
        "next_step": "done",
        "result": f"Request #{t['transfer_id']} sent — {state['transfer_qty']} units @ ₹{state['chosen_price']:.2f}/unit.",
    }


# ── Routing ───────────────────────────────────────────────────────────────────

def route_start(state):
    return "billing" if state.get("trigger") == "billing" else "threshold_check"


def route_after_threshold(state):
    if state.get("trigger") == "demand":
        return "ask_price"
    return "ask_price" if float(state.get("stock") or 0) < float(state.get("threshold") or 0) else "stock_ok"


def route_after_match(state):
    return "choose_seller" if state.get("candidates") else END


# ── Graph ─────────────────────────────────────────────────────────────────────

def build_graph():
    b = StateGraph(KiranaState)
    b.add_node("billing",          billing_node)
    b.add_node("threshold_check",  threshold_check_node)
    b.add_node("stock_ok",         stock_ok_node)
    b.add_node("ask_price",        ask_price_node)
    b.add_node("create_demand",    demand_node)
    b.add_node("match_sellers",    match_sellers_node)
    b.add_node("choose_seller",    choose_seller_node)
    b.add_node("create_transfer",  create_transfer_node)

    b.add_conditional_edges(START, route_start, {"billing": "billing", "threshold_check": "threshold_check"})
    b.add_edge("billing", "threshold_check")
    b.add_conditional_edges("threshold_check", route_after_threshold, {"ask_price": "ask_price", "stock_ok": "stock_ok"})
    b.add_edge("stock_ok", END)
    b.add_edge("ask_price", "create_demand")
    b.add_edge("create_demand", "match_sellers")
    b.add_conditional_edges("match_sellers", route_after_match, {"choose_seller": "choose_seller", END: END})
    b.add_edge("choose_seller", "create_transfer")
    b.add_edge("create_transfer", END)
    return b


_graph = None

def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph().compile(checkpointer=MemorySaver())
    return _graph


def route_query_to_agent(query: str) -> Literal["rag", "sql", "demand", "seller", "ml"]:
    import re
    q = query.lower()
    def has(words):
        return any(re.search(r"\b" + re.escape(w) + r"\b", q) for w in words)
    if has(["why", "explain", "reason", "anomaly", "flag", "rule"]):  return "rag"
    if has(["forecast", "predict", "next month"]):                     return "ml"
    if has(["profit", "revenue", "cost", "analytics", "total", "how much"]): return "sql"
    if has(["supplier", "source", "best price", "who sells"]):        return "seller"
    return "demand"
