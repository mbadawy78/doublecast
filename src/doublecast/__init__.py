"""Doublecast: keep your data home, send its double to the AI.

Doublecast swaps sensitive values (people, companies, sites, IDs, IBANs,
prices, secrets) for realistic stand-ins before text leaves your machine,
and puts the real values back into the AI's answer.
"""

__version__ = "0.2.2"

from .config import Config, load_config  # noqa: E402,F401
from .engine import Engine, ScrambleResult  # noqa: E402,F401
