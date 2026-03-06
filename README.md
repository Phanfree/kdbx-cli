# kdbx-cli — KeePass CLI Wrapper

Python3 wrapper around **kpcli** for automated KeePass KDBX v2.x database management.

## Features

- ✅ **add** — Create entries with auto-mkdir for nested groups
- ✅ **get** — Retrieve entry password/metadata
- ✅ **get --decrypt-to-env** — Export password as shell variable (`export VAR=value`)
- ✅ **list** — Show groups and entries (with `--verbose` for recursive details)
- ✅ **delete** — Remove entries
- ✅ **login / logout** — Cache master password for 2.5 hours (avoids repeated prompts)
- ✅ **No external dependencies** — Uses stdlib only + kpcli (system tool)

## Requirements

- Python 3.7+
- `kpcli` (KeePass CLI tool) installed
- KDBX v2.x database file

## Installation

```bash
# Install kpcli
sudo apt install kpcli

# Copy kdbx-cli.py to your system
cp kdbx-cli.py /usr/local/bin/
chmod +x /usr/local/bin/kdbx-cli.py
```

## Usage

```bash
# Cache password (valid for 2.5 hours)
python3 kdbx-cli.py login --db mydb.kdbx --password "mypassword"

# List all groups and entries
python3 kdbx-cli.py list --db mydb.kdbx

# List with recursive entry details
python3 kdbx-cli.py list --verbose --db mydb.kdbx

# Get entry password (JSON output)
python3 kdbx-cli.py get "services/github/token" --db mydb.kdbx

# Get password as shell export (for eval)
eval $(python3 kdbx-cli.py get "services/github/token" --decrypt-to-env GITHUB_TOKEN --db mydb.kdbx)

# Add new entry (creates groups if needed)
python3 kdbx-cli.py add "services/github/token" "ghp_xxx" \
  --username "myusername" \
  --db mydb.kdbx

# Delete entry
python3 kdbx-cli.py delete "services/github/token" --db mydb.kdbx

# Clear cached password
python3 kdbx-cli.py logout --db mydb.kdbx
```

> **Note:** `--password` can be omitted if you used `login` or set the `KDBX_PASSWORD` env var.

## Output Format

All commands return JSON:

```bash
# list
{
  "groups": ["General", "services"],
  "entries": []
}

# get
{
  "title": "token",
  "username": "myusername",
  "password": "ghp_xxx",
  "url": "",
  "notes": ""
}

# get --decrypt-to-env GITHUB_TOKEN
export GITHUB_TOKEN='ghp_xxx'

# add/delete
{
  "status": "ok",
  "path": "/services/github/token"
}
```

## Technical Details

**PTY Handling:** The wrapper uses two separate PTY sessions for add operations to avoid terminal state corruption:
1. Session 1: Create missing groups via `mkdir`
2. Session 2: Create entry in clean PTY environment

This ensures proper handling of interactive prompts without phantom input interference.

## License

MIT
