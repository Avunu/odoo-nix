"""Put on PYTHONPATH by `odoo` (odoo_nix_cli/__main__.py) before it execs
odoo-bin under journald, so odoo-bin's interpreter -- and every process that
inherits its environment, the gevent websocket child included -- patches
odoo.netsvc.init_logger as it is imported (see odoo_nix_cli/journald.py).

Python imports the first `sitecustomize` on sys.path and only that one, so
this one steps aside afterwards and imports whichever it shadowed.
"""
import importlib
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_lib = os.path.dirname(os.path.dirname(_here))

try:
    sys.path.insert(0, _lib)
    from odoo_nix_cli import journald

    if journald.enabled():
        journald.install_import_hook()
except Exception:  # noqa: BLE001, S110 -- never stop Odoo from starting over its log format
    pass
finally:
    sys.path.remove(_lib)
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _here]

# The import machinery re-reads sys.modules["sitecustomize"] once this module
# finishes executing, so something must be there: the shadowed module if
# there is one, else this one again.
_self = sys.modules.pop("sitecustomize")
try:
    importlib.import_module("sitecustomize")
except ImportError as exc:
    sys.modules["sitecustomize"] = _self
    if exc.name != "sitecustomize":
        raise
