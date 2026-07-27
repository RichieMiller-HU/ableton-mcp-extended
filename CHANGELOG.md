# Changelog

## 0.1.0 - Unreleased

### Added

- 31 additional MCP tools covering session organization, clip and note
  editing, device control, mixing feedback, undo/redo, and MIDI-to-audio bounce.
- Audio-track and return-track creation.
- Request and response size limits.
- Publication-safety and bridge unit tests.

### Changed

- Remote Script binding defaults to loopback-only `127.0.0.1`.
- Long-running command timeouts are preserved through response reads.
- Minimum supported Ableton version is documented as Live 11.
- Package and executable names are distinct from upstream.

### Removed

- Telemetry collection, persistent customer identifiers, and the Supabase
  dependency.
- Logging of command parameters, prompts, paths, and raw response bytes.
