"""Who can see which project, and what they may do inside it.

Every listing endpoint asks the same two questions - which rows may this user
see, and may they change this one - so both live here rather than being
re-derived, slightly differently, in each endpoint.

The rules, in full:

* An administrator sees everything. Administration is global; there is no such
  thing as an administrator of one project.
* A resource with no project is in the shared area, visible to every user
  except one flagged restricted_to_projects. Everything predating projects has
  no project, so an upgraded deployment behaves exactly as it did.
* Any other resource is visible only to members of its project.
* A member's project role grants access inside that project but is capped by
  their own role, so adding a viewer to a project as manager does not make them
  an editor. The cap is the point: project membership widens what you can
  reach, never what you are allowed to do.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from app.models import ROLE_RANK, Project, ProjectMember, Role, User


@dataclass(frozen=True)
class ProjectScope:
    """What one user is allowed to reach, resolved once per request."""

    unrestricted: bool = False
    project_ids: frozenset[str] = field(default_factory=frozenset)
    shared: bool = True

    def allows(self, project_id: str | None) -> bool:
        if self.unrestricted:
            return True
        if project_id is None:
            return self.shared
        return project_id in self.project_ids

    def filter(self, column: ColumnElement) -> ColumnElement | None:
        """A WHERE clause restricting `column` (a project_id) to this scope.

        None means "no restriction", which is not the same as an always-true
        clause: it lets callers skip the term entirely.
        """
        if self.unrestricted:
            return None
        allowed = column.in_(self.project_ids) if self.project_ids else None
        if not self.shared:
            # in_(()) is a valid always-false clause, which is what a
            # restricted user with no memberships should get: nothing.
            return allowed if allowed is not None else column.in_([])
        if allowed is None:
            return column.is_(None)
        return column.is_(None) | allowed


def memberships(db: Session, user: User) -> dict[str, Role]:
    rows = db.execute(
        select(ProjectMember.project_id, ProjectMember.role).where(
            ProjectMember.user_id == user.id
        )
    ).all()
    return dict(rows)  # (project_id, role) pairs


def scope_for(db: Session, user: User) -> ProjectScope:
    if user.role is Role.admin:
        return ProjectScope(unrestricted=True)
    return ProjectScope(
        project_ids=frozenset(memberships(db, user)),
        shared=not user.restricted_to_projects,
    )


def effective_role(db: Session, user: User, project_id: str | None) -> Role | None:
    """The role this user holds over a resource in `project_id`.

    None means no access at all, which callers should turn into a 404 rather
    than a 403: telling someone a project exists but is not theirs leaks the
    project list.
    """
    if user.role is Role.admin:
        return Role.admin
    if project_id is None:
        return user.role if not user.restricted_to_projects else None
    membership = memberships(db, user).get(project_id)
    if membership is None:
        return None
    # The lower of the two: membership can never exceed the user's own role.
    return min(user.role, membership, key=lambda role: ROLE_RANK[role])


def can_view(db: Session, user: User, project_id: str | None) -> bool:
    return effective_role(db, user, project_id) is not None


def can_edit(db: Session, user: User, project_id: str | None, minimum: Role) -> bool:
    role = effective_role(db, user, project_id)
    return role is not None and ROLE_RANK[role] >= ROLE_RANK[minimum]


def visible_projects(db: Session, user: User) -> list[Project]:
    scope = scope_for(db, user)
    statement = select(Project).order_by(Project.name)
    if not scope.unrestricted:
        statement = statement.where(Project.id.in_(scope.project_ids))
    return list(db.scalars(statement))


def dataset_clause(db: Session, user: User, column: ColumnElement) -> ColumnElement | None:
    """Restrict a dataset_id column to datasets this user can reach.

    Indicators, charts, quality rules and alert rules all hang off a dataset, so
    their visibility follows the dataset's project rather than being recorded
    again on each of them.
    """
    from app.models import Dataset

    inner = scope_for(db, user).filter(Dataset.project_id)
    if inner is None:
        return None
    return column.in_(select(Dataset.id).where(inner))


def alert_rule_clause(db: Session, user: User) -> ColumnElement | None:
    """An alert rule is reachable through its dataset, its indicator, or neither.

    A rule tied to nothing in particular is a global one and belongs to the
    shared area, so it follows the same rule as an unassigned dataset.
    """
    from app.models import AlertRule, Indicator

    scope = scope_for(db, user)
    if scope.unrestricted:
        return None
    by_dataset = dataset_clause(db, user, AlertRule.dataset_id)
    by_indicator = AlertRule.indicator_id.in_(
        select(Indicator.id).where(dataset_clause(db, user, Indicator.dataset_id))
    )
    clause = by_dataset | by_indicator
    if scope.shared:
        clause = clause | (
            AlertRule.dataset_id.is_(None) & AlertRule.indicator_id.is_(None)
        )
    return clause


def restrict(statement, clause: ColumnElement | None):
    """Apply a clause only when there is one; None means no restriction."""
    return statement if clause is None else statement.where(clause)
