from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base
import uuid

class MasterData(Base):
    __tablename__ = "master_data"
    
    id = Column(String(50), primary_key=True, default=lambda: f"ENTITY-{uuid.uuid4().hex[:6].upper()}")
    category = Column(String(50), nullable=False)
    name = Column(String(200), nullable=False)
    gst_no = Column(String(50), nullable=True)
    address = Column(Text, nullable=True)
    contact_person = Column(String(100), nullable=True)
    contact_no = Column(String(50), nullable=True)
    payment_term = Column(String(100), nullable=True)
    added_date = Column(DateTime, server_default=func.now())
    status = Column(String(20), default="ACTIVE")
    
    __table_args__ = (
        Index('idx_master_category', 'category'),
        Index('idx_master_name', 'name'),
    )

class ActivityLedger(Base):
    __tablename__ = "activity_ledger"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, server_default=func.now())
    fg_key = Column(String(100), nullable=False)
    activity_type = Column(String(50), nullable=False)
    status = Column(String(30), nullable=False)
    buyer_name = Column(String(100), nullable=True)
    buyer_order_no = Column(String(100), nullable=True)
    order_date = Column(DateTime, nullable=True)
    created_date = Column(DateTime, nullable=True)
    qty = Column(Float, default=0)
    size = Column(String(20), nullable=True)
    color = Column(String(50), nullable=True)
    extra_data = Column(JSON, nullable=True)
    workflow_position = Column(Float, default=0)
    
    __table_args__ = (
        Index('idx_ledger_fg_key', 'fg_key'),
        Index('idx_ledger_activity_type', 'activity_type'),
        Index('idx_ledger_status', 'status'),
        Index('idx_ledger_fg_activity', 'fg_key', 'activity_type'),
        # No index on extra_data - PostgreSQL doesn't support default indexing on JSON
    )

class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshot"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    requirement_key = Column(String(200), unique=True, nullable=False)
    fg_key = Column(String(100), nullable=False)
    item_no = Column(String(50), nullable=True)
    item_name = Column(String(200), nullable=True)
    garment_size = Column(String(20), nullable=True)
    color = Column(String(50), nullable=True)
    supplier = Column(String(100), nullable=True)
    total_required_qty = Column(Float, default=0)
    total_grn_received_qty = Column(Float, default=0)
    total_issued_qty = Column(Float, default=0)
    current_stock = Column(Float, default=0)
    pending_shortfall = Column(Float, default=0)
    last_updated = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    __table_args__ = (
        Index('idx_snapshot_fg_key', 'fg_key'),
        Index('idx_snapshot_req_key', 'requirement_key'),
    )

class Settings(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text, nullable=True)
