import sys
from typing import Any


def _get_app_state():
    """Access the AppState instance from the entry-point module.

    ``main.py`` creates ``app_state = AppState(APP_ROOT_DIR)`` at module level;
    this helper retrieves it via ``sys.modules`` to avoid circular
    imports or duplicating the singleton in ``app_state.py``.

    Checks both ``__main__`` (direct ``python main.py`` / ``uv run main.py``)
    and ``main`` (``uvicorn main:app``) execution modes.
    """
    for mod_name in ("__main__", "main"):
        main_mod = sys.modules.get(mod_name)
        if main_mod is not None and hasattr(main_mod, "app_state"):
            return main_mod.app_state
    return None


def filter_resources_by_controller_type(
    resources: list[dict[str, Any]], controller_type: str
) -> list[dict[str, Any]]:
    """Filter resource dicts by controller type.

    Returns resources whose ``controller`` field is *None* (compatible
    with all), empty, or contains at least one controller name matching
    the given type.

    Controller-name-to-type mapping is resolved from the loaded
    interface (``InterfaceModel.controller``).  When the interface is
    not available (e.g. worker not yet initialised) the function skips
    filtering and returns all resources unchanged to avoid false
    negatives.
    """
    controller_names: list[str] | None = None

    app_state = _get_app_state()
    if app_state is not None:
        worker = getattr(app_state, "worker", None)
        if worker is not None:
            interface = getattr(worker, "interface", None)
            if interface is not None:
                controllers = getattr(interface, "controller", None)
                if controllers is not None:
                    controller_names = [
                        c.name for c in controllers if c.type == controller_type
                    ]

    result: list[dict[str, Any]] = []
    for resource in resources:
        rc = resource.get("controller")

        # None or empty list → compatible with all controller types
        if not rc:
            result.append(resource)
            continue

        if controller_names is not None:
            # Interface was available — match against known names
            if any(name in controller_names for name in rc):
                result.append(resource)
        else:
            # Interface mapping unavailable — cannot reliably match
            # controller names to types, so keep the resource to avoid
            # false negatives.
            result.append(resource)

    return result
