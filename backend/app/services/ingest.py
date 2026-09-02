"""Reads survey data files into the platform's Parquet + metadata format.

Supported inputs: Stata (.dta), SPSS (.sav), CSV, tab-delimited (Survey
Solutions exports) and Excel. Variable labels and value labels are preserved
wherever the source format carries them, because a monitoring dashboard is far
more useful showing "Female" than "2".
"""

from __future__ import annotations

import datetime as dt
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.logging import get_logger

logger = get_logger(__name__)

# A variable with at most this many distinct values is treated as categorical
CATEGORICAL_MAX_UNIQUE = 50
CATEGORICAL_MAX_RATIO = 0.3

SUPPORTED_EXTENSIONS = {".dta", ".sav", ".csv", ".tab", ".txt", ".tsv", ".xlsx", ".xls"}


class IngestError(RuntimeError):
    pass


@dataclass
class VariableMeta:
    name: str
    label: str = ""
    var_type: str = "text"
    storage_type: str = ""
    position: int = 0
    n_missing: int = 0
    n_unique: int = 0
    min_value: float | None = None
    max_value: float | None = None
    mean_value: float | None = None
    value_labels: dict[str, str] = field(default_factory=dict)
    missing_tags: list[str] = field(default_factory=list)
    is_hidden: bool = False


@dataclass
class IngestResult:
    parquet_path: Path
    row_count: int
    column_count: int
    file_size: int
    variables: list[VariableMeta]
    warnings: list[str] = field(default_factory=list)


def _clean_column_name(name: Any, index: int) -> str:
    text = str(name).strip()
    if not text or text.lower() == "nan":
        text = f"column_{index + 1}"
    # Parquet and DuckDB cope with most characters, but newlines break tooling
    return re.sub(r"[\r\n\t]+", " ", text)[:300]


def _deduplicate(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for name in names:
        if name in seen:
            seen[name] += 1
            result.append(f"{name}_{seen[name]}")
        else:
            seen[name] = 0
            result.append(name)
    return result


def read_source(path: Path) -> tuple[pd.DataFrame, dict[str, str], dict[str, dict[str, str]]]:
    """Return (dataframe, variable_labels, value_labels)."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise IngestError(
            f"Unsupported file type '{suffix}'. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    if suffix == ".dta":
        return _read_stata(path)
    if suffix == ".sav":
        return _read_spss(path)
    if suffix in (".xlsx", ".xls"):
        frame = pd.read_excel(path)
        return frame, {}, {}
    return _read_delimited(path)


# Columns holding Stata's tagged missing values get a companion column with this
# suffix, so ".a" survives without turning a numeric column into text.
MISSING_TAG_SUFFIX = "__mv"


def _split_missing_tags(
    frame: pd.DataFrame, missing_user_values: dict[str, list[str]] | None
) -> pd.DataFrame:
    """Separate Stata tagged missings from the values they are mixed in with.

    Reading with user_missing=True returns a column like [25.0, nan, 'a', 33.0]:
    the tag is preserved but the column is now object dtype, so means and sums
    stop working. Split it into a clean numeric column plus a companion column
    holding the tag, and both survive.
    """
    if not missing_user_values:
        return frame

    for column in list(missing_user_values):
        if column not in frame.columns:
            continue
        series = frame[column]
        if not pd.api.types.is_object_dtype(series):
            continue
        is_tag = series.map(lambda v: isinstance(v, str) and len(v) == 1 and v.isalpha())
        if not is_tag.any():
            continue
        frame[f"{column}{MISSING_TAG_SUFFIX}"] = series.where(is_tag).map(
            lambda v: f".{v}" if isinstance(v, str) else None
        )
        frame[column] = pd.to_numeric(series.where(~is_tag), errors="coerce")
    return frame


def _read_stata(path: Path) -> tuple[pd.DataFrame, dict[str, str], dict[str, dict[str, str]]]:
    """pyreadstat keeps labels intact; pandas is the fallback for odd versions."""
    try:
        import pyreadstat

        # user_missing=True keeps Stata's tagged missing values (.a to .z) instead
        # of flattening every kind of missing into NaN. Survey Solutions uses them
        # for answers like "don't know", so losing them loses real information.
        frame, meta = pyreadstat.read_dta(
            str(path), apply_value_formats=False, user_missing=True
        )
        frame = _split_missing_tags(frame, getattr(meta, "missing_user_values", None))
        variable_labels = dict(meta.column_names_to_labels or {})
        value_labels = {
            variable: {str(k): str(v) for k, v in labels.items()}
            for variable, labels in (meta.variable_value_labels or {}).items()
        }
        return frame, variable_labels, value_labels
    except Exception as exc:  # noqa: BLE001 - fall back to pandas on any reader issue
        logger.warning("pyreadstat could not read %s (%s); falling back to pandas", path.name, exc)

    try:
        with pd.io.stata.StataReader(str(path), convert_categoricals=False) as reader:
            frame = reader.read()
            variable_labels = dict(reader.variable_labels() or {})
            raw_value_labels = reader.value_labels() or {}
        # pandas maps label-set names to labels; align them to variables by name
        value_labels = {
            variable: {str(k): str(v) for k, v in labels.items()}
            for variable, labels in raw_value_labels.items()
        }
        return frame, variable_labels, value_labels
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Could not read Stata file: {exc}") from exc


def _read_spss(path: Path) -> tuple[pd.DataFrame, dict[str, str], dict[str, dict[str, str]]]:
    try:
        import pyreadstat

        frame, meta = pyreadstat.read_sav(str(path), apply_value_formats=False)
        return (
            frame,
            dict(meta.column_names_to_labels or {}),
            {
                variable: {str(k): str(v) for k, v in labels.items()}
                for variable, labels in (meta.variable_value_labels or {}).items()
            },
        )
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Could not read SPSS file: {exc}") from exc


def _read_delimited(path: Path) -> tuple[pd.DataFrame, dict[str, str], dict[str, dict[str, str]]]:
    separators = {".tab": "\t", ".tsv": "\t", ".txt": "\t", ".csv": ","}
    separator = separators.get(path.suffix.lower(), ",")
    last_error: Exception | None = None
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            frame = pd.read_csv(
                path,
                sep=separator,
                encoding=encoding,
                low_memory=False,
                on_bad_lines="warn",
                na_values=["", "NA", "N/A", "##N/A##", "null", "NULL"],
                keep_default_na=True,
            )
            return frame, {}, {}
        except (UnicodeDecodeError, pd.errors.ParserError) as exc:
            last_error = exc
    raise IngestError(f"Could not parse delimited file: {last_error}")


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return round(result, 6)


def _classify(series: pd.Series, has_value_labels: bool) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "datetime"
    non_null = series.dropna()
    if pd.api.types.is_numeric_dtype(series):
        if has_value_labels:
            return "categorical"
        n_unique = non_null.nunique()
        # Small integer code sets behave like categories in practice
        if (
            n_unique <= 20
            and len(non_null) > 0
            and pd.api.types.is_integer_dtype(series.dtype)
        ):
            return "categorical"
        return "numeric"
    if len(non_null) == 0:
        return "text"
    n_unique = non_null.nunique()
    if n_unique <= CATEGORICAL_MAX_UNIQUE and n_unique / max(len(non_null), 1) < (
        CATEGORICAL_MAX_RATIO
    ):
        return "categorical"
    return "text"


def _coerce_datetime_columns(frame: pd.DataFrame) -> list[str]:
    """Detect ISO-like date strings so they can be used on time axes."""
    converted: list[str] = []
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2})?)?")
    for column in frame.columns:
        series = frame[column]
        if not pd.api.types.is_object_dtype(series):
            continue
        sample = series.dropna().astype(str).head(50)
        if len(sample) < 3:
            continue
        if all(pattern.match(value) for value in sample):
            try:
                frame[column] = pd.to_datetime(series, errors="coerce", format="mixed")
                converted.append(str(column))
            except (ValueError, TypeError):
                continue
    return converted


def build_metadata(
    frame: pd.DataFrame,
    variable_labels: dict[str, str],
    value_labels: dict[str, dict[str, str]],
) -> list[VariableMeta]:
    metas: list[VariableMeta] = []
    total = len(frame)
    for position, column in enumerate(frame.columns):
        series = frame[column]
        name = str(column)
        labels = value_labels.get(name, {})
        var_type = _classify(series, bool(labels))
        non_null = series.dropna()

        companion = f"{name}{MISSING_TAG_SUFFIX}"
        tags: list[str] = []
        if companion in frame.columns:
            tags = sorted({str(v) for v in frame[companion].dropna().unique()})

        meta = VariableMeta(
            name=name,
            label=str(variable_labels.get(name, "") or "")[:1000],
            var_type=var_type,
            storage_type=str(series.dtype),
            position=position,
            n_missing=int(total - len(non_null)),
            n_unique=int(non_null.nunique()) if total else 0,
            value_labels=labels,
            missing_tags=tags,
            # The companion column is an implementation detail; it should not
            # appear in variable pickers alongside the variable it belongs to.
            is_hidden=name.endswith(MISSING_TAG_SUFFIX),
        )
        if var_type in ("numeric", "categorical") and pd.api.types.is_numeric_dtype(series):
            meta.min_value = _safe_float(non_null.min()) if len(non_null) else None
            meta.max_value = _safe_float(non_null.max()) if len(non_null) else None
            meta.mean_value = _safe_float(non_null.mean()) if len(non_null) else None
        metas.append(meta)
    return metas


def ingest_file(source: Path, destination_dir: Path) -> IngestResult:
    """Read a data file, normalise it, and persist it as Parquet."""
    if not source.exists():
        raise IngestError(f"File not found: {source}")

    frame, variable_labels, value_labels = read_source(source)
    warnings: list[str] = []

    if frame.empty:
        warnings.append("The file contains no data rows.")

    original_columns = list(frame.columns)
    cleaned = _deduplicate(
        [_clean_column_name(name, index) for index, name in enumerate(original_columns)]
    )
    rename_map = dict(zip(original_columns, cleaned, strict=False))
    frame = frame.rename(columns=rename_map)
    variable_labels = {rename_map.get(k, k): v for k, v in variable_labels.items()}
    value_labels = {rename_map.get(k, k): v for k, v in value_labels.items()}

    converted = _coerce_datetime_columns(frame)
    if converted:
        warnings.append(f"Detected {len(converted)} date column(s): {', '.join(converted[:5])}")

    # Object columns holding mixed types break Parquet; normalise them to text
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_object_dtype(series):
            types = {type(v) for v in series.dropna().head(1000)}
            if len(types) > 1:
                frame[column] = series.astype(str).replace({"nan": None, "None": None})

    metas = build_metadata(frame, variable_labels, value_labels)

    destination_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = destination_dir / "data.parquet"
    try:
        frame.to_parquet(parquet_path, index=False, engine="pyarrow", compression="zstd")
    except Exception as exc:  # noqa: BLE001 - retry with everything stringified
        logger.warning("Parquet write failed (%s); retrying with text coercion", exc)
        fallback = frame.copy()
        for column in fallback.columns:
            if pd.api.types.is_object_dtype(fallback[column]):
                fallback[column] = fallback[column].astype(str)
        fallback.to_parquet(parquet_path, index=False, engine="pyarrow")
        warnings.append("Some columns were stored as text because of mixed value types.")

    return IngestResult(
        parquet_path=parquet_path,
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        file_size=parquet_path.stat().st_size,
        variables=metas,
        warnings=warnings,
    )


def detect_monitoring_fields(variables: list[VariableMeta]) -> dict[str, str]:
    """Guess which variables carry the standard Survey Solutions monitoring fields.

    Recognising these lets the platform pre-build field-progress views without the
    user configuring anything.
    """
    lookup = {v.name.lower(): v.name for v in variables}
    patterns = {
        "interview_key": ["interview__key", "interviewkey", "interview_key"],
        "interview_id": ["interview__id", "interviewid"],
        "status": ["interview__status", "assignment__status", "status"],
        "interviewer": ["interviewer", "responsible", "interviewername"],
        "supervisor": ["supervisor", "team", "teamlead"],
        "assignment": ["assignment__id", "assignmentid", "assignment"],
        "date": ["interview__date", "submitteddate", "date", "interviewdate", "starttime"],
        "duration": ["duration", "interview__duration", "interviewduration"],
        "latitude": ["latitude", "gpslatitude", "gps__latitude", "lat"],
        "longitude": ["longitude", "gpslongitude", "gps__longitude", "lon", "lng"],
        "region": ["region", "province", "state", "district", "admin1"],
    }
    detected: dict[str, str] = {}
    for key, candidates in patterns.items():
        for candidate in candidates:
            if candidate in lookup:
                detected[key] = lookup[candidate]
                break
        else:
            # Fall back to a substring match for prefixed export columns
            for lower_name, actual in lookup.items():
                if any(lower_name.endswith(c) or c in lower_name for c in candidates):
                    detected[key] = actual
                    break
    return detected


def dataframe_preview(path: Path, limit: int = 20) -> dict[str, Any]:
    """Small helper used by the upload preview endpoint."""
    frame = pd.read_parquet(path).head(limit)
    return {
        "columns": [str(c) for c in frame.columns],
        "rows": frame.replace({np.nan: None}).values.tolist(),
    }


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)
