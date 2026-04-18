"""Admin routes — Management of users, stores, products, and data."""
import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.security import get_current_user, create_user, pwd_context
from app.core.config import get_settings

router = APIRouter()
settings = get_settings()


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def require_admin(current_user: dict = Depends(get_current_user)):
    """Dependency to ensure user is admin."""
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


# ══════════════════════════════════════════════════════════════════════════════
# USER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class UserResponse(BaseModel):
    user_id: int
    username: str
    seller_id: Optional[int]
    role: str
    created_at: str


class UserUpdate(BaseModel):
    seller_id: Optional[int] = None
    role: Optional[str] = None
    password: Optional[str] = None


@router.get("/users", response_model=List[UserResponse])
async def list_users(admin: dict = Depends(require_admin)):
    """List all users in the system."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT user_id, username, seller_id, role, created_at FROM users ORDER BY user_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.put("/users/{user_id}")
async def update_user(user_id: int, update: UserUpdate, admin: dict = Depends(require_admin)):
    """Update user details."""
    conn = get_db()
    try:
        # Build dynamic update query
        updates = []
        params = []
        
        if update.seller_id is not None:
            updates.append("seller_id = ?")
            params.append(update.seller_id)
        
        if update.role is not None:
            updates.append("role = ?")
            params.append(update.role)
        
        if update.password is not None:
            updates.append("hashed_password = ?")
            params.append(pwd_context.hash(update.password))
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        params.append(user_id)
        query = f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?"
        
        cursor = conn.execute(query, params)
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "User updated successfully"}
    finally:
        conn.close()


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """Delete a user."""
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        
        return {"message": "User deleted successfully"}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# STORE/SELLER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class SellerCreate(BaseModel):
    name: str
    location: str
    sector: str


class SellerUpdate(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    sector: Optional[str] = None


class SellerResponse(BaseModel):
    seller_id: int
    name: str
    location: str
    sector: str


@router.get("/sellers", response_model=List[SellerResponse])
async def list_sellers(admin: dict = Depends(require_admin)):
    """List all sellers/stores."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT seller_id, name, location, sector FROM sellers ORDER BY seller_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.post("/sellers", response_model=SellerResponse)
async def create_seller(seller: SellerCreate, admin: dict = Depends(require_admin)):
    """Create a new seller/store."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO sellers (name, location, sector) VALUES (?, ?, ?)",
            (seller.name, seller.location, seller.sector)
        )
        conn.commit()
        seller_id = cursor.lastrowid
        
        return {
            "seller_id": seller_id,
            "name": seller.name,
            "location": seller.location,
            "sector": seller.sector
        }
    finally:
        conn.close()


@router.put("/sellers/{seller_id}")
async def update_seller(seller_id: int, update: SellerUpdate, admin: dict = Depends(require_admin)):
    """Update seller/store details."""
    conn = get_db()
    try:
        updates = []
        params = []
        
        if update.name is not None:
            updates.append("name = ?")
            params.append(update.name)
        
        if update.location is not None:
            updates.append("location = ?")
            params.append(update.location)
        
        if update.sector is not None:
            updates.append("sector = ?")
            params.append(update.sector)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        params.append(seller_id)
        query = f"UPDATE sellers SET {', '.join(updates)} WHERE seller_id = ?"
        
        cursor = conn.execute(query, params)
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Seller not found")
        
        return {"message": "Seller updated successfully"}
    finally:
        conn.close()


@router.delete("/sellers/{seller_id}")
async def delete_seller(seller_id: int, admin: dict = Depends(require_admin)):
    """Delete a seller/store and all associated data."""
    conn = get_db()
    try:
        # Check if seller exists
        seller = conn.execute("SELECT seller_id FROM sellers WHERE seller_id = ?", (seller_id,)).fetchone()
        if not seller:
            raise HTTPException(status_code=404, detail="Seller not found")
        
        # Delete associated data
        conn.execute("DELETE FROM inventory WHERE seller_id = ?", (seller_id,))
        conn.execute("DELETE FROM demand_posts WHERE seller_id = ?", (seller_id,))
        conn.execute("DELETE FROM transactions WHERE seller_id = ?", (seller_id,))
        conn.execute("DELETE FROM transfers WHERE from_seller_id = ? OR to_seller_id = ?", (seller_id, seller_id))
        conn.execute("DELETE FROM profits WHERE seller_id = ?", (seller_id,))
        conn.execute("DELETE FROM users WHERE seller_id = ?", (seller_id,))
        conn.execute("DELETE FROM sellers WHERE seller_id = ?", (seller_id,))
        
        conn.commit()
        return {"message": "Seller and all associated data deleted successfully"}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class ProductCreate(BaseModel):
    name: str
    category: str
    unit: str


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    unit: Optional[str] = None


class ProductResponse(BaseModel):
    product_id: int
    name: str
    category: str
    unit: str


@router.get("/products", response_model=List[ProductResponse])
async def list_products(admin: dict = Depends(require_admin)):
    """List all products."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT product_id, name, category, unit FROM products ORDER BY product_id"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.post("/products", response_model=ProductResponse)
async def create_product(product: ProductCreate, admin: dict = Depends(require_admin)):
    """Create a new product."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO products (name, category, unit) VALUES (?, ?, ?)",
            (product.name, product.category, product.unit)
        )
        conn.commit()
        product_id = cursor.lastrowid
        
        return {
            "product_id": product_id,
            "name": product.name,
            "category": product.category,
            "unit": product.unit
        }
    finally:
        conn.close()


@router.put("/products/{product_id}")
async def update_product(product_id: int, update: ProductUpdate, admin: dict = Depends(require_admin)):
    """Update product details."""
    conn = get_db()
    try:
        updates = []
        params = []
        
        if update.name is not None:
            updates.append("name = ?")
            params.append(update.name)
        
        if update.category is not None:
            updates.append("category = ?")
            params.append(update.category)
        
        if update.unit is not None:
            updates.append("unit = ?")
            params.append(update.unit)
        
        if not updates:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        params.append(product_id)
        query = f"UPDATE products SET {', '.join(updates)} WHERE product_id = ?"
        
        cursor = conn.execute(query, params)
        conn.commit()
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Product not found")
        
        return {"message": "Product updated successfully"}
    finally:
        conn.close()


@router.delete("/products/{product_id}")
async def delete_product(product_id: int, admin: dict = Depends(require_admin)):
    """Delete a product and all associated data."""
    conn = get_db()
    try:
        # Check if product exists
        product = conn.execute("SELECT product_id FROM products WHERE product_id = ?", (product_id,)).fetchone()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        
        # Delete associated data
        conn.execute("DELETE FROM inventory WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM demand_posts WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM transactions WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM transfers WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM products WHERE product_id = ?", (product_id,))
        
        conn.commit()
        return {"message": "Product and all associated data deleted successfully"}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# DATA MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@router.delete("/data/transactions")
async def clear_transactions(admin: dict = Depends(require_admin)):
    """Clear all transaction history."""
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM transactions")
        conn.commit()
        return {"message": f"Deleted {cursor.rowcount} transactions"}
    finally:
        conn.close()


@router.delete("/data/demand-posts")
async def clear_demand_posts(admin: dict = Depends(require_admin)):
    """Clear all demand posts."""
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM demand_posts")
        conn.commit()
        return {"message": f"Deleted {cursor.rowcount} demand posts"}
    finally:
        conn.close()


@router.delete("/data/transfers")
async def clear_transfers(admin: dict = Depends(require_admin)):
    """Clear all transfer records."""
    conn = get_db()
    try:
        cursor = conn.execute("DELETE FROM transfers")
        conn.commit()
        return {"message": f"Deleted {cursor.rowcount} transfers"}
    finally:
        conn.close()


@router.post("/data/reset-inventory")
async def reset_inventory(admin: dict = Depends(require_admin)):
    """Reset all inventory to zero."""
    conn = get_db()
    try:
        cursor = conn.execute("UPDATE inventory SET stock_qty = 0")
        conn.commit()
        return {"message": f"Reset {cursor.rowcount} inventory items to zero"}
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM STATS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/stats")
async def get_system_stats(admin: dict = Depends(require_admin)):
    """Get overall system statistics."""
    conn = get_db()
    try:
        stats = {
            "total_users": conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"],
            "total_sellers": conn.execute("SELECT COUNT(*) as c FROM sellers").fetchone()["c"],
            "total_products": conn.execute("SELECT COUNT(*) as c FROM products").fetchone()["c"],
            "total_inventory_items": conn.execute("SELECT COUNT(*) as c FROM inventory").fetchone()["c"],
            "total_transactions": conn.execute("SELECT COUNT(*) as c FROM transactions").fetchone()["c"],
            "total_demand_posts": conn.execute("SELECT COUNT(*) as c FROM demand_posts").fetchone()["c"],
            "total_transfers": conn.execute("SELECT COUNT(*) as c FROM transfers").fetchone()["c"],
            "active_users": conn.execute("SELECT COUNT(*) as c FROM users WHERE role != 'admin'").fetchone()["c"],
            "admin_users": conn.execute("SELECT COUNT(*) as c FROM users WHERE role = 'admin'").fetchone()["c"],
        }
        return stats
    finally:
        conn.close()
