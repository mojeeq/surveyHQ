"""SQLAlchemy models. Importing this package registers every table."""

from app.db.base import Base
from app.models.analytics import (
    Chart,
    ChartType,
    Dashboard,
    SavedQuery,
    Widget,
    WidgetType,
)
from app.models.connection import (
    Connection,
    ExportFormat,
    SyncRun,
    SyncStatus,
)
from app.models.dataset import (
    Dataset,
    DatasetSource,
    DatasetStatus,
    Variable,
    VariableType,
)
from app.models.monitoring import (
    Alert,
    AlertRule,
    AlertStatus,
    CheckType,
    Direction,
    Indicator,
    IndicatorSnapshot,
    QualityResult,
    QualityRule,
    Severity,
)
from app.models.system import (
    AuditLog,
    Job,
    JobStatus,
    JobType,
    Notification,
    SystemSetting,
)
from app.models.user import ROLE_RANK, ApiKey, Role, User

__all__ = [
    "Base",
    "User",
    "Role",
    "ROLE_RANK",
    "ApiKey",
    "Dataset",
    "DatasetSource",
    "DatasetStatus",
    "Variable",
    "VariableType",
    "Connection",
    "ExportFormat",
    "SyncRun",
    "SyncStatus",
    "SavedQuery",
    "Chart",
    "ChartType",
    "Dashboard",
    "Widget",
    "WidgetType",
    "Indicator",
    "IndicatorSnapshot",
    "AlertRule",
    "Alert",
    "AlertStatus",
    "Severity",
    "Direction",
    "QualityRule",
    "QualityResult",
    "CheckType",
    "Job",
    "JobStatus",
    "JobType",
    "Notification",
    "AuditLog",
    "SystemSetting",
]
