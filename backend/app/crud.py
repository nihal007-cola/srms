from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func
from . import models
from .config import settings
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import uuid
import re
import logging

TOLERANCE = settings.tolerance

# ==================== MASTER DATA ====================

def get_master_data(db: Session, category: Optional[str] = None):
    query = db.query(models.MasterData)
    if category:
        query = query.filter(models.MasterData.category == category.upper())
    return query.all()

def get_buyers(db: Session):
    return [m.name for m in get_master_data(db, "BUYER")]

def get_buyer_details(db: Session, name: str):
    return db.query(models.MasterData).filter(
        models.MasterData.category == "BUYER",
        models.MasterData.name == name
    ).first()

def get_rmsuppliers(db: Session):
    return [m.name for m in get_master_data(db, "SUPPLIER")]

def get_rmsupplier_details(db: Session, name: str):
    return db.query(models.MasterData).filter(
        models.MasterData.category == "SUPPLIER",
        models.MasterData.name == name
    ).first()

def add_master_entity(db: Session, data: Dict):
    entity = models.MasterData(
        id=f"{data['category'].upper()}-{uuid.uuid4().hex[:6].upper()}",
        category=data['category'].upper(),
        name=data['name'],
        gst_no=data.get('gst_no', ''),
        address=data.get('address', ''),
        contact_person=data.get('contact_person', ''),
        contact_no=data.get('contact_no', ''),
        payment_term=data.get('payment_term', ''),
        status="ACTIVE"
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity

# ==================== LEDGER ====================

def add_ledger_entry(db: Session, data: Dict):
    entry = models.ActivityLedger(
        fg_key=data['fg_key'],
        activity_type=data['activity_type'].upper(),
        status=data['status'].upper(),
        buyer_name=data.get('buyer_name', ''),
        buyer_order_no=data.get('buyer_order_no', ''),
        order_date=data.get('order_date'),
        created_date=data.get('created_date'),
        qty=data.get('qty', 0),
        size=data.get('size', ''),
        color=data.get('color', ''),
        extra_data=data.get('extra_data'),
        workflow_position=data.get('workflow_position', 0)
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry

def add_ledger_entries_bulk(db: Session, rows: List[Dict]):
    entries = []
    for data in rows:
        entry = models.ActivityLedger(
            fg_key=data['fg_key'],
            activity_type=data['activity_type'].upper(),
            status=data['status'].upper(),
            buyer_name=data.get('buyer_name', ''),
            buyer_order_no=data.get('buyer_order_no', ''),
            order_date=data.get('order_date'),
            created_date=data.get('created_date'),
            qty=data.get('qty', 0),
            size=data.get('size', ''),
            color=data.get('color', ''),
            extra_data=data.get('extra_data'),
            workflow_position=data.get('workflow_position', 0)
        )
        entries.append(entry)
    db.add_all(entries)
    db.commit()
    return entries

def get_ledger_entries(db: Session, fg_key: Optional[str] = None, workflow_position: Optional[float] = None,
                       activity_type: Optional[str] = None, status: Optional[str] = None):
    query = db.query(models.ActivityLedger)
    if fg_key:
        query = query.filter(models.ActivityLedger.fg_key == fg_key)
    if workflow_position is not None:
        query = query.filter(models.ActivityLedger.workflow_position == workflow_position)
    if activity_type:
        query = query.filter(models.ActivityLedger.activity_type == activity_type.upper())
    if status:
        query = query.filter(models.ActivityLedger.status == status.upper())
    return query.order_by(models.ActivityLedger.timestamp).all()

def get_latest_status(db: Session, fg_key: str, activity_type: str):
    entries = get_ledger_entries(db, fg_key, None, activity_type)
    if not entries:
        return None
    return entries[-1]

def get_current_workflow_position(db: Session, fg_key: str):
    entries = get_ledger_entries(db, fg_key)
    if not entries:
        return 0
    latest = entries[-1]
    return int(latest.workflow_position) if latest.workflow_position is not None else 0

# ==================== INVENTORY SNAPSHOT ====================
def update_inventory_snapshot(db: Session, updates: List[Dict]):
    """Update inventory snapshot with the given updates"""
    print("🔍 FUNCTION CALLED: update_inventory_snapshot")
    
    if not updates:
        print("⚠️ No snapshot updates to process")
        return
    
    print(f"📊 Processing {len(updates)} snapshot updates")
    
    from datetime import datetime
    
    for update in updates:
        requirement_key = update.get('requirementKey')
        if not requirement_key:
            print("⚠️ Skipping update with no requirement_key")
            continue
        
        print(f"🔑 Processing requirement_key: {requirement_key}")
        
        # CRITICAL FIX: Get fg_key from update
        fg_key = update.get('fgKey', '')
        print(f"📋 fgKey from update: {fg_key}")
        
        # Check if the requirement exists
        snapshot = db.query(models.InventorySnapshot).filter(
            models.InventorySnapshot.requirement_key == requirement_key
        ).first()
        
        if snapshot:
            # Update existing - including fg_key
            snapshot.fg_key = fg_key
            snapshot.total_required_qty += update.get('requiredDelta', 0)
            snapshot.total_grn_received_qty += update.get('grnDelta', 0)
            snapshot.total_issued_qty += update.get('issueDelta', 0)
            snapshot.current_stock = snapshot.total_grn_received_qty - snapshot.total_issued_qty
            snapshot.pending_shortfall = snapshot.total_required_qty - snapshot.total_grn_received_qty
            snapshot.last_updated = datetime.utcnow()
            print(f"📝 Updated: {requirement_key} - GRN: {snapshot.total_grn_received_qty} - FG: {fg_key}")
        else:
            # Create new with fg_key
            grn_delta = update.get('grnDelta', 0)
            new_entry = models.InventorySnapshot(
                requirement_key=requirement_key,
                fg_key=fg_key,  # This was missing!
                item_no=update.get('itemNo', ''),
                item_name=update.get('itemName', ''),
                garment_size=update.get('size', ''),
                color=update.get('color', ''),
                supplier=update.get('supplier', ''),
                total_required_qty=update.get('requiredDelta', 0),
                total_grn_received_qty=grn_delta,
                total_issued_qty=update.get('issueDelta', 0),
                current_stock=grn_delta - update.get('issueDelta', 0),
                pending_shortfall=update.get('requiredDelta', 0) - grn_delta
            )
            db.add(new_entry)
            print(f"✅ CREATED NEW: {requirement_key} - GRN: {grn_delta} - FG: {fg_key}")
    
    db.commit()
    print("💾 Snapshot updates committed to database")

# ==================== UTILITY ====================

def generate_fg_serial(db: Session) -> str:
    """Generate a new FG serial number"""
    from datetime import datetime
    date = datetime.utcnow()
    prefix = f"FG-{date.strftime('%y%m%d')}"
    
    # Get all FG keys that start with the prefix
    fg_keys = db.query(models.ActivityLedger.fg_key).filter(
        models.ActivityLedger.fg_key.like(f"{prefix}-%")
    ).distinct().all()
    
    # Extract serial numbers from FG keys (only the base FG key, not the full key with pipe)
    serials = []
    for row in fg_keys:
        key = row[0]
        # Extract the base FG key (before any pipe)
        base_key = key.split('|')[0]
        parts = base_key.split('-')
        if len(parts) == 3:
            try:
                serials.append(int(parts[2]))
            except ValueError:
                pass
    
    if serials:
        last_serial = max(serials)
        new_serial = last_serial + 1
    else:
        new_serial = 1
    
    return f"{prefix}-{str(new_serial).zfill(3)}"

def generate_po_token() -> str:
    from datetime import datetime
    date = datetime.utcnow()
    return f"PO-{date.strftime('%y%m%d')}-{uuid.uuid4().hex[:3].upper()}"

def get_requirement_key(fg_key: str, size: str, color: str, item_size: str) -> str:
    return f"{fg_key}|{size}|{color}|{item_size}"

def clean_key(key: str) -> str:
    if not key:
        return ''
    return str(key).strip().upper()

def clean_key_exact(key: str) -> str:
    if not key:
        return ''
    return str(key).strip()

def get_module_position(module_name: str) -> int:
    try:
        workflow = settings.get_workflow_list()
        return workflow.index(module_name.upper())
    except ValueError:
        return -1

def get_inventory_snapshot(db: Session, fg_key: Optional[str] = None, requirement_key: Optional[str] = None):
    """Get inventory snapshot data"""
    query = db.query(models.InventorySnapshot)
    if fg_key:
        query = query.filter(models.InventorySnapshot.fg_key == fg_key)
    if requirement_key:
        query = query.filter(models.InventorySnapshot.requirement_key == requirement_key)
    return query.all()
