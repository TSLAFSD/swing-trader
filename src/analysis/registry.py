"""Strategy auto-registry: strategies self-register via decorator at import.

The engine discovers strategies by importing this package's strategy modules;
no hardcoded strategy list exists anywhere else.
"""

import importlib
import logging
import pkgutil
from typing import Any

from src.analysis.base_strategy import BaseStrategy

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, type[BaseStrategy]] = {}


def register(cls: type[BaseStrategy]) -> type[BaseStrategy]:
    """Class decorator: add a BaseStrategy subclass to the registry."""
    if not cls.strategy_id:
        raise ValueError(f"{cls.__name__} must define strategy_id")
    if cls.strategy_id in _REGISTRY:
        raise ValueError(f"duplicate strategy_id {cls.strategy_id!r}")
    _REGISTRY[cls.strategy_id] = cls
    return cls


def _import_strategy_modules() -> None:
    """Import every src.analysis.strategy_* module so decorators run."""
    import src.analysis as pkg

    for info in pkgutil.iter_modules(pkg.__path__):
        if info.name.startswith("strategy_"):
            importlib.import_module(f"src.analysis.{info.name}")


def get_strategies(
    config: dict[str, Any] | None = None, enabled_only: bool = True
) -> list[BaseStrategy]:
    """Instantiate registered strategies.

    Args:
        config: strategies.yaml dict override (tests); default file config.
        enabled_only: If True, return only YAML-enabled strategies.

    Returns:
        Strategy instances (deterministic order by strategy_id).
    """
    _import_strategy_modules()
    instances = [cls(config) for _, cls in sorted(_REGISTRY.items())]
    if enabled_only:
        instances = [s for s in instances if s.enabled]
    logger.info("registry: %d strategies loaded (enabled_only=%s)", len(instances), enabled_only)
    return instances
