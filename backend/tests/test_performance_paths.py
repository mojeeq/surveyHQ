from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from app.schemas.query import Aggregation, Measure, QuerySpec
from app.services import columnar, monitoring_precompute
from app.services.fast_ingest import build_metadata_from_parquet_fast
from app.services.query_runtime import _key


def test_columnar_append_unions_schema_without_loading_existing_frame(tmp_path):
    existing = tmp_path / "data.parquet"
    pd.DataFrame(
        {
            "interview__key": ["a", "b"],
            "age": [30, 40],
        }
    ).to_parquet(existing, index=False)

    incoming = pd.DataFrame(
        {
            "interview__key": ["c", "d"],
            "age": [50, 60],
            "new_question": [1, 2],
            "__source_file": ["round2", "round2"],
        }
    )
    old_columns, new_columns = columnar.append_frame_to_parquet(
        existing,
        incoming,
        existing,
        source_column="__source_file",
        existing_source_value="round1",
    )

    assert old_columns == ["interview__key", "age"]
    assert "new_question" in new_columns
    result = pd.read_parquet(existing)
    assert len(result) == 4
    assert list(result["interview__key"]) == ["a", "b", "c", "d"]
    assert result.loc[0, "__source_file"] == "round1"
    assert result.loc[3, "__source_file"] == "round2"
    assert pd.isna(result.loc[0, "new_question"])


def test_wide_metadata_profile_keeps_exact_statistics(tmp_path):
    path = tmp_path / "wide.parquet"
    frame = pd.DataFrame(
        {
            **{f"code_{i}": [1, 2, 1, None] for i in range(30)},
            "continuous": [1.25, 2.5, 5.75, None],
            "category": ["a", "b", "a", None],
        }
    )
    frame.to_parquet(path, index=False)

    metas = build_metadata_from_parquet_fast(path, {}, {})
    by_name = {meta.name: meta for meta in metas}
    assert len(metas) == 32
    assert by_name["continuous"].n_missing == 1
    assert by_name["continuous"].n_unique == 3
    assert by_name["continuous"].min_value == 1.25
    assert by_name["continuous"].max_value == 5.75
    assert by_name["continuous"].var_type == "numeric"
    assert by_name["code_0"].var_type == "categorical"
    assert by_name["category"].n_unique == 2


def test_duckdb_delimited_reader_streams_to_parquet(tmp_path):
    source = tmp_path / "survey.tab"
    source.write_text(
        "interview__key\tage\tregion\n"
        "k1\t25\tCentral\n"
        "k2\t31\tWestern\n",
        encoding="utf-8",
    )
    destination = tmp_path / "survey.parquet"
    columnar.delimited_to_parquet(source, destination)

    result = pd.read_parquet(destination)
    assert result.to_dict("records") == [
        {"interview__key": "k1", "age": 25, "region": "Central"},
        {"interview__key": "k2", "age": 31, "region": "Western"},
    ]


def test_monitoring_summary_is_versioned_and_reusable(tmp_path):
    path = tmp_path / "data.parquet"
    pd.DataFrame(
        {
            "status": [1, 1, 2],
            "interviewer": ["Ana", "Ana", "Ben"],
            "region": ["North", "South", "North"],
            "duration": [10.0, 20.0, 15.0],
            "submitted": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-01-02"]),
        }
    ).to_parquet(path, index=False)

    variables = [
        SimpleNamespace(name="status", value_labels={"1": "Completed", "2": "Rejected"}),
        SimpleNamespace(name="interviewer", value_labels={}),
        SimpleNamespace(name="region", value_labels={}),
        SimpleNamespace(name="duration", value_labels={}),
        SimpleNamespace(name="submitted", value_labels={}),
    ]
    dataset = SimpleNamespace(
        id="dataset-1",
        name="Fieldwork",
        storage_path=str(path),
        version=7,
        row_count=3,
        variables=variables,
        meta={
            "monitoring_fields": {
                "status": "status",
                "interviewer": "interviewer",
                "region": "region",
                "duration": "duration",
                "date": "submitted",
            }
        },
    )

    built = monitoring_precompute.build(dataset)
    loaded = monitoring_precompute.load(dataset)
    assert built is not None
    assert loaded is not None
    assert loaded["dataset_version"] == 7
    assert loaded["completed_records"] == 2
    assert loaded["completion_rate"] == 66.67
    assert loaded["by_interviewer"][0]["interviews"] == 2

    dataset.version = 8
    assert monitoring_precompute.load(dataset) is None


def test_query_cache_key_changes_with_dataset_version():
    spec = QuerySpec(measures=[Measure(agg=Aggregation.count, alias="n")])
    context = SimpleNamespace(dataset_id="abc", version=3)
    first = _key(context, spec)
    context.version = 4
    second = _key(context, spec)
    assert first != second
    assert ":v3:" in first
    assert ":v4:" in second
