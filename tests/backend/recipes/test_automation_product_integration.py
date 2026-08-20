from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pandas as pd
import pytest

from data_formulator import data_connector
from data_formulator.agents.client_utils import Client
from data_formulator.automation.models import AutomationRunStatus
from data_formulator.automation.repository import AutomationRepository
from data_formulator.automation.scheduler import AutomationScheduler
from data_formulator.automation.service import AutomationService
from data_formulator.automation.worker import AutomationWorker
from data_formulator.data_loader import sample_datasets_loader
from data_formulator.data_loader.sample_datasets_loader import (
    SampleDatasetsLoader,
)
from data_formulator.data_operations import (
    ConnectorQueryStep,
    DataOperation,
    DataOperationExecutor,
    DataOperationPlan,
    DataOperationStatus,
    LoadQuery,
    OperationFilter,
)
from data_formulator.datalake.workspace import sanitize_identity_dirname
from data_formulator.datalake.workspace_manager import WorkspaceManager
from data_formulator.model_registry import ModelRegistry
from data_formulator.recipes.compiler import (
    CompiledRecipe,
    RecipeCompiler,
    RecipeParameterConfiguration,
)
from data_formulator.recipes.openers import (
    ExplicitConnectorOpener,
    LocalWorkspaceOpener,
)
from data_formulator.recipes.parameter_suggestions import (
    suggest_recipe_parameter_configurations,
)
from data_formulator.recipes.repository import RecipeRepository
from data_formulator.recipes.service import RecipeService
from data_formulator.recipes.visualize import record_visualize_artifacts
from data_formulator.security.code_signing import sign_code


pytestmark = [pytest.mark.backend]


_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _clear_sample_cache() -> None:
    with sample_datasets_loader._SAMPLE_CACHE_LOCK:
        sample_datasets_loader._SAMPLE_CACHE.clear()
        sample_datasets_loader._SAMPLE_CACHE_ORDER.clear()


@dataclass
class _MoviesSource:
    opener: ExplicitConnectorOpener
    state: dict[str, object]

    @property
    def request_count(self) -> int:
        value = self.state["request_count"]
        assert isinstance(value, int)
        return value

    def replace_rows(self, rows: list[dict[str, object]]) -> None:
        self.state["response"] = json.dumps(
            rows,
            ensure_ascii=False,
        ).encode("utf-8")
        _clear_sample_cache()


class _ParameterRecommendationClient:
    model = "test-model"

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.messages: list[dict[str, str]] | None = None

    def get_completion(self, messages, *, reasoning_effort, timeout):
        self.messages = messages
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(self.payload)),
        )])


@pytest.fixture
def movies_source(monkeypatch) -> _MoviesSource:
    packaged = json.loads(
        (_PROJECT_ROOT / "public" / "df_movies.json").read_text(
            encoding="utf-8"
        )
    )
    rows = packaged["tables"][0]["rows"]
    state: dict[str, object] = {
        "response": json.dumps(rows, ensure_ascii=False).encode("utf-8"),
        "request_count": 0,
    }
    state_lock = threading.Lock()

    class MoviesHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            if self.path.split("?", 1)[0] != "/movies.json":
                self.send_error(404)
                return
            with state_lock:
                state["request_count"] = int(state["request_count"]) + 1
                response = state["response"]
            assert isinstance(response, bytes)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, _format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), MoviesHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    host, port = server.server_address
    datasets = [{
        "name": "Movies",
        "description": "Packaged Data Formulator Movies sample.",
        "tables": [{
            "url": f"http://{host}:{port}/movies.json",
            "format": "json",
        }],
    }]

    monkeypatch.setattr(
        SampleDatasetsLoader,
        "_datasets",
        lambda _loader: datasets,
    )
    # Keep this integration test independent from connector registry mutations
    # made by the rest of the suite.
    monkeypatch.setattr(data_connector, "DATA_CONNECTORS", {})
    monkeypatch.setattr(data_connector, "_ADMIN_CONNECTOR_IDS", set())
    monkeypatch.setattr(data_connector, "_LOADED_USER_IDENTITIES", set())
    _clear_sample_cache()

    source = _MoviesSource(
        opener=ExplicitConnectorOpener(
            initialize_registry=True,
            disable_data_connectors=True,
        ),
        state=state,
    )
    try:
        yield source
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
        _clear_sample_cache()


def _create_movies_workspace(data_home: Path):
    identity_id = "user:movies-e2e"
    workspace_id = "ws-movies-e2e"
    workspace_root = (
        data_home
        / "users"
        / sanitize_identity_dirname(identity_id)
        / "workspaces"
    )
    manager = WorkspaceManager(workspace_root)
    manager.create_workspace(workspace_id)
    return manager.open_workspace(workspace_id, identity_id)


def _compile_movies_recipe(
    workspace,
    connector_opener: ExplicitConnectorOpener,
    *,
    genre_filter: str | None = None,
    parameterize_filter: bool = False,
    parameterize_transform: bool = False,
) -> CompiledRecipe:
    connector_step = ConnectorQueryStep(
        source_id="sample_datasets",
        table_key="Movies",
        display_name="Movies",
        source_table="Movies",
        query=LoadQuery(filters=(
            (OperationFilter("Major Genre", "EQ", genre_filter),)
            if genre_filter is not None
            else ()
        )),
    )
    plan = DataOperationPlan(
        id="movies-plan",
        label="Movies",
        summary="Load the packaged Movies dataset through its real connector.",
        steps=(connector_step,),
    )
    operation = DataOperation(
        id="movies-operation",
        reason="Build a deterministic genre summary.",
        plans=(plan,),
        status=DataOperationStatus.RUNNING,
        selected_plan_id=plan.id,
    )
    loaded = DataOperationExecutor(
        workspace,
        lambda source_id: connector_opener.open(
            workspace.identity_id,
            source_id,
        ),
    ).execute(operation)

    assert loaded.failed_steps == ()
    assert loaded.result_table_ids == ("movies",)
    movies = workspace.read_data_as_df("movies")
    if genre_filter is None:
        assert movies.shape == (3201, 16)
    else:
        assert set(movies["Major Genre"].dropna()) == {genre_filter}

    summary = (
        movies.dropna(subset=["Major Genre"])
        .groupby("Major Genre", as_index=False)
        .agg(
            movie_count=("Title", "size"),
            worldwide_gross=("Worldwide Gross", "sum"),
        )
        .sort_values(
            ["movie_count", "Major Genre"],
            ascending=[False, True],
        )
        .reset_index(drop=True)
    )
    if parameterize_transform:
        summary = summary.head(5).reset_index(drop=True)
    workspace.write_parquet(summary, "genre_summary")
    code = "\n".join([
        "import pandas as pd",
        'movies = pd.read_parquet("data/movies.parquet")',
        "result_df = (",
        '    movies.dropna(subset=["Major Genre"])',
        '    .groupby("Major Genre", as_index=False)',
        "    .agg(",
        '        movie_count=("Title", "size"),',
        '        worldwide_gross=("Worldwide Gross", "sum"),',
        "    )",
        '    .sort_values(["movie_count", "Major Genre"],',
        "                 ascending=[False, True])",
        "    .reset_index(drop=True)",
        ")",
    ])
    parameter_slots: tuple[dict[str, object], ...] = ()
    if parameterize_transform:
        code += "\nresult_df = result_df.head(params['top_n']).reset_index(drop=True)"
        parameter_slots = ({
            "id": "top_n",
            "name": "Top genres",
            "description": "Number of highest-count genres included in the result.",
            "type": "integer",
            "default": 5,
        },)
    artifacts = record_visualize_artifacts(
        workspace,
        chart_id="movies-by-genre",
        input_table_names=("movies",),
        output_table_name="genre_summary",
        code=code,
        code_signature=sign_code(code),
        output_variable="result_df",
        parameter_slots=parameter_slots,
        chart_spec={
            "chart_type": "Bar Chart",
            "encodings": {
                "x": "Major Genre",
                "y": "movie_count",
            },
        },
        field_metadata={},
        field_display_names={},
        display_instruction="Compare movie counts by major genre.",
        title="Movies by genre",
        subtitle="Packaged 3,201-row sample",
    )
    compiler = RecipeCompiler.for_workspace(workspace)
    parameter_configurations: list[RecipeParameterConfiguration] = []
    if parameterize_filter:
        parameter_configurations.extend(
            RecipeParameterConfiguration(
                candidate_id=item.candidate_id,
                name="Movie genre",
                description="Genre included in the refreshed source data.",
                mode="ask",
            )
            for item in compiler.parameter_candidates((artifacts.chart.artifact_id,))
            if item.name == "Major Genre"
        )
        assert len(parameter_configurations) == 1
    if parameterize_transform:
        transform_candidates = tuple(
            item
            for item in compiler.parameter_candidates((artifacts.chart.artifact_id,))
            if item.kind == "transform" and item.name == "Top genres"
        )
        assert len(transform_candidates) == 1
        parameter_configurations.append(RecipeParameterConfiguration(
            candidate_id=transform_candidates[0].candidate_id,
            name="Top genres",
            description="Number of highest-count genres included in the result.",
            mode="ask",
        ))
    return compiler.compile(
        target_artifact_ids=(artifacts.chart.artifact_id,),
        name="Movies by genre",
        parameter_configurations=tuple(parameter_configurations),
    )


def _expected_director_portfolios(
    movies: pd.DataFrame,
    *,
    start_year: int,
    min_movies: int,
    min_roi: float,
    top_directors: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Independently calculate both stages of the complex Movies analysis."""
    source = movies.copy()
    source["release_year"] = pd.to_datetime(
        source["Release Date"],
        errors="coerce",
    ).dt.year
    eligible = source.loc[
        source["release_year"].ge(start_year)
        & source["Major Genre"].notna()
        & source["Director"].notna()
        & source["Production Budget"].gt(0)
        & source["Worldwide Gross"].notna()
    ].copy()
    eligible["profit"] = (
        eligible["Worldwide Gross"] - eligible["Production Budget"]
    )
    metrics = (
        eligible.groupby(["Major Genre", "Director"], as_index=False)
        .agg(
            movie_count=("Title", "size"),
            total_budget=("Production Budget", "sum"),
            total_gross=("Worldwide Gross", "sum"),
            total_profit=("profit", "sum"),
            avg_imdb=("IMDB Rating", "mean"),
        )
    )
    metrics["roi"] = metrics["total_profit"] / metrics["total_budget"]
    metrics = (
        metrics.loc[metrics["movie_count"].ge(min_movies)]
        .sort_values(
            ["Major Genre", "total_profit", "Director"],
            ascending=[True, False, True],
        )
        .reset_index(drop=True)
    )

    ranked = (
        metrics.loc[metrics["roi"].ge(min_roi)]
        .sort_values(
            ["Major Genre", "total_profit", "Director"],
            ascending=[True, False, True],
        )
        .reset_index(drop=True)
    )
    ranked["rank_within_genre"] = (
        ranked.groupby("Major Genre")["total_profit"]
        .rank(method="first", ascending=False)
        .astype("int64")
    )
    ranked = (
        ranked.loc[ranked["rank_within_genre"].le(top_directors)]
        .sort_values(["Major Genre", "rank_within_genre", "Director"])
        .reset_index(drop=True)
    )
    return metrics, ranked


def _compile_complex_movies_recipe(
    workspace,
    connector_opener: ExplicitConnectorOpener,
) -> tuple[CompiledRecipe, pd.DataFrame]:
    """Compile load -> transform -> transform -> chart from all 3,201 rows."""
    connector_step = ConnectorQueryStep(
        source_id="sample_datasets",
        table_key="Movies",
        display_name="Movies",
        source_table="Movies",
        query=LoadQuery(),
    )
    plan = DataOperationPlan(
        id="complex-movies-plan",
        label="Movies",
        summary="Load all packaged Movies rows for director portfolio analysis.",
        steps=(connector_step,),
    )
    operation = DataOperation(
        id="complex-movies-operation",
        reason="Rank durable director portfolios within each movie genre.",
        plans=(plan,),
        status=DataOperationStatus.RUNNING,
        selected_plan_id=plan.id,
    )
    loaded = DataOperationExecutor(
        workspace,
        lambda source_id: connector_opener.open(
            workspace.identity_id,
            source_id,
        ),
    ).execute(operation)
    assert loaded.failed_steps == ()
    assert loaded.result_table_ids == ("movies",)
    movies = workspace.read_data_as_df("movies")
    assert movies.shape == (3201, 16)

    defaults = {
        "start_year": 2000,
        "min_movies": 2,
        "min_roi": 0.5,
        "top_directors": 3,
    }
    director_metrics, ranked_directors = _expected_director_portfolios(
        movies,
        **defaults,
    )
    workspace.write_parquet(director_metrics, "director_metrics")
    metrics_code = "\n".join([
        "import pandas as pd",
        'movies = pd.read_parquet("data/movies.parquet")',
        'movies["release_year"] = pd.to_datetime(',
        '    movies["Release Date"], errors="coerce"',
        ").dt.year",
        "eligible = movies[",
        '    (movies["release_year"] >= params["start_year"])',
        '    & movies["Major Genre"].notna()',
        '    & movies["Director"].notna()',
        '    & (movies["Production Budget"] > 0)',
        '    & movies["Worldwide Gross"].notna()',
        "].copy()",
        'eligible["profit"] = (',
        '    eligible["Worldwide Gross"] - eligible["Production Budget"]',
        ")",
        "metrics = (",
        '    eligible.groupby(["Major Genre", "Director"], as_index=False)',
        "    .agg(",
        '        movie_count=("Title", "size"),',
        '        total_budget=("Production Budget", "sum"),',
        '        total_gross=("Worldwide Gross", "sum"),',
        '        total_profit=("profit", "sum"),',
        '        avg_imdb=("IMDB Rating", "mean"),',
        "    )",
        ")",
        'metrics["roi"] = metrics["total_profit"] / metrics["total_budget"]',
        "result_df = (",
        '    metrics[metrics["movie_count"] >= params["min_movies"]]',
        "    .sort_values(",
        '        ["Major Genre", "total_profit", "Director"],',
        "        ascending=[True, False, True],",
        "    )",
        "    .reset_index(drop=True)",
        ")",
    ])
    record_visualize_artifacts(
        workspace,
        chart_id="director-metrics-stage",
        input_table_names=("movies",),
        output_table_name="director_metrics",
        code=metrics_code,
        code_signature=sign_code(metrics_code),
        output_variable="result_df",
        parameter_slots=(
            {
                "id": "start_year",
                "name": "Release year from",
                "description": "Earliest release year included in the analysis.",
                "type": "integer",
                "default": defaults["start_year"],
            },
            {
                "id": "min_movies",
                "name": "Minimum movies per director",
                "description": "Minimum eligible movies required for a director.",
                "type": "integer",
                "default": defaults["min_movies"],
            },
        ),
        chart_spec={
            "chart_type": "Scatter Plot",
            "encodings": {"x": "total_budget", "y": "total_profit"},
        },
        field_metadata={},
        field_display_names={},
        display_instruction="Inspect director profit against production budget.",
        title="Director portfolio metrics",
        subtitle="Intermediate analysis stage",
    )

    workspace.write_parquet(ranked_directors, "ranked_directors")
    ranking_code = "\n".join([
        "import pandas as pd",
        'metrics = pd.read_parquet("data/director_metrics.parquet")',
        "ranked = (",
        '    metrics[metrics["roi"] >= params["min_roi"]]',
        "    .sort_values(",
        '        ["Major Genre", "total_profit", "Director"],',
        "        ascending=[True, False, True],",
        "    )",
        "    .reset_index(drop=True)",
        ")",
        'ranked["rank_within_genre"] = (',
        '    ranked.groupby("Major Genre").cumcount() + 1',
        ")",
        "result_df = (",
        '    ranked[ranked["rank_within_genre"] <= params["top_directors"]]',
        '    .sort_values(["Major Genre", "rank_within_genre", "Director"])',
        "    .reset_index(drop=True)",
        ")",
    ])
    final_artifacts = record_visualize_artifacts(
        workspace,
        chart_id="ranked-director-portfolios",
        input_table_names=("director_metrics",),
        output_table_name="ranked_directors",
        code=ranking_code,
        code_signature=sign_code(ranking_code),
        output_variable="result_df",
        parameter_slots=(
            {
                "id": "min_roi",
                "name": "Minimum ROI",
                "description": "Minimum portfolio return on production budget.",
                "type": "number",
                "default": defaults["min_roi"],
            },
            {
                "id": "top_directors",
                "name": "Top directors per genre",
                "description": "Number of highest-profit directors kept per genre.",
                "type": "integer",
                "default": defaults["top_directors"],
            },
        ),
        chart_spec={
            "chart_type": "Grouped Bar Chart",
            "encodings": {
                "x": "Director",
                "y": "total_profit",
                "color": "Major Genre",
            },
        },
        field_metadata={},
        field_display_names={},
        display_instruction=(
            "Compare the highest-profit director portfolios within each genre."
        ),
        title="Top director portfolios by genre",
        subtitle="Filtered by release year, volume, and ROI",
    )

    compiler = RecipeCompiler.for_workspace(workspace)
    candidates = compiler.parameter_candidates((final_artifacts.chart.artifact_id,))
    candidates_by_parameter = {item.parameter_id: item for item in candidates}
    expected_ids = {
        "start_year",
        "min_movies",
        "min_roi",
        "top_directors",
    }
    assert set(candidates_by_parameter) == expected_ids
    configuration_metadata = {
        "start_year": (
            "Release year from",
            "Earliest release year included in the analysis.",
        ),
        "min_movies": (
            "Minimum movies per director",
            "Minimum eligible movies required for a director.",
        ),
        "min_roi": (
            "Minimum ROI",
            "Minimum portfolio return on production budget.",
        ),
        "top_directors": (
            "Top directors per genre",
            "Number of highest-profit directors kept per genre.",
        ),
    }
    configurations = tuple(
        RecipeParameterConfiguration(
            candidate_id=candidates_by_parameter[parameter_id].candidate_id,
            name=configuration_metadata[parameter_id][0],
            description=configuration_metadata[parameter_id][1],
            mode="ask",
        )
        for parameter_id in (
            "start_year",
            "min_movies",
            "min_roi",
            "top_directors",
        )
    )
    return (
        compiler.compile(
            target_artifact_ids=(final_artifacts.chart.artifact_id,),
            name="Top director portfolios by genre",
            description=(
                "Rank multi-movie director portfolios by profit within genre."
            ),
            parameter_configurations=configurations,
        ),
        movies,
    )


def test_manual_movies_runs_use_different_typed_values_and_save_different_results(
    tmp_path,
    movies_source: _MoviesSource,
) -> None:
    data_home = tmp_path / "parameterized-data-home"
    workspace = _create_movies_workspace(data_home)
    compiled = _compile_movies_recipe(
        workspace,
        movies_source.opener,
        genre_filter="Drama",
        parameterize_filter=True,
    )
    assert [item.id for item in compiled.spec.parameters] == ["major_genre"]
    assert compiled.spec.parameters[0].name == "Movie genre"
    assert compiled.spec.parameters[0].description == (
        "Genre included in the refreshed source data."
    )
    assert compiled.spec.parameters[0].has_default is False

    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    recipe_service = RecipeService(recipes)
    draft = recipes.save_draft(workspace, compiled)
    validated = recipe_service.dry_run(
        workspace,
        draft.version_id,
        parameter_values={"major_genre": "Drama"},
        loader_resolver=lambda source_id: movies_source.opener.open(
            workspace.identity_id,
            source_id,
        ),
    )
    assert validated.status.value == "succeeded"
    published = recipe_service.publish(workspace, draft.version_id)

    now = datetime(2026, 8, 21, 9, tzinfo=timezone.utc)
    run_ids = iter((UUID("1" * 32), UUID("2" * 32)))
    automation = AutomationRepository(
        database_path,
        clock=lambda: now,
        id_factory=lambda: next(run_ids),
    )
    service = AutomationService(automation, recipes)
    drama = service.enqueue_manual_run(
        workspace,
        published.version_id,
        {"major_genre": "Drama"},
    )
    comedy = service.enqueue_manual_run(
        workspace,
        published.version_id,
        {"major_genre": "Comedy"},
    )
    attempt_ids = iter((UUID("c" * 32), UUID("d" * 32)))
    worker = AutomationWorker(
        automation,
        recipes,
        LocalWorkspaceOpener(data_home),
        movies_source.opener,
        worker_id="parameterized-movies-worker",
        enabled=True,
        clock=lambda: now,
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: next(attempt_ids),
    )

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        finished_drama = worker.run_once()
        finished_comedy = worker.run_once()

    assert finished_drama is not None
    assert finished_comedy is not None
    assert finished_drama.run_id == drama.run_id
    assert finished_comedy.run_id == comedy.run_id
    assert finished_drama.status is AutomationRunStatus.SUCCEEDED
    assert finished_comedy.status is AutomationRunStatus.SUCCEEDED
    assert finished_drama.parameter_values == {"major_genre": "Drama"}
    assert finished_comedy.parameter_values == {"major_genre": "Comedy"}
    assert finished_drama.binding_hash != finished_comedy.binding_hash

    drama_result = service.load_run_result(workspace, drama.run_id)
    comedy_result = service.load_run_result(workspace, comedy.run_id)
    assert drama_result.report["parameters"] == [{
        "id": "major_genre",
        "name": "Movie genre",
        "description": "Genre included in the refreshed source data.",
        "type": "string",
    }]
    assert comedy_result.report == drama_result.report
    drama_table = drama_result.outputs[0]["table"]
    comedy_table = comedy_result.outputs[0]["table"]
    assert drama_table["row_count"] == comedy_table["row_count"] == 1
    assert drama_table["rows"][0]["Major Genre"] == "Drama"
    assert comedy_table["rows"][0]["Major Genre"] == "Comedy"
    assert drama_table["rows"][0]["movie_count"] != (
        comedy_table["rows"][0]["movie_count"]
    )


def test_manual_movies_runs_change_a_typed_transform_top_n_slot(
    tmp_path,
    movies_source: _MoviesSource,
) -> None:
    data_home = tmp_path / "transform-parameter-data-home"
    workspace = _create_movies_workspace(data_home)
    compiled = _compile_movies_recipe(
        workspace,
        movies_source.opener,
        parameterize_transform=True,
    )
    compiler = RecipeCompiler.for_workspace(workspace)
    candidates = compiler.parameter_candidates(compiled.spec.target_artifact_ids)
    top_n_candidate = next(item for item in candidates if item.parameter_id == "top_n")
    recommendation_client = _ParameterRecommendationClient({
        "suggestions": [{
            "candidate_id": top_n_candidate.candidate_id,
            "name": "Top genres",
            "description": "Number of highest-count genres shown in each run.",
            "mode": "ask",
        }],
        "unmatched": [],
    })
    recommendation = suggest_recipe_parameter_configurations(
        recommendation_client,
        candidates,
        workflow_context={
            "threads": [{
                "thread_id": "movies-by-genre",
                "events": [{
                    "type": "message",
                    "from": "user",
                    "to": "data-agent",
                    "role": "user",
                    "content": (
                        "Show the top genres by movie count and let me change "
                        "how many genres are included."
                    ),
                }],
            }],
        },
        recipe_name="Movies by genre",
    )
    assert recommendation.unmatched == ()
    assert [item.candidate_id for item in recommendation.suggestions] == [
        top_n_candidate.candidate_id
    ]
    assert recommendation_client.messages is not None
    assert "Show the top genres" in recommendation_client.messages[1]["content"]
    compiled = compiler.compile(
        target_artifact_ids=compiled.spec.target_artifact_ids,
        name="Movies by genre",
        parameter_configurations=tuple(
            RecipeParameterConfiguration(
                candidate_id=item.candidate_id,
                name=item.name,
                description=item.description,
                mode=item.mode,
            )
            for item in recommendation.suggestions
        ),
    )
    assert [item.id for item in compiled.spec.parameters] == ["top_n"]
    assert compiled.spec.parameters[0].value_type.value == "integer"
    assert compiled.spec.parameters[0].has_default is False

    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    recipe_service = RecipeService(recipes)
    draft = recipes.save_draft(workspace, compiled)
    validated = recipe_service.dry_run(
        workspace,
        draft.version_id,
        parameter_values={"top_n": 5},
        loader_resolver=lambda source_id: movies_source.opener.open(
            workspace.identity_id,
            source_id,
        ),
    )
    assert validated.status.value == "succeeded"
    published = recipe_service.publish(workspace, draft.version_id)

    now = datetime(2026, 8, 21, 10, tzinfo=timezone.utc)
    run_ids = iter((UUID("3" * 32), UUID("4" * 32)))
    automation = AutomationRepository(
        database_path,
        clock=lambda: now,
        id_factory=lambda: next(run_ids),
    )
    service = AutomationService(automation, recipes)
    top_three = service.enqueue_manual_run(
        workspace,
        published.version_id,
        {"top_n": 3},
    )
    top_seven = service.enqueue_manual_run(
        workspace,
        published.version_id,
        {"top_n": 7},
    )
    attempt_ids = iter((UUID("e" * 32), UUID("f" * 32)))
    worker = AutomationWorker(
        automation,
        recipes,
        LocalWorkspaceOpener(data_home),
        movies_source.opener,
        worker_id="parameterized-transform-movies-worker",
        enabled=True,
        clock=lambda: now,
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: next(attempt_ids),
    )

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        finished_three = worker.run_once()
        finished_seven = worker.run_once()

    assert finished_three is not None
    assert finished_seven is not None
    assert finished_three.run_id == top_three.run_id
    assert finished_seven.run_id == top_seven.run_id
    assert finished_three.status is AutomationRunStatus.SUCCEEDED
    assert finished_seven.status is AutomationRunStatus.SUCCEEDED
    assert finished_three.parameter_values == {"top_n": 3}
    assert finished_seven.parameter_values == {"top_n": 7}
    assert finished_three.binding_hash != finished_seven.binding_hash

    three_table = service.load_run_result(workspace, top_three.run_id).outputs[0][
        "table"
    ]
    seven_table = service.load_run_result(workspace, top_seven.run_id).outputs[0][
        "table"
    ]
    assert three_table["row_count"] == 3
    assert seven_table["row_count"] == 7
    assert three_table["rows"] == seven_table["rows"][:3]
    assert sum(row["movie_count"] for row in three_table["rows"]) < sum(
        row["movie_count"] for row in seven_table["rows"]
    )


def test_ai_recommendations_drive_a_complex_real_movies_automation(
    tmp_path,
    movies_source: _MoviesSource,
) -> None:
    data_home = tmp_path / "ai-recommended-complex-analysis-data-home"
    workspace = _create_movies_workspace(data_home)
    compiled_all, movies = _compile_complex_movies_recipe(
        workspace,
        movies_source.opener,
    )
    compiler = RecipeCompiler.for_workspace(workspace)
    candidates = compiler.parameter_candidates(compiled_all.spec.target_artifact_ids)
    candidates_by_parameter = {item.parameter_id: item for item in candidates}
    assert set(candidates_by_parameter) == {
        "start_year",
        "min_movies",
        "min_roi",
        "top_directors",
    }

    # This is a deterministic model boundary: the lineage, candidates, data,
    # compiler, repositories, scheduler and worker below are all production
    # paths. The response represents the semantic choice a live model is
    # expected to make from the supplied workflow conversation.
    recommendation_client = _ParameterRecommendationClient({
        "suggestions": [
            {
                "candidate_id": candidates_by_parameter[
                    "start_year"
                ].candidate_id,
                "name": "分析起始年份",
                "description": "每次运行纳入分析的最早上映年份。",
                "mode": "ask",
            },
            {
                "candidate_id": candidates_by_parameter["min_roi"].candidate_id,
                "name": "最低投资回报率",
                "description": "每次运行保留的最低导演组合投资回报率。",
                "mode": "ask",
            },
            {
                "candidate_id": candidates_by_parameter[
                    "top_directors"
                ].candidate_id,
                "name": "每类导演数",
                "description": "每个电影类型最终保留的高利润导演数量。",
                "mode": "ask",
            },
        ],
        "unmatched": ["最低 IMDb 评分"],
    })
    workflow_request = (
        "分析不同电影类型中导演组合的利润和投资回报率。"
        "最低两部电影是固定的数据质量门槛，不要让每次运行修改；"
        "但分析起始年份、最低投资回报率和每类保留的导演数需要按运行调整。"
        "我还希望以后能按最低 IMDb 评分筛选。"
    )
    recommendation = suggest_recipe_parameter_configurations(
        recommendation_client,
        candidates,
        workflow_context={
            "threads": [{
                "thread_id": "director-portfolio-analysis",
                "events": [{
                    "type": "message",
                    "from": "user",
                    "to": "data-agent",
                    "role": "user",
                    "content": workflow_request,
                }],
            }],
        },
        recipe_name="按类型分析导演组合",
        description="定期刷新导演组合的利润、ROI 和类型内排名。",
        language_code="zh",
    )
    assert [
        item.candidate_id for item in recommendation.suggestions
    ] == [
        candidates_by_parameter[parameter_id].candidate_id
        for parameter_id in ("start_year", "min_roi", "top_directors")
    ]
    assert recommendation.unmatched == ("最低 IMDb 评分",)
    assert recommendation_client.messages is not None
    recommendation_prompt = recommendation_client.messages[1]["content"]
    assert workflow_request in recommendation_prompt
    assert recommendation_prompt.index(
        "Relevant analysis workflow context"
    ) < recommendation_prompt.index("Available typed binding candidates")
    assert all(
        item.candidate_id in recommendation_prompt for item in candidates
    )

    compiled = compiler.compile(
        target_artifact_ids=compiled_all.spec.target_artifact_ids,
        name="按类型分析导演组合",
        description="定期刷新导演组合的利润、ROI 和类型内排名。",
        parameter_configurations=tuple(
            RecipeParameterConfiguration(
                candidate_id=item.candidate_id,
                name=item.name,
                description=item.description,
                mode=item.mode,
            )
            for item in recommendation.suggestions
        ),
    )
    compiled_parameters_by_id = {
        item.id: item for item in compiled.spec.parameters
    }
    assert set(compiled_parameters_by_id) == {
        "start_year",
        "min_roi",
        "top_directors",
    }
    assert {
        parameter_id: item.name
        for parameter_id, item in compiled_parameters_by_id.items()
    } == {
        "start_year": "分析起始年份",
        "min_roi": "最低投资回报率",
        "top_directors": "每类导演数",
    }
    assert {
        parameter_id: item.value_type.value
        for parameter_id, item in compiled_parameters_by_id.items()
    } == {
        "start_year": "integer",
        "min_roi": "number",
        "top_directors": "integer",
    }
    assert all(not item.has_default for item in compiled.spec.parameters)
    assert "min_movies" not in {item.id for item in compiled.spec.parameters}
    assert len(compiled.spec.bindings) == 3

    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    recipe_service = RecipeService(recipes)
    draft = recipes.save_draft(workspace, compiled)
    scheduled_values = {
        "start_year": 2000,
        "min_roi": 0.5,
        "top_directors": 3,
    }
    _clear_sample_cache()
    dry_run = recipe_service.dry_run(
        workspace,
        draft.version_id,
        parameter_values=scheduled_values,
        loader_resolver=lambda source_id: movies_source.opener.open(
            workspace.identity_id,
            source_id,
        ),
    )
    assert dry_run.status.value == "succeeded"
    assert [step.kind.value for step in dry_run.step_results] == [
        "load",
        "transform",
        "transform",
        "chart",
    ]
    published = recipe_service.publish(workspace, draft.version_id)

    clock_state = {"now": datetime(2026, 8, 21, 8, 59, tzinfo=timezone.utc)}
    automation = AutomationRepository(
        database_path,
        clock=lambda: clock_state["now"],
    )
    automation_service = AutomationService(automation, recipes)
    schedule = automation_service.create_schedule(
        workspace,
        version_id=published.version_id,
        name="导演组合每日分析",
        cron_expression="0 9 * * *",
        timezone_name="UTC",
        parameter_policy={
            parameter_id: {"source": "literal", "value": value}
            for parameter_id, value in scheduled_values.items()
        },
    )
    clock_state["now"] = datetime(2026, 8, 21, 9, tzinfo=timezone.utc)
    scheduled_batch = AutomationScheduler(
        automation,
        clock=lambda: clock_state["now"],
    ).tick()
    assert len(scheduled_batch.runs) == 1
    scheduled_run = scheduled_batch.runs[0]
    assert scheduled_run.schedule_id == schedule.schedule_id

    manual_values = {
        "start_year": 1990,
        "min_roi": 1.0,
        "top_directors": 2,
    }
    manual_run = automation_service.enqueue_manual_run(
        workspace,
        published.version_id,
        manual_values,
    )

    attempt_ids = iter((UUID("b" * 32), UUID("c" * 32)))
    worker = AutomationWorker(
        AutomationRepository(
            database_path,
            clock=lambda: clock_state["now"],
        ),
        RecipeRepository(database_path),
        LocalWorkspaceOpener(data_home),
        ExplicitConnectorOpener(initialize_registry=False),
        worker_id="ai-recommended-complex-movies-worker",
        enabled=True,
        clock=lambda: clock_state["now"],
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: next(attempt_ids),
    )
    finished_by_id = {}
    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        for _ in range(2):
            _clear_sample_cache()
            finished = worker.run_once()
            assert finished is not None
            assert finished.status is AutomationRunStatus.SUCCEEDED
            finished_by_id[finished.run_id] = finished

    cases = {
        scheduled_run.run_id: (
            scheduled_values,
            209,
            22,
            8,
            72,
            20_035_909_513.0,
        ),
        manual_run.run_id: (
            manual_values,
            337,
            18,
            10,
            69,
            21_326_749_404.0,
        ),
    }
    assert set(finished_by_id) == set(cases)
    assert len({item.binding_hash for item in finished_by_id.values()}) == 2

    result_service = AutomationService(
        AutomationRepository(database_path),
        RecipeRepository(database_path),
    )
    for run_id, (
        parameter_values,
        expected_metric_rows,
        expected_rows,
        expected_genres,
        expected_movie_count,
        expected_profit,
    ) in cases.items():
        finished = finished_by_id[run_id]
        assert finished.parameter_values == parameter_values
        assert finished.artifact_path is not None
        expected_metrics, expected_ranked = _expected_director_portfolios(
            movies,
            min_movies=2,
            **parameter_values,
        )
        actual_metrics = pd.read_parquet(workspace.confined_root.resolve(
            f"{finished.artifact_path}/workspace/data/director_metrics.parquet"
        ))
        actual_ranked = pd.read_parquet(workspace.confined_root.resolve(
            f"{finished.artifact_path}/workspace/data/ranked_directors.parquet"
        ))
        pd.testing.assert_frame_equal(
            actual_metrics,
            expected_metrics,
            check_exact=False,
            rtol=1e-12,
            atol=1e-9,
        )
        pd.testing.assert_frame_equal(
            actual_ranked,
            expected_ranked,
            check_exact=False,
            rtol=1e-12,
            atol=1e-9,
        )
        assert len(actual_metrics) == expected_metric_rows
        assert len(actual_ranked) == expected_rows
        assert actual_ranked["Major Genre"].nunique() == expected_genres
        assert int(actual_ranked["movie_count"].sum()) == expected_movie_count
        assert float(actual_ranked["total_profit"].sum()) == pytest.approx(
            expected_profit
        )

        # Prove that the candidate AI intentionally left out stayed frozen at
        # two movies rather than silently becoming a fourth run input.
        one_movie_metrics, _ = _expected_director_portfolios(
            movies,
            min_movies=1,
            **parameter_values,
        )
        assert len(one_movie_metrics) > len(actual_metrics)

        result = result_service.load_run_result(workspace, run_id)
        assert result.outputs[0]["table"]["row_count"] == expected_rows
        assert {
            item["id"] for item in result.report["parameters"]
        } == set(compiled_parameters_by_id)


_LIVE_SILICONFLOW_ENV = (
    "SILICONFLOW_ENABLED",
    "SILICONFLOW_API_KEY",
    "SILICONFLOW_API_BASE",
    "SILICONFLOW_MODELS",
)


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("DF_RUN_LIVE_SILICONFLOW_TESTS") != "1"
    or not all(os.environ.get(key) for key in _LIVE_SILICONFLOW_ENV),
    reason=(
        "set DF_RUN_LIVE_SILICONFLOW_TESTS=1 and the SILICONFLOW_* model "
        "environment to run this external-service test"
    ),
)
def test_live_siliconflow_recommendation_drives_complex_movies_run(
    tmp_path,
    movies_source: _MoviesSource,
) -> None:
    """Let the configured live model choose slots, then execute that Recipe."""
    model_id = "global-siliconflow-Qwen/Qwen3.5-27B"
    model_config = ModelRegistry().get_config(model_id)
    assert model_config is not None
    client = Client.from_config(dict(model_config))
    assert client.params["extra_body"] == {"enable_thinking": False}

    data_home = tmp_path / "live-ai-complex-analysis-data-home"
    workspace = _create_movies_workspace(data_home)
    compiled_all, movies = _compile_complex_movies_recipe(
        workspace,
        movies_source.opener,
    )
    compiler = RecipeCompiler.for_workspace(workspace)
    candidates = compiler.parameter_candidates(
        compiled_all.spec.target_artifact_ids
    )
    candidates_by_id = {item.candidate_id: item for item in candidates}
    years = pd.to_datetime(movies["Release Date"], errors="coerce").dt.year
    workflow_request = (
        f"真实 Movies 数据有 {len(movies)} 行、{len(movies.columns)} 列，"
        f"上映年份 {int(years.min())}-{int(years.max())}。"
        "分析不同电影类型中导演组合的利润和投资回报率。"
        "最低两部电影是固定数据质量门槛，不要作为运行输入；"
        "分析起始年份、最低投资回报率、每类保留导演数需要按运行调整。"
        "未来还希望按最低 IMDb 评分筛选。"
    )
    recommendation = suggest_recipe_parameter_configurations(
        client,
        candidates,
        workflow_context={
            "threads": [{
                "thread_id": "live-director-analysis",
                "events": [{
                    "type": "message",
                    "from": "user",
                    "to": "data-agent",
                    "role": "user",
                    "content": workflow_request,
                }],
            }],
        },
        recipe_name="按类型分析导演组合",
        description="定期刷新导演组合的利润、ROI 和类型内排名。",
        language_code="zh",
        timeout_seconds=120,
    )
    recommended_ids = [
        candidates_by_id[item.candidate_id].parameter_id
        for item in recommendation.suggestions
    ]
    assert set(recommended_ids) == {
        "start_year",
        "min_roi",
        "top_directors",
    }
    assert "min_movies" not in recommended_ids
    assert all("IMDb" in item for item in recommendation.unmatched)

    compiled = compiler.compile(
        target_artifact_ids=compiled_all.spec.target_artifact_ids,
        name="按类型分析导演组合",
        description="定期刷新导演组合的利润、ROI 和类型内排名。",
        parameter_configurations=tuple(
            RecipeParameterConfiguration(
                candidate_id=item.candidate_id,
                name=item.name,
                description=item.description,
                mode=item.mode,
            )
            for item in recommendation.suggestions
        ),
    )
    assert {item.id for item in compiled.spec.parameters} == set(
        recommended_ids
    )

    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    recipe_service = RecipeService(recipes)
    draft = recipes.save_draft(workspace, compiled)
    parameter_values = {
        "start_year": 1990,
        "min_roi": 1.0,
        "top_directors": 2,
    }
    _clear_sample_cache()
    dry_run = recipe_service.dry_run(
        workspace,
        draft.version_id,
        parameter_values=parameter_values,
        loader_resolver=lambda source_id: movies_source.opener.open(
            workspace.identity_id,
            source_id,
        ),
    )
    assert dry_run.status.value == "succeeded"
    assert [step.kind.value for step in dry_run.step_results] == [
        "load",
        "transform",
        "transform",
        "chart",
    ]
    published = recipe_service.publish(workspace, draft.version_id)
    automation = AutomationRepository(database_path)
    automation_service = AutomationService(automation, recipes)
    queued = automation_service.enqueue_manual_run(
        workspace,
        published.version_id,
        parameter_values,
    )
    worker = AutomationWorker(
        AutomationRepository(database_path),
        RecipeRepository(database_path),
        LocalWorkspaceOpener(data_home),
        ExplicitConnectorOpener(initialize_registry=False),
        worker_id="live-siliconflow-complex-movies-worker",
        enabled=True,
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: UUID("f" * 32),
    )
    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        _clear_sample_cache()
        finished = worker.run_once()
    assert finished is not None
    assert finished.run_id == queued.run_id
    assert finished.status is AutomationRunStatus.SUCCEEDED

    expected_metrics, expected_ranked = _expected_director_portfolios(
        movies,
        min_movies=2,
        **parameter_values,
    )
    actual_ranked = pd.read_parquet(workspace.confined_root.resolve(
        f"{finished.artifact_path}/workspace/data/ranked_directors.parquet"
    ))
    pd.testing.assert_frame_equal(
        actual_ranked,
        expected_ranked,
        check_exact=False,
        rtol=1e-12,
        atol=1e-9,
    )
    result = automation_service.load_run_result(workspace, finished.run_id)
    assert result.outputs[0]["table"]["row_count"] == len(expected_ranked)
    assert {item["id"] for item in result.report["parameters"]} == set(
        recommended_ids
    )

    print(json.dumps({
        "model": "Qwen/Qwen3.5-27B",
        "thinking": False,
        "dataset": {"rows": len(movies), "columns": len(movies.columns)},
        "recommended": recommended_ids,
        "unmatched": list(recommendation.unmatched),
        "fixed": ["min_movies"],
        "dry_run_steps": [item.kind.value for item in dry_run.step_results],
        "run": {
            "status": finished.status.value,
            "parameters": parameter_values,
            "metric_rows": len(expected_metrics),
            "result_rows": len(actual_ranked),
            "genres": int(actual_ranked["Major Genre"].nunique()),
            "movie_count": int(actual_ranked["movie_count"].sum()),
            "total_profit": float(actual_ranked["total_profit"].sum()),
        },
    }, ensure_ascii=False))


def test_complex_movies_analysis_runs_two_transforms_with_four_parameters(
    tmp_path,
    movies_source: _MoviesSource,
) -> None:
    data_home = tmp_path / "complex-analysis-data-home"
    workspace = _create_movies_workspace(data_home)
    compiled, movies = _compile_complex_movies_recipe(
        workspace,
        movies_source.opener,
    )
    assert [step.kind.value for step in compiled.spec.steps] == [
        "load",
        "transform",
        "transform",
        "chart",
    ]
    parameters_by_id = {item.id: item for item in compiled.spec.parameters}
    assert set(parameters_by_id) == {
        "start_year",
        "min_movies",
        "min_roi",
        "top_directors",
    }
    assert {
        parameter_id: item.value_type.value
        for parameter_id, item in parameters_by_id.items()
    } == {
        "start_year": "integer",
        "min_movies": "integer",
        "min_roi": "number",
        "top_directors": "integer",
    }
    assert all(not item.has_default for item in parameters_by_id.values())

    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    recipe_service = RecipeService(recipes)
    draft = recipes.save_draft(workspace, compiled)
    recent_case = {
        "start_year": 2000,
        "min_movies": 2,
        "min_roi": 0.5,
        "top_directors": 3,
    }
    _clear_sample_cache()
    dry_run = recipe_service.dry_run(
        workspace,
        draft.version_id,
        parameter_values=recent_case,
        loader_resolver=lambda source_id: movies_source.opener.open(
            workspace.identity_id,
            source_id,
        ),
    )
    assert dry_run.status.value == "succeeded"
    assert [step.kind.value for step in dry_run.step_results] == [
        "load",
        "transform",
        "transform",
        "chart",
    ]
    published = recipe_service.publish(workspace, draft.version_id)

    clock_state = {"now": datetime(2026, 8, 21, 8, 59, tzinfo=timezone.utc)}
    automation = AutomationRepository(
        database_path,
        clock=lambda: clock_state["now"],
    )
    service = AutomationService(automation, recipes)
    schedule = service.create_schedule(
        workspace,
        version_id=published.version_id,
        name="Recent proven director portfolios",
        cron_expression="0 9 * * *",
        timezone_name="UTC",
        parameter_policy={
            parameter_id: {"source": "literal", "value": value}
            for parameter_id, value in recent_case.items()
        },
    )
    assert schedule.next_run_at == "2026-08-21T09:00:00.000000Z"
    clock_state["now"] = datetime(2026, 8, 21, 9, tzinfo=timezone.utc)
    scheduled_batch = AutomationScheduler(
        automation,
        clock=lambda: clock_state["now"],
    ).tick()
    assert len(scheduled_batch.runs) == 1
    scheduled_run = scheduled_batch.runs[0]
    assert scheduled_run.schedule_id == schedule.schedule_id
    assert scheduled_run.parameter_values == recent_case

    broad_case = {
        "start_year": 1980,
        "min_movies": 1,
        "min_roi": 0.0,
        "top_directors": 5,
    }
    selective_case = {
        "start_year": 1990,
        "min_movies": 2,
        "min_roi": 1.0,
        "top_directors": 2,
    }
    broad_run = service.enqueue_manual_run(
        workspace,
        published.version_id,
        broad_case,
    )
    selective_run = service.enqueue_manual_run(
        workspace,
        published.version_id,
        selective_case,
    )

    restarted_automation = AutomationRepository(
        database_path,
        clock=lambda: clock_state["now"],
    )
    restarted_recipes = RecipeRepository(database_path)
    complex_attempt_ids = iter((
        UUID("7" * 32),
        UUID("8" * 32),
        UUID("9" * 32),
        UUID("a" * 32),
    ))
    worker = AutomationWorker(
        restarted_automation,
        restarted_recipes,
        LocalWorkspaceOpener(data_home),
        ExplicitConnectorOpener(initialize_registry=False),
        worker_id="complex-movies-worker",
        enabled=True,
        clock=lambda: clock_state["now"],
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: next(complex_attempt_ids),
    )
    finished_by_id = {}
    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        for _ in range(3):
            _clear_sample_cache()
            finished = worker.run_once()
            assert finished is not None
            assert finished.status is AutomationRunStatus.SUCCEEDED
            finished_by_id[finished.run_id] = finished

    cases = {
        scheduled_run.run_id: (recent_case, 209, 22, 8, 72, 20_035_909_513.0),
        broad_run.run_id: (broad_case, 961, 56, 12, 157, 44_053_344_636.0),
        selective_run.run_id: (selective_case, 337, 18, 10, 69, 21_326_749_404.0),
    }
    assert set(finished_by_id) == set(cases)
    assert len({item.binding_hash for item in finished_by_id.values()}) == 3
    assert movies_source.request_count >= 5

    restarted_service = AutomationService(
        restarted_automation,
        restarted_recipes,
    )
    ranked_frames_by_run = {}
    for run_id, (
        parameter_values,
        expected_metric_rows,
        expected_rows,
        expected_genres,
        expected_movie_count,
        expected_profit,
    ) in cases.items():
        finished = finished_by_id[run_id]
        assert finished.parameter_values == parameter_values
        assert finished.artifact_path is not None
        artifact = restarted_service.load_run_artifact(workspace, run_id)
        assert [event["kind"] for event in artifact.events] == [
            "load",
            "load",
            "transform",
            "transform",
            "transform",
            "transform",
            "chart",
            "chart",
        ]
        assert [event["status"] for event in artifact.events] == [
            "started",
            "succeeded",
            "started",
            "succeeded",
            "started",
            "succeeded",
            "started",
            "succeeded",
        ]

        expected_metrics, expected_ranked = _expected_director_portfolios(
            movies,
            **parameter_values,
        )
        metrics_path = workspace.confined_root.resolve(
            f"{finished.artifact_path}/workspace/data/director_metrics.parquet"
        )
        ranked_path = workspace.confined_root.resolve(
            f"{finished.artifact_path}/workspace/data/ranked_directors.parquet"
        )
        actual_metrics = pd.read_parquet(metrics_path)
        actual_ranked = pd.read_parquet(ranked_path)
        pd.testing.assert_frame_equal(
            actual_metrics,
            expected_metrics,
            check_exact=False,
            rtol=1e-12,
            atol=1e-9,
        )
        pd.testing.assert_frame_equal(
            actual_ranked,
            expected_ranked,
            check_exact=False,
            rtol=1e-12,
            atol=1e-9,
        )
        ranked_frames_by_run[run_id] = actual_ranked
        assert len(actual_metrics) == expected_metric_rows
        assert len(actual_ranked) == expected_rows
        assert actual_ranked["Major Genre"].nunique() == expected_genres
        assert int(actual_ranked["movie_count"].sum()) == expected_movie_count
        assert float(actual_ranked["total_profit"].sum()) == pytest.approx(
            expected_profit
        )

        result = restarted_service.load_run_result(workspace, run_id)
        assert len(result.outputs) == 1
        assert result.outputs[0]["title"] == "Top director portfolios by genre"
        assert result.outputs[0]["table"]["row_count"] == expected_rows
        assert {
            item["id"]: (item["name"], item["type"])
            for item in result.report["parameters"]
        } == {
            "start_year": ("Release year from", "integer"),
            "min_movies": ("Minimum movies per director", "integer"),
            "min_roi": ("Minimum ROI", "number"),
            "top_directors": ("Top directors per genre", "integer"),
        }

    # Refresh the same fixed RecipeVersion with a schema-compatible source
    # update. Identical parameters keep the same binding hash, while the
    # immutable result must incorporate the newly fetched business value.
    updated_rows = json.loads(
        (_PROJECT_ROOT / "public" / "df_movies.json").read_text(
            encoding="utf-8"
        )
    )["tables"][0]["rows"]
    avatar = next(row for row in updated_rows if row["Title"] == "Avatar")
    gross_delta = 123_456_789.0
    avatar["Worldwide Gross"] = float(avatar["Worldwide Gross"]) + gross_delta
    movies_source.replace_rows(updated_rows)
    refreshed_run = restarted_service.enqueue_manual_run(
        workspace,
        published.version_id,
        broad_case,
    )
    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        refreshed = worker.run_once()
    assert refreshed is not None
    assert refreshed.run_id == refreshed_run.run_id
    assert refreshed.status is AutomationRunStatus.SUCCEEDED
    assert refreshed.parameter_values == broad_case
    assert refreshed.binding_hash == finished_by_id[broad_run.run_id].binding_hash
    assert refreshed.artifact_path is not None
    assert refreshed.artifact_path != finished_by_id[broad_run.run_id].artifact_path
    assert movies_source.request_count >= 6

    updated_movies = pd.DataFrame(updated_rows)
    expected_refreshed_metrics, expected_refreshed_ranked = (
        _expected_director_portfolios(updated_movies, **broad_case)
    )
    refreshed_metrics = pd.read_parquet(workspace.confined_root.resolve(
        f"{refreshed.artifact_path}/workspace/data/director_metrics.parquet"
    ))
    refreshed_ranked = pd.read_parquet(workspace.confined_root.resolve(
        f"{refreshed.artifact_path}/workspace/data/ranked_directors.parquet"
    ))
    pd.testing.assert_frame_equal(
        refreshed_metrics,
        expected_refreshed_metrics,
        check_exact=False,
        rtol=1e-12,
        atol=1e-9,
    )
    pd.testing.assert_frame_equal(
        refreshed_ranked,
        expected_refreshed_ranked,
        check_exact=False,
        rtol=1e-12,
        atol=1e-9,
    )
    original_broad_ranked = ranked_frames_by_run[broad_run.run_id]
    original_cameron = original_broad_ranked.loc[
        (original_broad_ranked["Major Genre"] == "Action")
        & (original_broad_ranked["Director"] == "James Cameron")
    ].iloc[0]
    refreshed_cameron = refreshed_ranked.loc[
        (refreshed_ranked["Major Genre"] == "Action")
        & (refreshed_ranked["Director"] == "James Cameron")
    ].iloc[0]
    assert float(refreshed_cameron["total_profit"]) == pytest.approx(
        float(original_cameron["total_profit"]) + gross_delta
    )
    assert float(refreshed_ranked["total_profit"].sum()) == pytest.approx(
        float(original_broad_ranked["total_profit"].sum()) + gross_delta
    )

    original_broad_path = workspace.confined_root.resolve(
        f"{finished_by_id[broad_run.run_id].artifact_path}"
        "/workspace/data/ranked_directors.parquet"
    )
    pd.testing.assert_frame_equal(
        pd.read_parquet(original_broad_path),
        original_broad_ranked,
        check_exact=False,
        rtol=1e-12,
        atol=1e-9,
    )


def test_scheduled_movies_recipe_uses_real_http_data_and_executes_three_steps(
    tmp_path,
    movies_source: _MoviesSource,
) -> None:
    data_home = tmp_path / "data-home"
    workspace = _create_movies_workspace(data_home)
    compiled = _compile_movies_recipe(workspace, movies_source.opener)
    database_path = data_home / "automation" / "automation.db"
    recipes = RecipeRepository(database_path)
    draft = recipes.save_draft(workspace, compiled)
    dry_run = RecipeService(recipes).dry_run(
        workspace,
        draft.version_id,
        parameter_values={},
        loader_resolver=lambda source_id: movies_source.opener.open(
            workspace.identity_id,
            source_id,
        ),
    )
    assert dry_run.reference is not None
    assert [step.kind.value for step in dry_run.step_results] == [
        "load",
        "transform",
        "chart",
    ]
    published = RecipeService(recipes).publish(workspace, draft.version_id)

    now = datetime(2026, 8, 21, 9, tzinfo=timezone.utc)
    clock = lambda: now
    automation = AutomationRepository(database_path, clock=clock)
    schedule = automation.create_schedule(
        identity_id=workspace.identity_id,
        workspace_id=workspace.workspace_id,
        version_id=published.version_id,
        name="Daily Movies summary",
        cron_expression="0 9 * * *",
        timezone_name="UTC",
        next_run_at=now,
        schedule_id="sch_" + "9" * 32,
    )
    scheduled = AutomationScheduler(automation, clock=clock).tick()
    assert len(scheduled.runs) == 1
    assert scheduled.runs[0].schedule_id == schedule.schedule_id

    # Model the Web/Worker process boundary: discard the sample cache and
    # reconstruct every repository, opener, and Worker from durable paths.
    _clear_sample_cache()
    restarted_automation = AutomationRepository(database_path, clock=clock)
    restarted_recipes = RecipeRepository(database_path)
    restarted_connector_opener = ExplicitConnectorOpener(
        initialize_registry=False
    )
    worker = AutomationWorker(
        restarted_automation,
        restarted_recipes,
        LocalWorkspaceOpener(data_home),
        restarted_connector_opener,
        worker_id="movies-worker",
        enabled=True,
        clock=clock,
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: UUID("a" * 32),
    )

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        finished = worker.run_once()

    assert finished is not None
    assert finished.status is AutomationRunStatus.SUCCEEDED
    assert finished.attempt_count == 1
    assert movies_source.request_count >= 2

    automation_service = AutomationService(
        restarted_automation,
        restarted_recipes,
    )
    stored = automation_service.load_run_artifact(workspace, finished.run_id)
    assert [event["kind"] for event in stored.events] == [
        "load",
        "load",
        "transform",
        "transform",
        "chart",
        "chart",
    ]
    assert [event["status"] for event in stored.events] == [
        "started",
        "succeeded",
        "started",
        "succeeded",
        "started",
        "succeeded",
    ]

    result = automation_service.load_run_result(workspace, finished.run_id)
    assert result.artifact == stored
    assert result.report == {
        "title": "Movies by genre",
        "description": "",
        "parameters": [],
        "steps": [
                {
                    "step_id": compiled.spec.steps[0].id,
                    "kind": "load",
                    "title": "Movies",
                },
            {
                "step_id": compiled.spec.steps[1].id,
                "kind": "transform",
                "title": "genre_summary",
            },
            {
                "step_id": compiled.spec.steps[2].id,
                "kind": "chart",
                "title": "Movies by genre",
            },
        ],
    }
    assert len(result.outputs) == 1
    result_output = result.outputs[0]
    assert result_output["kind"] == "chart"
    assert result_output["title"] == "Movies by genre"
    assert result_output["subtitle"] == "Packaged 3,201-row sample"
    assert result_output["chart"]["spec"] == {
        "chart_type": "Bar Chart",
        "encodings": {
            "x": "Major Genre",
            "y": "movie_count",
        },
    }
    preview = result_output["table"]
    assert preview["name"] == "genre_summary"
    assert preview["row_count"] == 12
    assert preview["column_count"] == 3
    assert preview["rows_truncated"] is False
    assert preview["columns_truncated"] is False
    preview_by_genre = {row["Major Genre"]: row for row in preview["rows"]}
    assert preview_by_genre["Drama"]["movie_count"] == 789
    assert preview_by_genre["Drama"]["worldwide_gross"] == pytest.approx(
        40_476_168_953.0
    )

    assert finished.artifact_path is not None
    output_path = workspace.confined_root.resolve(
        f"{finished.artifact_path}/workspace/data/genre_summary.parquet"
    )
    output = pd.read_parquet(output_path)
    assert len(output) == 12
    assert int(output["movie_count"].sum()) == 2926
    drama = output.loc[output["Major Genre"] == "Drama"].iloc[0]
    assert int(drama["movie_count"]) == 789
    assert float(drama["worldwide_gross"]) == pytest.approx(40_476_168_953.0)

    # The same fixed RecipeVersion must fail closed when the source schema
    # becomes incompatible; it must not reuse the previous successful data.
    movies_source.replace_rows([
        {"region": "west", "amount": 30},
        {"region": "east", "amount": 40},
    ])
    drift_run = AutomationService(
        restarted_automation,
        restarted_recipes,
    ).enqueue_manual_run(workspace, published.version_id)
    drift_worker = AutomationWorker(
        restarted_automation,
        restarted_recipes,
        LocalWorkspaceOpener(data_home),
        ExplicitConnectorOpener(initialize_registry=False),
        worker_id="movies-drift-worker",
        enabled=True,
        clock=clock,
        lease_duration=timedelta(seconds=30),
        attempt_id_factory=lambda: UUID("b" * 32),
    )

    with patch(
        "litellm.completion",
        side_effect=AssertionError("Automation execution must not call an LLM"),
    ):
        drifted = drift_worker.run_once()

    assert drifted is not None
    assert drifted.run_id == drift_run.run_id
    assert drifted.status is AutomationRunStatus.NEEDS_REVIEW
    assert drifted.attempt_count == 1
    assert drifted.error_code == "schema_drift"
    assert movies_source.request_count >= 3
    drift_artifact = AutomationService(
        restarted_automation,
        restarted_recipes,
    ).load_run_artifact(workspace, drifted.run_id)
    assert [(event["kind"], event["status"]) for event in drift_artifact.events] == [
        ("load", "started"),
        ("load", "needs_review"),
    ]
