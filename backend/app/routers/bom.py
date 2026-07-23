from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
import json

router = APIRouter(prefix="/bom", tags=["BOM"])

@router.get("/orders")
def get_bom_orders(db: Session = Depends(get_db)):
    entries = crud.get_ledger_entries(db)
    result = []
    processed_fg = set()
    
    for entry in entries:
        fg_key = crud.clean_key_exact(entry.fg_key)
        if not fg_key or fg_key in processed_fg:
            continue
        if entry.activity_type == 'BUYER_ORDER' and entry.status == 'COMPLETED':
            bom_status = crud.get_latest_status(db, fg_key, 'BOM')
            req_status = crud.get_latest_status(db, fg_key, 'MATERIAL_REQUIREMENT')
            if not bom_status or bom_status.status != 'COMPLETED':
                serial = fg_key.split('|')[0] or fg_key
                result.append({
                    'fgKey': fg_key,
                    'fgOrderSerial': serial,
                    'buyerOrderNo': entry.buyer_order_no or '',
                    'orderDate': entry.order_date,
                    'bomStatus': bom_status.status if bom_status else 'PENDING',
                    'requirementStatus': req_status.status if req_status else 'PENDING'
                })
                processed_fg.add(fg_key)
    
    return result

@router.get("/{fg_key}")
def get_bom_data(fg_key: str, db: Session = Depends(get_db)):
    clean_fg_key = crud.clean_key_exact(fg_key)
    entries = crud.get_ledger_entries(db, clean_fg_key)
    
    bom_entries = [e for e in entries if e.activity_type == 'BOM']
    items = []
    if bom_entries:
        latest_bom = bom_entries[-1]
        if latest_bom.extra_data and latest_bom.extra_data.get('items'):
            items = latest_bom.extra_data['items']
    
    buyer_order = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
    grid_data = None
    if buyer_order and buyer_order.extra_data:
        grid_data = buyer_order.extra_data.get('gridRow')
    
    bom_status = bom_entries[-1].status if bom_entries else 'PENDING'
    
    return {
        'fgKey': clean_fg_key,
        'bomStatus': bom_status,
        'items': items,
        'gridData': grid_data,
        'buyerName': buyer_order.buyer_name if buyer_order else '',
        'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else '',
        'orderDate': buyer_order.order_date if buyer_order else '',
        'createdDate': buyer_order.created_date if buyer_order else ''
    }

@router.post("/save")
def save_bom(data: schemas.BOMSaveRequest, db: Session = Depends(get_db)):
    try:
        fg_key = crud.clean_key_exact(data.fg_key)
        if not fg_key:
            raise ValueError('FG Key missing')
        if not data.items:
            raise ValueError('No items to save')
        
        entries = crud.get_ledger_entries(db, fg_key)
        buyer_order = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        if not buyer_order:
            raise ValueError(f'BUYER_ORDER not found or not COMPLETED for FG: {fg_key}')
        
        existing_bom = next((e for e in entries if e.activity_type == 'BOM' and e.status == 'COMPLETED'), None)
        if existing_bom:
            raise ValueError(f'BOM is already COMPLETED for FG: {fg_key}')
        
        # Validate items
        for i, item in enumerate(data.items):
            if not item.item_no.strip():
                raise ValueError(f'Row {i+1}: Item No is required')
            if not item.item_name.strip():
                raise ValueError(f'Row {i+1}: Item Name is required')
            if not item.item_color.strip():
                raise ValueError(f'Row {i+1}: Item Color is required')
            if not item.item_size.strip():
                raise ValueError(f'Row {i+1}: Item Size is required')
            if item.consumption <= 0:
                raise ValueError(f'Row {i+1}: Consumption must be > 0')
            if not item.uom.strip():
                raise ValueError(f'Row {i+1}: UOM is required')
            if item.rate <= 0:
                raise ValueError(f'Row {i+1}: Rate must be > 0')
            if not item.supplier.strip():
                raise ValueError(f'Row {i+1}: Supplier is required')
            if item.leadtime <= 0:
                raise ValueError(f'Row {i+1}: Leadtime must be > 0')
        
        default_sizes = settings.get_default_sizes_list()
        grid_data = None
        if buyer_order.extra_data and buyer_order.extra_data.get('gridRow'):
            grid_row = buyer_order.extra_data['gridRow']
            grid_data = {}
            for i, size in enumerate(default_sizes):
                qty_index = 3 + i
                if qty_index < len(grid_row):
                    grid_data[str(size)] = grid_row[qty_index] or 0
        
        order_info = {
            'buyerName': buyer_order.buyer_name or '',
            'buyerOrderNo': buyer_order.buyer_order_no or '',
            'orderDate': buyer_order.order_date,
            'createdDate': buyer_order.created_date
        }
        
        entries_to_insert = []
        snapshot_updates = []
        
        # Cancel existing requirements
        existing_reqs = [e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                        and e.status not in ['CANCELLED', 'RECEIVED', 'ISSUED']]
        for req in existing_reqs:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'CANCELLED',
                'buyer_name': req.buyer_name,
                'buyer_order_no': req.buyer_order_no,
                'order_date': req.order_date,
                'created_date': req.created_date,
                'qty': req.qty,
                'size': req.size,
                'color': req.color,
                'workflow_position': 1.5,
                'extra_data': {**(req.extra_data or {}), 'cancelledAt': datetime.utcnow().isoformat(), 'cancelledReason': 'New BOM saved'}
            })
        
        # Save BOM
        entries_to_insert.append({
            'fg_key': fg_key,
            'activity_type': 'BOM',
            'status': 'COMPLETED',
            'buyer_name': order_info['buyerName'],
            'buyer_order_no': order_info['buyerOrderNo'],
            'order_date': order_info['orderDate'],
            'created_date': order_info['createdDate'],
            'workflow_position': 1,
            'extra_data': {
                'items': [item.model_dump() for item in data.items],
                'itemCount': len(data.items),
                'savedAt': datetime.utcnow().isoformat()
            }
        })
        
        # Calculate requirements
        def calculate_requirements(item, grid_data):
            consumption = item.consumption
            is_sensitive = item.size_sensitive == 'Yes'
            item_size = item.item_size.strip()
            default_sizes = settings.get_default_sizes_list()
            
            size_map = {}
            for size in default_sizes:
                size_str = str(size)
                if grid_data:
                    size_map[size_str] = grid_data.get(size_str, 0)
                else:
                    size_map[size_str] = 0
            
            requirements = []
            if is_sensitive:
                for size in default_sizes:
                    size_str = str(size)
                    order_qty = size_map.get(size_str, 0)
                    if order_qty > 0:
                        required_qty = order_qty * consumption
                        requirements.append({
                            'size': size_str,
                            'itemSize': item_size,
                            'qty': required_qty,
                            'color': item.item_color,
                            'itemNo': item.item_no,
                            'itemName': item.item_name,
                            'uom': item.uom,
                            'isSizeSensitive': True,
                            'orderQty': order_qty,
                            'consumption': consumption
                        })
            else:
                total_order_qty = sum(size_map.values())
                if total_order_qty > 0:
                    required_qty = total_order_qty * consumption
                    requirements.append({
                        'size': 'ALL',
                        'itemSize': item_size,
                        'qty': required_qty,
                        'color': item.item_color,
                        'itemNo': item.item_no,
                        'itemName': item.item_name,
                        'uom': item.uom,
                        'isSizeSensitive': False,
                        'totalOrderQty': total_order_qty,
                        'consumption': consumption
                    })
            return requirements
        
        for item in data.items:
            requirements = calculate_requirements(item, grid_data)
            for req in requirements:
                if req['qty'] > 0:
                    requirement_key = crud.get_requirement_key(fg_key, req['size'], req['color'], req['itemSize'])
                    
                    entries_to_insert.append({
                        'fg_key': fg_key,
                        'activity_type': 'MATERIAL_REQUIREMENT',
                        'status': 'PENDING',
                        'buyer_name': order_info['buyerName'],
                        'buyer_order_no': order_info['buyerOrderNo'],
                        'order_date': order_info['orderDate'],
                        'created_date': order_info['createdDate'],
                        'qty': round(req['qty'] * 100) / 100,
                        'size': req['size'],
                        'color': req['color'],
                        'workflow_position': 1.5,
                        'extra_data': {
                            'itemNo': req['itemNo'],
                            'itemName': req['itemName'],
                            'uom': req['uom'],
                            'consumption': req['consumption'],
                            'supplier': item.supplier,
                            'rate': item.rate,
                            'leadtime': item.leadtime,
                            'cgst': item.cgst or 0,
                            'igst': item.igst or 0,
                            'hsn': item.hsn or '',
                            'isSizeSensitive': req['isSizeSensitive'],
                            'itemSize': req['itemSize'],
                            'garmentSize': req['size'],
                            'orderQty': req.get('orderQty') or req.get('totalOrderQty') or 0,
                            'requirementKey': requirement_key
                        }
                    })
                    
                    snapshot_updates.append({
                        'requirementKey': requirement_key,
                        'fgKey': fg_key,
                        'itemNo': req['itemNo'],
                        'itemName': req['itemName'],
                        'size': req['size'],
                        'color': req['color'],
                        'supplier': item.supplier,
                        'requiredDelta': round(req['qty'] * 100) / 100,
                        'grnDelta': 0,
                        'issueDelta': 0
                    })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        return {"success": True, "message": f"BOM saved with {len(entries_to_insert)} entries"}
    except Exception as e:
        return {"success": False, "message": str(e)}
