import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from harnesskit.testing import scripted_query
from retrieval_lab import answer, metrics, rerank, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import HashEmbedder

QUERY_IDS = ("q03", "q40", "q46")
MAX_TOTAL_USD = 0.20


def logged_in() -> bool:
    try:
        from miubais.model import claude_available
    except ImportError:
        proc = subprocess.run(
            ["claude", "auth", "status"], check=False, capture_output=True, text=True, timeout=30
        )
        return proc.returncode == 0 and '"loggedIn": true' in proc.stdout
    return claude_available()


@pytest.fixture(scope="module")
def indexed(conn, corpus_dir):
    embedder = HashEmbedder()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    return embedder, chunks


@pytest.fixture
def picked(golden):
    by_id = {q.id: q for q in golden}
    return [by_id[i] for i in QUERY_IDS]


@pytest.fixture
def workspace() -> Path:
    root = os.environ.get("MIUBAIS_WORKSPACE")
    if not root:
        pytest.fail("set MIUBAIS_WORKSPACE to your workspace (miubais check sets it for you)")
    return Path(root)


def ask(conn, indexed, q, query_fn=None) -> dict:
    embedder, chunks = indexed
    found, scores = answer.sources(conn, embedder, rerank.LexicalReranker(), q.query)
    draft = answer.assemble(q.query, found, scores=scores)
    reply = answer.run(q.query, draft, query_fn=query_fn)
    rel = metrics.relevant(chunks, q)
    cited = [draft.citations[n - 1] for n in reply.faithfulness.cited]
    return {
        "id": q.id,
        "kind": q.kind,
        "refused": reply.faithfulness.refused,
        "cited": cited,
        "cites_relevant": bool(rel & set(cited)),
        "uncited_claims": reply.faithfulness.uncited_claims,
        "invalid_citations": answer.invalid_citations(reply.text, draft.citations),
        "cost_usd": reply.cost_usd,
        "text": reply.text,
    }


def aggregate(answers: list[dict]) -> dict:
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "stage": "09-live-answer",
        "model": answer.MODEL,
        "limit_usd": answer.MAX_BUDGET_USD,
        "support_floor": answer.SUPPORT_FLOOR,
        "cost_usd": round(sum(a["cost_usd"] for a in answers), 4),
        "answers": answers,
    }


def problems(record: dict) -> list[str]:
    found = []
    for a in record["answers"]:
        if not (a["refused"] or a["cites_relevant"]):
            found.append(f"{a['id']} neither refuses nor cites a relevant chunk: {a['cited']}")
        if a["invalid_citations"]:
            found.append(f"{a['id']} cites sources that were not given: {a['invalid_citations']}")
    if record["cost_usd"] > MAX_TOTAL_USD:
        found.append(f"cost {record['cost_usd']} above {MAX_TOTAL_USD}")
    return found


def save(record: dict, workspace: Path) -> Path:
    path = workspace / "runs" / f"live-{datetime.now(UTC).date().isoformat()}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n")
    return path


def fake(text: str, cost: float) -> list:
    return [
        AssistantMessage(content=[TextBlock(text=text)], model=answer.MODEL),
        ResultMessage(
            subtype="success",
            duration_ms=5,
            duration_api_ms=4,
            is_error=False,
            num_turns=1,
            session_id="s-1",
            total_cost_usd=cost,
        ),
    ]


def test_the_picked_queries_clear_the_support_floor(conn, indexed, picked):
    embedder, chunks = indexed
    for q in picked:
        found, scores = answer.sources(conn, embedder, rerank.LexicalReranker(), q.query)
        assert max(scores) >= answer.SUPPORT_FLOOR, q.id
        assert metrics.relevant(chunks, q) & {c.chunk_id for c in found}, q.id


def test_a_scripted_run_cites_or_refuses(conn, indexed, picked, tmp_path):
    embedder, chunks = indexed
    answers = []
    for q in picked:
        found, _ = answer.sources(conn, embedder, rerank.LexicalReranker(), q.query)
        rel = metrics.relevant(chunks, q)
        n = next(i for i, c in enumerate(found, 1) if c.chunk_id in rel)
        answers.append(ask(conn, indexed, q, scripted_query(fake(f"It says so [{n}].", 0.02))))
    record = aggregate(answers)
    assert problems(record) == []
    assert record["cost_usd"] == pytest.approx(0.06)
    assert all(a["cites_relevant"] and a["uncited_claims"] == 0 for a in answers)
    path = save(record, tmp_path)
    assert json.loads(path.read_text())["answers"][0]["id"] == QUERY_IDS[0]


def test_problems_catches_wrong_citations_and_cost(conn, indexed, picked):
    q = picked[0]
    wrong = ask(conn, indexed, q, scripted_query(fake("Somewhere else [9].", 0.3)))
    found = problems(aggregate([wrong]))
    assert any("neither refuses" in p for p in found)
    assert any("not given" in p for p in found)
    assert any("cost" in p for p in found)
    refused = ask(conn, indexed, q, scripted_query(fake(f"{answer.REFUSAL}.", 0.01)))
    assert problems(aggregate([refused])) == []


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("MIUBAIS_SKIP_LIVE") == "1", reason="MIUBAIS_SKIP_LIVE=1")
def test_live_answers_cite_or_refuse(conn, indexed, picked, workspace):
    if not logged_in():
        pytest.skip("needs claude-auth")
    record = aggregate([ask(conn, indexed, q) for q in picked])
    print(f"\nlive answers: {json.dumps(record, indent=2)}")
    print(f"saved {save(record, workspace)}")
    assert problems(record) == [], problems(record)
