"""Aggregates every v1 endpoint module."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    analytics,
    auth,
    connections,
    dashboards,
    datasets,
    monitoring,
    projects,
    public,
    relationships,
    system,
    users,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(projects.router, prefix="/projects", tags=["projects"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(
    relationships.router, prefix="/relationships", tags=["relationships"]
)
api_router.include_router(connections.router, prefix="/connections", tags=["connections"])
api_router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
api_router.include_router(dashboards.router, prefix="/dashboards", tags=["dashboards"])
api_router.include_router(monitoring.router, prefix="/monitoring", tags=["monitoring"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
api_router.include_router(public.router, prefix="/public", tags=["public"])
