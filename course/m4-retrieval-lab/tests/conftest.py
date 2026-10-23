import re
import shutil
import subprocess
import time
from pathlib import Path

import psycopg
import pytest
import yaml
from pgvector.psycopg import register_vector
from psycopg import sql
from retrieval_lab.types import GoldenQuery

LAB = Path(__file__).resolve().parent.parent
REPO_ROOT = LAB.parent.parent
CORPUS = REPO_ROOT / "fixtures" / "corpus"
IMAGE = "pgvector/pgvector:pg17"
PASSWORD = "miubais"
READY_TIMEOUT = 60.0
LABEL = "miubais=m4-tests"
STALE_SECONDS = 3600


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model; deselected under offline grading")


@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    return CORPUS


@pytest.fixture(scope="session")
def golden() -> list[GoldenQuery]:
    raw = yaml.safe_load((CORPUS / "golden.yaml").read_text(encoding="utf-8"))["queries"]
    return [GoldenQuery(**q) for q in raw]


def _docker(*args: str) -> str:
    proc = subprocess.run(
        ["docker", *args], check=True, capture_output=True, text=True, timeout=120
    )
    return proc.stdout.strip()


def _docker_running() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        return (
            subprocess.run(
                ["docker", "info"], check=False, capture_output=True, timeout=15
            ).returncode
            == 0
        )
    except subprocess.TimeoutExpired:
        return False


def _wait_ready(dsn: str, container: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=2) as conn:
                conn.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            time.sleep(0.2)
    logs = subprocess.run(
        ["docker", "logs", "--tail", "20", container], check=False, capture_output=True
    )
    raise RuntimeError(
        f"postgres in {container[:12]} not ready after {READY_TIMEOUT:.0f} s:\n"
        + logs.stdout.decode(errors="replace")
        + logs.stderr.decode(errors="replace")
    )


def _stop_stale_containers() -> None:
    # a grader timeout SIGKILLs pytest, so its finally never stops the container
    listed = _docker(
        "ps", "--filter", f"label={LABEL}", "--format", '{{.ID}} {{.Label "miubais.started"}}'
    )
    for line in listed.splitlines():
        container, _, started = line.partition(" ")
        if not started.isdigit() or time.time() - int(started) > STALE_SECONDS:
            subprocess.run(
                ["docker", "stop", container], check=False, capture_output=True, timeout=60
            )


@pytest.fixture(scope="session")
def pg_dsn():
    if not _docker_running():
        pytest.skip("needs docker: `docker info` failed, start Docker to grade stages 02-06")
    _stop_stale_containers()
    container = _docker(
        "run", "-d", "--rm", "-e", f"POSTGRES_PASSWORD={PASSWORD}",
        "--label", LABEL, "--label", f"miubais.started={int(time.time())}",
        "-p", "127.0.0.1:0:5432", IMAGE,
    )  # fmt: skip
    try:
        port = _docker("port", container, "5432").splitlines()[0].rsplit(":", 1)[1]
        dsn = f"postgresql://postgres:{PASSWORD}@127.0.0.1:{port}/postgres"
        _wait_ready(dsn, container)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        yield dsn
    finally:
        subprocess.run(["docker", "stop", container], check=False, capture_output=True, timeout=60)


@pytest.fixture(scope="module")
def conn(pg_dsn, request):
    schema = "lab_" + re.sub(r"\W", "_", request.module.__name__.rsplit(".", 1)[-1])
    with psycopg.connect(pg_dsn, autocommit=True) as connection:
        name = sql.Identifier(schema)
        connection.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(name))
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(name))
        connection.execute(sql.SQL("SET search_path TO {}, public").format(name))
        register_vector(connection)
        yield connection
