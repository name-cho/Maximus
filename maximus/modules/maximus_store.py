"""Module store — search, list, download, and update modules."""
# scope: maximus_only
# meta developer: @name_cho

from __future__ import annotations

import os
import re
import time

import aiohttp
from pymax import Message

from .. import loader, utils

REPO = "name-cho/MaximusStore"
API = f"https://gitverse.ru/api/v1/repos/{REPO}/contents"
RAW = f"https://gitverse.ru/{REPO}/raw/branch/main"

PENDING_UPDATES = {}
UPDATES_TTL = 600


def v2t(v):
    try:
        return tuple(map(int, re.sub(r'[^0-9.]', '', v).split('.')))
    except Exception:
        return (0, 0, 0)


def parse_meta(text):
    h = {"name": None, "version": None, "id": None}
    for line in text.splitlines()[:15]:
        if not line.startswith('#'):
            continue
        for k in ("name", "version", "id"):
            m = re.search(rf"^\s*#\s*{k}\s*:\s*(.+)", line, re.IGNORECASE)
            if m:
                h[k] = m.group(1).strip()
    return h


def local_mods():
    local = {}
    mods_dir = utils.relative_path("modules")
    if not os.path.isdir(mods_dir):
        return local
    for fn in os.listdir(mods_dir):
        if not fn.endswith(".py") or fn == "__init__.py":
            continue
        fp = os.path.join(mods_dir, fn)
        try:
            with open(fp, encoding="utf-8") as f:
                meta = parse_meta(f.read())
            local[meta.get("id") or fn.replace(".py", "")] = {
                "name": meta.get("name", fn.replace(".py", "")),
                "version": meta.get("version", "0.0.0"),
                "file": fn,
            }
        except Exception:
            pass
    return local


@loader.tds
class MaximusStore(loader.Module):
    """Module store — search, list, download, update"""

    strings = {"name": "Store"}
    strings_ru = {"name": "Магазин"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "color",
                "blue",
                lambda: "Цвет",
                validator=loader.validators.Choice(["blue", "red", "green"]),
            ),
        )

    async def _tree(self):
        async with aiohttp.ClientSession() as s:
            async with s.get(API, headers={"User-Agent": "Maximus"}) as r:
                if r.status == 200:
                    data = await r.json()
                    return [i for i in data if i.get("type") == "file" and i["name"].endswith(".py")]
        return None

    async def _meta(self, name):
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{RAW}/{name}", headers={"User-Agent": "Maximus"}) as r:
                if r.status == 200:
                    text = await r.text()
                    return parse_meta(text), len(text)
        return None, 0

    @loader.command()
    async def sscmd(self, message: Message):
        """.ss <запрос> — поиск модулей"""
        q = " ".join(utils.get_args(message)).lower()
        if not q:
            await utils.answer(message, "❌ .ss <запрос>")
            return
        tree = await self._tree()
        if tree is None:
            await utils.answer(message, "❌ Не могу подключиться к магазину")
            return
        matched = [m for m in tree if q in m["name"].lower().replace(".py", "")][:20]
        if not matched:
            await utils.answer(message, f"❌ Ничего не найдено: {q}")
            return
        p = self.get_prefix()
        body = "\n".join(f"{i}. {m['name'].replace('.py', '')}" for i, m in enumerate(matched, 1))
        await utils.answer(message, utils.heading(f"🔍 {q}") + "\n" + utils.quote(body) + f"\n💾 {p}sd <номер>")

    @loader.command()
    async def slcmd(self, message: Message):
        """.sl — список всех модулей"""
        tree = await self._tree()
        if tree is None:
            await utils.answer(message, "❌ Не могу подключиться к магазину")
            return
        p = self.get_prefix()
        shown = tree[:30]
        body = "\n".join(f"{i}. {m['name'].replace('.py', '')}" for i, m in enumerate(shown, 1))
        if len(tree) > 30:
            body += f"\n… +{len(tree) - 30}"
        await utils.answer(message, utils.heading(f"📦 {len(tree)} модулей") + "\n" + utils.quote(body) + f"\n💾 {p}sd <номер>")

    @loader.command()
    async def sdcmd(self, message: Message):
        """.sd <номер|имя> — скачать модуль"""
        args = utils.get_args(message)
        if not args:
            await utils.answer(message, "❌ .sd <номер> или .sd <имя>")
            return
        tree = await self._tree()
        if tree is None:
            await utils.answer(message, "❌ Не могу подключиться к магазину")
            return
        q = args[0]
        if q.isdigit():
            i = int(q) - 1
            if 0 <= i < len(tree):
                mod = tree[i]
            else:
                await utils.answer(message, f"❌ Неверный номер (1-{len(tree)})")
                return
        else:
            name = " ".join(args).lower()
            matched = [m for m in tree if m["name"].lower().replace(".py", "") == name]
            if not matched:
                matched = [m for m in tree if name in m["name"].lower().replace(".py", "")]
            if not matched:
                await utils.answer(message, f"❌ Не найдено: {name}")
                return
            if len(matched) > 1:
                await utils.answer(message, "❌ Несколько совпадений:\n" + "\n".join(f"• {m['name'].replace('.py', '')}" for m in matched[:5]))
                return
            mod = matched[0]

        mod_name = mod["name"].replace(".py", "")
        await utils.answer(message, f"⬇️ **{mod_name}**...")
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{RAW}/{mod['name']}", headers={"User-Agent": "Maximus"}) as r:
                if r.status != 200:
                    await utils.answer(message, "❌ Ошибка скачивания")
                    return
                content = await r.text()

        dst = utils.relative_path("modules", mod["name"])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)

        meta = parse_meta(content)
        sz = len(content) / 1024
        await utils.answer(message, f"✅ **{meta.get('name', mod_name)}** установлен\n" + utils.quote(f"{sz:.1f} КБ | modules/{mod['name']}") + f"\n♻️ {self.get_prefix()}restart")

    @loader.command()
    async def sucmd(self, message: Message):
        """.su — проверить обновления"""
        tree = await self._tree()
        if tree is None:
            await utils.answer(message, "❌ Не могу подключиться к магазину")
            return
        local = local_mods()
        updates = []
        for m in tree:
            mid = m["name"].replace(".py", "")
            li = local.get(mid)
            if not li:
                continue
            meta, _ = await self._meta(m["name"])
            if meta and v2t(meta.get("version", "0")) > v2t(li["version"]):
                updates.append({"id": mid, "name": meta.get("name", mid), "local": li["version"], "remote": meta.get("version", "0"), "file": m["name"]})

        if updates:
            body = "\n".join(f"• **{u['name']}** {u['local']} → {u['remote']}" for u in updates)
            PENDING_UPDATES["modules"] = updates
            PENDING_UPDATES["expires_at"] = time.time() + UPDATES_TTL
            await utils.answer(message, utils.heading(f"🆕 {len(updates)} обновлений") + "\n" + utils.quote(body) + f"\n💡 {self.get_prefix()}sg y")
        else:
            await utils.answer(message, "✅ Всё актуально")

    @loader.command()
    async def sgcmd(self, message: Message):
        """.sg y|n — применить или отменить обновления"""
        args = utils.get_args(message)
        a = args[0].lower() if args else ""

        if a == "y":
            if PENDING_UPDATES and PENDING_UPDATES.get("expires_at", 0) > time.time():
                updates = PENDING_UPDATES["modules"]
            else:
                tree = await self._tree()
                if tree is None:
                    await utils.answer(message, "❌ Не могу подключиться к магазину")
                    return
                local = local_mods()
                updates = []
                for m in tree:
                    mid = m["name"].replace(".py", "")
                    li = local.get(mid)
                    if not li:
                        continue
                    meta, _ = await self._meta(m["name"])
                    if meta and v2t(meta.get("version", "0")) > v2t(li["version"]):
                        updates.append({"id": mid, "name": meta.get("name", mid), "file": m["name"]})

            if not updates:
                await utils.answer(message, "✅ Нечего обновлять")
                return

            await utils.answer(message, f"⬇️ Обновляю {len(updates)}...")
            results = []
            async with aiohttp.ClientSession() as s:
                for u in updates:
                    try:
                        async with s.get(f"{RAW}/{u['file']}", headers={"User-Agent": "Maximus"}) as r:
                            if r.status != 200:
                                results.append(f"❌ {u['name']} — ошибка")
                                continue
                            content = await r.text()
                        with open(utils.relative_path("modules", u["file"]), "w", encoding="utf-8") as f:
                            f.write(content)
                        results.append(f"✅ {u['name']}")
                    except Exception as e:
                        results.append(f"❌ {u['name']} — {e}")
            PENDING_UPDATES.clear()
            await utils.answer(message, utils.heading("Результат") + "\n" + utils.quote("\n".join(results)))
            return

        if a == "n":
            PENDING_UPDATES.clear()
            await utils.answer(message, "❌ Отменено")
            return

        if not PENDING_UPDATES or PENDING_UPDATES.get("expires_at", 0) <= time.time():
            await utils.answer(message, f"ℹ️ Сначала {self.get_prefix()}su")
            return

        updates = PENDING_UPDATES["modules"]
        body = "\n".join(f"• **{u['name']}**" for u in updates)
        await utils.answer(message, utils.heading(f"📦 {len(updates)} ожидают") + "\n" + utils.quote(body) + f"\n💡 {self.get_prefix()}sg y | {self.get_prefix()}sg n")

    @loader.command()
    async def srcmd(self, message: Message):
        """.sr — информация о магазине"""
        p = self.get_prefix()
        await utils.answer(message, utils.heading("📂 Магазин модулей") + "\n" + utils.quote(f"🔗 https://gitverse.ru/{REPO}") + f"\n{p}ss <запрос> — поиск\n{p}sl — список\n{p}sd <номер> — скачать\n{p}su — проверить\n{p}sg y — обновить")