# kdbx-cli — KeePass CLI Wrapper

Python3 wrapper around **kpcli** for automated KeePass KDBX v2.x database management.

## Features

- ✅ **add** — Create entries with auto-mkdir for nested groups
- ✅ **get** — Retrieve entry password/metadata
- ✅ **list** — Show groups and entries
- ✅ **delete** — Remove entries
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
# List all groups and entries
python3 kdbx-cli.py list --db mydb.kdbx --password "mypassword"

# Get entry password
python3 kdbx-cli.py get "services/github/token" --db mydb.kdbx --password "mypassword"

# Add new entry (creates groups if needed)
python3 kdbx-cli.py add "services/github/token" "ghp_xxx" \
  --username "myusername" \
  --db mydb.kdbx \
  --password "mypassword"

# Delete entry
python3 kdbx-cli.py delete "services/github/token" --db mydb.kdbx --password "mypassword"
```

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
