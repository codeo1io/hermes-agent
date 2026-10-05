"""Companion GGUFs (mmproj projectors, draft/MTP heads) are never servable presets.

A user dropping ``model-Q4_K_M.gguf`` + ``mmproj-model-F16.gguf`` into the local models dir
got BOTH staged: the projector has no standalone language head, so llama.cpp cannot serve
it and preset admission wrote a nonsense section for it (upstream #133037). One shared
predicate — ``gguf.is_companion_gguf`` — now guards every consumer: staging
(``bootstrap.staged_in``, which ``staged_models``/``staged_model_ids`` and preset
generation all flow through) and the HF repo picker (``hf_browse.repo_files``), so the
families can never drift apart again.
"""

from hermes_cli.local_runtime import bootstrap, gguf, hf_browse, presets
from hermes_cli.local_runtime.estimator import HardwareBudget

# Every companion family seen in the wild: vision projectors (prefix or mid-name),
# speculative draft/MTP heads, dSpark partners. None is a servable base model.
COMPANIONS = [
    "mmproj-model-F16.gguf",
    "model-mmproj-Q8_0.gguf",       # mid-name projector
    "projector-model-F16.gguf",
    "model-draft-vocab.gguf",
    "model-mtp-q4_k_m.gguf",
    "dspark-model-F16.gguf",
]


def test_predicate_recognizes_every_companion_family():
    for name in COMPANIONS:
        assert gguf.is_companion_gguf(name), name
    for name in ("model-Q4_K_M.gguf", "Qwen3-30B-A3B-Instruct-Q8_0.gguf",
                 "mistral-small-24b-2501.gguf"):
        assert not gguf.is_companion_gguf(name), name
    # Case-blind, and full paths (callers pass Path objects from directory walks).
    assert gguf.is_companion_gguf("Model-MMPROJ-F16.gguf")
    assert gguf.is_companion_gguf("/cache/models/mmproj-7b-F16.gguf")


def test_staged_in_serves_only_base_models(tmp_path):
    mdir = tmp_path / "models"
    mdir.mkdir()
    (mdir / "model-Q4_K_M.gguf").touch()
    for name in COMPANIONS:
        (mdir / name).touch()

    staged = {p.name for p in bootstrap.staged_in(mdir)}
    assert staged == {"model-Q4_K_M.gguf"}


def test_generate_presets_never_decides_a_projector(tmp_path, monkeypatch):
    mdir = tmp_path / "models"
    mdir.mkdir()
    (mdir / "model-Q4_K_M.gguf").touch()
    (mdir / "mmproj-model-F16.gguf").touch()

    seen = []

    def _fake_decision(gguf, _budget, _mtp_capable, **_kw):
        seen.append(gguf.name)
        return presets.PresetEntry(model_id=gguf.stem, window=4096, spilled=False,
                                   keys={"model": str(gguf)})

    monkeypatch.setattr(presets, "preset_for_model", _fake_decision)

    ini = tmp_path / "presets.ini"
    entries = presets.generate_presets(
        mdir, HardwareBudget(8 << 30, 8 << 30, 8 << 30), ini)

    # The projector never reaches a launch decision at all, let alone the INI.
    assert seen == ["model-Q4_K_M.gguf"]
    assert "mmproj" not in ini.read_text()
    assert [e.model_id for e in entries] == ["model-Q4_K_M"]


def test_repo_files_drops_every_companion_family(monkeypatch):
    payload = [{"path": p, "size": 1 << 30} for p in (
        "model-Q4_K_M.gguf", "mmproj-model-F16.gguf", "model-mtp-q4.gguf",
        "model-draft-vocab.gguf", "dspark-model-F16.gguf", "notes.txt")]
    monkeypatch.setattr(hf_browse, "_get_json", lambda _url: payload)

    groups = hf_browse.repo_files("some/model")
    assert [g.paths for g in groups] == [("model-Q4_K_M.gguf",)]
