"""SQLAlchemy ORM models for RetailFlow AI."""
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.db.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_role", "role"),
        Index("ix_users_seller_id", "seller_id"),
    )

    user_id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=True)
    role = Column(String, default="seller", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Product(Base):
    __tablename__ = "products"
    product_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    category = Column(String, nullable=False)
    unit = Column(String, nullable=False)


class Seller(Base):
    __tablename__ = "sellers"
    seller_id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    location = Column(String, nullable=False)
    sector = Column(String, nullable=False)


class Inventory(Base):
    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("seller_id", "product_id", name="uq_inventory_seller_product"),
        Index("ix_inventory_seller_product", "seller_id", "product_id"),
        Index("ix_inventory_product_stock", "product_id", "stock_qty"),
    )

    inventory_id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id"), nullable=False)
    stock_qty = Column(Integer, default=0, nullable=False)
    cost_price = Column(Float, nullable=False)
    selling_price = Column(Float, nullable=False)


class DemandPost(Base):
    __tablename__ = "demand_posts"
    __table_args__ = (
        Index("ix_demand_seller_product_status", "seller_id", "product_id", "status"),
        Index("ix_demand_status_created", "status", "created_at"),
    )

    demand_id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id"), nullable=False)
    qty_needed = Column(Integer, nullable=False)
    status = Column(String, default="open", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_seller_product_created", "seller_id", "product_id", "created_at"),
        Index("ix_transactions_status_created", "status", "created_at"),
    )

    txn_id = Column(Integer, primary_key=True, index=True)
    demand_id = Column(Integer, nullable=True)
    seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id"), nullable=False)
    qty = Column(Integer, nullable=False)
    agreed_price = Column(Float, nullable=False)
    status = Column(String, default="completed", nullable=False)
    negotiation_rounds = Column(Integer, default=1, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        Index("ix_transfers_from_status", "from_seller_id", "status"),
        Index("ix_transfers_to_status", "to_seller_id", "status"),
        Index("ix_transfers_product_status", "product_id", "status"),
        Index("ix_transfers_demand_id", "demand_id"),
    )

    transfer_id = Column(Integer, primary_key=True, index=True)
    from_seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=False)
    to_seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=False)
    product_id = Column(Integer, ForeignKey("products.product_id"), nullable=False)
    qty = Column(Integer, nullable=False)
    transfer_price = Column(Float, nullable=False)
    status = Column(String, default="pending", nullable=False)
    demand_id = Column(Integer, nullable=True)
    counter_price = Column(Float, nullable=True)
    negotiation_rounds = Column(Integer, default=1, nullable=False)


class Profit(Base):
    __tablename__ = "profits"
    __table_args__ = (
        UniqueConstraint("seller_id", "month", name="uq_profits_seller_month"),
        Index("ix_profits_seller_month", "seller_id", "month"),
    )

    profit_id = Column(Integer, primary_key=True, index=True)
    seller_id = Column(Integer, ForeignKey("sellers.seller_id"), nullable=False)
    month = Column(String, nullable=False)
    revenue = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    profit = Column(Float, nullable=False)
