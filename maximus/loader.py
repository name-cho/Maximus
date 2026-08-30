"""Module loader for Maximus."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import importlib
import importlib.machinery
import importlib.util
import inspect
import logging
import re
import sys
import typing
from pathlib import Path
from uuid import uuid4

from . import types, utils, validators
from .security import (
    ALL, CHAT_ADMIN, CHAT_MEMBER, CHAT_OWNER, DEFAULT_PERMISSIONS,
    EVERYONE, OWNER, PM, PUBLIC_PERMISSIONS, SUDO, SUPPORT,
    chat_admin, chat_member, chat_owner, owner, pm, sudo, support, unrestricted,
)
from .translations import Strings
from .types import (
    ConfigCategory, ConfigValue, CoreOverwriteError, CoreUnloadError,
    Library, LibraryConfig, LoadError, Module, ModuleConfig,
    SelfSuspend, SelfUnload, StopLoop, StringLoader,
)

logger = logging.getLogger(__name__)

Command = typing.Callable[..., typing.Awaitable[typing.Any]]

BASE_DIR = Path(utils.get_base_dir())
MODULES_PATH = Path(__file__).parent / "modules"
LOADED_MODULES_DIR = BASE_DIR / "loaded_modules"
LOADED_MODULES_DIR.mkdir(parents=True, exist_ok=True)

VALID_URL = re.compile(r"^https?://\S+$")
VALID_PIP_PACKAGES = re.compile(
    r"^\s*# ?requires:(?P<packages>(?:\s*[-_\w\d.=<>;\[\]]+)+)\s*$", re.MULTILINE,
)
VALID_META_DEVELOPER = re.compile(r"^\s*# ?meta developer:\s*(?P<developer>.+)$", re.M)
VALID_META_PIC = re.compile(r"^\s*# ?meta pic:\s*(?P<pic>.+)$", re.M)
VALID_META_BANNER = re.compile(r"^\s*# ?meta banner:\s*(?P<banner>.+)$", re.M)
VALID_META_MIN = re.compile(r"^\s*# ?min-maximus:\s*(?P<version>\d+)\s*$", re.M)
VALID_SCOPE = re.compile(r"^\s*# ?scope:\s*(?P<scope>.+)$", re.M)

IMPORT_PIP_ALIASES = {
    "bs4": "beautifulsoup4", "cv2": "opencv-python",
    "PIL": "Pillow", "yaml": "PyYAML",
    "dateutil": "python-dateutil",
}


class InfiniteLoop:
    """Infinite loop tied to a module's lifecycle."""

    _task: asyncio.Task | None = None
    module_instance: Module | None = None

    def __init__(self, func: typing.Callable, interval: float, autostart: bool,
                 wait_before: bool, stop_clause: str | None):
        self.func = func
        self.interval = interval
        self.autostart = autostart
        self.wait_before = wait_before
        self.stop_clause = stop_clause
        self.status = False
        self._stopped = False
        for attr in ("__doc__", "__name__", "__qualname__"):
            with contextlib.suppress(AttributeError):
                setattr(self, attr, getattr(func, attr))

    def stop(self, *args, **kwargs) -> None:
        if self._task:
            self._stopped = True
            self._task.cancel()
            self._task = None
            self.status = False

    def start(self, *args, **kwargs) -> None:
        if not self._task:
            self._task = asyncio.ensure_future(self.actual_loop(*args, **kwargs))

    async def actual_loop(self, *args, **kwargs) -> None:
        while self.module_instance is None:
            await asyncio.sleep(0.01)
        if self.wait_before:
            await asyncio.sleep(self.interval)
        self.status = True
        while self.status:
            if self.stop_clause and not getattr(self.module_instance, self.stop_clause, True):
                break
            try:
                await self.func(self.module_instance, *args, **kwargs)
            except StopLoop:
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Loop error in %s", self.func)
            await asyncio.sleep(self.interval)
        self._stopped = True
        self.status = False
        self._task = None

    def __del__(self):
        self.stop()


def loop(interval: float = 5, autostart: bool = False,
         wait_before: bool = False, stop_clause: str | None = None) -> typing.Callable:
    def wrapped(func: typing.Callable) -> InfiniteLoop:
        return InfiniteLoop(func, interval, autostart, wait_before, stop_clause)
    return wrapped


def translatable_docstring(cls):
    @functools_wraps_safe(cls.config_complete)
    def config_complete(self, *args, **kwargs):
        for command_, func in get_callable_members(self, "is_command").items():
            with contextlib.suppress(AttributeError, KeyError):
                func.__func__.__doc__ = self.strings[f"_cmd_doc_{command_}"]
        self.__doc__ = self.strings["_cls_doc"]
        return self.config_complete._old_(self, *args, **kwargs)

    config_complete._old_ = cls.config_complete
    cls.config_complete = config_complete
    cls.strings = dict(cls.__dict__.get("strings") or cls.strings)
    for command_, func in get_callable_members(cls, "is_command").items():
        cls.strings[f"_cmd_doc_{command_}"] = inspect.getdoc(func) or "No docs"
    cls.strings["_cls_doc"] = inspect.getdoc(cls) or "No docs"
    return cls


tds = translatable_docstring


def functools_wraps_safe(original):
    def decorator(func):
        with contextlib.suppress(AttributeError, TypeError):
            return functools.wraps(original)(func)
        return func
    return decorator


def get_callable_members(obj: typing.Any, attribute: str) -> dict:
    result = {}
    for name in dir(obj):
        if isinstance(getattr(type(obj), name, None), property):
            continue
        member = getattr(obj, name, None)
        if callable(member) and getattr(member, attribute, False):
            result[name.removesuffix("cmd").lower()] = member
    return result


def ratelimit(func: Command) -> Command:
    func.ratelimit = True
    return func


def tag(*tags: str, **kwarg_tags: typing.Any) -> typing.Callable:
    def inner(func: Command) -> Command:
        for _tag in tags:
            setattr(func, _tag, True)
        for _tag, value in kwarg_tags.items():
            setattr(func, _tag, value)
        return func
    return inner


def _mark_method(mark: str, *args, **kwargs) -> typing.Callable:
    def decorator(func: Command) -> Command:
        setattr(func, mark, True)
        for arg in args:
            setattr(func, arg, True)
        for kwarg, value in kwargs.items():
            setattr(func, kwarg, value)
        return func
    return decorator


def command(*args, **kwargs) -> typing.Callable:
    return _mark_method("is_command", *args, **kwargs)


def watcher(*args, **kwargs) -> typing.Callable:
    return _mark_method("is_watcher", *args, **kwargs)


def raw_handler(*events: str) -> typing.Callable:
    def inner(func: Command) -> Command:
        func.is_raw_handler = True
        func.events = events
        func.id = uuid4().hex
        return func
    return inner


def placeholder(placeholder_name: str, description: str | None = None) -> typing.Callable:
    def decorator(func: typing.Callable) -> typing.Callable:
        func.is_placeholder = True
        func.placeholder_name = placeholder_name
        func.placeholder_description = description
        return func
    return decorator


class Modules:
    """Registry of all loaded modules."""

    def __init__(self, client, db, translator):
        self.client = client
        self.db = db
        self._db = db
        self.translator = translator

        self.modules: list[Module] = []
        self.libraries: list[Library] = []
        self.commands: dict[str, Command] = {}
        self.watchers: list[Command] = []
        self.raw_handlers: list[Command] = []
        self.aliases: dict[str, str] = dict(db.get(__name__, "aliases", {}) or {})
        self.security = None
        self._core_commands: list[str] = []

    def attach_security(self, security) -> None:
        self.security = security

    @property
    def max_id(self) -> int | None:
        return utils.get_me_id()

    async def register_all(self, core_only: bool = False) -> list[Module]:
        external_dir = BASE_DIR / "modules"
        external_dir.mkdir(parents=True, exist_ok=True)

        core = [
            str(path) for path in sorted(MODULES_PATH.glob("*.py"))
            if not path.name.startswith("_")
        ]
        await self._register_modules(core, "<core>")

        if not core_only:
            external = [
                str(path)
                for directory in (external_dir, LOADED_MODULES_DIR)
                for path in sorted(directory.glob("*.py"))
                if not path.name.startswith("_")
            ]
            await self._register_modules(external, "<file>")

        return self.modules

    async def _register_modules(self, paths: list[str], origin: str) -> None:
        for path in paths:
            module_name = f"maximus.modules.{Path(path).stem}"
            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None:
                    raise ImportError(f"Cannot build spec for {path}")
                await self.register_module(spec, module_name, origin)
            except Exception:
                logger.exception("Failed to load module %s", path)

    async def register_module(self, spec: importlib.machinery.ModuleSpec,
                               module_name: str, origin: str = "<core>",
                               save_fs: bool = False) -> Module:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        source_data = None
        if getattr(spec.loader, "data", None):
            source_data = spec.loader.data.decode("utf-8", errors="ignore")
        elif spec.origin and Path(spec.origin).is_file():
            source_data = Path(spec.origin).read_text(encoding="utf-8", errors="ignore")

        await self._exec_module(spec, module, source_data)

        instance = next(
            (value() for value in vars(module).values()
             if inspect.isclass(value) and issubclass(value, Module) and value is not Module),
            None,
        )

        if instance is None:
            if not hasattr(module, "register"):
                raise LoadError(f"Module {module_name} has no Module subclass")
            instance = module.register(module_name)
            if not isinstance(instance, Module):
                raise TypeError(f"Instance is not a Module, it is {type(instance)}")

        if hasattr(module, "__version__"):
            instance.__version__ = module.__version__

        instance.__origin__ = origin
        try:
            instance.__source__ = source_data or inspect.getsource(instance.__class__)
        except OSError:
            instance.__source__ = source_data or ""

        instance.__meta__ = self.parse_meta(instance.__source__)

        if not getattr(instance, "name", None) or instance.name == "Unknown":
            instance.name = instance.strings.get("name", instance.__class__.__name__)

        await self.complete_registration(instance)

        if save_fs and not origin.startswith("<core") and source_data:
            path = LOADED_MODULES_DIR / f"{instance.__class__.__name__}.py"
            path.write_text(source_data, encoding="utf-8")

        return instance

    async def _exec_module(self, spec, module, source_data: str | None) -> None:
        attempted = False
        while True:
            try:
                spec.loader.exec_module(module)
                return
            except ImportError as e:
                if not source_data or attempted:
                    raise
                requirements = self.parse_requirements(source_data)
                missing = (getattr(e, "name", None) or "").split(".")[0]
                if missing:
                    requirements.append(IMPORT_PIP_ALIASES.get(missing, missing))
                if not requirements:
                    raise
                loader_mod = self.lookup("LoaderMod")
                if not loader_mod or not await loader_mod.install_requirements(requirements):
                    raise
                importlib.invalidate_caches()
                attempted = True

    @staticmethod
    def parse_requirements(source: str) -> list[str]:
        match = VALID_PIP_PACKAGES.search(source)
        if not match:
            return []
        return [p for p in map(str.strip, match.group("packages").split())
                if p and not p.startswith(("-", "_", "."))]

    @staticmethod
    def parse_meta(source: str) -> dict:
        meta: dict = {}
        if match := VALID_META_DEVELOPER.search(source):
            meta["developer"] = match.group("developer").strip()
        if match := VALID_META_PIC.search(source):
            meta["pic"] = match.group("pic").strip()
        if match := VALID_META_BANNER.search(source):
            meta["banner"] = match.group("banner").strip()
        if match := VALID_META_MIN.search(source):
            meta["min_maximus"] = int(match.group("version"))
        if match := VALID_SCOPE.search(source):
            meta["scope"] = match.group("scope").strip()
        return meta

    async def complete_registration(self, instance: Module) -> None:
        instance.allmodules = self
        instance.internal_init()
        instance.strings = Strings(instance, self.translator)

        for module in list(self.modules):
            if module.__class__.__name__ != instance.__class__.__name__:
                continue
            if module.__origin__.startswith("<core") and not self._remove_core_protection:
                raise CoreOverwriteError(module=module.__class__.__name__)
            with contextlib.suppress(Exception):
                await module.on_unload()
            self.unregister_loops(module, "update")
            utils.unregister_placeholders(module.__class__.__name__)
            self.modules.remove(module)

        if instance.__origin__.startswith("<core"):
            self._core_commands += [cmd.lower() for cmd in instance.commands]

        self.modules.append(instance)

    @property
    def _remove_core_protection(self) -> bool:
        from . import main
        return bool(self._db.get(main.__name__, "remove_core_protection", False))

    def register_commands(self, instance: Module) -> None:
        for name, func in instance.commands.items():
            if (not self._remove_core_protection
                    and name.lower() in self._core_commands
                    and not instance.__origin__.startswith("<core")):
                with contextlib.suppress(ValueError):
                    self.modules.remove(instance)
                raise CoreOverwriteError(command=name)
            self.commands[name.lower()] = func

        for alias, cmd in self.aliases.copy().items():
            if cmd.split(maxsplit=1)[0] in instance.commands:
                self.add_alias(alias, cmd)

    def register_watchers(self, instance: Module) -> None:
        for existing in self.watchers.copy():
            if existing.__self__.__class__.__name__ == instance.__class__.__name__:
                self.watchers.remove(existing)
        self.watchers += list(instance.watchers.values())

    def register_raw_handlers(self, instance: Module) -> None:
        for existing in self.raw_handlers.copy():
            if existing.__self__.__class__.__name__ == instance.__class__.__name__:
                self.raw_handlers.remove(existing)
        self.raw_handlers += list(instance.raw_handlers.values())

    def unregister_commands(self, instance: Module, purpose: str) -> None:
        for name, func in self.commands.copy().items():
            if func.__self__.__class__.__name__ == instance.__class__.__name__:
                del self.commands[name]

    def unregister_watchers(self, instance: Module, purpose: str) -> None:
        for existing in self.watchers.copy():
            if existing.__self__.__class__.__name__ == instance.__class__.__name__:
                self.watchers.remove(existing)

    def unregister_raw_handlers(self, instance: Module, purpose: str) -> None:
        for existing in self.raw_handlers.copy():
            if existing.__self__.__class__.__name__ == instance.__class__.__name__:
                self.raw_handlers.remove(existing)

    def unregister_loops(self, instance: Module, purpose: str) -> None:
        for name, method in utils.iter_attrs(instance):
            if isinstance(method, InfiniteLoop):
                method.stop()

    def add_alias(self, alias: str, cmd: str) -> bool:
        alias = alias.lower()
        if cmd.split(maxsplit=1)[0].lower() not in self.commands:
            return False
        self.aliases[alias] = cmd
        self._db.set(__name__, "aliases", self.aliases)
        return True

    def remove_alias(self, alias: str) -> bool:
        if self.aliases.pop(alias.lower(), None) is None:
            return False
        self._db.set(__name__, "aliases", self.aliases)
        return True

    def find_alias(self, alias: str) -> str | None:
        if not alias:
            return None
        for command_name, func in self.commands.items():
            aliases = getattr(func, "aliases", None) or (
                [func.alias] if getattr(func, "alias", None) else []
            )
            if any(alias.lower() == str(item).lower() for item in aliases):
                return command_name
        return self.aliases.get(alias.lower())

    def lookup(self, name: str) -> Module | Library | typing.Literal[False]:
        return next(
            (lib for lib in self.libraries if lib.name.lower() == name.lower()), False
        ) or next(
            (mod for mod in self.modules if name.lower() in self._module_names(mod)), False
        )

    @staticmethod
    def _module_names(module: Module) -> set[str]:
        names = {module.__class__.__name__.lower(), str(getattr(module, "name", "")).lower()}
        with contextlib.suppress(Exception):
            names.add(str(module.strings["name"]).lower())
        return names - {""}

    def get_classname(self, name: str) -> str:
        module = self.lookup(name)
        return module.__class__.__name__ if module else name

    def dispatch(self, command_: str):
        from . import main

        homoglyphs = str.maketrans("саеорхуАВЕКМНОРСТХ", "caeorxyABEKMHOPCTX")
        norm_cmd = command_.translate(homoglyphs)

        ru_en = str.maketrans(
            "йцукенгшщзхъфывапролджэячсмитьбюёЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ",
            "qwertyuiop[]asdfghjkl;'zxcvbnm,.`QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~",
        )

        candidates = [
            command_, norm_cmd, command_.translate(ru_en),
            self.aliases.get(command_.lower()),
            self.aliases.get(norm_cmd.lower()),
            self.find_alias(command_), self.find_alias(norm_cmd),
        ]

        resolved = next(
            ((cmd, self.commands[cmd.split()[0].lower()])
             for cmd in candidates
             if cmd and cmd.split()[0].lower() in self.commands),
            (command_, None),
        )

        cmd, func = resolved
        if func is None:
            return resolved

        disabled_modules = self._db.get(main.__name__, "disabled_modules", [])
        disabled_commands = self._db.get(main.__name__, "disabled_commands", {})

        module_name = getattr(getattr(func, "__self__", None), "__class__", None)
        module_name = module_name.__name__ if module_name else None

        if module_name and module_name in disabled_modules:
            return (command_, None)
        if module_name and cmd.split()[0].lower() in [
            item.lower() for item in disabled_commands.get(module_name, [])
        ]:
            return (command_, None)

        return (cmd, func)

    def get_prefix(self, ent_id: int | None = None) -> str:
        from . import main
        if ent_id:
            prefixes = self._db.get(main.__name__, "command_prefixes", {})
            return prefixes.get(str(ent_id), self.get_prefix())
        return self._db.get(main.__name__, "command_prefix", ".")

    def get_prefixes(self) -> set[str]:
        from . import main
        prefixes = {self.get_prefix()}
        prefixes.update(self._db.get(main.__name__, "command_prefixes", {}).values())
        return prefixes

    def set_prefix(self, prefix: str) -> bool:
        from . import main
        return self._db.set(main.__name__, "command_prefix", prefix)

    def send_config(self, skip_hook: bool = False) -> None:
        for module in self.modules:
            self.send_config_one(module, skip_hook)

    def send_config_one(self, mod: Module, skip_hook: bool = False) -> None:
        if getattr(mod, "config", None) is not None:
            modcfg = self._db.get(__name__, "__config__", {}).get(mod.__class__.__name__, {})
            for option in mod.config:
                if option in modcfg:
                    mod.config.set_no_raise(option, modcfg[option])
                else:
                    mod.config.set_no_raise(option, mod.config.getdef(option))
        if skip_hook:
            return
        with contextlib.suppress(Exception):
            mod.config_complete()

    def save_config(self, mod: Module) -> bool:
        if not getattr(mod, "config", None):
            return False
        stored = self._db.get(__name__, "__config__", {})
        stored[mod.__class__.__name__] = dict(mod.config)
        return self._db.set(__name__, "__config__", stored)

    async def send_ready(self) -> None:
        await asyncio.gather(
            *[self.send_ready_one(module) for module in self.modules],
            return_exceptions=True,
        )

    async def send_ready_one(self, mod: Module, no_self_unload: bool = False) -> bool:
        try:
            await mod.client_ready()
        except SelfUnload as e:
            if no_self_unload:
                raise
            await self.unload_module(mod.__class__.__name__)
            return False
        except SelfSuspend:
            return False
        except Exception:
            logger.exception("Failed to send ready to %s", mod)
            return False

        for _, method in utils.iter_attrs(mod):
            if isinstance(method, InfiniteLoop):
                method.module_instance = mod
                if method.autostart:
                    method.start()
            elif callable(method) and getattr(method, "is_placeholder", False):
                utils.register_placeholder(
                    getattr(method, "placeholder_name"),
                    method,
                    getattr(method, "placeholder_description", None),
                )

        self.register_commands(mod)
        self.register_watchers(mod)
        self.register_raw_handlers(mod)
        return True

    async def unload_module(self, classname: str) -> list[str]:
        worked = []
        for module in self.modules.copy():
            if classname.lower() not in self._module_names(module):
                continue
            if module.__origin__.startswith("<core") and not self._remove_core_protection:
                raise CoreUnloadError(module.__class__.__name__)
            worked.append(module.__class__.__name__)
            with contextlib.suppress(Exception):
                await module.on_unload()
            self.unregister_commands(module, "unload")
            self.unregister_watchers(module, "unload")
            self.unregister_raw_handlers(module, "unload")
            self.unregister_loops(module, "unload")
            utils.unregister_placeholders(module.__class__.__name__)
            self.modules.remove(module)
            sys.modules.pop(module.__class__.__module__, None)

        if worked:
            stored = set(self._db.get(__name__, "loaded_modules", [])) - set(worked)
            self._db.set(__name__, "loaded_modules", list(stored))
        return worked

    async def load_module_source(self, source: str, origin: str = "<string>",
                                  save_fs: bool = True) -> Module:
        module_name = f"maximus.modules.{uuid4().hex}"
        loader_ = StringLoader(source, origin)
        spec = importlib.util.spec_from_loader(module_name, loader_)
        instance = await self.register_module(spec, module_name, origin, save_fs)
        self.send_config_one(instance)
        await self.send_ready_one(instance)
        return instance

    async def reload_translations(self) -> bool:
        if not await self.translator.init():
            return False
        for module in self.modules:
            module.strings = Strings(module, self.translator)
            with contextlib.suppress(Exception):
                module.config_complete()
        return True