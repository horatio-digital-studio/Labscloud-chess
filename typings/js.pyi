# Type stub for Pyodide's `js` module (the JavaScript global scope inside a Python Worker).
# Every attribute is a JavaScript object, so everything is Any.
from typing import Any

def __getattr__(name: str) -> Any: ...
