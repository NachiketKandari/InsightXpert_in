import pytest

from insightxpert_api.services.conversation_store import (
    ConversationNotFoundError,
    ConversationStore,
)


def test_create_and_get():
    store = ConversationStore()
    convo = store.create(session_id="s1", title="hello")
    assert convo.session_id == "s1"
    assert convo.title == "hello"
    got = store.get("s1", convo.conversation_id)
    assert got is convo


def test_get_missing_raises():
    store = ConversationStore()
    with pytest.raises(ConversationNotFoundError):
        store.get("s1", "nope")


def test_list_filters_by_session():
    store = ConversationStore()
    store.create(session_id="s1")
    store.create(session_id="s1")
    store.create(session_id="s2")
    assert len(store.list("s1")) == 2
    assert len(store.list("s2")) == 1


def test_get_or_create_with_none_creates_new():
    store = ConversationStore()
    convo = store.get_or_create("s1", None)
    assert convo.conversation_id  # non-empty


def test_get_or_create_with_existing_returns_same():
    store = ConversationStore()
    convo = store.create(session_id="s1")
    again = store.get_or_create("s1", convo.conversation_id)
    assert again is convo


def test_get_or_create_with_unknown_id_materializes():
    store = ConversationStore()
    convo = store.get_or_create("s1", "preset-id")
    assert convo.conversation_id == "preset-id"
    assert store.get("s1", "preset-id") is convo


def test_append_message_increments_and_updates_timestamp():
    store = ConversationStore()
    convo = store.create(session_id="s1")
    before = convo.updated_at
    msg = store.append_message("s1", convo.conversation_id, role="user", content="hi")
    assert msg.role == "user"
    assert msg.content == "hi"
    assert convo.messages[-1] is msg
    assert convo.updated_at >= before


def test_append_chunk_stores_serialized_dict():
    store = ConversationStore()
    convo = store.create(session_id="s1")
    store.append_chunk("s1", convo.conversation_id, {"type": "status", "data": {"message": "hi"}})
    assert len(convo.chunks) == 1
    assert convo.chunks[0]["type"] == "status"


def test_rename_and_star_toggle():
    store = ConversationStore()
    convo = store.create(session_id="s1")
    store.rename("s1", convo.conversation_id, "renamed")
    assert convo.title == "renamed"
    store.set_starred("s1", convo.conversation_id, True)
    assert convo.starred is True
    store.set_starred("s1", convo.conversation_id, False)
    assert convo.starred is False


def test_delete_removes_and_subsequent_get_raises():
    store = ConversationStore()
    convo = store.create(session_id="s1")
    store.delete("s1", convo.conversation_id)
    with pytest.raises(ConversationNotFoundError):
        store.get("s1", convo.conversation_id)


def test_sessions_are_isolated():
    store = ConversationStore()
    c1 = store.create(session_id="s1")
    # s2 cannot see s1's conversation
    with pytest.raises(ConversationNotFoundError):
        store.get("s2", c1.conversation_id)


def test_to_dict_serializes_messages_and_chunks():
    store = ConversationStore()
    convo = store.create(session_id="s1", title="t")
    store.append_message("s1", convo.conversation_id, role="user", content="q")
    store.append_chunk("s1", convo.conversation_id, {"type": "answer", "data": {"text": "a"}})
    d = ConversationStore.to_dict(convo)
    assert d["title"] == "t"
    assert d["messages"][0]["content"] == "q"
    assert d["chunks"][0]["type"] == "answer"
