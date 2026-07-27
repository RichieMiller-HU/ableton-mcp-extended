# Ableton MCP Extended

An independently maintained, privacy-focused derivative of
[ahujasid/ableton-mcp](https://github.com/ahujasid/ableton-mcp) that adds
deeper session editing, feedback, mixing, MIDI surgery, and bounce workflows
for Ableton Live.

This project is not affiliated with or endorsed by Ableton. It remains in
private staging while the extended commands are tested against real Live sets.

## Why this derivative exists

The upstream project provides the MCP-to-Ableton bridge. This derivative keeps
that architecture and adds 31 MCP tools:

- Session structure: create audio and return tracks, delete tracks, create and
  name scenes, duplicate clips between scenes, and inspect scene names.
- Clip editing: delete clips, clear notes, read notes, update individual notes,
  remove notes by pitch/time range, set loop markers, and quantize clips.
- Instruments and devices: load samples onto Drum Rack pads, inspect pad names,
  inspect device parameters, and set device parameters.
- Mixing and feedback: set volume, pan, mute, solo, arm, monitoring, color, and
  send levels; inspect return tracks and output meters; undo and redo.
- Rendering: bounce a Session View MIDI clip to audio in real time.

It also changes the privacy posture:

- No telemetry code or Supabase dependency.
- The Ableton Remote Script listens on `127.0.0.1` by default, not every
  network interface.
- MCP request and response sizes are bounded.
- Command parameters, prompts, paths, and raw responses are not written to
  normal MCP logs.

See [UPSTREAM.md](UPSTREAM.md) for provenance and [CHANGELOG.md](CHANGELOG.md)
for the maintained change summary.

## Requirements

- Ableton Live 11 or newer; Live 12 is recommended.
- Python 3.10 or newer for the MCP server.
- [uv](https://docs.astral.sh/uv/).

Some note-editing and clip-duplication operations depend on APIs introduced in
newer Live versions. Save a copy of important sets before testing destructive
commands.

## Install for development

```bash
git clone https://github.com/RichieMiller-HU/ableton-mcp-extended.git
cd ableton-mcp-extended
uv sync --extra dev
```

Copy `AbletonMCP_Remote_Script` into Ableton's User Remote Scripts directory,
restart Live, and select `AbletonMCP` as a Control Surface.

During private staging, configure an MCP client to run the local checkout:

```json
{
  "mcpServers": {
    "AbletonMCP-Extended": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/ableton-mcp-extended",
        "run",
        "ableton-mcp-extended"
      ]
    }
  }
}
```

The path above is an example. Never commit a personal absolute path or MCP
client configuration containing credentials.

Only run one Ableton MCP server at a time.

## Security model

The Remote Script has no authentication. Loopback binding prevents direct
connections from other computers, but any process running as a local user may
attempt to connect to port `9877` and issue Ableton commands. Do not change the
bind address to `0.0.0.0` or expose the port through forwarding or tunneling.

See [SECURITY.md](SECURITY.md) for reporting and deployment guidance.

## Development checks

```bash
uv run --extra dev pytest
uv run --extra dev detect-secrets scan --all-files --exclude-files '^\.git/'
uv build
```

Live API behavior still requires an integration pass inside Ableton; the unit
suite covers the Python bridge and publication/privacy invariants.

## License and attribution

MIT licensed. The original copyright and permission notice are preserved in
[LICENSE](LICENSE). Modifications are documented rather than presented as
original upstream work.
