import ast
from pathlib import Path

import pytest

from MCP_Server.server import AbletonConnection, MAX_RESPONSE_BYTES


ROOT = Path(__file__).resolve().parents[1]


class FakeSocket:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.sent = []
        self.timeouts = []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, _buffer_size):
        return self.chunks.pop(0) if self.chunks else b""

    def settimeout(self, value):
        self.timeouts.append(value)


def test_long_running_timeout_reaches_response_reader():
    sock = FakeSocket([b'{"status":"success","result":{"ok":true}}'])
    connection = AbletonConnection("127.0.0.1", 9877, sock=sock)

    assert connection.send_command("create_audio_clip", {"path": "example.wav"}) == {
        "ok": True
    }
    assert sock.timeouts[-1] == 65.0


def test_response_size_is_bounded():
    sock = FakeSocket([b"x" * (MAX_RESPONSE_BYTES + 1)])
    connection = AbletonConnection("127.0.0.1", 9877, sock=sock)

    with pytest.raises(ValueError, match="exceeded"):
        connection.receive_full_response(sock)


def test_extended_tool_contract_is_present():
    tree = ast.parse((ROOT / "MCP_Server" / "server.py").read_text())
    functions = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    expected = {
        "bounce_midi_clip_to_audio",
        "clear_clip_notes",
        "create_audio_track",
        "create_return_track",
        "create_scene",
        "delete_clip",
        "delete_track",
        "duplicate_clip_to_scene",
        "get_clip_notes",
        "get_device_parameters",
        "get_drum_pad_names",
        "get_meters",
        "get_return_tracks",
        "get_scene_names",
        "load_sample_to_drum_pad",
        "quantize_clip",
        "redo",
        "remove_notes_in_range",
        "set_clip_loop",
        "set_device_parameter",
        "set_scene_name",
        "set_send_level",
        "set_track_arm",
        "set_track_color",
        "set_track_monitor",
        "set_track_mute",
        "set_track_pan",
        "set_track_solo",
        "set_track_volume",
        "undo",
        "update_notes",
    }
    assert expected <= functions
