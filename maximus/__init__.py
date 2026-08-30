"""Maximus — modular userbot for messenger MAX.

Transport — PyMax (``maxapi-python``).

Example module::

    from maximus import loader, utils


    @loader.tds
    class HelloMod(loader.Module):
        \"\"\"Says hello\"\"\"

        strings = {"name": "Hello"}

        @loader.command()
        async def hellocmd(self, message):
            \"\"\"Say hello\"\"\"
            await utils.answer(message, "Hello!")
"""

from .version import __version__, branch, version_code

__all__ = ("__version__", "branch", "version_code")