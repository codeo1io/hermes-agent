"""The Kimi (Moonshot) provider must never offer brotli (#28043, #48428, #59556).

httpx's brotlicffi backend mis-decodes Moonshot's `content-encoding: br` SSE
responses (notably in the Electron-packaged venv on Windows), surfacing as
"API call failed after 3 retries: Connection error". The provider pins
`Accept-Encoding: gzip` so the API falls back to gzip, which httpx handles
everywhere. This pins the invariant: the header never re-admits br.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

_PLUGIN = (Path(__file__).resolve().parents[2]
           / "plugins" / "model-providers" / "kimi-coding" / "__init__.py")


def _load_plugin():
    providers = types.ModuleType("providers")
    providers.register_provider = lambda *a, **k: None
    base = types.ModuleType("providers.base")
    base.OMIT_TEMPERATURE = object()

    class _Profile:  # permissive stand-in; the plugin instantiates profiles at import
        def __init__(self, *args, **kwargs):
            pass

    base.ProviderProfile = _Profile
    providers.base = base
    spec = importlib.util.spec_from_file_location("_kimi_coding_under_test", _PLUGIN)
    module = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, {"providers": providers, "providers.base": base}):
        spec.loader.exec_module(module)
    return module


class TestKimiCodingNeverOffersBrotli:
    def test_accept_encoding_excludes_brotli(self):
        headers = _load_plugin()._HEADERS
        accepted = headers.get("Accept-Encoding", "")
        assert "br" not in accepted.split(","), (
            "Accept-Encoding re-admitted brotli; Moonshot SSE streams will "
            "hit the brotlicffi decode bug again (#28043, #48428, #59556)"
        )
        assert "gzip" in accepted  # compression stays on, just a safe codec
