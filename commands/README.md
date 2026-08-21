# Commands (commands/)

Each file is a command. Two formats are supported:

## TOML (simple shell commands)

```toml
[command]
name        = "restart_cash"
description = "Restart SetRetail"
category    = "user"
cash_types  = ["pos", "touch"]
timeout     = 30
show_output = true

[[steps]]
label   = "Restart service"
command = "sudo systemctl restart sr10"
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | Unique command name |
| `description` | no | Displayed in menu |
| `category` | no | `user`, `builtin`, `info`, `other` |
| `cash_types` | no | Filter by terminal type |
| `timeout` | no (default: 30) | Per-step timeout in seconds |
| `show_output` | no (default: true) | Show result dialog |
| `requires_confirmation` | no (default: false) | Ask before execution |

## Python (commands with logic)

```python
# [command]
# name        = find_cashier
# description = Search cashier in config
# category    = info
# cash_types  = pos, touch
# timeout     = 15

async def execute(session, **kwargs) -> str:
    result = await session.ssh.execute("grep cashier /etc/config.ini")
    return result.stdout
```

Metadata in `# [command]` block parsed as TOML (same fields as above).
File must contain `async def execute(session, **kwargs)`.

Supported variables: `INPUT_PROMPT` at module level to show an input dialog.