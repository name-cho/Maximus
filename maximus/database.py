"""Database for Maximus.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import typing
from pathlib import Path

from . import utils

logger = logging.getLogger(__name__)

JSONSerializable = typing.Union[str, int, float, bool, list, dict, None]


class Database(dict):
    """Persistent key-value store, namespaced by owner."""

    SAVE_DELAY = 1.0

    def __init__(self, path: str | Path | None = None):
        super().__init__()
        self._path = Path(path or utils.relative_path("maximus-db.json"))
        self._saving = False
        self._save_task: asyncio.Task | None = None

    def __repr__(self) -> str:
        return f"Database({self._path}, {len(self)} owners)"

    async def init(self) -> None:
        self.read()

    def read(self) -> dict:
        if not self._path.exists():
            logger.debug("Database file %s does not exist, starting empty", self._path)
            return self

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error("Database is corrupted, backing it up and starting fresh")
            self._backup_corrupted()
            return self
        except OSError as e:
            logger.error("Cannot read database: %s", e)
            return self

        if not isinstance(data, dict):
            logger.error("Database root is not an object, ignoring")
            return self

        self.clear()
        self.update(data)
        logger.debug("Loaded database with %s owners", len(self))
        return self

    def _backup_corrupted(self) -> None:
        broken = self._path.with_suffix(".json.broken")
        try:
            os.replace(self._path, broken)
            logger.warning("Corrupted database moved to %s", broken)
        except OSError:
            logger.exception("Failed to back up corrupted database")

    def save(self) -> bool:
        if self._saving:
            return True

        self._saving = True
        tmp = self._path.with_suffix(".json.tmp")

        try:
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(
                json.dumps(self, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            os.replace(tmp, self._path)
        except Exception:
            logger.exception("Database save failed")
            return False
        finally:
            self._saving = False

        return True

    def schedule_save(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return self.save()

        if self._save_task and not self._save_task.done():
            return True

        async def _delayed() -> None:
            await asyncio.sleep(self.SAVE_DELAY)
            self.save()

        self._save_task = loop.create_task(_delayed())
        return True

    async def close(self) -> None:
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._save_task
        self.save()

    def get(self, owner: str, key: str, default: JSONSerializable = None) -> JSONSerializable:
        try:
            return super().__getitem__(owner)[key]
        except KeyError:
            return default

    def set(self, owner: str, key: str, value: JSONSerializable) -> bool:
        if not _is_serializable(value):
            raise RuntimeError(f"Value {value!r} is not JSON-serializable")

        super().setdefault(owner, {})[key] = value
        return self.schedule_save()

    def unset(self, owner: str, key: str) -> bool:
        try:
            del super().__getitem__(owner)[key]
        except KeyError:
            return False
        return self.schedule_save()

    def pointer(self, owner: str, key: str, default: JSONSerializable = None, item_type: typing.Any = None):
        from .pointers import PointerDict, PointerList, PointerSet

        value = self.get(owner, key, default)
        mapping = {list: PointerList, dict: PointerDict, set: PointerSet}
        pointer_cls = mapping.get(item_type or type(value))

        if pointer_cls is None:
            return value

        return pointer_cls(self, owner, key, default)

    def __setitem__(self, owner: str, value: JSONSerializable) -> None:
        super().__setitem__(owner, value)
        self.schedule_save()

    def __delitem__(self, owner: str) -> None:
        super().__delitem__(owner)
        self.schedule_save()

    def update(self, *args, **kwargs) -> None:
        super().update(*args, **kwargs)


def _is_serializable(value: typing.Any) -> bool:
    try:
        json.dumps(value, default=str)
    except (TypeError, ValueError):
        return False
    return True