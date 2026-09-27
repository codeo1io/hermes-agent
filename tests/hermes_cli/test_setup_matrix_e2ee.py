"""Matrix E2EE auto-install contract: setup.py's mautrix path can resolve tools via shutil."""

import shutil

from hermes_cli import setup


class TestSetupShutilImport:
    def test_shutil_bound_at_module_level(self):
        """``setup_gateway``'s mautrix auto-install calls ``shutil.which('uv')``; the
        binding must resolve through the import system (module attribute == the stdlib
        module), not merely read well in source form. A NameError here breaks the
        Matrix E2EE auto-install path."""
        assert setup.shutil is shutil
