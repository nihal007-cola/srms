from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
import json
import logging

router = APIRouter(prefix="/grn", tags=["GRN"])

def build_identity(po_token, fg_key, item_no, garment_size):
    return {
        'poToken': crud.clean_key_exact(po_token),
        'fgKey': crud.clean_key_exact(fg_key),
        'itemNo': crud.clean_key_exact(item_no),
        'garmentSize': crud.clean_key_exact(garment_size)
    }

def identity_to_string(identity):
    return f"{identity['poToken']}|{identity['fgKey']}|{identity['itemNo']}|{identity['garmentSize']}"

def find_po_line(entries, identity):
    clean_po_token = crud.clean_key_exact(identity['poToken'])
    clean_fg_key = crud.clean_key_exact(identity['fgKey'])
    clean_item_no = crud.clean_key_exact(identity['itemNo'])
    clean_garment_size = crud.clean_key_exact(identity['garmentSize'])
    
    for e in entries:
        if (e.activity_type == 'RM_ORDER' and 
            (e.status == 'PROCESSED' or e.status == 'PARTIAL') and
            e.extra_data and 
            crud.clean_key_exact(e.extra_data.get('poToken', '')) == clean_po_token and
            crud.clean_key_exact(e.fg_key) == clean_fg_key and
            crud.clean_key_exact(e.extra_data.get('itemNo', '')) == clean_item_no and
            crud.clean_key_exact(e.size) == clean_garment_size):
            return e
    return None

def calculate_received_qty(grn_entries, identity):
    total = 0
    clean_po_token = crud.clean_key_exact(identity['poToken'])
    clean_fg_key = crud.clean_key_exact(identity['fgKey'])
    clean_item_no = crud.clean_key_exact(identity['itemNo'])
    clean_garment_size = crud.clean_key_exact(identity['garmentSize'])
    
    for grn in grn_entries:
        grn_items = grn.extra_data.get('items', []) if grn.extra_data else []
        for grn_item in grn_items:
            grn_identity = build_identity(
                grn.extra_data.get('poToken', '') if grn.extra_data else '',
                grn_item.get('fgKey', ''),
                grn_item.get('itemNo', ''),
                grn_item.get('garmentSize', '')
            )
            if identity_to_string(grn_identity) == identity_to_string({
                'poToken': clean_po_token,
                'fgKey': clean_fg_key,
                'itemNo': clean_item_no,
                'garmentSize': clean_garment_size
            }):
                total += grn_item.get('receivedQty', 0)
    return total

@router.get("/orders")
def get_grn_orders(db: Session = Depends(get_db)):
    all_entries = crud.get_ledger_entries(db)
    result = []
    processed_po_tokens = set()
    
    rm_orders = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                and (e.status == 'PROCESSED' or e.status == 'PARTIAL')
                and e.extra_data and e.extra_data.get('poToken')]
    
    for entry in rm_orders:
        po_token = entry.extra_data.get('poToken', '')
        if not po_token or po_token in processed_po_tokens:
            continue
        
        line_items = [e for e in rm_orders if crud.clean_key_exact(e.extra_data.get('poToken', '')) == crud.clean_key_exact(po_token)]
        if not line_items:
            continue
        
        first_item = line_items[0]
        metadata = first_item.extra_data or {}
        
        grn_entries = [e for e in all_entries if e.activity_type == 'GRN' 
                      and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == crud.clean_key_exact(po_token)]
        
        has_grn = len(grn_entries) > 0
        status = metadata.get('status', 'PROCESSED')
        if has_grn:
            total_ordered = sum(e.qty or e.extra_data.get('orderedQty', 0) for e in line_items)
            total_received = 0
            for grn in grn_entries:
                items = grn.extra_data.get('items', []) if grn.extra_data else []
                for item in items:
                    total_received += item.get('receivedQty', 0)
            is_complete = total_received >= total_ordered - settings.tolerance
            status = 'COMPLETED' if is_complete else 'PARTIAL'
        
        unpacked_items = []
        for item in line_items:
            identity = build_identity(po_token, item.fg_key or '', item.extra_data.get('itemNo', ''), item.size or 'ALL')
            ordered_qty = item.qty or item.extra_data.get('orderedQty', 0)
            received_qty = calculate_received_qty(grn_entries, identity)
            balance_to_receive = ordered_qty - received_qty
            
            unpacked_items.append({
                'poToken': identity['poToken'],
                'fgKey': identity['fgKey'],
                'itemNo': identity['itemNo'],
                'garmentSize': identity['garmentSize'],
                'itemName': item.extra_data.get('itemName', ''),
                'itemSize': item.extra_data.get('itemSize', ''),
                'color': item.color or item.extra_data.get('color', ''),
                'orderedQty': ordered_qty,
                'receivedQty': received_qty,
                'balanceToReceive': balance_to_receive if balance_to_receive > settings.tolerance else 0,
                'isComplete': balance_to_receive <= settings.tolerance,
                'uom': item.extra_data.get('uom', 'PCS'),
                'rate': item.extra_data.get('rate', 0),
                'cgst': item.extra_data.get('cgst', 0),
                'igst': item.extra_data.get('igst', 0),
                'hsn': item.extra_data.get('hsn', ''),
                'requirementKey': item.extra_data.get('requirementKey', ''),
                'supplier': item.extra_data.get('supplier', ''),
                'supplierAlias': item.extra_data.get('supplierAlias', '')
            })
        
        grouped_by_fg = {}
        for item in unpacked_items:
            if item['fgKey'] not in grouped_by_fg:
                grouped_by_fg[item['fgKey']] = {
                    'fgKey': item['fgKey'],
                    'items': []
                }
            grouped_by_fg[item['fgKey']]['items'].append(item)
        
        result.append({
            'poToken': po_token,
            'supplier': metadata.get('supplier', metadata.get('supplierAlias', '')),
            'supplierAlias': metadata.get('supplierAlias', metadata.get('supplier', '')),
            'items': unpacked_items,
            'groupedByFG': list(grouped_by_fg.values()),
            'totalOrdered': sum(i['orderedQty'] for i in unpacked_items),
            'totalReceived': sum(i['receivedQty'] for i in unpacked_items),
            'totalBalance': sum(i['balanceToReceive'] for i in unpacked_items),
            'status': status,
            'hasGRN': has_grn,
            'orderDate': entry.order_date,
            'fgKeys': list(set(i['fgKey'] for i in unpacked_items if i['fgKey']))
        })
        processed_po_tokens.add(po_token)
    
    return result

@router.post("/save")
def save_grn(data: schemas.GRNSaveRequest, db: Session = Depends(get_db)):
    try:
        po_token = crud.clean_key_exact(data.po_token)
        invoice_no = data.invoice_no or ''
        received_items = data.items
        
        if not po_token:
            raise ValueError('PO Token is required')
        if not received_items:
            raise ValueError('No items to receive')
        
        valid_items = [item for item in received_items if item.received_qty > settings.tolerance]
        if not valid_items:
            raise ValueError('No valid items to receive')
        
        all_entries = crud.get_ledger_entries(db)
        validated_items = []
        has_shortfall = False
        shortfall_map = {}
        grn_entries = [e for e in all_entries if e.activity_type == 'GRN' 
                      and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token]
        
        snapshot_updates = []
        processed_lines = {}  # For deduplication
        
        for received in valid_items:
            identity = build_identity(po_token, received.fg_key or '', received.item_no or '', received.garment_size or 'ALL')
            
            matching_line = find_po_line(all_entries, identity)
            if not matching_line:
                raise ValueError(f"Item {identity['itemNo']} for FG {identity['fgKey']} not found in ledger")
            
            ordered_qty = matching_line.qty or matching_line.extra_data.get('orderedQty', 0)
            previously_received = calculate_received_qty(grn_entries, identity)
            received_qty = received.received_qty
            balance_to_receive = ordered_qty - previously_received
            
            if received_qty > balance_to_receive + settings.tolerance:
                raise ValueError(f"Over-receipt for {identity['itemNo']} (Balance: {balance_to_receive})")
            
            total_received_after = previously_received + received_qty
            if total_received_after < ordered_qty - settings.tolerance:
                has_shortfall = True
                shortfall_map[identity_to_string(identity)] = {
                    'poToken': identity['poToken'],
                    'fgKey': identity['fgKey'],
                    'itemNo': identity['itemNo'],
                    'garmentSize': identity['garmentSize'],
                    'itemName': received.item_name or matching_line.extra_data.get('itemName', ''),
                    'itemSize': received.item_size or matching_line.extra_data.get('itemSize', ''),
                    'color': received.color or matching_line.extra_data.get('color', ''),
                    'orderedQty': ordered_qty,
                    'previouslyReceived': previously_received,
                    'receivedQty': received_qty,
                    'shortfall': ordered_qty - total_received_after,
                    'uom': received.uom or matching_line.extra_data.get('uom', 'PCS'),
                    'rate': received.rate or matching_line.extra_data.get('rate', 0),
                    'requirementKey': matching_line.extra_data.get('requirementKey', '')
                }
            
            # Generate requirement key if missing
            requirement_key = received.requirement_key or matching_line.extra_data.get('requirementKey', '')
            if not requirement_key:
                requirement_key = crud.get_requirement_key(
                    identity['fgKey'], 
                    identity['garmentSize'], 
                    received.color or matching_line.extra_data.get('color', ''),
                    received.item_size or matching_line.extra_data.get('itemSize', '')
                )
            
            validated_items.append({
                'poToken': identity['poToken'],
                'fgKey': identity['fgKey'],
                'itemNo': identity['itemNo'],
                'garmentSize': identity['garmentSize'],
                'itemName': received.item_name or matching_line.extra_data.get('itemName', ''),
                'itemSize': received.item_size or matching_line.extra_data.get('itemSize', ''),
                'color': received.color or matching_line.extra_data.get('color', ''),
                'orderedQty': ordered_qty,
                'previouslyReceived': previously_received,
                'receivedQty': received_qty,
                'rate': received.rate or matching_line.extra_data.get('rate', 0),
                'hsn': received.hsn or matching_line.extra_data.get('hsn', ''),
                'uom': received.uom or matching_line.extra_data.get('uom', 'PCS'),
                'cgst': received.cgst or matching_line.extra_data.get('cgst', 0),
                'igst': received.igst or matching_line.extra_data.get('igst', 0),
                'requirementKey': requirement_key,
                'balanceToReceive': balance_to_receive,
                'supplier': matching_line.extra_data.get('supplier', ''),
                'supplierAlias': matching_line.extra_data.get('supplierAlias', '')
            })
            
            line_key = matching_line.extra_data.get('requirementKey', identity_to_string(identity))
            if line_key not in processed_lines:
                processed_lines[line_key] = matching_line
        
        entries_to_insert = []
        grn_metadata = {
            'poToken': po_token,
            'invoiceNo': invoice_no,
            'items': [{
                'poToken': item['poToken'],
                'fgKey': item['fgKey'],
                'itemNo': item['itemNo'],
                'garmentSize': item['garmentSize'],
                'itemName': item['itemName'],
                'itemSize': item['itemSize'],
                'color': item['color'],
                'orderedQty': item['orderedQty'],
                'receivedQty': item['receivedQty'],
                'rate': item['rate'],
                'hsn': item['hsn'],
                'uom': item['uom'],
                'cgst': item['cgst'],
                'igst': item['igst'],
                'requirementKey': item['requirementKey'],
                'balanceToReceive': item['balanceToReceive'],
                'supplier': item['supplier'],
                'supplierAlias': item['supplierAlias']
            } for item in validated_items],
            'receivedAt': datetime.utcnow().isoformat(),
            'hasShortfall': has_shortfall
        }
        
        fg_keys = list(set(item['fgKey'] for item in validated_items if item['fgKey']))
        
        for fg_key in fg_keys:
            fg_items = [item for item in validated_items if item['fgKey'] == fg_key]
            fg_metadata = dict(grn_metadata)
            fg_metadata['fgKey'] = fg_key
            fg_metadata['fgItems'] = fg_items
            
            rm_order = next((e for e in all_entries if e.activity_type == 'RM_ORDER' 
                           and crud.clean_key_exact(e.fg_key) == crud.clean_key_exact(fg_key)
                           and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token), None)
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'GRN',
                'status': 'PARTIAL' if has_shortfall else 'COMPLETED',
                'buyer_name': rm_order.buyer_name if rm_order else '',
                'buyer_order_no': rm_order.buyer_order_no if rm_order else '',
                'order_date': rm_order.order_date if rm_order else None,
                'created_date': rm_order.created_date if rm_order else None,
                'qty': sum(item['receivedQty'] for item in fg_items),
                'size': fg_items[0]['garmentSize'] if fg_items else 'ALL',
                'color': fg_items[0]['color'] if fg_items else '',
                'workflow_position': 3,
                'extra_data': fg_metadata
            })
        
        new_status = 'PARTIAL' if has_shortfall else 'COMPLETED'
        
        for line_key, item in processed_lines.items():
            metadata_copy = dict(item.extra_data or {})
            metadata_copy['status'] = new_status
            metadata_copy['grnCompletedAt'] = datetime.utcnow().isoformat()
            
            entries_to_insert.append({
                'fg_key': item.fg_key,
                'activity_type': 'RM_ORDER',
                'status': new_status,
                'buyer_name': item.buyer_name,
                'buyer_order_no': item.buyer_order_no,
                'order_date': item.order_date,
                'created_date': item.created_date,
                'qty': item.qty,
                'size': item.size,
                'color': item.color,
                'workflow_position': 2,
                'extra_data': metadata_copy
            })
        
        for item in validated_items:
            req_entries = [e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                          and e.extra_data and e.extra_data.get('requirementKey') == item['requirementKey']
                          and e.status == 'ORDERED']
            
            for req in req_entries:
                entries_to_insert.append({
                    'fg_key': req.fg_key,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'RECEIVED',
                    'buyer_name': req.buyer_name,
                    'buyer_order_no': req.buyer_order_no,
                    'order_date': req.order_date,
                    'created_date': req.created_date,
                    'qty': req.qty,
                    'size': req.size,
                    'color': req.color,
                    'workflow_position': 1.5,
                    'extra_data': {
                        **(req.extra_data or {}),
                        'grnReceivedAt': datetime.utcnow().isoformat(),
                        'poToken': po_token,
                        'receivedQty': item['receivedQty']
                    }
                })
            
            # FIX: Ensure requirement_key is properly set for snapshot update
            requirement_key = item['requirementKey']
            if not requirement_key:
                requirement_key = crud.get_requirement_key(
                    item['fgKey'],
                    item['garmentSize'],
                    item['color'],
                    item['itemSize']
                )
            
            snapshot_updates.append({
                'requirementKey': requirement_key,
                'fgKey': item['fgKey'],
                'itemNo': item['itemNo'],
                'itemName': item['itemName'],
                'size': item['garmentSize'],
                'color': item['color'],
                'supplier': item['supplier'],
                'requiredDelta': 0,
                'grnDelta': item['receivedQty'],
                'issueDelta': 0
            })
        
        # Handle shortfalls
        if has_shortfall:
            buyer_order = next((e for e in all_entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
            for key, shortfall in shortfall_map.items():
                entries_to_insert.append({
                    'fg_key': shortfall['fgKey'],
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'PENDING',
                    'buyer_name': buyer_order.buyer_name if buyer_order else '',
                    'buyer_order_no': buyer_order.buyer_order_no if buyer_order else '',
                    'order_date': buyer_order.order_date if buyer_order else None,
                    'created_date': buyer_order.created_date if buyer_order else None,
                    'qty': shortfall['shortfall'],
                    'size': shortfall['garmentSize'] or 'ALL',
                    'color': shortfall['color'] or '',
                    'workflow_position': 1.5,
                    'extra_data': {
                        'itemNo': shortfall['itemNo'],
                        'itemName': shortfall['itemName'],
                        'uom': shortfall['uom'],
                        'consumption': 1,
                        'supplier': '',
                        'rate': shortfall['rate'],
                        'leadtime': 0,
                        'cgst': 0,
                        'igst': 0,
                        'hsn': '',
                        'isSizeSensitive': False,
                        'itemSize': shortfall['itemSize'],
                        'shortfallFrom': po_token,
                        'requirementKey': shortfall['requirementKey']
                    }
                })
                
                snapshot_updates.append({
                    'requirementKey': shortfall['requirementKey'],
                    'fgKey': shortfall['fgKey'],
                    'itemNo': shortfall['itemNo'],
                    'itemName': shortfall['itemName'],
                    'size': shortfall['garmentSize'],
                    'color': shortfall['color'],
                    'supplier': '',
                    'requiredDelta': shortfall['shortfall'],
                    'grnDelta': 0,
                    'issueDelta': 0
                })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        # FIX: Ensure snapshot is updated with all items
        if snapshot_updates:
            crud.update_inventory_snapshot(db, snapshot_updates)
            logging.info(f"Updated inventory snapshot with {len(snapshot_updates)} items")
        
        return {
            'success': True,
            'message': f'GRN saved successfully. Status: {new_status}',
            'hasShortfall': has_shortfall,
            'shortfallCount': len(shortfall_map),
            'fgKeys': fg_keys,
            'snapshotUpdates': len(snapshot_updates)
        }
    except Exception as e:
        logging.error(f"GRN save error: {str(e)}")
        return {'success': False, 'message': str(e)}

@router.post("/cancel")
def cancel_grn(data: Dict, db: Session = Depends(get_db)):
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        invoice_no = crud.clean_key_exact(data.get('invoice_no', ''))
        
        if not po_token:
            raise ValueError('PO Token is required')
        
        all_entries = crud.get_ledger_entries(db)
        grn_entries = [e for e in all_entries if e.activity_type == 'GRN' 
                      and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token
                      and e.status != 'CANCELLED']
        
        if invoice_no:
            grn_entries = [e for e in grn_entries if crud.clean_key_exact(e.extra_data.get('invoiceNo', '')) == invoice_no]
        
        if not grn_entries:
            raise ValueError(f'No active GRN found for PO: {po_token}')
        
        entries_to_insert = []
        snapshot_updates = []
        
        for grn in grn_entries:
            grn_items = grn.extra_data.get('items', []) if grn.extra_data else []
            
            for grn_item in grn_items:
                received_qty = grn_item.get('receivedQty', 0)
                if received_qty <= settings.tolerance:
                    continue
                
                entries_to_insert.append({
                    'fg_key': grn.fg_key,
                    'activity_type': 'GRN',
                    'status': 'CANCELLED',
                    'buyer_name': grn.buyer_name,
                    'buyer_order_no': grn.buyer_order_no,
                    'order_date': grn.order_date,
                    'created_date': grn.created_date,
                    'qty': -received_qty,
                    'size': grn_item.get('garmentSize', 'ALL'),
                    'color': grn_item.get('color', ''),
                    'workflow_position': 3,
                    'extra_data': {
                        'poToken': po_token,
                        'invoiceNo': invoice_no or (grn.extra_data.get('invoiceNo', '') if grn.extra_data else ''),
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'cancelledFrom': grn.timestamp.isoformat() if grn.timestamp else None,
                        'originalItems': grn_items,
                        'reversal': True,
                        'reason': 'GRN Cancellation'
                    }
                })
                
                snapshot_updates.append({
                    'requirementKey': grn_item.get('requirementKey', ''),
                    'fgKey': grn.fg_key,
                    'itemNo': grn_item.get('itemNo', ''),
                    'itemName': grn_item.get('itemName', ''),
                    'size': grn_item.get('garmentSize', 'ALL'),
                    'color': grn_item.get('color', ''),
                    'supplier': grn_item.get('supplier', ''),
                    'requiredDelta': 0,
                    'grnDelta': -received_qty,
                    'issueDelta': 0
                })
            
            # Mark original GRN as CANCELLED
            entries_to_insert.append({
                'fg_key': grn.fg_key,
                'activity_type': 'GRN',
                'status': 'CANCELLED',
                'buyer_name': grn.buyer_name,
                'buyer_order_no': grn.buyer_order_no,
                'order_date': grn.order_date,
                'created_date': grn.created_date,
                'qty': 0,
                'size': grn.size or 'ALL',
                'color': grn.color or '',
                'workflow_position': 3,
                'extra_data': {
                    **(grn.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancellationReason': 'Manual cancellation'
                }
            })
        
        # Revert RM_ORDER status if all GRNs cancelled
        remaining_grns = [e for e in all_entries if e.activity_type == 'GRN' 
                         and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token
                         and e.status != 'CANCELLED']
        
        if not remaining_grns:
            rm_orders = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                        and e.extra_data and crud.clean_key_exact(e.extra_data.get('poToken', '')) == po_token
                        and e.status != 'CANCELLED']
            
            for rm in rm_orders:
                metadata_copy = dict(rm.extra_data or {})
                metadata_copy['status'] = 'PROCESSED'
                metadata_copy['grnCancelledAt'] = datetime.utcnow().isoformat()
                
                entries_to_insert.append({
                    'fg_key': rm.fg_key,
                    'activity_type': 'RM_ORDER',
                    'status': 'PROCESSED',
                    'buyer_name': rm.buyer_name,
                    'buyer_order_no': rm.buyer_order_no,
                    'order_date': rm.order_date,
                    'created_date': rm.created_date,
                    'qty': rm.qty,
                    'size': rm.size,
                    'color': rm.color,
                    'workflow_position': 2,
                    'extra_data': metadata_copy
                })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        return {
            'success': True,
            'message': f'GRN cancelled successfully',
            'cancelledCount': len(grn_entries),
            'reversedItems': len(snapshot_updates)
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.get("/shortfalls")
def get_pending_shortfalls(db: Session = Depends(get_db)):
    snapshot = crud.get_inventory_snapshot(db)
    result = []
    for item in snapshot:
        if item.pending_shortfall > settings.tolerance:
            result.append({
                'requirementKey': item.requirement_key,
                'fgKey': item.fg_key,
                'itemNo': item.item_no,
                'itemName': item.item_name,
                'garmentSize': item.garment_size,
                'color': item.color,
                'supplier': item.supplier,
                'orderedQty': item.total_required_qty,
                'receivedQty': item.total_grn_received_qty,
                'shortfall': item.pending_shortfall,
                'uom': 'PCS'
            })
    return result
