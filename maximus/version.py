"""Version of Maximus."""

__version__ = (1, 0, 0)

version_code = 100

branch = "main"

min_pymax = "2.3.1"


def pretty() -> str:
    return ".".join(map(str, __version__))