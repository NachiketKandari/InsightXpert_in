import pytest

from insightxpert_api.storage.local import LocalStorage


def test_write_read_roundtrip(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.put_bytes("a/b.txt", b"hello")
    assert s.get_bytes("a/b.txt") == b"hello"
    assert s.exists("a/b.txt") is True


def test_list_returns_keys_under_prefix(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.put_bytes("a/b.txt", b"1")
    s.put_bytes("a/c.txt", b"2")
    s.put_bytes("z/d.txt", b"3")
    assert sorted(s.list("a/")) == ["a/b.txt", "a/c.txt"]


def test_missing_key_exists_false(tmp_path):
    s = LocalStorage(str(tmp_path))
    assert s.exists("nope") is False


def test_delete_removes_file(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.put_bytes("x", b"y")
    s.delete("x")
    assert not s.exists("x")


def test_path_traversal_rejected(tmp_path):
    s = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        s.put_bytes("../outside.txt", b"nope")


def test_list_empty_prefix_enumerates_all(tmp_path):
    s = LocalStorage(str(tmp_path))
    s.put_bytes("a.txt", b"1")
    s.put_bytes("nested/b.txt", b"2")
    assert set(s.list("")) >= {"a.txt", "nested/b.txt"}
