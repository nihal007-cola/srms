from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from .database import engine, Base
from .routers import (
    master_data, buyer_order, bom, rm_order, grn, issue_rm, reports, utils
)
from . import auth
from .config import settings
import os
import jwt

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Sneha Creations ERP", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(master_data.router)
app.include_router(buyer_order.router)
app.include_router(bom.router)
app.include_router(rm_order.router)
app.include_router(grn.router)
app.include_router(issue_rm.router)
app.include_router(reports.router)
app.include_router(utils.router)

FRONTEND_DIR = "/home/ubuntu/srms/frontend"
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key-change-in-production")

@app.get("/")
async def root():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

@app.get("/login")
async def login():
    return FileResponse(os.path.join(FRONTEND_DIR, "login.html"))

@app.get("/static/index.html")
async def serve_index(request: Request):
    # Get token from query parameter
    token = request.query_params.get("token")
    
    # If no token, check Authorization header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    # If still no token, redirect to login
    if not token:
        return RedirectResponse(url="/login", status_code=302)
    
    # Verify the token
    try:
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception as e:
        print(f"Token validation error: {e}")
        return RedirectResponse(url="/login", status_code=302)
    
    # Token is valid, serve the file
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/static/js/{filename}")
async def serve_js(filename: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "js", filename))

@app.get("/static/css/{filename}")
async def serve_css(filename: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "css", filename))

@app.get("/static/assets/{path:path}")
async def serve_assets(path: str):
    return FileResponse(os.path.join(FRONTEND_DIR, "assets", path))
