"""app/services/catalogue_service.py — Service catalog logic."""

from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException
from app.models import Service

class CatalogueService:
    @staticmethod
    async def list_services(db: AsyncSession, category: Optional[str] = None, search: Optional[str] = None) -> List[Service]:
        q = select(Service).where(Service.is_active == True)
        if category:
            q = q.where(Service.category == category)
        if search:
            q = q.where(Service.name.ilike(f"%{search}%"))
        q = q.order_by(Service.category, Service.name)
        r = await db.execute(q)
        return list(r.scalars().all())

    @staticmethod
    async def list_categories(db: AsyncSession) -> List[str]:
        r = await db.execute(
            select(Service.category).distinct().where(Service.is_active == True)
        )
        return [row[0] for row in r.fetchall()]

    @staticmethod
    async def list_services_grouped(db: AsyncSession) -> Dict:
        r = await db.execute(
            select(Service).where(Service.is_active == True).order_by(Service.category, Service.group, Service.name)
        )
        services = r.scalars().all()

        grouped: dict = {}
        for s in services:
            if s.category not in grouped:
                grouped[s.category] = {}
            if s.group not in grouped[s.category]:
                grouped[s.category][s.group] = []
            grouped[s.category][s.group].append({
                "id": str(s.id), "name": s.name,
                "base_price": s.base_price,
                "duration_minutes": s.duration_minutes,
                "description": s.description,
            })
        return grouped

    @staticmethod
    async def get_service(db: AsyncSession, service_id: str) -> Service:
        s = await db.get(Service, service_id)
        if not s or not s.is_active:
            raise HTTPException(status_code=404, detail="Service not found")
        return s
