import pytest
from retrieval_lab.chunker import chunk, load_documents
from retrieval_lab.types import Document

OUTLINE = """# Title

Intro paragraph.

## Section A

Para A1.

```
# not a heading, a comment in a fence
```

### Sub A.1

Para A11.

## Section B

Para B1.
"""


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def doc(text: str, doc_id: str = "invented") -> Document:
    return Document(doc_id=doc_id, title="Invented", text=text)


def paragraphs(count: int, size: int = 300) -> list[str]:
    return [f"p{i:02d} " + chr(ord("a") + i) * (size - 4) for i in range(count)]


@pytest.fixture(scope="module")
def corpus(corpus_dir) -> list[Document]:
    return load_documents(corpus_dir)


@pytest.fixture(scope="module")
def corpus_chunks(corpus) -> dict[str, list]:
    return {d.doc_id: chunk(d) for d in corpus}


def fence_lines(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.lstrip().startswith(("```", "~~~")))


def test_load_documents_reads_docs_and_stories(corpus):
    ids = [d.doc_id for d in corpus]
    assert len(ids) == 32 == len(set(ids))
    by_id = {d.doc_id: d for d in corpus}
    assert by_id["m1-02-hooks-permissions-and-modes"].title == "Hooks, permissions and modes"
    assert by_id["tell-tale-heart"].title == "The Tell-Tale Heart"
    assert by_id["gift-of-the-magi"].text.startswith("The Gift of the Magi")


def test_heading_paths_follow_the_outline():
    chunks = chunk(doc(OUTLINE))
    assert [c.heading_path for c in chunks] == [
        "Title",
        "Title > Section A",
        "Title > Section A > Sub A.1",
        "Title > Section B",
    ]
    assert chunks[1].text.startswith("## Section A")
    assert "# not a heading" in chunks[1].text
    assert chunks[3].text == "## Section B\n\nPara B1."


def test_text_before_the_first_heading_has_an_empty_path():
    chunks = chunk(doc("Preface line.\n\n# Title\n\nBody."))
    assert [c.heading_path for c in chunks] == ["", "Title"]


def test_paragraphs_pack_up_to_max_chars_without_overlap():
    paras = paragraphs(7)
    chunks = chunk(doc("\n\n".join(paras)), max_chars=1000, overlap=0)
    assert [c.text for c in chunks] == [
        "\n\n".join(paras[0:3]),
        "\n\n".join(paras[3:6]),
        paras[6],
    ]


def test_overlap_repeats_the_last_paragraph():
    paras = paragraphs(7)
    chunks = chunk(doc("\n\n".join(paras)), max_chars=1000, overlap=1)
    assert [c.text for c in chunks] == [
        "\n\n".join(paras[0:3]),
        "\n\n".join(paras[2:5]),
        "\n\n".join(paras[4:7]),
    ]
    assert all(len(c.text) <= 1000 for c in chunks)


def test_a_long_fenced_block_is_one_oversized_chunk():
    body = "\n\n".join(f"line_{i} = {i}  # " + "x" * 60 for i in range(30))
    fence = f"```python\n{body}\n```"
    text = "# Code\n\nBefore the fence.\n\n" + fence + "\n\nAfter the fence."
    chunks = chunk(doc(text), max_chars=1200, overlap=1)
    fenced = [c for c in chunks if "```" in c.text]
    assert len(fence) > 1200
    assert len(fenced) == 1
    assert fence in fenced[0].text
    assert fence_lines(fenced[0].text) == 2
    assert any("After the fence." in c.text for c in chunks)


def test_an_unclosed_fence_runs_to_the_end():
    text = "Intro.\n\n```\ncode\n\n# still code\n"
    chunks = chunk(doc(text))
    assert len(chunks) == 1
    assert chunks[0].heading_path == ""
    assert chunks[0].text.endswith("# still code")


def test_offsets_reproduce_the_text_and_ids_are_sequential(corpus, corpus_chunks):
    for d in corpus:
        chunks = corpus_chunks[d.doc_id]
        assert chunks, d.doc_id
        assert [c.chunk_id for c in chunks] == [f"{d.doc_id}#{i:03d}" for i in range(len(chunks))]
        for c in chunks:
            assert c.doc_id == d.doc_id
            assert d.text[c.start_char : c.end_char] == c.text, c.chunk_id


def test_chunking_is_deterministic(corpus, corpus_chunks):
    for d in corpus[:5] + corpus[-3:]:
        assert chunk(d) == corpus_chunks[d.doc_id]


def test_chunks_cover_every_non_blank_character(corpus, corpus_chunks):
    for d in corpus:
        covered = bytearray(len(d.text))
        for c in corpus_chunks[d.doc_id]:
            covered[c.start_char : c.end_char] = b"\x01" * (c.end_char - c.start_char)
        missed = [i for i, ch in enumerate(d.text) if not ch.isspace() and not covered[i]]
        assert not missed, (d.doc_id, d.text[missed[0] : missed[0] + 40])


def test_no_corpus_chunk_splits_a_fence(corpus_chunks):
    for chunks in corpus_chunks.values():
        for c in chunks:
            assert fence_lines(c.text) % 2 == 0, c.chunk_id


def test_every_golden_anchor_lies_inside_a_chunk(golden, corpus_chunks):
    for q in golden:
        texts = [norm(c.text) for c in corpus_chunks[q.doc_id]]
        assert any(norm(q.anchor) in t for t in texts), q.id
