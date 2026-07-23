import re

with open('crud.py', 'r') as f:
    content = f.read()

# Find the function and replace it
pattern = r'def update_inventory_snapshot\(db: Session, updates: List\[Dict\]\):.*?(?=\ndef |\Z)'

new_function = '''def update_inventory_snapshot(db: Session, updates: List[Dict]):
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
        
        # Get fg_key from update
        fg_key = update.get('fgKey', '')
        if not fg_key:
            # Try to extract from requirement_key
            parts = requirement_key.split('|')
            if len(parts) >= 3:
                fg_key = f"{parts[0]}|{parts[1]}|{parts[2]}"
            else:
                fg_key = requirement_key
        
        print(f"📋 Full update dict: {update}")
        print(f"📊 grnDelta: {update.get('grnDelta', 0)}")
        print(f"📊 fg_key being saved: {fg_key}")
        
        # Check if the requirement exists
        snapshot = db.query(models.InventorySnapshot).filter(
            models.InventorySnapshot.requirement_key == requirement_key
        ).first()
        
        if snapshot:
            # Update existing
            old_grn = snapshot.total_grn_received_qty
            snapshot.fg_key = fg_key
            snapshot.total_required_qty += update.get('requiredDelta', 0)
            snapshot.total_grn_received_qty += update.get('grnDelta', 0)
            snapshot.total_issued_qty += update.get('issueDelta', 0)
            snapshot.current_stock = snapshot.total_grn_received_qty - snapshot.total_issued_qty
            snapshot.pending_shortfall = snapshot.total_required_qty - snapshot.total_grn_received_qty
            snapshot.last_updated = datetime.utcnow()
            print(f"📝 Updated: {requirement_key} - GRN: {old_grn} -> {snapshot.total_grn_received_qty}")
        else:
            # Create new
            grn_delta = update.get('grnDelta', 0)
            new_entry = models.InventorySnapshot(
                requirement_key=requirement_key,
                fg_key=fg_key,
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
            print(f"✅ CREATED NEW: {requirement_key} - GRN: {grn_delta}")
    
    db.commit()
    print("💾 Snapshot updates committed to database")'''

# Replace the function
new_content = re.sub(pattern, new_function, content, flags=re.DOTALL)

with open('crud.py', 'w') as f:
    f.write(new_content)

print("✅ crud.py updated")
