from fastapi import APIRouter
from .endpoints import pdfs

api_router = APIRouter()
api_router.include_router(pdfs.router, prefix="/pdfs", tags=["pdfs"])