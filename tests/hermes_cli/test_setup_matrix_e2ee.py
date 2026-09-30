"""hermes_cli/setup.py must bind shutil at module level.

The Matrix E2EE auto-install path in ``setup_gateway`` calls
``shutil.which('uv')`` while resolving the mautrix bridge installer; losing the
module-level binding produced a NameError mid-setup. The contract is checked on
the live imported module — the behavior the regression is actually about — not
on the file's source text.
"""

import shutil as _stdlib_shutil


def test_setup_module_binds_shutil_at_module_level():
    from hermes_cli import setup as setup_module

    # The module-level name must resolve to the stdlib module and be usable by
    # setup_gateway's mautrix auto-install path (shutil.which('uv')).
    assert setup_module.shutil is _stdlib_shutil
    assert callable(setup_module.shutil.which)
