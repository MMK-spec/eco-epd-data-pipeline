#!/usr/bin/env python3
"""
EPD data pipeline orchestrator.

Recommended Docker usage:
    docker compose run --rm pipeline python scripts/run_pipeline.py run-all rebar --init-db -y
    docker compose run --rm pipeline python scripts/run_pipeline.py transform-test
    docker compose run --rm pipeline python scripts/run_pipeline.py summary
    docker compose run --rm pipeline python scripts/run_pipeline.py provision-superset

If PIPELINE_KEYWORDS is set in .env, this also works:
    docker compose run --rm pipeline python scripts/run_pipeline.py run-all --init-db -y

Stages:
1. Optional DB object creation from 00_create_objects.sql
2. API extraction + staging load through api_request.py
3. Mart transformation through 01_transform.sql
4. Quality tests through 02_quality_tests_fixed.sql
5. Optional summary output
6. Optional Superset database + dataset provisioning through the Superset REST API
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from urllib.parse import urljoin

import requests
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv
from psycopg2 import OperationalError, connect
from psycopg2.extras import RealDictCursor


COMMANDS = {"run-all", "init-db", "load", "transform-test", "transform", "test", "summary"}

DEFAULT_API_SCRIPT_NAMES = ("api_request.py", "API request.py", "otsing_updated_v2.py", "otsing.py")
DEFAULT_CREATE_SQL_NAMES = ("00_create_objects.sql", "00_create_objects(1).sql")
DEFAULT_TRANSFORM_SQL_NAMES = ("01_transform.sql", "01_transform(1).sql")
DEFAULT_TEST_SQL_NAMES = ("02_quality_tests_fixed.sql", "02_quality_tests.sql", "02_quality_tests(1).sql")


class PipelineError(RuntimeError):
    """Raised when a pipeline stage fails."""


def now_label() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def log(message: str) -> None:
    print(f"[{now_label()}] {message}", flush=True)


def load_environment(script_dir: Path) -> None:
    """Load .env from common locations without failing if one location is missing."""
    load_dotenv(script_dir / ".env")
    load_dotenv(script_dir.parent / ".env")
    load_dotenv(Path.cwd() / ".env")
    load_dotenv()


def resolve_path(script_dir: Path, explicit_path: str | None, candidates: Iterable[str], label: str) -> Path:
    """Resolve explicit path or find first candidate next to this script."""
    if explicit_path:
        raw_path = Path(explicit_path)
        attempted: list[Path] = []

        if raw_path.is_absolute():
            attempted.append(raw_path)
        else:
            attempted.extend([Path.cwd() / raw_path, script_dir / raw_path, script_dir.parent / raw_path])

        for path in attempted:
            if path.exists():
                return path.resolve()

        attempted_text = ", ".join(str(path) for path in attempted)
        raise FileNotFoundError(f"{label} file not found. Tried: {attempted_text}")

    for name in candidates:
        for base_dir in (script_dir, script_dir.parent, Path.cwd()):
            path = base_dir / name
            if path.exists():
                return path.resolve()

    candidate_text = ", ".join(candidates)
    raise FileNotFoundError(f"{label} file not found. Tried candidate names: {candidate_text}")


def get_db_connection():
    missing = [
        name
        for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")
        if not os.getenv(name)
    ]
    if missing:
        raise PipelineError(f"Missing .env variables: {', '.join(missing)}")

    host = os.getenv("POSTGRES_HOST") or os.getenv("DB_HOST") or "localhost"

    explicit_port = os.getenv("POSTGRES_PORT") or os.getenv("DB_PORT_CONTAINER")
    if explicit_port:
        port = explicit_port
    elif host in {"localhost", "127.0.0.1", "host.docker.internal"}:
        port = os.getenv("DB_PORT_HOST") or "5432"
    else:
        port = "5432"

    return connect(
        host=host,
        port=port,
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )


def wait_for_db(max_attempts: int = 30, delay_seconds: int = 2) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            log("Database is ready")
            return
        except OperationalError as exc:
            if attempt == max_attempts:
                raise PipelineError(f"Database did not become ready after {max_attempts} attempts: {exc}") from exc
            log(f"Database not ready yet, retrying ({attempt}/{max_attempts})")
            time.sleep(delay_seconds)


def run_sql_file(sql_file: Path, stage_name: str) -> None:
    sql = sql_file.read_text(encoding="utf-8").strip()
    if not sql:
        raise PipelineError(f"{stage_name} SQL file is empty: {sql_file}")

    log(f"Starting {stage_name}: {sql_file}")
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
    except Exception as exc:
        raise PipelineError(f"{stage_name} failed while running {sql_file}: {exc}") from exc
    log(f"Finished {stage_name}")


def run_api_loader(
    api_script: Path,
    keywords: list[str],
    output_file: Path | None,
    yes: bool,
    extra_api_args: list[str],
) -> None:
    if not keywords:
        raise PipelineError(
            "No API search keywords provided. Use, for example, 'run-all rebar', "
            "or set PIPELINE_KEYWORDS=rebar in .env."
        )

    command = [sys.executable, str(api_script), *keywords]

    if output_file:
        command.extend(["--output", str(output_file)])

    if yes:
        command.append("--yes")

    if extra_api_args:
        command.extend(extra_api_args)

    printable_command = " ".join(shlex.quote(part) for part in command)
    log(f"Starting API load through: {api_script.name}")
    log(f"Command: {printable_command}")

    completed = subprocess.run(command, cwd=str(api_script.parent))
    if completed.returncode != 0:
        raise PipelineError(f"API loading failed with exit code {completed.returncode}")

    log("Finished API load")


def fetch_latest_run() -> dict | None:
    query = """
        SELECT run_id, fetched_at, source_name, status, message
        FROM staging.pipeline_runs
        ORDER BY fetched_at DESC
        LIMIT 1
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            row = cur.fetchone()
            return dict(row) if row else None


def fetch_row_counts_for_latest_successful_run() -> dict:
    query = """
        WITH latest_run AS (
            SELECT run_id
            FROM staging.pipeline_runs
            WHERE status = 'success'
            ORDER BY fetched_at DESC
            LIMIT 1
        )
        SELECT
            (SELECT run_id::text FROM latest_run) AS run_id,
            (
                SELECT COUNT(*)::integer
                FROM staging.eco_epd_raw AS e
                INNER JOIN latest_run AS r ON e.run_id = r.run_id
            ) AS staging_rows,
            (
                SELECT COUNT(*)::integer
                FROM mart.eco_epd AS e
                INNER JOIN latest_run AS r ON e.run_id = r.run_id
            ) AS mart_rows
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            row = cur.fetchone()
            return dict(row) if row else {"run_id": None, "staging_rows": 0, "mart_rows": 0}


def fetch_quality_results() -> list[dict]:
    query = """
        SELECT test_name, status, failed_rows, message, test_run_at
        FROM quality.test_results
        ORDER BY
            CASE WHEN status <> 'passed' THEN 0 ELSE 1 END,
            test_name
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            return [dict(row) for row in cur.fetchall()]


def fetch_latest_mart_rows(limit: int) -> list[dict]:
    query = """
        SELECT
            uuid,
            version,
            location_code,
            declaration_owner,
            quantity,
            ref_unit,
            gwp_total_a1a3,
            gwp_control,
            fetched_at
        FROM mart.latest_eco_epd
        ORDER BY uuid
        LIMIT %s
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (limit,))
            return [dict(row) for row in cur.fetchall()]


def print_quality_results(require_passed: bool = False) -> None:
    results = fetch_quality_results()
    if not results:
        raise PipelineError("No rows found in quality.test_results.")

    log("Quality test results:")
    for row in results:
        log(
            f"  {row['status'].upper():6} | "
            f"{row['test_name']} | failed_rows={row['failed_rows']} | {row['message']}"
        )

    failed = [row for row in results if row["status"] != "passed"]
    if require_passed and failed:
        failed_names = ", ".join(row["test_name"] for row in failed)
        raise PipelineError(f"Quality tests failed: {failed_names}")


def print_summary(show_rows: int = 10) -> None:
    latest_run = fetch_latest_run()
    if latest_run:
        log(
            "Latest pipeline run: "
            f"run_id={latest_run['run_id']} | status={latest_run['status']} | "
            f"fetched_at={latest_run['fetched_at']} | message={latest_run['message']}"
        )
    else:
        log("No pipeline runs found yet")

    counts = fetch_row_counts_for_latest_successful_run()
    log(
        "Latest successful run counts: "
        f"run_id={counts['run_id']} | staging_rows={counts['staging_rows']} | mart_rows={counts['mart_rows']}"
    )

    if show_rows > 0:
        rows = fetch_latest_mart_rows(show_rows)
        log(f"mart.latest_eco_epd sample rows: {len(rows)}")
        for row in rows:
            log(
                "  "
                f"uuid={row['uuid']} | version={row['version']} | "
                f"qty={row['quantity']} {row['ref_unit']} | "
                f"gwp_total={row['gwp_total_a1a3']} | owner={row['declaration_owner']}"
            )

    try:
        print_quality_results(require_passed=False)
    except Exception as exc:
        log(f"Quality results unavailable: {exc}")



def env_first(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def parse_dataset_specs(raw_specs: list[str] | None = None) -> list[tuple[str, str]]:
    specs = raw_specs or []
    if not specs:
        raw = os.getenv("SUPERSET_DATASETS") or "mart.latest_eco_epd,mart.eco_epd,quality.test_results"
        specs = [part.strip() for part in raw.split(",") if part.strip()]

    parsed: list[tuple[str, str]] = []
    for spec in specs:
        text = spec.strip()
        if not text:
            continue
        if ":" in text:
            schema, table = text.split(":", 1)
        elif "." in text:
            schema, table = text.split(".", 1)
        else:
            raise PipelineError(
                f"Invalid Superset dataset spec '{spec}'. Use schema.table, e.g. mart.latest_eco_epd."
            )
        parsed.append((schema.strip(), table.strip()))

    if not parsed:
        raise PipelineError("No Superset datasets specified.")

    return parsed


def build_epd_sqlalchemy_uri(explicit_uri: str | None = None) -> str:
    if explicit_uri:
        return explicit_uri

    env_uri = os.getenv("SUPERSET_EPD_SQLALCHEMY_URI") or os.getenv("EPD_SQLALCHEMY_URI")
    if env_uri:
        return env_uri

    db_name = os.getenv("POSTGRES_DB")
    if not db_name:
        raise PipelineError("POSTGRES_DB is missing; cannot build Superset EPD database URI.")

    user = env_first("SUPERSET_READER_USER", "SUPERSET_EPD_USER", "POSTGRES_USER")
    password = env_first("SUPERSET_READER_PASSWORD", "SUPERSET_EPD_PASSWORD", "POSTGRES_PASSWORD")
    host = env_first("SUPERSET_EPD_DB_HOST", "POSTGRES_HOST", "DB_HOST", default="db")
    if host in {"localhost", "127.0.0.1"} and os.getenv("RUNNING_IN_DOCKER", "1") != "0":
        # When run_pipeline.py runs inside Docker, Superset also needs the Docker service name.
        host = "db"
    port = env_first("SUPERSET_EPD_DB_PORT", "DB_PORT_CONTAINER", default="5432")

    if not user or not password:
        raise PipelineError(
            "Missing database credentials for Superset. Set SUPERSET_READER_USER and "
            "SUPERSET_READER_PASSWORD, or POSTGRES_USER and POSTGRES_PASSWORD."
        )

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"


class SupersetClient:
    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/") + "/"
        self.username = username
        self.password = password
        self.session = requests.Session()

    def url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def request(self, method: str, path: str, **kwargs):
        response = self.session.request(method, self.url(path), timeout=60, **kwargs)
        if response.status_code >= 400:
            raise PipelineError(
                f"Superset API {method.upper()} {path} failed with {response.status_code}: {response.text[:1000]}"
            )
        if not response.text:
            return {}
        return response.json()

    def login(self) -> None:
        payload = {
            "username": self.username,
            "password": self.password,
            "provider": "db",
            "refresh": True,
        }
        data = self.request("post", "/api/v1/security/login", json=payload)
        token = data.get("access_token") or data.get("result", {}).get("access_token")
        if not token:
            raise PipelineError(f"Superset login succeeded but no access token was returned: {data}")

        self.session.headers.update({"Authorization": f"Bearer {token}"})

        csrf_data = self.request("get", "/api/v1/security/csrf_token/")
        csrf_token = csrf_data.get("result") or csrf_data.get("csrf_token")
        if csrf_token:
            self.session.headers.update({"X-CSRFToken": csrf_token})

    def list_objects(self, endpoint: str) -> list[dict]:
        # Superset list responses have changed shape across versions. This parser handles
        # both {'result': {'data': [...]}} and {'result': [...]} forms.
        data = self.request("get", endpoint)
        result = data.get("result", data)
        if isinstance(result, dict):
            objects = result.get("data") or result.get("result") or []
        elif isinstance(result, list):
            objects = result
        else:
            objects = []
        return objects if isinstance(objects, list) else []

    def find_database(self, database_name: str) -> dict | None:
        for item in self.list_objects("/api/v1/database/?page_size=500"):
            if item.get("database_name") == database_name:
                return item
        return None

    def create_database(self, database_name: str, sqlalchemy_uri: str) -> dict:
        payload = {
            "database_name": database_name,
            "sqlalchemy_uri": sqlalchemy_uri,
            "expose_in_sqllab": True,
            "allow_run_async": False,
            "allow_ctas": False,
            "allow_cvas": False,
            "allow_dml": False,
        }
        try:
            data = self.request("post", "/api/v1/database/", json=payload)
            return data.get("result", data)
        except PipelineError as exc:
            # If it already exists, fetch and continue idempotently.
            existing = self.find_database(database_name)
            if existing:
                log(f"Superset database already exists: {database_name}")
                return existing
            raise exc

    def get_or_create_database(self, database_name: str, sqlalchemy_uri: str) -> dict:
        existing = self.find_database(database_name)
        if existing:
            log(f"Superset database exists: {database_name} (id={existing.get('id')})")
            return existing

        created = self.create_database(database_name, sqlalchemy_uri)

        # Superset 6 may return the created database object without numeric "id".
        # Dataset creation still needs that numeric id, so fetch the database list again
        # after creation and merge the richer/list response back into the created object.
        if created.get("id") is None:
            refreshed = self.find_database(database_name)
            if refreshed:
                created = {**created, **refreshed}

        log(f"Created Superset database: {database_name} (id={created.get('id')})")
        return created

    def find_dataset(self, database_id: int, schema: str, table_name: str) -> dict | None:
        for item in self.list_objects("/api/v1/dataset/?page_size=1000"):
            item_schema = item.get("schema")
            item_table = item.get("table_name")
            item_database = item.get("database")

            item_db_id = None
            if isinstance(item_database, dict):
                item_db_id = item_database.get("id")
            elif isinstance(item_database, int):
                item_db_id = item_database
            elif item.get("database_id") is not None:
                item_db_id = item.get("database_id")

            if item_schema == schema and item_table == table_name and int(item_db_id or -1) == int(database_id):
                return item
        return None

    def create_dataset(self, database_id: int, schema: str, table_name: str) -> dict:
        payload = {
            "database": database_id,
            "schema": schema,
            "table_name": table_name,
        }
        try:
            data = self.request("post", "/api/v1/dataset/", json=payload)
            return data.get("result", data)
        except PipelineError as exc:
            existing = self.find_dataset(database_id, schema, table_name)
            if existing:
                log(f"Superset dataset already exists: {schema}.{table_name}")
                return existing
            raise exc

    def get_or_create_dataset(self, database_id: int, schema: str, table_name: str) -> dict:
        existing = self.find_dataset(database_id, schema, table_name)
        if existing:
            log(f"Superset dataset exists: {schema}.{table_name} (id={existing.get('id')})")
            return existing
        created = self.create_dataset(database_id, schema, table_name)
        log(f"Created Superset dataset: {schema}.{table_name} (id={created.get('id')})")
        return created


def wait_for_superset(base_url: str, max_attempts: int = 30, delay_seconds: int = 2) -> None:
    health_url = base_url.rstrip("/") + "/health"
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(health_url, timeout=10)
            if response.status_code < 500:
                log("Superset is reachable")
                return
        except requests.RequestException:
            pass

        if attempt == max_attempts:
            raise PipelineError(f"Superset did not become reachable at {health_url}")
        log(f"Superset not ready yet, retrying ({attempt}/{max_attempts})")
        time.sleep(delay_seconds)


def provision_superset(
    superset_url: str | None,
    database_name: str | None,
    sqlalchemy_uri: str | None,
    dataset_specs: list[str] | None,
) -> None:
    base_url = superset_url or os.getenv("SUPERSET_URL") or "http://superset:8088"
    username = env_first("SUPERSET_ADMIN_USER", "SUPERSET_ADMIN_USERNAME", "ADMIN_USERNAME", default="admin")
    password = env_first("SUPERSET_ADMIN_PASSWORD", "ADMIN_PASSWORD")
    if not password:
        raise PipelineError("Missing SUPERSET_ADMIN_PASSWORD or ADMIN_PASSWORD for Superset API login.")

    final_database_name = database_name or os.getenv("SUPERSET_EPD_DATABASE_NAME") or "EPD mart"
    final_sqlalchemy_uri = build_epd_sqlalchemy_uri(sqlalchemy_uri)
    datasets = parse_dataset_specs(dataset_specs)

    log(f"Provisioning Superset at {base_url}")
    wait_for_superset(base_url)

    client = SupersetClient(base_url, username, password)
    client.login()

    database = client.get_or_create_database(final_database_name, final_sqlalchemy_uri)
    database_id = database.get("id")

    if database_id is None:
        # One more refresh makes this robust against Superset API responses that include
        # only UUID/connection metadata immediately after creation.
        refreshed = client.find_database(final_database_name)
        if refreshed:
            database_id = refreshed.get("id")

    if database_id is None:
        raise PipelineError(
            "Could not determine Superset database numeric id. "
            "The database connection was probably created, but Superset did not return its id. "
            "Open Superset → Settings → Database Connections to verify it exists, then rerun "
            "`python scripts/run_pipeline.py provision-superset`. "
            f"Last response: {database}"
        )

    for schema, table_name in datasets:
        client.get_or_create_dataset(int(database_id), schema, table_name)

    log("Superset provisioning finished")

def env_keywords() -> list[str]:
    raw = os.getenv("PIPELINE_KEYWORDS") or os.getenv("DEFAULT_KEYWORDS") or ""
    return shlex.split(raw)


def add_superset_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provision-superset", action="store_true", help="Create/update Superset database and datasets after the pipeline run.")
    parser.add_argument("--superset-url", default=None, help="Superset base URL. Default: SUPERSET_URL or http://superset:8088.")
    parser.add_argument("--superset-database-name", default=None, help="Superset display name for the EPD database. Default: SUPERSET_EPD_DATABASE_NAME or EPD mart.")
    parser.add_argument("--superset-sqlalchemy-uri", default=None, help="SQLAlchemy URI Superset uses to reach the EPD database. Default is built from env vars.")
    parser.add_argument("--superset-dataset", action="append", default=[], help="Dataset to create, e.g. mart.latest_eco_epd. Can be repeated.")


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-script", default=None, help="Path to API loader. Default: api_request.py.")
    parser.add_argument("--create-sql", default=None, help="Path to DB creation SQL. Default: 00_create_objects.sql.")
    parser.add_argument("--transform-sql", default=None, help="Path to transform SQL. Default: 01_transform.sql.")
    parser.add_argument("--test-sql", default=None, help="Path to quality test SQL. Default: 02_quality_tests_fixed.sql.")
    parser.add_argument("--output", default=None, help="CSV output path passed to API script.")
    parser.add_argument("-y", "--yes", action="store_true", help="Pass --yes to API script.")
    parser.add_argument("--api-arg", action="append", default=[], help="Extra argument passed to API script. Can be repeated.")
    parser.add_argument("--summary-rows", type=int, default=10, help="Number of mart rows to print in summary.")
    add_superset_options(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Orchestrate EPD loading, transformation, and quality tests.")
    subparsers = parser.add_subparsers(dest="command")

    run_all = subparsers.add_parser("run-all", help="Run DB init optionally, API load, transform, tests, summary.")
    run_all.add_argument("keywords", nargs="*", help="Search keywords, e.g. rebar or steel rebar.")
    run_all.add_argument("--init-db", action="store_true", help="Run 00_create_objects.sql first.")
    run_all.add_argument("--skip-tests", action="store_true", help="Skip quality tests.")
    add_common_options(run_all)

    init_db = subparsers.add_parser("init-db", help="Create database schemas/tables/views only.")
    add_common_options(init_db)

    load = subparsers.add_parser("load", help="Run API load only.")
    load.add_argument("keywords", nargs="*", help="Search keywords, e.g. rebar.")
    add_common_options(load)

    transform = subparsers.add_parser("transform", help="Run transform SQL only.")
    add_common_options(transform)

    test = subparsers.add_parser("test", help="Run quality tests only.")
    add_common_options(test)

    transform_test = subparsers.add_parser("transform-test", help="Run transform SQL, then tests and summary.")
    add_common_options(transform_test)

    provision = subparsers.add_parser("provision-superset", help="Create/update Superset database connection and datasets.")
    add_superset_options(provision)

    summary = subparsers.add_parser("summary", help="Print latest run counts, mart sample rows, and test results.")
    summary.add_argument("--summary-rows", type=int, default=10, help="Number of mart rows to print.")

    # Backward-compatible mode: `python run_pipeline.py rebar --init-db -y`
    parser.add_argument("legacy_keywords", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--init-db", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-load", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-transform", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-tests", action="store_true", help=argparse.SUPPRESS)
    add_common_options(parser)

    return parser


def resolve_runtime_files(script_dir: Path, args: argparse.Namespace) -> dict[str, Path]:
    return {
        "api_script": resolve_path(script_dir, getattr(args, "api_script", None), DEFAULT_API_SCRIPT_NAMES, "API loader"),
        "create_sql": resolve_path(script_dir, getattr(args, "create_sql", None), DEFAULT_CREATE_SQL_NAMES, "Create-objects SQL"),
        "transform_sql": resolve_path(script_dir, getattr(args, "transform_sql", None), DEFAULT_TRANSFORM_SQL_NAMES, "Transform SQL"),
        "test_sql": resolve_path(script_dir, getattr(args, "test_sql", None), DEFAULT_TEST_SQL_NAMES, "Quality-test SQL"),
    }


def resolve_output_file(script_dir: Path, output: str | None) -> Path | None:
    if not output:
        return None
    raw_path = Path(output)
    if raw_path.is_absolute():
        return raw_path
    return (Path.cwd() / raw_path).resolve()


def command_keywords(args: argparse.Namespace) -> list[str]:
    keywords = getattr(args, "keywords", None)
    if keywords:
        return keywords
    return env_keywords()


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    load_environment(script_dir)

    parser = build_parser()
    args = parser.parse_args()

    # Backward compatibility: if no subcommand is provided, old behavior is run-all.
    if not args.command:
        args.command = "run-all"
        args.keywords = args.legacy_keywords or env_keywords()

    try:
        log(f"Pipeline command: {args.command}")
        wait_for_db()

        if args.command == "summary":
            print_summary(show_rows=args.summary_rows)
            return 0

        if args.command == "provision-superset":
            provision_superset(
                getattr(args, "superset_url", None),
                getattr(args, "superset_database_name", None),
                getattr(args, "superset_sqlalchemy_uri", None),
                getattr(args, "superset_dataset", None),
            )
            return 0

        files = resolve_runtime_files(script_dir, args)
        output_file = resolve_output_file(script_dir, getattr(args, "output", None))

        if args.command == "init-db":
            run_sql_file(files["create_sql"], "database object creation")
            log("Database initialized successfully")
            return 0

        if args.command == "load":
            run_api_loader(files["api_script"], command_keywords(args), output_file, args.yes, args.api_arg)
            print_summary(show_rows=args.summary_rows)
            return 0

        if args.command == "transform":
            run_sql_file(files["transform_sql"], "mart transformation")
            print_summary(show_rows=args.summary_rows)
            return 0

        if args.command == "test":
            run_sql_file(files["test_sql"], "quality tests")
            print_quality_results(require_passed=True)
            return 0

        if args.command == "transform-test":
            run_sql_file(files["transform_sql"], "mart transformation")
            run_sql_file(files["test_sql"], "quality tests")
            print_summary(show_rows=args.summary_rows)
            print_quality_results(require_passed=True)
            if getattr(args, "provision_superset", False):
                provision_superset(
                    getattr(args, "superset_url", None),
                    getattr(args, "superset_database_name", None),
                    getattr(args, "superset_sqlalchemy_uri", None),
                    getattr(args, "superset_dataset", None),
                )
            log("Transform + tests finished successfully")
            return 0

        if args.command == "run-all":
            log("Full pipeline started")
            if getattr(args, "init_db", False):
                run_sql_file(files["create_sql"], "database object creation")

            run_api_loader(files["api_script"], command_keywords(args), output_file, args.yes, args.api_arg)
            run_sql_file(files["transform_sql"], "mart transformation")

            if not getattr(args, "skip_tests", False):
                run_sql_file(files["test_sql"], "quality tests")
                print_summary(show_rows=args.summary_rows)
                print_quality_results(require_passed=True)
            else:
                log("Skipping quality tests (--skip-tests)")
                print_summary(show_rows=args.summary_rows)

            if getattr(args, "provision_superset", False):
                provision_superset(
                    getattr(args, "superset_url", None),
                    getattr(args, "superset_database_name", None),
                    getattr(args, "superset_sqlalchemy_uri", None),
                    getattr(args, "superset_dataset", None),
                )

            log("Full pipeline finished successfully")
            return 0

        raise PipelineError(f"Unknown command: {args.command}")

    except Exception as exc:
        log(f"PIPELINE FAILED: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
