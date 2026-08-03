from . import patch


def post_load():
    """Manifest ``post_load`` hook.

    Invoked by ``odoo.service.server.load_server_wide_modules()`` at server
    start — before any registry is built, and for every entrypoint that goes
    through ``odoo.service.server.start()`` (HTTP server, ``--stop-after-init``
    runs such as ``-i``/``-u``, and ``odoo-bin shell``).
    """
    patch.install()
