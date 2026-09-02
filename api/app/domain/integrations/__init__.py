"""Module J — integration adapters (Docs/APIs.md §4, Docs/Backend.md §1).

The public surface is `base`: `get_adapter(name)` and `list_adapters()`. The six
adapter modules register themselves the first time the registry is asked for
anything, so importing this package has no side effects on the database or MinIO.
"""

from app.domain.integrations.base import (  # noqa: F401
    ADAPTER_ORDER,
    Adapter,
    BaseAdapter,
    get_adapter,
    list_adapters,
    register,
)
