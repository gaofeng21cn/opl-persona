from opl_persona.core import build_memo_proposals, build_publication_proposals


def test_publication_creates_knowledge_and_website_proposals() -> None:
    result = build_publication_proposals(
        {
            "publication_id": "doi:10.1000/example",
            "title": "A publication",
            "authors": ["Feng Gao"],
            "doi": "10.1000/example",
            "source_refs": ["paper://sha256:abc"],
        }
    )
    assert result["schema_version"] == "opl-persona-proposal.v1"
    assert [item["proposal_kind"] for item in result["proposals"]] == [
        "knowledge.ingest",
        "website.publication",
    ]
    assert all(item["approval"]["external_write_allowed"] is False for item in result["proposals"])


def test_memo_creates_website_and_relay_context_proposals() -> None:
    result = build_memo_proposals(
        {
            "memo_id": "obsidian://vault/memo.md",
            "title": "A technical memo",
            "body": "Evidence-backed memo.",
            "tags": ["OPL"],
            "source_refs": ["obsidian://vault/memo.md"],
        }
    )
    assert [item["target"] for item in result["proposals"]] == [
        "gflab_web.content.post",
        "opl-relay.draft.context",
    ]


def test_inputs_require_provenance() -> None:
    try:
        build_publication_proposals({"publication_id": "p", "title": "t"})
    except ValueError as exc:
        assert "source_ref" in str(exc)
    else:
        raise AssertionError("missing provenance must fail closed")
