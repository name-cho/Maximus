"""Placeholders for Maximus."""

from __future__ import annotations

import inspect
import logging
import typing

logger = logging.getLogger(__name__)

custom_placeholders: dict[str, dict[str, typing.Any]] = {}


def register_placeholder(placeholder: str, callback: typing.Callable,
                          description: str | None = None) -> bool:
    owner_cls = getattr(getattr(callback, "__self__", None), "__class__", None)
    module_name = owner_cls.__name__ if owner_cls else "core"
    module_instance = getattr(callback, "__self__", None)

    custom_placeholders[placeholder] = {
        "module_name": module_name, "module_instance": module_instance,
        "callback": callback, "description": description,
        "placeholder_name": placeholder,
    }
    logger.debug("Registered placeholder {%s} from %s", placeholder, module_name)
    return True


async def get_placeholder(placeholder: str, data: dict | None = None) -> str:
    if placeholder not in custom_placeholders:
        return ""
    callback = custom_placeholders[placeholder]["callback"]
    try:
        if inspect.iscoroutinefunction(callback):
            try:
                res = await callback(data)
            except TypeError:
                res = await callback()
        else:
            try:
                res = callback(data)
            except TypeError:
                res = callback()
        return str(res)
    except Exception:
        logger.exception("Error evaluating placeholder {%s}", placeholder)
        return ""


async def get_placeholders(data: dict, custom_message: str | None) -> dict:
    if custom_message is None:
        return data
    res = dict(data)
    for placeholder_name, placeholder_data in custom_placeholders.items():
        if f"{{{placeholder_name}}}" in custom_message:
            res[placeholder_name] = await get_placeholder(placeholder_name, res)
    return res


def unregister_placeholders(module_name: str) -> bool:
    to_remove = [n for n, d in custom_placeholders.items() if d.get("module_name") == module_name]
    for name in to_remove:
        del custom_placeholders[name]
    return True


def config_placeholders() -> str | None:
    result = [f"{{{n}}} — {d.get('description') or 'Без описания'}"
              for n, d in sorted(custom_placeholders.items())]
    return "\n".join(result) if result else None


def module_placeholders(module_name: str) -> list[str]:
    return [n for n, d in custom_placeholders.items() if d.get("module_name") == module_name]


def help_placeholders(module_name: str) -> list[str]:
    return [f"{{{n}}} — {d.get('description') or 'Без описания'}"
            for n, d in sorted(custom_placeholders.items())
            if d.get("module_name") == module_name]


def debug_placeholders() -> dict:
    return custom_placeholders