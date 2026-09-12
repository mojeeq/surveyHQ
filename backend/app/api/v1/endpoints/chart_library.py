"""Saved-chart library metadata for the Dashboards page."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Chart, Dataset, Project
from app.schemas.analytics import ChartLibraryOut, ChartOut
from app.services.projects import dataset_clause, in_project_clause, restrict

router = APIRouter()


@router.get("/chart-library", response_model=list[ChartLibraryOut])
def list_chart_library(
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = None,
) -> list[ChartLibraryOut]:
    """Return saved charts with their dataset and project names.

    A chart inherits its project from its dataset. Keeping that relationship on
    the server means the library never has to reconstruct ownership from a
    separately paginated dataset list, and the labels remain correct if a
    dataset is moved to another project.
    """
    statement = restrict(
        select(Chart).order_by(Chart.created_at.desc()),
        dataset_clause(db, user, Chart.dataset_id),
    )
    if project_id is not None:
        statement = statement.where(
            in_project_clause(Chart.dataset_id, "" if project_id == "none" else project_id)
        )

    charts = list(db.scalars(statement).all())
    if not charts:
        return []

    dataset_ids = {chart.dataset_id for chart in charts}
    datasets = {
        dataset.id: dataset
        for dataset in db.scalars(select(Dataset).where(Dataset.id.in_(dataset_ids))).all()
    }
    project_ids = {
        dataset.project_id
        for dataset in datasets.values()
        if dataset.project_id is not None
    }
    projects = (
        {
            project.id: project
            for project in db.scalars(select(Project).where(Project.id.in_(project_ids))).all()
        }
        if project_ids
        else {}
    )

    result: list[ChartLibraryOut] = []
    for chart in charts:
        dataset = datasets.get(chart.dataset_id)
        if dataset is None:
            continue
        project = projects.get(dataset.project_id) if dataset.project_id else None
        result.append(
            ChartLibraryOut(
                **ChartOut.model_validate(chart).model_dump(),
                dataset_name=dataset.name,
                project_id=dataset.project_id,
                project_name=project.name if project else None,
            )
        )
    return result
