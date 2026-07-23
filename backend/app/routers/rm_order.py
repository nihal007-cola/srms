from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings
import json

router = APIRouter(prefix="/rm-order", tags=["RM Order"])

@router.get("/orders")
def get_rm_orders(db: Session = Depends(get_db)):
    all_entries = crud.get_ledger_entries(db)
    supplier_map = {}
    
    for entry in all_entries:
        if entry.activity_type == 'MATERIAL_REQUIREMENT' and entry.status == 'PENDING':
            fg_key = crud.clean_key_exact(entry.fg_key)
            if not fg_key:
                continue
            supplier = entry.extra_data.get('supplier', '') if entry.extra_data else ''
            if not supplier:
                continue
            
            requirement_key = entry.extra_data.get('requirementKey', '') if entry.extra_data else ''
            if not requirement_key:
                requirement_key = crud.get_requirement_key(fg_key, entry.size, entry.color, 
                                                          entry.extra_data.get('itemSize', '') if entry.extra_data else '')
            
            ordered_entries = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                              and e.extra_data and e.extra_data.get('requirementKey') == requirement_key]
            total_ordered = sum(e.qty or 0 for e in ordered_entries)
            required_qty = entry.qty or 0
            balance_to_order = required_qty - total_ordered
            
            if balance_to_order > settings.tolerance:
                if supplier not in supplier_map:
                    supplier_map[supplier] = {
                        'supplier': supplier,
                        'fgKeys': [],
                        'items': [],
                        'totalQuantity': 0,
                        'buyerOrderNo': entry.buyer_order_no or '',
                        'orderDate': entry.order_date
                    }
                
                if fg_key not in supplier_map[supplier]['fgKeys']:
                    supplier_map[supplier]['fgKeys'].append(fg_key)
                
                supplier_map[supplier]['items'].append({
                    'fgKey': entry.fg_key,
                    'itemNo': entry.extra_data.get('itemNo', '') if entry.extra_data else '',
                    'itemName': entry.extra_data.get('itemName', '') if entry.extra_data else '',
                    'itemColor': entry.color or '',
                    'garmentSize': entry.size or '',
                    'itemSize': entry.extra_data.get('itemSize', '') if entry.extra_data else '',
                    'consumption': entry.extra_data.get('consumption', 0) if entry.extra_data else 0,
                    'requiredQty': required_qty,
                    'balanceToOrder': balance_to_order,
                    'uom': entry.extra_data.get('uom', 'PCS') if entry.extra_data else 'PCS',
                    'rate': entry.extra_data.get('rate', 0) if entry.extra_data else 0,
                    'cgst': entry.extra_data.get('cgst', 0) if entry.extra_data else 0,
                    'igst': entry.extra_data.get('igst', 0) if entry.extra_data else 0,
                    'hsn': entry.extra_data.get('hsn', '') if entry.extra_data else '',
                    'leadtime': entry.extra_data.get('leadtime', 0) if entry.extra_data else 0,
                    'supplier': entry.extra_data.get('supplier', '') if entry.extra_data else '',
                    'status': entry.status,
                    'isSizeSensitive': entry.extra_data.get('isSizeSensitive', False) if entry.extra_data else False,
                    'requirementKey': requirement_key,
                    'buyerOrderNo': entry.buyer_order_no or '',
                    'orderDate': entry.order_date,
                    'size': entry.size or '',
                    'color': entry.color or ''
                })
                
                supplier_map[supplier]['totalQuantity'] += balance_to_order
    
    return list(supplier_map.values())

@router.post("/generate-po")
def generate_po_for_supplier(data: Dict, db: Session = Depends(get_db)):
    try:
        supplier = crud.clean_key_exact(data.get('supplier', ''))
        selected_items = data.get('selected_items', [])
        cgst_override = data.get('cgst_override', {})
        igst_override = data.get('igst_override', {})
        allow_extra = data.get('allow_extra', False)
        supplier_alias = data.get('supplier_alias', supplier)
        excess_percentage = data.get('excess_percentage', 0)
        
        if not supplier:
            raise ValueError('Supplier is required')
        if not selected_items:
            raise ValueError('No items selected for PO')
        
        all_entries = crud.get_ledger_entries(db)
        
        # Validate balances
        for item in selected_items:
            requirement_key = item.get('requirementKey')
            req_entry = next((e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                             and e.extra_data and e.extra_data.get('requirementKey') == requirement_key), None)
            if not req_entry:
                continue
            
            ordered_entries = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                              and e.extra_data and e.extra_data.get('requirementKey') == requirement_key]
            total_ordered = sum(e.qty or 0 for e in ordered_entries)
            required_qty = req_entry.qty or 0
            balance_to_order = required_qty - total_ordered
            order_qty = item.get('orderedQty', item.get('balanceToOrder', item.get('requiredQty', 0)))
            
            if order_qty > balance_to_order + settings.tolerance and not allow_extra:
                raise ValueError(f"Cannot order {order_qty} for {item.get('itemName')} (Balance: {balance_to_order})")
        
        po_token = crud.generate_po_token()
        po_date = datetime.utcnow()
        supplier_details = crud.get_rmsupplier_details(db, supplier)
        if not supplier_details:
            raise ValueError('Supplier details not found')
        
        total_amount = 0
        total_cgst = 0
        total_igst = 0
        fg_keys = set()
        
        aggregated_items = {}
        
        # FIX: Properly indented loop
        for item in selected_items:
            fg_key = item.get('fgKey')
            fg_keys.add(fg_key)
            
            hsn = item.get('hsn', '')
            cgst = float(cgst_override.get(item.get('requirementKey'), item.get('cgst', 0)))
            igst = float(igst_override.get(item.get('requirementKey'), item.get('igst', 0)))
            quantity = float(item.get('balanceToOrder', item.get('requiredQty', 0)))
            rate = float(item.get('rate', 0))
            
            # Limit excess to 5%
            if excess_percentage > 5:
                raise ValueError(f"Excess percentage cannot exceed 5%. Current: {excess_percentage}%")
            if excess_percentage > 0:
                quantity = quantity * (1 + (excess_percentage / 100))
                quantity = round(quantity * 100) / 100
            
            amount = quantity * rate
            cgst_amount = amount * (cgst / 100)
            igst_amount = amount * (igst / 100)
            
            agg_key = f"{item.get('itemName')}|{item.get('garmentSize', 'ALL')}|{item.get('color', '')}|{item.get('itemSize', '')}"
            
            if agg_key not in aggregated_items:
                aggregated_items[agg_key] = {
                    'itemNo': item.get('itemNo'),
                    'itemName': item.get('itemName'),
                    'garmentSize': item.get('garmentSize', 'ALL'),
                    'color': item.get('color', ''),
                    'itemSize': item.get('itemSize', ''),
                    'totalQuantity': 0,
                    'uom': item.get('uom', 'PCS'),
                    'rate': rate,
                    'cgst': cgst,
                    'igst': igst,
                    'hsn': hsn,
                    'supplierAlias': supplier_alias,
                    'amount': 0
                }
            
            aggregated_items[agg_key]['totalQuantity'] += quantity
            aggregated_items[agg_key]['amount'] += amount
            
            total_amount += amount
            total_cgst += cgst_amount
            total_igst += igst_amount
        
        display_items = list(aggregated_items.values())
        grand_total = total_amount + total_cgst + total_igst
        
        entries_to_insert = []
        snapshot_updates = []
        
        # FIX: Properly indented loop for creating RM_ORDER entries
        for item in selected_items:
            fg_key = item.get('fgKey')
            hsn = item.get('hsn', '')
            cgst = float(cgst_override.get(item.get('requirementKey'), item.get('cgst', 0)))
            igst = float(igst_override.get(item.get('requirementKey'), item.get('igst', 0)))
            quantity = float(item.get('balanceToOrder', item.get('requiredQty', 0)))
            rate = float(item.get('rate', 0))
            
            # Limit excess to 5%
            if excess_percentage > 5:
                raise ValueError(f"Excess percentage cannot exceed 5%. Current: {excess_percentage}%")
            if excess_percentage > 0:
                quantity = quantity * (1 + (excess_percentage / 100))
                quantity = round(quantity * 100) / 100
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'RM_ORDER',
                'status': 'DRAFT',
                'buyer_name': 'Unknown',
                'buyer_order_no': item.get('buyerOrderNo', ''),
                'order_date': item.get('orderDate'),
                'created_date': datetime.utcnow(),
                'qty': quantity,
                'size': item.get('garmentSize', item.get('size', '')),
                'color': item.get('color', ''),
                'workflow_position': 2,
                'extra_data': {
                    'poToken': po_token,
                    'supplier': supplier,
                    'supplierAlias': supplier_alias,
                    'supplierDetails': {
                        'id': supplier_details.id,
                        'category': supplier_details.category,
                        'name': supplier_details.name,
                        'gstNo': supplier_details.gst_no,
                        'address': supplier_details.address,
                        'contactPerson': supplier_details.contact_person,
                        'contactNo': supplier_details.contact_no,
                        'paymentTerm': supplier_details.payment_term
                    },
                    'itemNo': item.get('itemNo'),
                    'itemName': item.get('itemName'),
                    'hsn': hsn,
                    'reqQty': float(item.get('requiredQty', 0)),
                    'balanceToOrder': float(item.get('balanceToOrder', 0)),
                    'orderedQty': quantity,
                    'uom': item.get('uom', 'PCS'),
                    'rate': rate,
                    'cgst': cgst,
                    'igst': igst,
                    'garmentSize': item.get('garmentSize', 'ALL'),
                    'itemSize': item.get('itemSize', ''),
                    'color': item.get('color', ''),
                    'requirementKey': item.get('requirementKey'),
                    'originalFGKey': fg_key,
                    'excessPercentage': excess_percentage,
                    'allowExtra': allow_extra,
                    'status': 'DRAFT',
                    'displayGroup': f"{item.get('itemName')}|{item.get('garmentSize')}|{item.get('color')}",
                    'consumption': item.get('consumption', 0),
                    'leadtime': item.get('leadtime', 0)
                }
            })
            
            req_entries = [e for e in all_entries if e.activity_type == 'MATERIAL_REQUIREMENT' 
                          and e.status == 'PENDING'
                          and e.extra_data and e.extra_data.get('requirementKey') == item.get('requirementKey')]
            
            for req in req_entries:
                entries_to_insert.append({
                    'fg_key': req.fg_key,
                    'activity_type': 'MATERIAL_REQUIREMENT',
                    'status': 'ORDERED',
                    'buyer_name': req.buyer_name,
                    'buyer_order_no': req.buyer_order_no,
                    'order_date': req.order_date,
                    'created_date': req.created_date,
                    'qty': req.qty,
                    'size': req.size,
                    'color': req.color,
                    'workflow_position': 1.5,
                    'extra_data': {**(req.extra_data or {}), 'poToken': po_token, 'orderedAt': datetime.utcnow().isoformat()}
                })
                
                snapshot_updates.append({
                    'requirementKey': req.extra_data.get('requirementKey') if req.extra_data else None,
                    'fgKey': req.fg_key,
                    'itemNo': req.extra_data.get('itemNo') if req.extra_data else None,
                    'itemName': req.extra_data.get('itemName') if req.extra_data else None,
                    'size': req.size,
                    'color': req.color,
                    'supplier': req.extra_data.get('supplier') if req.extra_data else None,
                    'requiredDelta': 0,
                    'grnDelta': 0,
                    'issueDelta': 0
                })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        crud.update_inventory_snapshot(db, snapshot_updates)
        
        # Generate PO HTML
        po_html = generate_po_html(po_token, supplier_alias, supplier_details, display_items, grand_total, total_cgst, total_igst, po_date)
        
        return {
            'success': True,
            'poToken': po_token,
            'poHTML': po_html,
            'message': 'PO generated successfully',
            'itemCount': len(display_items),
            'fgCount': len(fg_keys),
            'aggregatedItems': display_items
        }
    except Exception as e:
        return {'success': False, 'message': str(e)}

def generate_po_html(po_token, supplier_alias, supplier_details, items, grand_total, total_cgst, total_igst, po_date):
    company = {
        'name': settings.company_name,
        'address': settings.company_address,
        'gst': settings.company_gst,
        'state': settings.company_state
    }
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>Purchase Order - {po_token}</title>
    <style>
      * {{ margin:0; padding:0; box-sizing:border-box; }}
      body {{ font-family:'Segoe UI',Arial,sans-serif; margin:20px; background:#f8f9fa; }}
      .container {{ max-width:1100px; margin:0 auto; background:white; padding:30px; border-radius:12px; }}
      .header {{ text-align:center; border-bottom:3px solid #2a6df4; padding-bottom:20px; margin-bottom:20px; }}
      .company-name {{ font-size:24px; font-weight:700; color:#1a3a6a; }}
      .po-title {{ text-align:center; font-size:20px; font-weight:700; color:#1a3a6a; margin:15px 0; }}
      table {{ width:100%; border-collapse:collapse; margin:15px 0; font-size:11px; }}
      table th {{ background:#1a3a6a; color:white; padding:8px; text-align:left; }}
      table td {{ padding:6px; border-bottom:1px solid #e9edf4; }}
      .totals {{ text-align:right; margin-top:15px; }}
      .grand-total {{ font-size:18px; font-weight:700; color:#1a3a6a; }}
    </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <div class="company-name">{company['name']}</div>
          <div style="font-size:12px;color:#555;">{company['address']}</div>
          <div style="font-size:12px;color:#555;">GST: {company['gst']} | State: {company['state']}</div>
        </div>
        <div class="po-title">PURCHASE ORDER</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;background:#f0f4fe;padding:12px;border-radius:8px;margin:10px 0;">
          <span><strong>PO Number:</strong> {po_token}</span>
          <span><strong>Date:</strong> {po_date.strftime('%d-%m-%Y')}</span>
          <span><strong>Supplier:</strong> {supplier_alias}</span>
        </div>
        <div style="background:#f8faff;padding:12px;border-radius:8px;margin:10px 0;">
          <strong>Supplier Details</strong>
          <div>{supplier_alias}</div>
          <div>{supplier_details.address or 'Address not available'}</div>
          <div>GST: {supplier_details.gst_no or 'N/A'}</div>
        </div>
        <table>
          <thead><tr><th>#</th><th>Item</th><th>Size</th><th>Color</th><th>HSN</th><th>Quantity</th><th>UOM</th><th>Rate</th><th>Amount</th></tr></thead>
          <tbody>"""
    
    for idx, item in enumerate(items, 1):
        html += f"<tr><td>{idx}</td><td>{item.get('itemName', '')}</td><td>{item.get('garmentSize', 'ALL')}</td>"
        html += f"<td>{item.get('color', '-')}</td><td>{item.get('hsn', '-')}</td>"
        html += f"<td>{item.get('totalQuantity', 0):.2f}</td><td>{item.get('uom', 'PCS')}</td>"
        html += f"<td>₹{item.get('rate', 0):.2f}</td><td>₹{item.get('amount', 0):.2f}</td></tr>"
    
    subtotal = grand_total - total_cgst - total_igst
    html += f"""
          </tbody></table>
        <div class="totals">
          <div><strong>Subtotal:</strong> ₹{subtotal:.2f}</div>
          <div><strong>CGST:</strong> ₹{total_cgst:.2f}</div>
          <div><strong>IGST:</strong> ₹{total_igst:.2f}</div>
          <div class="grand-total"><strong>Grand Total:</strong> ₹{grand_total:.2f}</div>
        </div>
        <div style="margin-top:20px;padding-top:20px;border-top:2px solid #e9edf4;text-align:center;font-size:12px;color:#666;">
          <p>This is a computer generated Purchase Order. No signature required.</p>
          <p><strong>For {company['name']}</strong></p>
        </div>
      </div>
    </body>
    </html>
    """
    return html

@router.post("/process")
def process_po(data: Dict, db: Session = Depends(get_db)):
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        all_entries = crud.get_ledger_entries(db)
        
        draft_entries = [e for e in all_entries if e.activity_type == 'RM_ORDER' 
                        and e.extra_data and e.extra_data.get('poToken') == po_token 
                        and e.status == 'DRAFT']
        
        if not draft_entries:
            raise ValueError('PO Token not found: ' + po_token)
        
        fg_keys = set()
        entries_to_insert = []
        
        for entry in draft_entries:
            fg_key = entry.fg_key
            if fg_key:
                fg_keys.add(fg_key)
            
            extra_data_copy = dict(entry.extra_data or {})
            extra_data_copy['status'] = 'PROCESSED'
            extra_data_copy['processedAt'] = datetime.utcnow().isoformat()
            
            entries_to_insert.append({
                'fg_key': fg_key,
                'activity_type': 'RM_ORDER',
                'status': 'PROCESSED',
                'buyer_name': entry.buyer_name,
                'buyer_order_no': entry.buyer_order_no,
                'order_date': entry.order_date,
                'created_date': entry.created_date,
                'qty': entry.qty,
                'size': entry.size,
                'color': entry.color,
                'workflow_position': 2,
                'extra_data': extra_data_copy
            })
        
        crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {'success': True, 'message': 'PO processed successfully', 'fgKeys': list(fg_keys)}
    except Exception as e:
        return {'success': False, 'message': str(e)}

@router.post("/save")
def save_po(data: Dict, db: Session = Depends(get_db)):
    try:
        po_token = crud.clean_key_exact(data.get('po_token', ''))
        all_entries = crud.get_ledger_entries(db)
        entries_to_insert = []
        updated = 0
        
        for entry in all_entries:
            if entry.activity_type == 'RM_ORDER' and entry.extra_data and entry.extra_data.get('poToken') == po_token and entry.status == 'DRAFT':
                extra_data_copy = dict(entry.extra_data or {})
                extra_data_copy['status'] = 'SAVED'
                
                entries_to_insert.append({
                    'fg_key': entry.fg_key,
                    'activity_type': 'RM_ORDER',
                    'status': 'SAVED',
                    'buyer_name': entry.buyer_name,
                    'buyer_order_no': entry.buyer_order_no,
                    'order_date': entry.order_date,
                    'created_date': entry.created_date,
                    'qty': entry.qty,
                    'size': entry.size,
                    'color': entry.color,
                    'workflow_position': 2,
                    'extra_data': extra_data_copy
                })
                updated += 1
        
        if entries_to_insert:
            crud.add_ledger_entries_bulk(db, entries_to_insert)
        
        return {'success': True, 'message': 'PO saved successfully', 'updated': updated}
    except Exception as e:
        return {'success': False, 'message': str(e)}
