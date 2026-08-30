"""Utility functions for Maximus modules."""

from __future__ import annotations

import asyncio
import collections
import contextlib
import functools
import inspect
import io
import logging
import os
import random
import re
import shlex
import string
import time
import typing
from pathlib import Path
from urllib.parse import urlparse

from pymax import Client, File, Message, Photo, Video
from pymax.types import Chat, User

logger = logging.getLogger(__name__)

init_ts = time.perf_counter()

_client: Client | None = None


def bind_client(client: Client) -> None:
    global _client
    _client = client


def get_client() -> Client:
    if _client is None:
        raise RuntimeError("Client is not bound yet")
    return _client


def get_me_id() -> int | None:
    if _client is None or _client.me is None:
        return None
    return _client.me.contact.id


def is_outgoing(message: Message) -> bool:
    me = get_me_id()
    return me is not None and message.sender == me


_own_edits: collections.deque = collections.deque(maxlen=512)


def mark_own_edit(message_id: int) -> None:
    _own_edits.append(message_id)


def is_own_edit(message_id: int) -> bool:
    return message_id in _own_edits


def get_args_raw(message: Message | str) -> str:
    text = message if isinstance(message, str) else (message.text or "")
    return args[1] if len(args := text.split(maxsplit=1)) > 1 else ""


def get_args(message: Message | str) -> list[str]:
    raw = get_args_raw(message)
    if not raw:
        return []
    try:
        parsed = shlex.split(raw)
    except ValueError:
        parsed = raw.split()
    return [item for item in map(str.strip, parsed) if item]


def get_args_split_by(message: Message | str, separator: str) -> list[str]:
    raw = get_args_raw(message)
    return [item for item in map(str.strip, raw.split(separator)) if item]


def get_chat_id(message: Message | Chat | int | None) -> int | None:
    if message is None:
        return None
    if isinstance(message, int):
        return message
    if isinstance(message, Message):
        return message.chat_id
    return getattr(message, "id", None)


def get_sender_id(message: Message) -> int | None:
    return getattr(message, "sender", None)


def get_display_name(entity: User | Chat | None) -> str:
    if entity is None:
        return "Unknown"
    if isinstance(entity, Chat) or hasattr(entity, "title"):
        title = getattr(entity, "title", None)
        if title:
            return title
    names = getattr(entity, "names", None) or []
    for name in names:
        value = getattr(name, "name", None) or getattr(name, "first_name", None)
        if value:
            return value
    return str(getattr(entity, "id", "Unknown"))


_chat_cache: dict[int, tuple[float, Chat]] = {}
CHAT_CACHE_TTL = 300


async def get_self_chat_id() -> int | None:
    me = get_me_id()
    if me is None:
        return None

    def find(chats) -> int | None:
        for chat in chats or []:
            participants = getattr(chat, "participants", None) or {}
            if is_private(chat) and set(participants) == {me}:
                return chat.id
        return None

    client = get_client()
    if (found := find(getattr(client, "chats", None))) is not None:
        return found
    with contextlib.suppress(Exception):
        return find(await client.fetch_chats())
    return None


def get_reply_id(message: Message) -> int | None:
    link = getattr(message, "link", None)
    if isinstance(link, dict):
        if str(link.get("type", "")).upper() != "REPLY":
            return None
        raw = link.get("messageId") or link.get("message_id")
        if raw is None and isinstance(link.get("message"), dict):
            raw = link["message"].get("id")
        with contextlib.suppress(TypeError, ValueError):
            return int(raw)
    return None


async def get_reply(message: Message) -> Message | None:
    reply_id = get_reply_id(message)
    chat_id = get_chat_id(message)
    if reply_id is None or chat_id is None:
        return None
    with contextlib.suppress(Exception):
        return await get_client().get_message(chat_id, reply_id)
    return None


async def get_target_user(message: Message, args: str = "") -> User | None:
    args = (args or "").strip()
    client = get_client()
    if args:
        if args.lstrip("-").isdigit():
            with contextlib.suppress(Exception):
                if (user := await client.get_user(int(args))) is not None:
                    return user
        if args.startswith("+"):
            with contextlib.suppress(Exception):
                return await client.search_by_phone(args)
    reply = await get_reply(message)
    if reply is not None and reply.sender is not None:
        with contextlib.suppress(Exception):
            return await client.get_user(reply.sender)
    return None


async def get_target_id(message: Message, args: str = "") -> int | None:
    args = (args or "").strip()
    with contextlib.suppress(TypeError, ValueError):
        return int(args)
    user = await get_target_user(message, args)
    return user.id if user else None


async def get_chat(message: Message | int) -> Chat | None:
    chat_id = get_chat_id(message)
    if chat_id is None:
        return None
    cached = _chat_cache.get(chat_id)
    if cached and time.time() - cached[0] < CHAT_CACHE_TTL:
        return cached[1]
    with contextlib.suppress(Exception):
        chat = await get_client().get_chat(chat_id)
        if chat is not None:
            _chat_cache[chat_id] = (time.time(), chat)
        return chat
    return None


def drop_chat_cache(chat_id: int | None = None) -> None:
    if chat_id is None:
        _chat_cache.clear()
    else:
        _chat_cache.pop(chat_id, None)


def is_private(chat: Chat | None) -> bool:
    return chat is not None and str(getattr(chat, "type", "")).upper().endswith("DIALOG")


def is_channel(chat: Chat | None) -> bool:
    return chat is not None and str(getattr(chat, "type", "")).upper().endswith("CHANNEL")


def is_group(chat: Chat | None) -> bool:
    return chat is not None and str(getattr(chat, "type", "")).upper().endswith("CHAT")


async def answer(message: Message, response: str, *, reply: bool = False,
                 attachments: typing.Sequence = None, notify: bool = True) -> Message | None:
    if is_outgoing(message) and not reply and not attachments:
        with contextlib.suppress(Exception):
            edited = await message.edit(response)
            mark_own_edit(message.id)
            return edited
    if reply:
        return await message.reply(response, attachments, notify=notify)
    return await message.answer(response, attachments=attachments, notify=notify)


async def answer_file(message: Message, file: str | bytes | Path, caption: str = "",
                      *, name: str | None = None, photo: bool = False,
                      video: bool = False) -> Message | None:
    kind = Photo if photo else Video if video else File
    if isinstance(file, bytes):
        attachment = kind(file, name=name or "file.bin")
    elif str(file).startswith(("http://", "https://")):
        attachment = kind(url=str(file), name=name)
    else:
        attachment = kind(path=str(file), name=name)
    return await message.answer(caption, attachments=[attachment])


async def delete(message: Message, for_me: bool = False) -> bool:
    with contextlib.suppress(Exception):
        return await message.delete(for_me=for_me)
    return False


def escape_quotes(text: str) -> str:
    return str(text).replace('"', '\\"')


def escape_md(text: str) -> str:
    return re.sub(r"([*_`~\[\]])", r"\\\1", str(text))


def mono(text: str) -> str:
    return str(text).replace("`", "")


def heading(text: str) -> str:
    return "# " + str(text).replace("\n", " ")


def quote(text: str, limit: int = 0) -> str:
    if not text or not text.strip():
        return ""
    lines = str(text).splitlines()
    if limit and len(text) > limit:
        lines = text[:limit].splitlines()
    return "\n".join(f"> {line}" if line.strip() else ">  " for line in lines)


_MD_MARKERS = re.compile(r"```|\*\*|~~|`|\*")
_MD_LINE_PREFIX = re.compile(r"^\s*[>#]+\s*", re.MULTILINE)


def unmark(text: str) -> str:
    return _MD_LINE_PREFIX.sub("", _MD_MARKERS.sub("", str(text)))


def code_block(text: str, limit: int = 3000) -> str:
    return smart_truncate(str(text), limit)


def censor(text: str) -> str:
    text = re.sub(r"\+?\d{10,15}", "+**********", text)
    return re.sub(r"[0-9a-f]{32,}", "**********", text, flags=re.I)


def chunks(seq: typing.Sequence, size: int) -> list:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def rand(size: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=size))


def check_url(url: str) -> bool:
    with contextlib.suppress(Exception):
        parsed = urlparse(url)
        return bool(parsed.scheme in {"http", "https"} and parsed.netloc)
    return False


def humanbytes(size: int | float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(size) < 1024:
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.2f} PiB"


def uptime() -> int:
    return round(time.perf_counter() - init_ts)


def formatted_uptime() -> str:
    total = uptime()
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or parts:
        parts.append(f"{hours}h")
    if minutes or parts:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)


async def run_sync(func, *args, **kwargs):
    return await asyncio.get_event_loop().run_in_executor(
        None, functools.partial(func, *args, **kwargs),
    )


async def maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def iter_attrs(obj):
    return [(name, getattr(obj, name)) for name in dir(obj) if not name.startswith("__")]


def get_base_dir() -> str:
    if "MAXIMUS_DOCKER" in os.environ:
        return "/data"
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def relative_path(*parts: str) -> Path:
    return Path(get_base_dir()).joinpath(*parts)


def as_document(text: str, name: str = "output.txt") -> File:
    return File(io.BytesIO(text.encode()).getvalue(), name=name)


def smart_truncate(text: str, limit: int = 4000, tail: str = "…") -> str:
    return text if len(text) <= limit else text[:limit - len(tail)] + tail


_known_created_chats: set[int] = set()


async def create_service_group(client, name: str) -> int | None:
    if not client or not getattr(client, "_app", None):
        logger.warning("create_service_group: client or _app is None")
        return None
    try:
        from pymax.api.chats.payloads import CreateGroupAttach, CreateGroupMessage, CreateGroupPayload
        from pymax.protocol import Opcode
        frame = CreateGroupPayload(
            message=CreateGroupMessage(
                cid=int(time.time() * 1000),
                attaches=[CreateGroupAttach(title=name, user_ids=[])],
            ),
            notify=True,
        )
        resp = await client._app.invoke(Opcode.MSG_SEND, frame.to_payload())
        data = resp.payload if hasattr(resp, "payload") else resp
        if isinstance(data, dict):
            chat_obj = data.get("chat")
            if chat_obj:
                cid_data = chat_obj["id"] if isinstance(chat_obj, dict) else getattr(chat_obj, "id", None)
                if cid_data:
                    cid = int(cid_data)
                    _known_created_chats.add(cid)
                    return cid
    except Exception as e:
        logger.exception("Failed to create group '%s': %s", name, e)
    return None


async def get_log_chat(client=None, db=None) -> int | None:
    client = client or _client
    if client is None:
        return None
    try:
        chats = await client.fetch_chats()
    except Exception as e:
        logger.debug("Failed to fetch chats: %s", e)
        chats = getattr(client, "chats", []) or []

    if db is not None:
        saved_id = db.get("main", "log_chat", 0)
        if saved_id:
            if (int(saved_id) in _known_created_chats or
                any(chat.id == int(saved_id) for chat in chats)):
                return int(saved_id)
            db.set("main", "log_chat", 0)

    for chat in chats:
        title = str(getattr(chat, "title", "")).strip().lower()
        if title in {"maximus logs", "maximus log"}:
            if db is not None:
                db.set("main", "log_chat", chat.id)
            return chat.id

    new_id = await create_service_group(client, "Maximus Logs")
    if new_id and db is not None:
        db.set("main", "log_chat", new_id)
    return new_id or 0


async def get_backup_chat(client=None, db=None) -> int | None:
    client = client or _client
    if client is None:
        return None
    try:
        chats = await client.fetch_chats()
    except Exception as e:
        logger.debug("Failed to fetch chats: %s", e)
        chats = getattr(client, "chats", []) or []

    if db is not None:
        saved_id = db.get("main", "backup_chat", 0)
        if saved_id and (int(saved_id) in _known_created_chats or
                         any(chat.id == int(saved_id) for chat in chats)):
            return int(saved_id)
        db.set("main", "backup_chat", 0)

    for chat in chats:
        title = str(getattr(chat, "title", "")).strip().lower()
        if title in {"maximus backups", "maximus backup"}:
            if db is not None:
                db.set("main", "backup_chat", chat.id)
            return chat.id

    new_id = await create_service_group(client, "Maximus Backups")
    if new_id and db is not None:
        db.set("main", "backup_chat", new_id)
    return new_id or 0


from .placeholders import (
    config_placeholders, debug_placeholders, get_placeholder, get_placeholders,
    help_placeholders, module_placeholders, register_placeholder, unregister_placeholders,
)