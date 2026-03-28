# REPL Guide

The `argus` CLI includes an interactive REPL (Read-Eval-Print Loop) powered by
[prompt-toolkit](https://python-prompt-toolkit.readthedocs.io/). When invoked
without a subcommand, `argus` drops into the REPL session.

## Starting the REPL

```bash
# Default — connects to http://127.0.0.1:9000
argus

# Connect to a specific server
argus --server http://192.168.1.100:9000

# With authentication
argus --server http://192.168.1.100:9000 --token my-token

# With a theme
argus --theme dracula
```

On startup the REPL:

1. Connects to the server and checks health
2. Fetches dynamic completions (backend names, tool names, resources, etc.)
3. Displays a banner with connection status, version, and backend summary
4. Enters the prompt loop

## REPL Commands

All `argus` CLI commands work inside the REPL without the `argus` prefix:

```
argus» backends list
argus» tools call my-tool --params '{"key": "value"}'
argus» health status
argus» events list --limit 20
```

### REPL-Specific Commands

These commands are only available inside the REPL session:

| Command | Description |
|---------|-------------|
| `use <backend\|none>` | Scope all commands to a specific backend |
| `alias name=command` | Create a session alias (e.g., `alias bl=backends list`) |
| `unalias <name>` | Remove a session alias |
| `watch [--interval N] <command>` | Auto-refresh a command every N seconds |
| `connect <url>` | Switch to a different server mid-session |
| `set <key> <value>` | Change settings (e.g., `set output json`) |
| `history` | Show command history |
| `clear` | Clear the screen |
| `help` | Show available commands |
| `exit` / `quit` | End the REPL session |

### Backend Scoping

The `use` command scopes subsequent commands to a specific backend:

```
argus» use my-backend
argus[my-backend]» tools list       # only tools from my-backend
argus[my-backend]» health status    # only health for my-backend
argus[my-backend]» use none         # clear scope
argus» tools list                   # all tools again
```

The active scope is shown in the prompt and toolbar.

### Watch Mode

Repeatedly execute a command with auto-refresh:

```
argus» watch backends list               # refresh every 2s (default)
argus» watch --interval 5 health status  # refresh every 5s
```

Press `Ctrl+C` to stop watching.

### Aliases

Create shorthand aliases for frequently used commands:

```
argus» alias bl=backends list
argus» alias hs=health status
argus» bl               # runs: backends list
argus» unalias bl       # remove alias
```

Aliases persist across REPL sessions. They are saved to
`~/.config/argus-mcp/aliases.yaml` and loaded automatically on startup.

### Settings Persistence

Changes made with the `set` command are written to
`~/.config/argus-mcp/config.yaml` so they survive across sessions:

```
argus» set theme dracula        # persisted
argus» set output json          # persisted
argus» set vi-mode true         # persisted (restart for keybindings)
```

## Features

### Tab Completion

The REPL provides context-aware tab completion for:

- Command groups and subcommands
- Backend names (fetched from the server)
- Tool, resource, and prompt names
- Skill and workflow names
- Secret names

Completions are refreshed from the server when the connection changes.

### Command History

History is saved to `~/.config/argus-mcp/history` and persists across REPL
sessions. Use the `history` command to view recent entries, or press
`↑` / `↓` to navigate history.

Auto-suggest from history appears as dimmed text ahead of the cursor.

### Status Toolbar

The bottom toolbar shows:

- Active server URL
- Connection state (connected / disconnected)
- Active backend scope (if set)
- Output format

### Multiline Input

Commands that require JSON or long arguments support multiline input.
The REPL detects incomplete input and prompts for continuation.

## Architecture

```
packages/argus_cli/argus_cli/repl/
├── loop.py          # Main REPL loop — prompt-toolkit session, input dispatch
├── completions.py   # Dynamic tab completion trees from API data
├── dispatch.py      # Route input to REPL handler or Typer command
├── handlers.py      # REPL-only command implementations
├── state.py         # Session state (connection, aliases, completions)
└── toolbar.py       # Prompt formatting and bottom toolbar
```

## Configuration Directory

The REPL stores persistent data in `~/.config/argus-mcp/`:

```
~/.config/argus-mcp/
├── aliases.yaml   # User-defined command aliases
├── config.yaml    # Persisted REPL settings (theme, output format, etc.)
├── history        # prompt-toolkit command history
└── skills.txt     # Cached skill completions
```
