import json
from pathlib import Path

import pytest

from opl_persona.core import build_inbox_capture_proposals
from opl_persona.inbox import InboxStore


def test_capture_uses_persona_home_and_stores_refs_summary_only(tmp_path: Path) -> None:
    data_root = tmp_path / "persona-private"
    store = InboxStore(environ={"OPL_PERSONA_HOME": str(data_root)})

    item = store.capture(
        capture_id="paper://doi/10.1000/example",
        item_kind="publication",
        title="A new paper",
        summary="Route this paper to knowledge and website proposals.",
        source_refs=["paper://doi/10.1000/example", "file-ref://paper.pdf"],
    )

    assert item.status == "staged"
    assert store.path == data_root / "inbox/items.json"
    persisted = json.loads(store.path.read_text(encoding="utf-8"))
    stored = persisted["items"][0]
    assert set(stored) == {
        "item_id",
        "capture_id",
        "item_kind",
        "title",
        "summary",
        "source_refs",
        "status",
        "route_refs",
        "created_at",
        "updated_at",
    }
    assert "body" not in json.dumps(persisted)
    assert "content" not in json.dumps(persisted)


def test_capture_proposal_is_idempotent_and_route_is_refs_only(tmp_path: Path) -> None:
    proposal = build_inbox_capture_proposals(
        {
            "capture_id": "knowledge://memo/1",
            "item_kind": "knowledge",
            "title": "Technical memo",
            "summary": "Review and route this memo.",
            "source_refs": ["obsidian://vault/Knowledge/memo.md"],
        }
    )["proposals"][0]
    store = InboxStore(tmp_path / "private")

    first = store.capture_proposal(proposal)
    second = store.capture_proposal(proposal)
    routed = store.route(first.item_id, "proposal://knowledge/2")

    assert first.item_id == second.item_id
    assert len(store.list()) == 1
    assert routed.status == "routed"
    assert routed.route_refs == ("proposal://knowledge/2",)
    assert store.get(first.item_id) == routed


def test_inbox_rejects_external_write_capture_and_body_sized_summary(tmp_path: Path) -> None:
    proposal = build_inbox_capture_proposals(
        {
            "capture_id": "knowledge://memo/1",
            "item_kind": "knowledge",
            "title": "Memo",
            "summary": "Summary",
            "source_refs": ["obsidian://vault/memo.md"],
        }
    )["proposals"][0]
    proposal["approval"]["external_write_allowed"] = True
    store = InboxStore(tmp_path / "private")

    with pytest.raises(ValueError, match="cannot authorize an external write"):
        store.capture_proposal(proposal)
    with pytest.raises(ValueError, match="staging limit"):
        store.capture(
            capture_id="note://large",
            item_kind="note",
            title="Large",
            summary="x" * 4097,
            source_refs=["note://large"],
        )
    assert not store.path.exists()
