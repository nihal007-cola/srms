# Replace the update_inventory_snapshot function in crud.py with this:

def update_inventory_snapshot(db: Session, updates: List[Dict]):
    """Update inventory snapshot with the given updates"""
    if not updates:
        return
    
    from app.models import InventorySnapshot
    from datetime import datetime
    
    for update in updates:
        requirement_key = update.get('requirement_key')
        if not requirement_key:
            continue
        
        # Check if the requirement exists using a direct query
        existing = db.query(InventorySnapshot).filter(
            InventorySnapshot.requirement_key == requirement_key
        ).first()
        
        if existing:
            # Update existing
            existing.total_required_qty += update.get('required_delta', 0)
            existing.total_grn_received_qty += update.get('grn_delta', 0)
            existing.total_issued_qty += update.get('issue_delta', 0)
            existing.current_stock = existing.total_grn_received_qty - existing.total_issued_qty
            existing.pending_shortfall = existing.total_required_qty - existing.total_grn_received_qty
            existing.last_updated = datetime.utcnow()
        else:
            # Create new
            new_entry = InventorySnapshot(
                requirement_key=requirement_key,
                fg_key=update.get('fg_key', ''),
                item_no=update.get('item_no', ''),
                item_name=update.get('item_name', ''),
                garment_size=update.get('size', ''),
                color=update.get('color', ''),
                supplier=update.get('supplier', ''),
                total_required_qty=update.get('required_delta', 0),
                total_grn_received_qty=update.get('grn_delta', 0),
                total_issued_qty=update.get('issue_delta', 0),
                current_stock=update.get('grn_delta', 0) - update.get('issue_delta', 0),
                pending_shortfall=update.get('required_delta', 0) - update.get('grn_delta', 0)
            )
            db.add(new_entry)
    
    db.commit()
