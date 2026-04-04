"""app/routers/services.py — Service catalogue endpoints."""

from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.service import ServiceOut
from app.services.catalogue_service import CatalogueService

router = APIRouter(prefix="/api/v1/services", tags=["Services"])

@router.get("/", response_model=List[ServiceOut])
async def list_services(
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await CatalogueService.list_services(db, category, search)

@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    return await CatalogueService.list_categories(db)

@router.get("/grouped")
async def list_services_grouped(db: AsyncSession = Depends(get_db)):
    return await CatalogueService.list_services_grouped(db)

@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(service_id: str, db: AsyncSession = Depends(get_db)):
    return await CatalogueService.get_service(db, service_id)
