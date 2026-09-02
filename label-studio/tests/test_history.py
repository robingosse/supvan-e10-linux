from supvan_label_studio.core import LabelDocument, LineItem
from supvan_label_studio.history import DocumentHistory, document_from_snapshot, document_snapshot


def test_history_undo_redo_roundtrip():
    document = LabelDocument(auto_size=False)
    before = document_snapshot(document)
    document.add(LineItem())
    after = document_snapshot(document)
    history = DocumentHistory()
    assert history.record(before, after)
    restored = history.undo(after)
    assert restored == before
    assert document_from_snapshot(restored).items == []
    assert history.redo(restored) == after


def test_history_ignores_no_op_and_respects_limit():
    history = DocumentHistory(limit=2)
    assert not history.record("same", "same")
    history.record("a", "b")
    history.record("b", "c")
    history.record("c", "d")
    assert history.undo_stack == ["b", "c"]
