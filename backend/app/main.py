from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from .database import engine, Base
from .routers import (
    master_data, buyer_order, bom, rm_order, grn, issue_rm, reports, utils
)
from .config import settings
import os

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sneha Creations ERP", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(master_data.router)
app.include_router(buyer_order.router)
app.include_router(bom.router)
app.include_router(rm_order.router)
app.include_router(grn.router)
app.include_router(issue_rm.router)
app.include_router(reports.router)
app.include_router(utils.router)

# Serve static files - fixed path
frontend_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")
    
    @app.get("/")
    def serve_index():
        return FileResponse(os.path.join(frontend_path, "index.html"))
else:
    @app.get("/")
    def serve_index():
        return {"message": "Frontend not found. Please check the frontend directory."}
