# Maximus

Модульный юзербот для мессенджера **MAX**. Транспорт — [PyMax](https://github.com/MaxApiTeam/PyMax) (`maxapi-python`).

## Установка

```bash
git clone https://github.com/name-cho/Maximus
cd Maximus
pip install -r requirements.txt
python -m maximus
```

При первом запуске спросит номер телефона и код из SMS. Сессия — `sessions/maximus.db`, конфиг — `config.json`, база — `maximus-db.json`.

QR-логин:
```bash
python -m maximus --web
```

## Аргументы

| Аргумент | Описание |
|---|---|
| `--phone`, `-p` | Номер телефона |
| `--session` | Имя файла сессии |
| `--proxy` | Прокси |
| `--web` | WebClient + QR |
| `--log-level` | Уровень логов |
| `--no-modules` | Без пользовательских модулей |

## Модули и команды

### Ядро

| Модуль | Команды |
|---|---|
| **Help** | `.help [модуль]`, `.modinfo <модуль>` |
| **MaximusInfo** | `.info`, `.ping` |
| **Config** | `.config [модуль] [опция] [значение]`, `.resetcfg` |
| **Settings** | `.setprefix`, `.aliases`, `.addalias`, `.delalias`, `.blacklist`, `.unblacklist`, `.blacklistuser`, `.unblacklistuser`, `.blacklists`, `.togglemod`, `.togglecmd`, `.disabled`, `.clearmodule`, `.cleardb` |
| **MaximusSettings** | `.settings`, `.watchers`, `.watcher`, `.watcherbl`, `.whitelist`, `.unwhitelist`, `.coreprotection` |
| **MaximusSecurity** | `.owneradd`, `.ownerrm`, `.ownerlist`, `.sudoadd`, `.sudorm`, `.supportadd`, `.supportrm`, `.tsec`, `.tsecrm`, `.tsecclr` |
| **Loader** | `.load`, `.unload`, `.reload` |
| **Updater** | `.update`, `.restart`, `.version` |
| **MaximusBackup** | `.backupdb`, `.restoredb`, `.backupmods`, `.backupall` |
| **Translations** | `.setlang`, `.dllangpack`, `.langpacks`, `.reloadlang` |
| **Presets** | `.presets`, `.loadpreset`, `.savepreset`, `.mypresets` |
| **Tester** | `.logs`, `.clearlogs`, `.loglevel`, `.debugmods`, `.suspend`, `.dump` |
| **Quickstart** | `.quickstart`, `.start` |
| **Terminal** | `.terminal`, `.kill` |
| **Eval** | `.e`, `.db` |
| **Maximus Store** | `.ss <запрос>`, `.sl`, `.sd <номер>`, `.su`, `.sg`, `.sr` |

### Возможности MAX

| Модуль | Команды |
|---|---|
| **Chats** | `.chats`, `.chatinfo`, `.newgroup`, `.joinchat`, `.leavechat`, `.invite`, `.kick`, `.members`, `.setgrname`, `.setgrdesc` |
| **Users** | `.user`, `.searchphone`, `.contacts`, `.addcontact`, `.delcontact` |
| **Account** | `.setname`, `.setbio`, `.setpfp`, `.folders`, `.check2fa`, `.set2fa` |
| **Messages** | `.history`, `.id`, `.forward`, `.copy`, `.pin`, `.delmsg`, `.react`, `.unreact` |

## Maximus Store

Магазин модулей из репозитория [name-cho/MaximusStore](https://gitverse.ru/name-cho/MaximusStore).

```bash
.ss <запрос>   — поиск модулей
.sl            — список всех модулей
.sd <номер>    — скачать и установить
.su            — проверить обновления
.sg y          — применить обновления
.sr            — информация о сторе
```

Модули скачиваются в `modules/`, после установки нужен `.restart`.

## Написание модулей

```python
# meta developer: @username
# requires: aiohttp
# min-maximus: 100

from maximus import loader, utils


@loader.tds
class ExampleMod(loader.Module):
    """Пример модуля"""

    strings = {"name": "Example"}

    def __init__(self):
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "greeting",
                "Привет",
                lambda: "Текст приветствия",
                validator=loader.validators.String(),
            ),
        )

    async def client_ready(self):
        self.counter = self.pointer("counter", 0)

    @loader.command(alias="ex")
    async def examplecmd(self, message):
        """— поздороваться"""
        await utils.answer(message, self.config["greeting"])
```

### Разметка MAX

MAX понимает **markdown**. Хелперы в `utils`:

```python
utils.heading("Заголовок")   # → # Заголовок
utils.quote("строка\nещё")   # → > строка\n> ещё
utils.mono("значение")       # → `значение`
utils.unmark(text)           # снимает маркеры разметки
```

### Что даёт базовый класс

- `self.client` — клиент PyMax
- `self.db` — база данных, `self.get()` / `self.set()` / `self.pointer()`
- `self.allmodules` — реестр модулей, `self.lookup("Имя")`
- `self.strings["key"]` — строки из langpack
- `self.config` — настройки модуля
- `self.get_prefix()` — текущий префикс
- `self.invoke("cmd", "args", message)` — вызов другой команды

### Хуки

| Метод | Когда |
|---|---|
| `config_complete()` | Конфиг заполнен из БД |
| `client_ready()` | Клиент готов |
| `on_unload()` | Выгрузка модуля |

### Декораторы

`@loader.command()`, `@loader.watcher()`, `@loader.raw_handler()`, `@loader.loop(interval=...)`, `@loader.tag(...)`, `@loader.ratelimit`, `@loader.owner`, `@loader.sudo`, `@loader.support`, `@loader.chat_admin`, `@loader.pm`, `@loader.unrestricted`.

## Структура

```
maximus/
├── main.py          — сборка и запуск
├── loader.py        — реестр модулей, декораторы
├── types.py         — Module, ModuleConfig, ConfigValue
├── dispatcher.py    — разбор команд, вотчеры
├── security.py      — права доступа
├── database.py      — JSON-хранилище
├── translations.py  — Translator, Strings
├── validators.py    — валидаторы конфига
├── pointers.py      — самосохраняющиеся list/dict/set
├── utils.py         — утилиты
├── log.py           — логирование
├── _internal.py     — restart / update
├── placeholders.py  — плейсхолдеры
├── langpacks/       — en.yml, ru.yml
└── modules/         — системные модули
```

## Лицензия

AGPLv3.
