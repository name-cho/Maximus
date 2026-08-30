"""Pointers for DB records — auto-syncing list/dict/set."""

from __future__ import annotations

import typing


class BaseSerializingMiddleware:
    def __init__(self, db, owner: str, key: str, default: typing.Any):
        self._db = db
        self._owner = owner
        self._key = key
        self._default = default

    def _save(self) -> None:
        self._db.set(self._owner, self._key, self._serialize())

    def _serialize(self) -> typing.Any:
        raise NotImplementedError


class PointerList(list, BaseSerializingMiddleware):
    def __init__(self, db, owner: str, key: str, default: list | None = None):
        BaseSerializingMiddleware.__init__(self, db, owner, key, default or [])
        list.__init__(self, db.get(owner, key, default or []))

    def _serialize(self) -> list:
        return list(self)

    def append(self, value):
        list.append(self, value)
        self._save()

    def extend(self, values):
        list.extend(self, values)
        self._save()

    def insert(self, index, value):
        list.insert(self, index, value)
        self._save()

    def remove(self, value):
        list.remove(self, value)
        self._save()

    def pop(self, index=-1):
        result = list.pop(self, index)
        self._save()
        return result

    def clear(self):
        list.clear(self)
        self._save()

    def sort(self, **kwargs):
        list.sort(self, **kwargs)
        self._save()

    def reverse(self):
        list.reverse(self)
        self._save()

    def __setitem__(self, key, value):
        list.__setitem__(self, key, value)
        self._save()

    def __delitem__(self, key):
        list.__delitem__(self, key)
        self._save()

    def __iadd__(self, other):
        result = list.__iadd__(self, other)
        self._save()
        return result


class PointerDict(dict, BaseSerializingMiddleware):
    def __init__(self, db, owner: str, key: str, default: dict | None = None):
        BaseSerializingMiddleware.__init__(self, db, owner, key, default or {})
        dict.__init__(self, db.get(owner, key, default or {}))

    def _serialize(self) -> dict:
        return dict(self)

    def __setitem__(self, key, value):
        dict.__setitem__(self, key, value)
        self._save()

    def __delitem__(self, key):
        dict.__delitem__(self, key)
        self._save()

    def update(self, *args, **kwargs):
        dict.update(self, *args, **kwargs)
        self._save()

    def setdefault(self, key, default=None):
        result = dict.setdefault(self, key, default)
        self._save()
        return result

    def pop(self, *args):
        result = dict.pop(self, *args)
        self._save()
        return result

    def popitem(self):
        result = dict.popitem(self)
        self._save()
        return result

    def clear(self):
        dict.clear(self)
        self._save()


class PointerSet(set, BaseSerializingMiddleware):
    def __init__(self, db, owner: str, key: str, default: set | None = None):
        BaseSerializingMiddleware.__init__(self, db, owner, key, default or set())
        set.__init__(self, db.get(owner, key, list(default or [])))

    def _serialize(self) -> list:
        return list(self)

    def add(self, value):
        set.add(self, value)
        self._save()

    def discard(self, value):
        set.discard(self, value)
        self._save()

    def remove(self, value):
        set.remove(self, value)
        self._save()

    def pop(self):
        result = set.pop(self)
        self._save()
        return result

    def clear(self):
        set.clear(self)
        self._save()

    def update(self, *args):
        set.update(self, *args)
        self._save()