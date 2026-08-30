"""Permission system for Maximus. Bitmask-based: OWNER, SUDO, SUPPORT, etc."""

from __future__ import annotations

import logging
import time
import typing

from pymax import Message

from . import utils

logger = logging.getLogger(__name__)

OWNER = 1 << 0
SUDO = 1 << 1
SUPPORT = 1 << 2
CHAT_OWNER = 1 << 3
CHAT_ADMIN = 1 << 4
CHAT_MEMBER = 1 << 5
PM = 1 << 6
EVERYONE = 1 << 7

BITMAP = {k: v for k, v in locals().items() if isinstance(v, int) and v > 0 and k.isupper()}

DEFAULT_PERMISSIONS = OWNER
PUBLIC_PERMISSIONS = CHAT_OWNER | CHAT_ADMIN | CHAT_MEMBER | PM
ALL = (1 << 8) - 1


def _sec(func, flags: int):
    func.security = flags
    return func


def owner(func): return _sec(func, OWNER)
def sudo(func): return _sec(func, OWNER | SUDO)
def support(func): return _sec(func, OWNER | SUDO | SUPPORT)
def chat_owner(func): return _sec(func, OWNER | CHAT_OWNER)
def chat_admin(func): return _sec(func, OWNER | CHAT_OWNER | CHAT_ADMIN)
def chat_member(func): return _sec(func, OWNER | CHAT_OWNER | CHAT_ADMIN | CHAT_MEMBER)
def pm(func): return _sec(func, OWNER | PM)
def unrestricted(func): return _sec(func, ALL)


class SecurityManager:
    """Checks whether the sender is allowed to execute a command."""

    def __init__(self, client, db):
        self._client = client
        self._db = db
        self._reload_rights()

    def _reload_rights(self) -> None:
        self._owner = list(set(self._db.get(__name__, "owner", []) or []))
        self._sudo = list(set(self._db.get(__name__, "sudo", []) or []))
        self._support = list(set(self._db.get(__name__, "support", []) or []))
        self._tsec = self._db.get(__name__, "tsec", {}) or {}

    @property
    def owner(self) -> list[int]:
        self._reload_rights()
        return self._owner

    @property
    def sudo(self) -> list[int]:
        self._reload_rights()
        return self._sudo

    @property
    def support(self) -> list[int]:
        self._reload_rights()
        return self._support

    def add_owner(self, user_id: int) -> bool:
        owners = set(self.owner) | {int(user_id)}
        return self._db.set(__name__, "owner", list(owners))

    def remove_owner(self, user_id: int) -> bool:
        owners = set(self.owner) - {int(user_id)}
        return self._db.set(__name__, "owner", list(owners))

    def add_sudo(self, user_id: int) -> bool:
        return self._db.set(__name__, "sudo", list(set(self.sudo) | {int(user_id)}))

    def remove_sudo(self, user_id: int) -> bool:
        return self._db.set(__name__, "sudo", list(set(self.sudo) - {int(user_id)}))

    def add_support(self, user_id: int) -> bool:
        return self._db.set(__name__, "support", list(set(self.support) | {int(user_id)}))

    def remove_support(self, user_id: int) -> bool:
        return self._db.set(__name__, "support", list(set(self.support) - {int(user_id)}))

    @property
    def sgroups(self) -> dict:
        raw = self._db.get(__name__, "sgroups", {}) or {}
        return {name: {"users": list(d.get("users", [])), "permissions": int(d.get("permissions", 0))}
                for name, d in raw.items()}

    def _save_sgroups(self, groups: dict) -> bool:
        return self._db.set(__name__, "sgroups", groups)

    def create_sgroup(self, name: str, permissions: int = 0) -> bool:
        groups = self.sgroups
        if name in groups:
            return False
        groups[name] = {"users": [], "permissions": permissions}
        return self._save_sgroups(groups)

    def delete_sgroup(self, name: str) -> bool:
        groups = self.sgroups
        if groups.pop(name, None) is None:
            return False
        return self._save_sgroups(groups)

    def sgroup_add_user(self, name: str, user_id: int) -> bool:
        groups = self.sgroups
        if name not in groups:
            return False
        groups[name]["users"] = list(set(groups[name]["users"]) | {int(user_id)})
        return self._save_sgroups(groups)

    def sgroup_remove_user(self, name: str, user_id: int) -> bool:
        groups = self.sgroups
        if name not in groups:
            return False
        groups[name]["users"] = list(set(groups[name]["users"]) - {int(user_id)})
        return self._save_sgroups(groups)

    def sgroup_set_permissions(self, name: str, permissions: int) -> bool:
        groups = self.sgroups
        if name not in groups:
            return False
        groups[name]["permissions"] = int(permissions)
        return self._save_sgroups(groups)

    def get_sgroup_permissions(self, user_id: int) -> int:
        result = 0
        for group in self.sgroups.values():
            if user_id in group["users"]:
                result |= group["permissions"]
        return result

    def add_rule(self, target_type: str, target_id: int, rule: str, duration: int = 0) -> bool:
        if target_type not in {"user", "chat"}:
            raise ValueError("target_type must be 'user' or 'chat'")
        self._reload_rights()
        bucket = self._tsec.setdefault(target_type, {}).setdefault(str(target_id), [])
        bucket.append({"rule": rule, "expires": round(time.time()) + duration if duration else 0})
        return self._db.set(__name__, "tsec", self._tsec)

    def remove_rules(self, target_type: str, target_id: int) -> bool:
        self._reload_rights()
        if str(target_id) in self._tsec.get(target_type, {}):
            del self._tsec[target_type][str(target_id)]
            return self._db.set(__name__, "tsec", self._tsec)
        return False

    def check_tsec(self, user_id: int, command: str, module: str = "") -> bool:
        self._reload_rights()
        rules = self._tsec.get("user", {}).get(str(user_id), [])
        now = round(time.time())
        for rule in rules:
            if rule.get("expires") and rule["expires"] < now:
                continue
            value = rule.get("rule", "")
            if value == command.lower():
                return True
            if value.startswith("$") and value[1:].lower() == module.lower():
                return True
        return False

    def get_flags(self, func, default: int | None = None) -> int:
        owner_cls = getattr(getattr(func, "__self__", None), "__class__", None)
        if owner_cls is not None:
            configured = self._db.get(__name__, "masks", {}).get(f"{owner_cls.__name__}.{func.__name__}")
            if configured is not None:
                return int(configured)
        if hasattr(func, "security"):
            return func.security
        return self._db.get(__name__, "default_permissions", default or DEFAULT_PERMISSIONS)

    def set_flags(self, func, flags: int) -> bool:
        masks = self._db.get(__name__, "masks", {})
        masks[f"{func.__self__.__class__.__name__}.{func.__name__}"] = int(flags)
        return self._db.set(__name__, "masks", masks)

    async def check(self, message: Message | None, func, *,
                    user_id: int | None = None) -> bool:
        self._reload_rights()
        flags = self.get_flags(func)
        if not flags:
            return False
        if flags & EVERYONE:
            return True

        if user_id is None:
            user_id = utils.get_sender_id(message) if message else None
        if user_id is None:
            return False

        me = utils.get_me_id()
        if me is not None and user_id == me:
            return True
        if flags & OWNER and user_id in self._owner:
            return True
        if flags & SUDO and user_id in self._sudo:
            return True
        if flags & SUPPORT and user_id in self._support:
            return True
        if flags & self.get_sgroup_permissions(user_id):
            return True

        command = getattr(func, "__name__", "").removesuffix("cmd").lower()
        module = getattr(getattr(func, "__self__", None), "__class__", type(None)).__name__
        if self.check_tsec(user_id, command, module):
            return True

        if message is None:
            return False
        chat = await utils.get_chat(message)
        if chat is None:
            return False
        if flags & PM and utils.is_private(chat):
            return True
        if flags & CHAT_OWNER and getattr(chat, "owner", None) == user_id:
            return True
        if flags & CHAT_ADMIN and user_id in (getattr(chat, "admins", None) or []):
            return True
        if flags & CHAT_MEMBER and user_id in (getattr(chat, "participants", None) or {}):
            return True
        return False