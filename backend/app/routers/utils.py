from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/utils", tags=["Utilities"])

@router.get("/debug/fg-status")
def debug_fg_status(fg_key: str, db: Session = Depends(get_db)):
    """Debug endpoint to check FG status"""
    try:
        clean_fg_key = crud.clean_key_exact(fg_key)
        entries = crud.get_ledger_entries(db, clean_fg_key)
        workflow = settings.get_workflow_list()
        result = {
            'fgKey': clean_fg_key,
            'currentPosition': crud.get_current_workflow_position(db, clean_fg_key),
            'totalEntries': len(entries),
            'allStatuses': {},
            'entries': [{
                'activity': e.activity_type,
                'status': e.status,
                'qty': e.qty,
                'size': e.size,
                'color': e.color,
                'extra_data': e.extra_data
            } for e in entries]
        }
        for module in workflow:
            status = crud.get_latest_status(db, clean_fg_key, module)
            result['allStatuses'][module] = status.status if status else 'NOT FOUND'
        return result
    except Exception as e:
        return {'error': str(e), 'fgKey': fg_key}

@router.post("/cancel/stage")
def cancel_stage(data: Dict, db: Session = Depends(get_db)):
    """Cancel a specific stage for an FG"""
    try:
        fg_key = crud.clean_key_exact(data.get('fgKey', ''))
        target_stage = data.get('targetStage', '').upper()
        
        if not fg_key:
            raise ValueError('FG Key is required')
        if not target_stage:
            raise ValueError('Target stage is required')
        
        # Check if cancellation is allowed
        check = can_cancel_stage(db, fg_key, target_stage)
        if not check['canCancel']:
            raise ValueError(check['reason'])
        
        entries = crud.get_ledger_entries(db, fg_key)
        target_pos = crud.get_module_position(target_stage)
        entries_to_insert = []
        workflow = settings.get_workflow_list()
        
        target_entries = [e for e in entries if e.activity_type == target_stage and e.status != 'CANCELLED']
        
        for entry in target_entries:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': entry.activity_type,
                'status': 'CANCELLED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': target_pos - 1,
                'extra_data': {
                    **(entry.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledFrom': target_stage,
                    'previousStatus': entry.status
                }
            })
        
        # Special handling for RM_ORDER cancellation
        if target_stage == 'RM_ORDER':
            req_entries = [e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                          and e.status == 'ORDERED'
                          and e.extra_data and e.extra_data.get('poToken')]
            for req in req_entries:
                entries_to_insert.append({
                    'fg_key': fg_key,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'PENDING',
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
                        'poToken': None,
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'restoredFrom': 'CANCELLATION'
                    }
                })
        
        # Special handling for GRN cancellation
        if target_stage == 'GRN':
            grn_entries = [e for e in entries if e.activity_type == 'GRN' and e.status != 'CANCELLED']
            snapshot_updates = []
            for grn in grn_entries:
                grn_items = grn.extra_data.get('items', []) if grn.extra_data else []
                for grn_item in grn_items:
                    received_qty = grn_item.get('receivedQty', 0)
                    if received_qty > settings.tolerance:
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
            if snapshot_updates:
                crud.update_inventory_snapshot(db, snapshot_updates)
        
        if not entries_to_insert:
            return {'success': False, 'message': f'No {target_stage} entries found to cancel'}
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            'success': True,
            'message': f'{target_stage} cancelled successfully. Moved back to {workflow[target_pos - 1] if target_pos > 0 else "START"}.'
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

def can_cancel_stage(db: Session, fg_key: str, target_stage: str) -> Dict:
    """Check if a stage can be cancelled"""
    clean_fg_key = crud.clean_key_exact(fg_key)
    entries = crud.get_ledger_entries(db, clean_fg_key)
    workflow = settings.get_workflow_list()
    
    statuses = {}
    for module in workflow:
        status = crud.get_latest_status(db, clean_fg_key, module)
        statuses[module] = status.status if status else 'NOT_FOUND'
    
    target_pos = crud.get_module_position(target_stage)
    current_pos = crud.get_current_workflow_position(db, clean_fg_key)
    
    if current_pos < target_pos:
        return {'canCancel': False, 'reason': f'{target_stage} not yet reached. Current position: {current_pos}'}
    
    downstream_stages = workflow[target_pos + 1:]
    for stage in downstream_stages:
        status = statuses.get(stage)
        if status and status != 'NOT_FOUND' and status != 'CANCELLED':
            return {'canCancel': False, 'reason': f'Cannot cancel {target_stage}. {stage} already exists ({status}).'}
    
    return {'canCancel': True, 'reason': 'Can cancel'}

@router.post("/cancel/order")
def cancel_whole_order(data: Dict, db: Session = Depends(get_db)):
    """Cancel an entire order (all FGs)"""
    try:
        fg_order_serial = crud.clean_key_exact(data.get('fgOrderSerial', ''))
        if not fg_order_serial:
            raise ValueError('FG Order Serial is required')
        
        entries = crud.get_ledger_entries(db)
        fg_keys = []
        
        for entry in entries:
            fg_key = crud.clean_key_exact(entry.fg_key)
            serial = fg_key.split('|')[0] if fg_key else ''
            if serial == fg_order_serial:
                if fg_key not in fg_keys:
                    fg_keys.append(fg_key)
        
        if not fg_keys:
            raise ValueError('Order not found: ' + fg_order_serial)
        
        results = []
        for fg_key in fg_keys:
            current_pos = crud.get_current_workflow_position(db, fg_key)
            if current_pos > 1:
                check = can_cancel_stage(db, fg_key, 'BOM')
                if not check['canCancel']:
                    results.append({'fgKey': fg_key, 'success': False, 'reason': check['reason']})
                    continue
            
            cancel_result = cancel_stage({'fgKey': fg_key, 'targetStage': 'BUYER_ORDER'}, db)
            results.append({'fgKey': fg_key, 'success': cancel_result.get('success', False), 'message': cancel_result.get('message', '')})
        
        all_success = all(r.get('success', False) for r in results)
        return {
            'success': all_success,
            'message': 'Order cancelled successfully' if all_success else 'Some FGs could not be cancelled',
            'results': results
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.get("/health")
def health_check():
    return {"status": "healthy", "version": "1.0.0"}

@router.get("/workflow")
def get_workflow():
    return {"workflow": settings.get_workflow_list()}

@router.get("/settings")
def get_settings():
    return {
        "company_name": settings.company_name,
        "company_address": settings.company_address,
        "company_gst": settings.company_gst,
        "company_state": settings.company_state,
        "tolerance": settings.tolerance,
        "issue_buffer_percent": settings.issue_buffer_percent,
        "default_sizes": settings.get_default_sizes_list()
    }
# ==============================================================
# ADD THIS TO backend/app/routers/utils.py
# After the existing code, before the final router
# ==============================================================

# ==============================================================
# REPLACE the /cancel/fg endpoint in backend/app/routers/utils.py
# With this corrected version that enforces workflow rules
# ==============================================================

# ==============================================================
# FIX: Replace the /cancel/fg endpoint with corrected syntax
# ==============================================================

@router.post("/cancel/fg")
def cancel_entire_fg(data: Dict, db: Session = Depends(get_db)):
    """
    Cancel an FG ONLY if it's still in BOM stage.
    Cancellation is blocked if downstream records exist.
    """
    try:
        fg_key = crud.clean_key_exact(data.get('fg_key', ''))
        
        if not fg_key:
            raise ValueError('FG Key is required')
        
        # Get all entries for this FG
        entries = crud.get_ledger_entries(db, fg_key)
        
        if not entries:
            raise ValueError(f'FG {fg_key} not found')
        
        # Check if already cancelled
        latest = entries[-1] if entries else None
        if latest and latest.status == 'CANCELLED':
            return {'success': False, 'message': f'FG {fg_key} is already cancelled'}
        
        # Check for downstream records
        rm_order_exists = any(e for e in entries if e.activity_type == 'RM_ORDER' and e.status not in ['CANCELLED'])
        req_exists = any(e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                       and e.status in ['ORDERED', 'RECEIVED'] and e.status not in ['CANCELLED'])
        grn_exists = any(e for e in entries if e.activity_type == 'GRN' and e.status not in ['CANCELLED'])
        issue_exists = any(e for e in entries if e.activity_type == 'ISSUE_RM' and e.status not in ['CANCELLED'])
        
        # BLOCK cancellation if any downstream exists
        if rm_order_exists or req_exists or grn_exists or issue_exists:
            error_msg = []
            if rm_order_exists:
                error_msg.append("RM Order exists")
            if req_exists:
                error_msg.append("RM Requirement exists")
            if grn_exists:
                error_msg.append("GRN exists")
            if issue_exists:
                error_msg.append("Issue RM exists")
            
            # Build error message without backslash in f-string expression
            blocked_msg = "This FG has already progressed beyond the BOM stage.\n\nBlocked because:\n- " + "\n- ".join(error_msg) + "\n\nPlease reverse the workflow one stage before cancelling."
            
            return {
                'success': False, 
                'message': blocked_msg,
                'blocked': True,
                'reason': error_msg
            }
        
        # If we get here, cancellation is allowed (only BOM exists)
        entries_to_insert = []
        cancelled_count = 0
        
        # Find BOM entry
        bom_entry = next((e for e in entries if e.activity_type == 'BOM' and e.status not in ['CANCELLED']), None)
        if bom_entry:
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'BOM',
                'status': 'CANCELLED',
                'buyer_name': bom_entry.buyer_name,
                'buyer_order_no': bom_entry.buyer_order_no,
                'order_date': bom_entry.order_date,
                'created_date': bom_entry.created_date,
                'qty': bom_entry.qty,
                'size': bom_entry.size,
                'color': bom_entry.color,
                'workflow_position': 0,
                'extra_data': {
                    **(bom_entry.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledFrom': 'BOM',
                    'previousStatus': bom_entry.status,
                    'cancelReason': 'BOM cancelled by user'
                }
            })
            cancelled_count += 1
        
        # Also cancel any PENDING MATERIAL_REQUIREMENT
        req_entries = [e for e in entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                      and e.status == 'PENDING' and e.status not in ['CANCELLED']]
        for req in req_entries:
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
                'workflow_position': 0,
                'extra_data': {
                    **(req.extra_data or {}),
                    'cancelledAt': datetime.utcnow().isoformat(),
                    'cancelledFrom': 'BOM_CANCELLATION',
                    'previousStatus': req.status
                }
            })
            cancelled_count += 1
        
        if not bom_entry:
            buyer_order = next((e for e in entries if e.activity_type == 'BUYER_ORDER' and e.status == 'COMPLETED'), None)
            if buyer_order:
                entries_to_insert.append({
                    'fg_key': fg_key,
                    'activity_type': 'BUYER_ORDER',
                    'status': 'CANCELLED',
                    'buyer_name': buyer_order.buyer_name,
                    'buyer_order_no': buyer_order.buyer_order_no,
                    'order_date': buyer_order.order_date,
                    'created_date': buyer_order.created_date,
                    'qty': buyer_order.qty,
                    'size': buyer_order.size,
                    'color': buyer_order.color,
                    'workflow_position': -1,
                    'extra_data': {
                        **(buyer_order.extra_data or {}),
                        'cancelledAt': datetime.utcnow().isoformat(),
                        'cancelledFrom': 'BOM_CANCELLATION',
                        'cancelReason': 'BOM cancelled by user'
                    }
                })
                cancelled_count += 1
        
        if not entries_to_insert:
            return {'success': False, 'message': 'No active records found to cancel'}
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {
            'success': True,
            'message': f'FG {fg_key} cancelled successfully from BOM stage',
            'cancelledCount': cancelled_count
        }
        
    except Exception as e:
        db.rollback()
        logging.error(f"Cancel FG error: {str(e)}")
        return {'success': False, 'message': str(e)}
