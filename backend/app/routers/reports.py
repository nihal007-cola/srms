from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/reports", tags=["Reports"])

@router.post("/data")
def get_report_data(data: Dict, db: Session = Depends(get_db)):
    report_type = data.get('reportType')
    filters = data.get('filters', {})
    
    if report_type == 'BUYER_ORDER_STATUS':
        return get_buyer_order_status_report(db, filters)
    elif report_type == 'RM_STOCK':
        return get_rm_stock_report(db, filters)
    elif report_type == 'RM_ORDERED':
        return get_rm_ordered_report(db, filters)
    else:
        raise ValueError('Invalid report type')

def get_buyer_order_status_report(db: Session, filters: Dict):
    all_entries = crud.get_ledger_entries(db)
    fg_groups = {}
    
    for entry in all_entries:
        fg_key = crud.clean_key_exact(entry.fg_key)
        if not fg_key:
            continue
        if fg_key not in fg_groups:
            fg_groups[fg_key] = {'fgKey': fg_key, 'activities': []}
        fg_groups[fg_key]['activities'].append(entry)
    
    result = []
    for fg_key, group in fg_groups.items():
        buyer_order = next((e for e in group['activities'] if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
        bom = next((e for e in group['activities'] if e.activity_type == 'BOM' and e.status == 'COMPLETED'), None)
        rm_order = next((e for e in group['activities'] if e.activity_type == 'RM_ORDER' and e.status == 'PROCESSED'), None)
        grn = next((e for e in group['activities'] if e.activity_type == 'GRN' and e.status == 'COMPLETED'), None)
        issue = next((e for e in group['activities'] if e.activity_type == 'ISSUE_RM' and e.status == 'COMPLETED'), None)
        lifecycle = next((e for e in group['activities'] if e.activity_type == 'LIFECYCLE' and e.status == 'CLOSED'), None)
        
        current_pos = crud.get_current_workflow_position(db, fg_key)
        workflow = settings.get_workflow_list()
        current_stage = workflow[int(current_pos)] if int(current_pos) < len(workflow) else 'UNKNOWN'
        
        # Apply filters
        if filters.get('status') and filters['status'] != 'ALL':
            status = 'CLOSED' if lifecycle else current_stage
            if status != filters['status']:
                continue
        
        if filters.get('dateFrom'):
            try:
                date_from = datetime.fromisoformat(filters['dateFrom'])
                order_date = buyer_order.order_date if buyer_order else datetime(1970, 1, 1)
                if order_date < date_from:
                    continue
            except:
                pass
        
        if filters.get('dateTo'):
            try:
                date_to = datetime.fromisoformat(filters['dateTo'])
                order_date = buyer_order.order_date if buyer_order else datetime(1970, 1, 1)
                if order_date > date_to:
                    continue
            except:
                pass
        
        def get_status_time(activity):
            if not activity:
                return None
            return activity.timestamp.isoformat() if activity.timestamp else None
        
        result.append({
            'fgKey': fg_key or '—',
            'buyerOrderNo': buyer_order.buyer_order_no if buyer_order else 'N/A',
            'buyerName': buyer_order.buyer_name if buyer_order else 'N/A',
            'orderDate': buyer_order.order_date.isoformat() if buyer_order and buyer_order.order_date else None,
            'currentStatus': 'CLOSED' if lifecycle else current_stage,
            'bomTime': get_status_time(bom),
            'rmOrderTime': get_status_time(rm_order),
            'grnTime': get_status_time(grn),
            'issueTime': get_status_time(issue),
            'lifecycleTime': get_status_time(lifecycle),
            'isComplete': bool(lifecycle)
        })
    
    result.sort(key=lambda x: x.get('orderDate') or '', reverse=True)
    return result

def get_rm_stock_report(db: Session, filters: Dict):
    snapshot = crud.get_inventory_snapshot(db)
    result = []
    
    for item in snapshot:
        stock = item.current_stock or 0
        
        if filters.get('supplier') and filters['supplier'] != 'ALL':
            if item.supplier != filters['supplier']:
                continue
        if filters.get('fgKey'):
            if filters['fgKey'].lower() not in item.fg_key.lower():
                continue
        if filters.get('status') and filters['status'] != 'ALL':
            if filters['status'] == 'IN_STOCK' and stock <= settings.tolerance:
                continue
            if filters['status'] == 'OUT_OF_STOCK' and stock > settings.tolerance:
                continue
            if filters['status'] == 'LOW_STOCK' and (stock <= settings.tolerance or stock >= 10):
                continue
            if filters['status'] == 'ZERO_STOCK' and stock > settings.tolerance:
                continue
        
        result.append({
            'fgKey': item.fg_key or '—',
            'itemNo': item.item_no or '—',
            'itemName': item.item_name or '—',
            'garmentSize': item.garment_size or '—',
            'color': item.color or '—',
            'supplier': item.supplier or '—',
            'rate': 0,
            'uom': 'PCS',
            'grnReceived': item.total_grn_received_qty or 0,
            'issued': item.total_issued_qty or 0,
            'stock': stock,
            'required': item.total_required_qty or 0,
            'lastGRN': item.last_updated.isoformat() if item.last_updated else None,
            'lastIssue': item.last_updated.isoformat() if item.last_updated else None
        })
    
    result.sort(key=lambda x: x['stock'])
    return result

def get_rm_ordered_report(db: Session, filters: Dict):
    all_entries = crud.get_ledger_entries(db)
    resolved_lines = {}
    
    for entry in all_entries:
        if entry.activity_type == 'RM_ORDER' and entry.extra_data and entry.extra_data.get('poToken'):
            line_key = f"{entry.extra_data.get('poToken')}_{entry.extra_data.get('requirementKey', entry.fg_key)}"
            if line_key not in resolved_lines or (entry.timestamp and entry.timestamp > resolved_lines[line_key].timestamp):
                resolved_lines[line_key] = entry
    
    po_map = {}
    for line_key, entry in resolved_lines.items():
        if entry.status == 'CANCELLED':
            continue
        
        po_token = entry.extra_data.get('poToken')
        if not po_token:
            continue
        
        if po_token not in po_map:
            po_map[po_token] = {
                'poToken': po_token or '—',
                'supplier': entry.extra_data.get('supplier') or entry.extra_data.get('supplierAlias') or '',
                'orderDate': entry.order_date.isoformat() if entry.order_date else '',
                'fgKeys': [],
                'items': [],
                'totalQty': 0,
                'totalAmount': 0,
                'status': entry.status or 'DRAFT'
            }
        
        fg_key = crud.clean_key_exact(entry.fg_key)
        if fg_key and fg_key not in po_map[po_token]['fgKeys']:
            po_map[po_token]['fgKeys'].append(fg_key)
        
        qty = entry.qty or 0
        rate = entry.extra_data.get('rate', 0)
        
        po_map[po_token]['items'].append({
            'fgKey': fg_key or '—',
            'itemNo': entry.extra_data.get('itemNo', ''),
            'itemName': entry.extra_data.get('itemName', ''),
            'garmentSize': entry.size or 'ALL',
            'color': entry.color or '',
            'qty': qty,
            'rate': rate,
            'amount': qty * rate
        })
        
        po_map[po_token]['totalQty'] += qty
        po_map[po_token]['totalAmount'] += qty * rate
    
    result = []
    for po_token, po in po_map.items():
        if filters.get('supplier') and filters['supplier'] != 'ALL':
            if po['supplier'] != filters['supplier']:
                continue
        if filters.get('status') and filters['status'] != 'ALL':
            if po['status'] != filters['status']:
                continue
        if filters.get('dateFrom'):
            try:
                date_from = datetime.fromisoformat(filters['dateFrom'])
                order_date = datetime.fromisoformat(po['orderDate']) if po['orderDate'] else datetime(1970, 1, 1)
                if order_date < date_from:
                    continue
            except:
                pass
        if filters.get('dateTo'):
            try:
                date_to = datetime.fromisoformat(filters['dateTo'])
                order_date = datetime.fromisoformat(po['orderDate']) if po['orderDate'] else datetime(1970, 1, 1)
                if order_date > date_to:
                    continue
            except:
                pass
        
        result.append(po)
    
    result.sort(key=lambda x: x.get('orderDate') or '', reverse=True)
    return result

@router.get("/filters")
def get_report_filters(db: Session = Depends(get_db)):
    all_entries = crud.get_ledger_entries(db)
    suppliers = set()
    fg_keys = set()
    statuses = ['ALL', 'DRAFT', 'PROCESSED', 'COMPLETED', 'PARTIAL', 'CANCELLED', 'CLOSED']
    
    for entry in all_entries:
        if entry.extra_data:
            if entry.extra_data.get('supplier'):
                suppliers.add(entry.extra_data['supplier'])
            if entry.extra_data.get('supplierAlias'):
                suppliers.add(entry.extra_data['supplierAlias'])
        fg_key = crud.clean_key_exact(entry.fg_key)
        if fg_key:
            fg_keys.add(fg_key)
    
    snapshot = crud.get_inventory_snapshot(db)
    for item in snapshot:
        if item.supplier:
            suppliers.add(item.supplier)
    
    return {
        'suppliers': sorted([s for s in suppliers if s]),
        'fgKeys': sorted([k for k in fg_keys if k]),
        'statuses': statuses
    }
