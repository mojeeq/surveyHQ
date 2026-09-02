"""Ad-hoc analysis: aggregate queries, frequencies, crosstabs and exports."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from app.api.deps import (
    CurrentUser,
    DbSession,
    RequireAnalyst,
    get_dataset,
    get_ready_dataset,
)
from app.models import Dataset, SavedQuery, User
from app.schemas.analytics import (
    QueryRequest,
    SavedQueryCreate,
    SavedQueryOut,
)
from app.schemas.common import Message
from app.schemas.query import (
    CrosstabRequest,
    CrosstabResult,
    FilterGroup,
    FrequencyResult,
    QueryResult,
    SummaryStats,
)
from app.services.exporters import (
    crosstab_to_csv,
    query_result_to_csv,
    query_result_to_xlsx,
)
from app.services.projects import dataset_clause, restrict
from app.services.query_engine import (
    DatasetContext,
    QueryError,
    execute_crosstab,
    execute_frequency,
    execute_query,
    execute_summary,
)

router = APIRouter()


def _context(dataset_id: str, db: DbSession, user: User) -> tuple[Dataset, DatasetContext]:
    dataset = get_ready_dataset(dataset_id, db, user)
    return dataset, DatasetContext.from_model(dataset)


@router.post("/query", response_model=QueryResult)
def run_query(payload: QueryRequest, db: DbSession, user: CurrentUser) -> QueryResult:
    """Run an aggregate query - the engine behind every chart and table."""
    _, ctx = _context(payload.dataset_id, db, user)
    try:
        return execute_query(ctx, payload.spec)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/query/export")
def export_query(
    payload: QueryRequest,
    db: DbSession,
    user: CurrentUser,
    format: str = Query(default="csv", pattern="^(csv|xlsx)$"),
) -> Response:
    dataset, ctx = _context(payload.dataset_id, db, user)
    spec = payload.spec.model_copy(update={"limit": min(payload.spec.limit, 100_000)})
    try:
        result = execute_query(ctx, spec)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stem = dataset.slug or "results"
    if format == "xlsx":
        content = query_result_to_xlsx(result, dataset.name[:31])
        media_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"{stem}.xlsx"
    else:
        content = query_result_to_csv(result)
        media_type = "text/csv"
        filename = f"{stem}.csv"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/datasets/{dataset_id}/frequency/{variable}", response_model=FrequencyResult)
def frequency(
    dataset_id: str,
    variable: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=200, le=1000),
    use_labels: bool = True,
) -> FrequencyResult:
    """One-way frequency table with valid and cumulative percentages."""
    _, ctx = _context(dataset_id, db, user)
    try:
        return execute_frequency(ctx, variable, FilterGroup(), limit, use_labels)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/datasets/{dataset_id}/frequency/{variable}", response_model=FrequencyResult)
def frequency_filtered(
    dataset_id: str,
    variable: str,
    filters: FilterGroup,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=200, le=1000),
    use_labels: bool = True,
) -> FrequencyResult:
    _, ctx = _context(dataset_id, db, user)
    try:
        return execute_frequency(ctx, variable, filters, limit, use_labels)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/datasets/{dataset_id}/crosstab", response_model=CrosstabResult)
def crosstab(
    dataset_id: str, payload: CrosstabRequest, db: DbSession, user: CurrentUser
) -> CrosstabResult:
    """Two-way tabulation with row/column/total percentages and chi-square."""
    _, ctx = _context(dataset_id, db, user)
    try:
        return execute_crosstab(ctx, payload)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/datasets/{dataset_id}/crosstab/export")
def export_crosstab(
    dataset_id: str, payload: CrosstabRequest, db: DbSession, user: CurrentUser
) -> Response:
    dataset, ctx = _context(dataset_id, db, user)
    try:
        result = execute_crosstab(ctx, payload)
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=crosstab_to_csv(result),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{dataset.slug}-crosstab.csv"'
            )
        },
    )


@router.post("/datasets/{dataset_id}/summary", response_model=list[SummaryStats])
def summary(
    dataset_id: str,
    variables: list[str],
    db: DbSession,
    user: CurrentUser,
) -> list[SummaryStats]:
    """Descriptive statistics for one or more numeric variables."""
    if not variables:
        raise HTTPException(status_code=400, detail="Provide at least one variable")
    if len(variables) > 50:
        raise HTTPException(status_code=400, detail="At most 50 variables per request")
    _, ctx = _context(dataset_id, db, user)
    try:
        return execute_summary(ctx, variables, FilterGroup())
    except QueryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- saved queries ---------------------------------------------------------


@router.get("/saved-queries", response_model=list[SavedQueryOut])
def list_saved_queries(
    db: DbSession, user: CurrentUser, dataset_id: str = ""
) -> list[SavedQuery]:
    statement = restrict(
        select(SavedQuery).order_by(SavedQuery.created_at.desc()),
        dataset_clause(db, user, SavedQuery.dataset_id),
    )
    if dataset_id:
        statement = statement.where(SavedQuery.dataset_id == dataset_id)
    return list(db.scalars(statement).all())


@router.post("/saved-queries", response_model=SavedQueryOut, status_code=201)
def create_saved_query(
    payload: SavedQueryCreate, db: DbSession, user: RequireAnalyst
) -> SavedQuery:
    get_ready_dataset(payload.dataset_id, db, user)
    saved = SavedQuery(
        name=payload.name,
        description=payload.description,
        dataset_id=payload.dataset_id,
        spec=payload.spec.model_dump(mode="json"),
        created_by=user.id,
    )
    db.add(saved)
    db.commit()
    db.refresh(saved)
    return saved


@router.delete("/saved-queries/{query_id}", response_model=Message)
def delete_saved_query(query_id: str, db: DbSession, user: RequireAnalyst) -> Message:
    saved = db.get(SavedQuery, query_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="Saved query not found")
    # It follows its dataset's project, like a chart does.
    get_dataset(saved.dataset_id, db, user)
    db.delete(saved)
    db.commit()
    return Message(detail="Saved query deleted")


@router.post("/datasets/{dataset_id}/suggest", response_model=list[dict])
def suggest_analyses(dataset_id: str, db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    """Propose useful starting charts based on the dataset's variables."""
    dataset = get_ready_dataset(dataset_id, db, user)
    suggestions: list[dict[str, Any]] = []
    fields = (dataset.meta or {}).get("monitoring_fields", {})

    if fields.get("date"):
        suggestions.append(
            {
                "title": "Submissions over time",
                "chart_type": "line",
                "spec": {
                    "dimensions": [{"variable": fields["date"], "grain": "day"}],
                    "measures": [{"agg": "count", "alias": "interviews"}],
                    "sort": [{"field": fields["date"], "direction": "asc"}],
                },
            }
        )
    if fields.get("status"):
        suggestions.append(
            {
                "title": "Interviews by status",
                "chart_type": "donut",
                "spec": {
                    "dimensions": [{"variable": fields["status"]}],
                    "measures": [{"agg": "count", "alias": "interviews"}],
                },
            }
        )
    if fields.get("interviewer"):
        suggestions.append(
            {
                "title": "Interviews per interviewer",
                "chart_type": "horizontal_bar",
                "spec": {
                    "dimensions": [{"variable": fields["interviewer"], "limit": 20}],
                    "measures": [{"agg": "count", "alias": "interviews"}],
                    "sort": [{"field": "interviews", "direction": "desc"}],
                },
            }
        )

    categoricals = [
        v for v in dataset.variables if v.var_type.value == "categorical" and v.n_unique > 1
    ][:4]
    for variable in categoricals:
        suggestions.append(
            {
                "title": f"Distribution of {variable.label or variable.name}",
                "chart_type": "bar",
                "spec": {
                    "dimensions": [{"variable": variable.name, "limit": 15}],
                    "measures": [{"agg": "count", "alias": "count"}],
                    "sort": [{"field": "count", "direction": "desc"}],
                },
            }
        )
    return suggestions
