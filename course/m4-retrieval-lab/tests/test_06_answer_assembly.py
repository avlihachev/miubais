import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock
from harnesskit.testing import scripted_query
from retrieval_lab import answer, rerank, store
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.embed import HashEmbedder
from retrieval_lab.types import Chunk

OFF_CORPUS = [
    "What is the boiling point of tungsten?",
    "Who won the 1998 football world cup?",
    "How do penguins mate in Antarctica?",
    "best pizza recipe with mozzarella",
    "What is the capital city of Mongolia?",
    "xyzzy plugh",
]
SUPPORTED_GOLDEN = 47


def five() -> list[Chunk]:
    return [
        Chunk(f"doc{i}", f"doc{i}#00{i}", 0, 10, "", f"Source text number {i}.") for i in range(5)
    ]


def result(cost: float = 0.01) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=5,
        duration_api_ms=4,
        is_error=False,
        num_turns=1,
        session_id="s-1",
        total_cost_usd=cost,
    )


def reply(text: str, cost: float = 0.01) -> list:
    return [AssistantMessage(content=[TextBlock(text=text)], model=answer.MODEL), result(cost)]


@pytest.fixture(scope="module")
def indexed(conn, corpus_dir):
    embedder = HashEmbedder()
    chunks = [c for d in load_documents(corpus_dir) for c in chunk(d)]
    store.Schema.create(conn, embedder.dims)
    store.upsert(conn, chunks, embedder)
    return embedder


def test_assemble_numbers_the_sources_and_states_the_rules():
    chunks = five()
    draft = answer.assemble("what is number 3?", chunks, scores=[9, 8, 7, 6, 5])
    assert not draft.refused
    assert draft.citations == tuple(c.chunk_id for c in chunks)
    for i, c in enumerate(chunks, 1):
        assert f"[{i}] {c.chunk_id}\n{c.text}" in draft.prompt
    assert "what is number 3?" in draft.prompt
    assert "only the numbered sources" in draft.prompt
    assert "[n]" in draft.prompt
    assert f"{answer.REFUSAL}." in draft.prompt
    assert draft.prompt.index("[1] ") < draft.prompt.index("[5] ")


def test_assemble_refuses_when_no_source_clears_the_support_floor():
    below = answer.SUPPORT_FLOOR - 0.01
    draft = answer.assemble("q", five(), scores=[below] * 5)
    assert draft.refused
    assert draft.citations == ()
    assert "[1]" not in draft.prompt
    assert not answer.assemble("q", five(), scores=[answer.SUPPORT_FLOOR, 0, 0, 0, 0]).refused
    assert answer.assemble("q", [], scores=[]).refused


def test_min_support_counts_the_sources_above_the_floor():
    scores = [answer.SUPPORT_FLOOR + 1, 1.0, 1.0, 1.0, 1.0]
    assert not answer.assemble("q", five(), scores=scores, min_support=1).refused
    assert answer.assemble("q", five(), scores=scores, min_support=2).refused


def test_a_refused_draft_never_calls_the_model():
    draft = answer.assemble("q", five(), scores=[0.0] * 5)
    reply_ = answer.run("q", draft, query_fn=scripted_query([RuntimeError("model was called")]))
    assert reply_.text == f"{answer.REFUSAL}."
    assert reply_.faithfulness.refused
    assert reply_.faithfulness.cited == []
    assert reply_.cost_usd == 0.0


def test_check_counts_cited_sources():
    text = "Della sold her hair for twenty dollars [1]. Jim sold his watch to buy the combs [3]."
    f = answer.check(text, [c.chunk_id for c in five()])
    assert f.cited == [1, 3]
    assert f.uncited_claims == 0
    assert not f.refused


def test_check_flags_uncited_sentences():
    text = (
        "The cache lives five minutes [2]. Hits refresh it. It costs nothing to read!\nOk [2][4]."
    )
    f = answer.check(text, [c.chunk_id for c in five()])
    assert f.cited == [2, 4]
    assert f.uncited_claims == 2


def test_a_marker_after_the_full_stop_cites_its_sentence():
    f = answer.check("The cache lives five minutes. [2] Hits refresh it. [1]", ["a", "b"])
    assert f.cited == [1, 2]
    assert f.uncited_claims == 0


def test_abbreviations_do_not_end_a_sentence():
    text = (
        "Mme. Sofronie bought hair [1]. Mr. Young paid, e.g. in coins, i.e. all he had, "
        "a cost vs. the watch [2]. Della cried."
    )
    f = answer.check(text, ["a", "b"])
    assert f.cited == [1, 2] and f.uncited_claims == 1


def test_check_flags_a_citation_outside_the_sources():
    citations = [c.chunk_id for c in five()]
    f = answer.check("The answer is in the seventh source [7].", citations)
    assert f.cited == []
    assert f.uncited_claims == 1
    assert answer.invalid_citations("Both [7] and [0] and [5].", citations) == [0, 7]
    mixed = answer.check("Fine [5]. Wrong [6].", citations)
    assert mixed.cited == [5] and mixed.uncited_claims == 1


def test_check_recognises_the_refusal():
    f = answer.check(f"{answer.REFUSAL}.", ["a", "b"])
    assert f.refused
    assert f.cited == [] and f.uncited_claims == 0
    assert not answer.check("I cannot answer that well [1].", ["a"]).refused


def test_run_sends_the_pinned_options_and_checks_the_reply():
    seen = []

    async def capture(options):
        seen.append(options)

    draft = answer.assemble("q", five(), scores=[9.0] * 5)
    text = "Number one says so [1]. Number three agrees [3]."
    got = answer.run("q", draft, query_fn=scripted_query([capture, *reply(text, 0.0123)]))
    options = seen[0]
    assert options.tools == []
    assert options.max_turns == answer.MAX_TURNS == 1
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.max_budget_usd == answer.MAX_BUDGET_USD == 0.05
    assert options.model == answer.MODEL == "claude-opus-5-5"
    assert got.text == text
    assert got.faithfulness.cited == [1, 3]
    assert got.faithfulness.uncited_claims == 0
    assert got.cost_usd == pytest.approx(0.0123)
    assert (
        answer.run("q", draft, query_fn=scripted_query(reply("x [1].")), model="m").text == "x [1]."
    )


@pytest.mark.parametrize("query", OFF_CORPUS)
def test_off_corpus_questions_refuse(conn, indexed, query):
    chunks, scores = answer.sources(conn, indexed, rerank.LexicalReranker(), query)
    assert max(scores) < answer.SUPPORT_FLOOR, scores
    assert answer.assemble(query, chunks, scores=scores).refused


def test_golden_questions_find_support(conn, indexed, golden):
    reranker = rerank.LexicalReranker()
    supported = 0
    for q in golden:
        chunks, scores = answer.sources(conn, indexed, reranker, q.query)
        supported += not answer.assemble(q.query, chunks, scores=scores).refused
    assert supported == SUPPORTED_GOLDEN
