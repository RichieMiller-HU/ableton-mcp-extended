# Security

## Supported versions

This project is pre-release. Security fixes are applied only to the latest
private-staging branch until the first public release.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository when it is
enabled. Do not publish credentials, private Ableton project information,
personal file paths, or exploit details in a public issue.

## Deployment guidance

- Keep the Remote Script bound to `127.0.0.1`.
- Do not expose TCP port `9877` through a firewall rule, tunnel, container
  port mapping, or router.
- Run only one MCP server instance.
- Treat MCP clients and prompts as trusted inputs: commands can modify the
  active Ableton Live set.
- Save or duplicate important Live sets before destructive or experimental
  operations.
- Never place API keys or MCP client configuration files in this repository.

The local socket protocol does not authenticate clients. Loopback binding
reduces exposure but does not protect against untrusted processes already
running on the same computer.
