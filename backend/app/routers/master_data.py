from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Dict, Any
from .. import crud, schemas
from ..database import get_db

router = APIRouter(prefix="/master", tags=["Master Data"])

@router.get("/buyers", response_model=List[str])
def get_buyers(db: Session = Depends(get_db)):
    return crud.get_buyers(db)

@router.get("/buyers/{name}")
def get_buyer_details(name: str, db: Session = Depends(get_db)):
    buyer = crud.get_buyer_details(db, name)
    if not buyer:
        raise HTTPException(status_code=404, detail="Buyer not found")
    return {
        "id": buyer.id,
        "name": buyer.name,
        "gst_no": buyer.gst_no,
        "address": buyer.address,
        "contact_person": buyer.contact_person,
        "contact_no": buyer.contact_no,
        "payment_term": buyer.payment_term
    }

@router.get("/suppliers", response_model=List[str])
def get_rmsuppliers(db: Session = Depends(get_db)):
    return crud.get_rmsuppliers(db)

@router.get("/suppliers/{name}")
def get_rmsupplier_details(name: str, db: Session = Depends(get_db)):
    supplier = crud.get_rmsupplier_details(db, name)
    if not supplier:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return {
        "id": supplier.id,
        "name": supplier.name,
        "gst_no": supplier.gst_no,
        "address": supplier.address,
        "contact_person": supplier.contact_person,
        "contact_no": supplier.contact_no,
        "payment_term": supplier.payment_term
    }

@router.post("/buyers")
def add_buyer(data: Dict, db: Session = Depends(get_db)):
    data['category'] = 'BUYER'
    result = crud.add_master_entity(db, data)
    return {"success": True, "message": "Buyer added successfully", "id": result.id, "name": result.name}

@router.post("/suppliers")
def add_supplier(data: Dict, db: Session = Depends(get_db)):
    data['category'] = 'SUPPLIER'
    result = crud.add_master_entity(db, data)
    return {"success": True, "message": "Supplier added successfully", "id": result.id, "name": result.name}
