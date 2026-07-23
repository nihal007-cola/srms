from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from datetime import datetime
from .. import crud, schemas
from ..database import get_db
from ..config import settings

router = APIRouter(prefix="/buyer-order", tags=["Buyer Order"])

@router.get("/fg-serial")
def generate_fg_serial(db: Session = Depends(get_db)):
    return crud.generate_fg_serial(db)

@router.post("/generate-grid")
def generate_order_grid(request: schemas.OrderGridRequest, db: Session = Depends(get_db)):
    try:
        fg_order_serial = crud.generate_fg_serial(db)
        default_sizes = settings.get_default_sizes_list()
        grid_data = []
        for i in range(request.no_of_fg):
            row = [fg_order_serial, '', ''] + [0] * len(default_sizes)
            grid_data.append(row)
        return {
            "success": True,
            "fg_order_serial": fg_order_serial,
            "grid_data": grid_data,
            "total_rows": len(grid_data)
        }
    except Exception as e:
        return {"success": False, "message": str(e)}

@router.post("/save")
def save_order(request: schemas.SaveOrderRequest, db: Session = Depends(get_db)):
    try:
        fg_order_serial = request.fg_order_serial
        grid_data = request.grid_data
        
        if not fg_order_serial or not grid_data:
            raise ValueError("Invalid data provided")
        
        for i, row in enumerate(grid_data):
            if not row[1] or not row[1].strip():
                raise ValueError(f"Row {i+1}: FG Design No is required")
            if not row[2] or not row[2].strip():
                raise ValueError(f"Row {i+1}: FG Color No is required")
        
        default_sizes = settings.get_default_sizes_list()
        first_row = grid_data[0]
        size_count = len(default_sizes)
        buyer_name_index = 3 + size_count
        buyer_order_no_index = buyer_name_index + 1
        order_date_index = buyer_order_no_index + 1
        created_date_index = order_date_index + 1
        
        buyer_name = first_row[buyer_name_index] if len(first_row) > buyer_name_index else 'Unknown'
        buyer_order_no = first_row[buyer_order_no_index] if len(first_row) > buyer_order_no_index else 'N/A'
        order_date = first_row[order_date_index] if len(first_row) > order_date_index else datetime.utcnow()
        created_date = first_row[created_date_index] if len(first_row) > created_date_index else datetime.utcnow()
        
        entries = []
        for row in grid_data:
            fg_key = f"{fg_order_serial}|{row[1]}|{row[2]}"
            
            entries.append({
                'fg_key': fg_key,
                'activity_type': 'BUYER_ORDER',
                'status': 'COMPLETED',
                'buyer_name': buyer_name,
                'buyer_order_no': buyer_order_no,
                'order_date': order_date,
                'created_date': created_date,
                'workflow_position': 0,
                'extra_data': {
                    'gridRow': row,
                    'sizes': default_sizes,
                    'fgDesign': row[1] or '',
                    'fgColor': row[2] or ''
                }
            })
        
        crud.add_ledger_entries_bulk(db, entries)
        return {"success": True, "message": f"Order {fg_order_serial} saved"}
    except Exception as e:
        return {"success": False, "message": str(e)}
