"""Built-in adapters.

Importing this package registers every built-in view. `fairyview.views` holds
the registry and does not import these modules itself (they import it), so any
entry point that needs the registry imports this package first.
"""

from fairyview.adapters import (  # noqa: F401  (import registers)
    auto,
    chat_rows,
    columns_rows,
    hf_rows,
    multi_model,
    paired,
)

__all__ = ["auto", "chat_rows", "columns_rows", "hf_rows", "multi_model", "paired"]
