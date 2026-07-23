from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/issue-rm", tags=["Issue RM"])

@router.get("/orders")
def get_issue_rm_orders(db: Session = Depends(get_db)):
    snapshot = crud.get_inventory_snapshot(db)
    result = []
    processed_fg = set()
    
    fg_map = {}
    for item in snapshot:
        if item.total_grn_received_qty > settings.tolerance or item.total_required_qty > settings.tolerance:
            fg_key = item.fg_key
            if fg_key not in fg_map:
                fg_map[fg_key] = {'items': [], 'totalRequired': 0, 'totalGRN': 0, 'totalIssued': 0}
            fg_map[fg_key]['items'].append(item)
            fg_map[fg_key]['totalRequired'] += item.total_required_qty
            fg_map[fg_key]['totalGRN'] += item.total_grn_received_qty
            fg_map[fg_key]['totalIssued'] += item.total_issued_qty
    
    for fg_key, group in fg_map.items():
        if fg_key in processed_fg:
            continue
        
        total_required = group['totalRequired']
        total_grn = group['totalGRN']
        total_issued = group['totalIssued']
        available_to_issue = total_grn - total_issued
        remaining = total_required - total_issued
        
        item_details = []
        for item in group['items']:
            max_issuable = item.total_required_qty * settings.issue_buffer_percent
            available_for_item = item.total_grn_received_qty - item.total_issued_qty
            
            item_details.append({
                'itemNo': item.item_no or '',
                'itemName': item.item_name or '',
                'garmentSize': item.garment_size or 'ALL',
                'itemSize': '',
                'color': item.color or '',
                'requiredQty': item.total_required_qty or 0,
                'grnQty': item.total_grn_received_qty or 0,
                'issuedQty': item.total_issued_qty or 0,
                'availableToIssue': available_for_item if available_for_item > settings.tolerance else 0,
                'maxIssuable': max_issuable or 0,
                'uom': 'PCS',
                'requirementKey': item.requirement_key or ''
            })
        
        result.append({
            'fgKey': fg_key,
            'requirements': [{
                'requirementKey': item.requirement_key,
                'fgKey': item.fg_key,
                'itemNo': item.item_no,
                'itemName': item.item_name,
                'garmentSize': item.garment_size,
                'color': item.color,
                'supplier': item.supplier,
                'totalRequired': item.total_required_qty,
                'totalGRN': item.total_grn_received_qty,
                'totalIssued': item.total_issued_qty
            } for item in group['items']],
            'itemDetails': item_details,
            'totalRequired': total_required,
            'totalGRN': total_grn,
            'totalIssued': total_issued,
            'availableToIssue': available_to_issue,
            'remaining': remaining,
            'isComplete': remaining <= settings.tolerance,
            'isPartial': remaining > settings.tolerance and total_issued > settings.tolerance
        })
        processed_fg.add(fg_key)
    
    return result

@router.get("/{fg_key}/items")
def get_issuable_items(fg_key: str, db: Session = Depends(get_db)):
    clean_fg_key = crud.clean_key_exact(fg_key)
    snapshot = crud.get_inventory_snapshot(db, clean_fg_key)
    
    return [{
        'itemNo': item.item_no or '',
        'itemName': item.item_name or '',
        'garmentSize': item.garment_size or 'ALL',
        'itemSize': '',
        'color': item.color or '',
        'requiredQty': item.total_required_qty or 0,
        'grnQty': item.total_grn_received_qty or 0,
        'issuedQty': item.total_issued_qty or 0,
        'availableToIssue': (item.total_grn_received_qty - item.total_issued_qty) if (item.total_grn_received_qty - item.total_issued_qty) > settings.tolerance else 0,
        'maxIssuable': item.total_required_qty * settings.issue_buffer_percent,
        'uom': 'PCS',
        'requirementKey': item.requirement_key or ''
    } for item in snapshot]

@router.post("/save")
def save_issue_rm(data: schemas.IssueRMSaveRequest, db: Session = Depends(get_db)):
    try:
        fg_key = crud.clean_key_exact(data.fg_key)
        items = data.items
        
        if not fg_key:
            raise ValueError('FG Key is required')
        if not items:
            raise ValueError('No items to issue')
        
        all_entries = crud.get_ledger_entries(db, fg_key)
        grn = next((e for e in all_entries if e.activity_type == 'GRN' and e.status == 'COMPLETED'), None)
        if not grn:
            raise ValueError('GRN must be completed before issuing materials')
        
        buyer_order = next((e for e in all_entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        order_info = {
            'buyerName': buyer_order.buyer_name if buyer_order else '',
            'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else '',
            'orderDate': buyer_order.order_date if buyer_order else None,
            'createdDate': buyer_order.created_date if buyer_order else None
        }
        
        total_issued = 0
        total_required = 0
        all_complete = True
        issuance_items = []
        entries_to_insert = []
        snapshot_updates = []
        
        for item in items:
            requirement_key = item.requirement_key
            
            if not requirement_key:
                snapshot = crud.get_inventory_snapshot(db, fg_key)
                match = next((s for s in snapshot if s.item_name == item.item_name and 
                             (s.garment_size == item.garment_size or 'ALL')), None)
                if match:
                    requirement_key = match.requirement_key
            
            if not requirement_key:
                raise ValueError(f'Requirement key not found for item: {item.item_name}')
            
            required_qty = item.required_qty
            max_issuable = required_qty * settings.issue_buffer_percent
            issuing_qty = item.issuing_qty
            
            snapshot_items = crud.get_inventory_snapshot(db, None, requirement_key)
            current_stock = snapshot_items[0].current_stock if snapshot_items else 0
            total_req_from_snapshot = snapshot_items[0].total_required_qty if snapshot_items else required_qty
            
            if issuing_qty > current_stock + settings.tolerance:
                raise ValueError(f'Issuance for {item.item_name} exceeds available stock')
            if issuing_qty > max_issuable + settings.tolerance:
                raise ValueError(f'Issuance for {item.item_name} exceeds buffer limit')
            
            req_entry = next((e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                             and e.status == 'RECEIVED'
                             and e.extra_data and e.extra_data.get('requirementKey') == requirement_key), None)
            
            if not req_entry:
                raise ValueError(f'Requirement {requirement_key} not found')
            
            previously_issued = sum(e.qty or 0 for e in all_entries 
                                   if e.activity_type == 'MATERIAL_REQUIREMENT' 
                                   and e.status == 'ISSUED'
                                   and e.extra_data and e.extra_data.get('requirementKey') == requirement_key)
            
            remaining = total_req_from_snapshot - previously_issued - issuing_qty
            
            issuance_items.append({
                'itemNo': item.item_no or '',
                'itemName': item.item_name or '',
                'garmentSize': item.garment_size or 'ALL',
                'itemSize': item.item_size or '',
                'color': item.color or '',
                'requiredQty': total_req_from_snapshot,
                'previouslyIssued': previously_issued,
                'currentlyIssuing': issuing_qty,
                'remaining': remaining,
                'maxIssuable': max_issuable,
                'availableToIssue': current_stock,
                'uom': item.uom or 'PCS',
                'requirementKey': requirement_key
            })
            
            total_issued += issuing_qty
            total_required += total_req_from_snapshot
            if remaining > settings.tolerance:
                all_complete = False
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'MATERIAL_REQUIREMENT',
                'status': 'ISSUED',
                'buyer_name': req_entry.buyer_name,
                'buyer_order_no': req_entry.buyer_order_no,
                'order_date': req_entry.order_date,
                'created_date': req_entry.created_date,
                'qty': issuing_qty,
                'size': req_entry.size,
                'color': req_entry.color,
                'workflow_position': 1.5,
                'extra_data': {
                    **(req_entry.extra_data or {}),
                    'issuedAt': datetime.utcnow().isoformat(),
                    'previouslyIssued': previously_issued,
                    'cumulativeIssued': previously_issued + issuing_qty,
                    'remaining': remaining,
                    'grnAvailable': current_stock
                }
            })
            
            snapshot_updates.append({
                'requirementKey': requirement_key,
                'fgKey': fg_key,
                'itemNo': item.item_no or '',
                'itemName': item.item_name or '',
                'size': item.garment_size or 'ALL',
                'color': item.color or '',
                'supplier': '',
                'requiredDelta': 0,
                'grnDelta': 0,
                'issueDelta': issuing_qty
            })
        
        issue_status = 'COMPLETED' if all_complete else ('PARTIALLY_ISSUED' if total_issued > settings.tolerance else 'ISSUANCE_PENDING')
        
        entries_to_insert.append({
            'fg_key': fg_key,
            'activity_type': 'ISSUE_RM',
            'status': issue_status,
            'buyer_name': order_info['buyerName'],
            'buyer_order_no': order_info['buyerOrderNo'],
            'order_date': order_info['orderDate'],
            'created_date': order_info['createdDate'],
            'workflow_position': 4,
            'extra_data': {
                'items': issuance_items,
                'totalIssued': total_issued,
                'totalRequired': total_required,
                'allComplete': all_complete,
                'issuedAt': datetime.utcnow().isoformat()
            }
        })
        
        if all_complete:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'LIFECYCLE',
                'status': 'CLOSED',
                'buyer_name': order_info['buyerName'],
                'buyer_order_no': order_info['buyerOrderNo'],
                'order_date': order_info['orderDate'],
                'created_date': order_info['createdDate'],
                'workflow_position': 5,
                'extra_data': {
                    'closedAt': datetime.utcnow().isoformat(),
                    'totalIssued': total_issued,
                    'totalRequired': total_required,
                    'reason': 'All requirements fulfilled'
                }
            })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        return {
            'success': True,
            'message': f'Issue RM saved successfully. Status: {issue_status}',
            'status': issue_status,
            'allComplete': all_complete
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}
