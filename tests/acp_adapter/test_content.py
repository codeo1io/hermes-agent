"""Behavior contracts for acp_adapter.content (ACP prompt blocks -> OpenAI content payloads).

Covers the pure conversion helpers and the resource-link/embedded-resource paths that turn
client attachments into vision-model parts, plus the ``python -m acp_adapter`` entry smoke.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

from acp.schema import (
    BlobResourceContents,
    EmbeddedResourceContentBlock,
    ImageContentBlock,
    ResourceContentBlock,
    TextContentBlock,
    TextResourceContents,
)

from acp_adapter.content import (
    _content_blocks_to_openai_user_content,
    _decode_text_bytes,
    _is_image_resource,
    _is_text_resource,
    _mime_main,
    _path_from_file_uri,
    _resource_display_name,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestResourceDisplayName:
    def test_title_and_name_combine(self):
        assert _resource_display_name("file:///tmp/x.py", name="x.py", title="My patch") == "My patch (x.py)"

    def test_either_alone_wins_over_uri(self):
        assert _resource_display_name("file:///tmp/x.py", name="x.py") == "x.py"
        assert _resource_display_name("file:///tmp/x.py", title="Notes") == "Notes"

    def test_falls_back_to_percent_decoded_path_basename(self):
        assert _resource_display_name("file:///tmp/my%20file.txt") == "my file.txt"

    def test_non_file_uri_without_name_returns_itself(self):
        assert _resource_display_name("acp://resource") == "acp://resource"
        assert _resource_display_name("") == "resource"


class TestMimeClassification:
    def test_charset_parameters_are_stripped_and_case_folded(self):
        assert _mime_main("text/plain; charset=utf-8") == "text/plain"
        assert _mime_main("  IMAGE/PNG ") == "image/png"

    def test_text_and_image_prefixes_drive_classification(self):
        assert _is_text_resource("application/json")
        assert _is_text_resource("text/csv; charset=latin-1")
        assert not _is_text_resource("image/png")
        assert _is_image_resource("image/svg+xml")
        assert not _is_image_resource(None)


class TestPathFromFileUri:
    def test_plain_paths_and_file_uris(self):
        assert _path_from_file_uri("/tmp/notes.txt") == Path("/tmp/notes.txt")
        assert _path_from_file_uri("file:///tmp/notes.txt") == Path("/tmp/notes.txt")
        assert _path_from_file_uri("file://localhost/tmp/x") == Path("/tmp/x")

    def test_non_file_schemes_and_remote_hosts_are_rejected(self):
        assert _path_from_file_uri("https://example.com/x") is None
        assert _path_from_file_uri("file://nas/tmp/x") is None
        assert _path_from_file_uri("") is None

    def test_windows_drive_forms_map_to_wsl_mounts(self):
        assert _path_from_file_uri("file:///C:/Users/me/x.txt") == Path("/mnt/c/Users/me/x.txt")
        assert _path_from_file_uri("file://localhost/E:/data/x.yaml") == Path("/mnt/e/data/x.yaml")


class TestDecodeTextBytes:
    def test_bom_and_latin1_fallback(self):
        assert _decode_text_bytes("héllo".encode("utf-8"), "text/plain") == "héllo"
        assert _decode_text_bytes("héllo".encode("utf-8-sig"), "text/plain") == "héllo"
        assert _decode_text_bytes("héllo".encode("latin-1"), "text/plain") == "héllo"

    def test_nul_bytes_are_binary_unless_mime_says_text(self):
        assert _decode_text_bytes(b"ab\x00cd", "application/octet-stream") is None
        assert _decode_text_bytes(b"ab\x00cd", "text/plain") == "ab\x00cd"


class TestContentBlocksToUserContent:
    def test_text_only_prompts_stay_a_plain_string(self):
        result = _content_blocks_to_openai_user_content(
            [TextContentBlock(type="text", text="hello "), TextContentBlock(type="text", text="world")]
        )
        assert result == "hello \nworld"

    def test_empty_prompt_falls_back_to_extracted_text(self):
        assert _content_blocks_to_openai_user_content([]) == ""

    def test_image_block_becomes_data_url_part(self):
        result = _content_blocks_to_openai_user_content(
            [
                TextContentBlock(type="text", text="look"),
                ImageContentBlock(type="image", data="aGk=", mime_type="image/png"),
            ]
        )
        assert isinstance(result, list)
        assert result[0] == {"type": "text", "text": "look"}
        assert result[1]["image_url"]["url"] == "data:image/png;base64,aGk="

    def test_image_block_without_data_or_uri_is_dropped(self):
        # Empty data and no URI: schema-valid but nothing to render — the converter must not emit a part.
        assert _content_blocks_to_openai_user_content([ImageContentBlock(type="image", data="", mime_type="image/png")]) == ""

    def test_resource_link_reads_local_text_file(self, tmp_path):
        target = tmp_path / "notes.md"
        target.write_text("# notes", encoding="utf-8")
        block = ResourceContentBlock(
            type="resource_link", uri=target.as_uri(), name="notes.md", mime_type="text/markdown"
        )
        result = _content_blocks_to_openai_user_content([block])
        assert isinstance(result, str)
        assert "[Attached file: notes.md]" in result
        assert f"URI: {target.as_uri()}" in result
        assert "# notes" in result

    def test_resource_link_binary_file_is_omitted_with_a_note(self, tmp_path):
        target = tmp_path / "blob.bin"
        target.write_bytes(b"\x7fELF\x02\x01\x01\x00" + bytes(range(256)))
        block = ResourceContentBlock(
            type="resource_link", uri=target.as_uri(), name="blob.bin", mime_type="application/octet-stream"
        )
        result = _content_blocks_to_openai_user_content([block])
        assert "[Binary file omitted:" in result
        assert "mime=application/octet-stream" in result

    def test_resource_link_non_file_uri_explains_it_cannot_inline(self):
        block = ResourceContentBlock(type="resource_link", uri="acp://remote", name="remote")
        result = _content_blocks_to_openai_user_content([block])
        assert "[Resource link only;" in result

    def test_embedded_text_resource_is_inlined(self):
        block = EmbeddedResourceContentBlock(
            type="resource",
            resource=TextResourceContents(uri="file:///tmp/x.txt", text="body text"),
        )
        assert "body text" in _content_blocks_to_openai_user_content([block])

    def test_embedded_image_blob_becomes_data_url_part(self):
        block = EmbeddedResourceContentBlock(
            type="resource",
            resource=BlobResourceContents(
                uri="file:///tmp/pic.png",
                mime_type="image/png",
                blob=base64.b64encode(b"pngbytes").decode("ascii"),
            ),
        )
        result = _content_blocks_to_openai_user_content([block])
        assert isinstance(result, list)
        assert result[-1]["image_url"]["url"].endswith(base64.b64encode(b"pngbytes").decode("ascii"))

    def test_embedded_binary_blob_is_omitted_with_a_note(self):
        block = EmbeddedResourceContentBlock(
            type="resource",
            resource=BlobResourceContents(
                uri="file:///tmp/x.bin",
                mime_type="application/octet-stream",
                blob=base64.b64encode(b"\x00\x01\x02binary").decode("ascii"),
            ),
        )
        result = _content_blocks_to_openai_user_content([block])
        assert "[Binary embedded file omitted:" in result


class TestModuleEntry:
    def test_python_dash_m_acp_adapter_version_exits_zero(self):
        """``python -m acp_adapter`` (the __main__ wrapper) must stay runnable end to end —
        ``--version`` exercises the real arg parser and early exit without starting a server."""
        proc = subprocess.run(
            [sys.executable, "-m", "acp_adapter", "--version"],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip()
