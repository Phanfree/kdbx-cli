#!/usr/bin/env python3
"""Python3 wrapper around kpcli for KeePass KDBX v2.x databases."""

import argparse
import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time

TIMEOUT = 15


def strip_ansi(text):
    return re.sub(r'\x1b\[[\x20-\x3f]*[\x40-\x7e]', '', text)


def output_json(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0)


def error(msg):
    print(json.dumps({"error": msg}, ensure_ascii=False))
    sys.exit(1)


def find_kpcli():
    path = shutil.which("kpcli")
    if not path:
        error("kpcli not found in PATH")
    return path


def check_db(db_path):
    if not os.path.exists(db_path):
        error(f"Database file not found: {db_path}")
    lock = db_path + ".lock"
    if os.path.exists(lock):
        try:
            os.remove(lock)
        except OSError:
            pass


def check_output_for_errors(text):
    low = text.lower()
    if "couldn't load the file" in low:
        error("Failed to open database (wrong password or corrupted file)")
    if "file does not exist" in low:
        error("Database file not found")


# ── Command mode (read-only operations) ──────────────────────────────


def run_kpcli_command(db_path, password, commands):
    kpcli = find_kpcli()
    cmd = [kpcli, f"--kdb={db_path}"]
    for c in commands:
        cmd.append(f"--command={c}")

    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout_b, stderr_b = proc.communicate(
            input=(password + "\n").encode(), timeout=TIMEOUT
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        error("kpcli timed out")

    stdout = strip_ansi(stdout_b.decode("utf-8", errors="replace"))
    stderr = strip_ansi(stderr_b.decode("utf-8", errors="replace"))
    check_output_for_errors(stdout + "\n" + stderr)
    return stdout


# ── PTY session for write operations ─────────────────────────────────


class KpcliPTY:
    """Simple PTY session: send lines, read output, match prompts."""

    def __init__(self, db_path):
        self.kpcli = find_kpcli()
        self.db_path = db_path
        self.master_fd = None
        self.proc = None
        self.all_output = ""

    def open(self, password):
        master_fd, slave_fd = pty.openpty()
        self.proc = subprocess.Popen(
            [self.kpcli, f"--kdb={self.db_path}"],
            stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        self.master_fd = master_fd

        self._read(3)  # wait for password prompt
        self._send(password)
        out = self._read(3)
        if "couldn't load" in out.lower():
            self.close()
            error("Failed to open database (wrong password or corrupted file)")
        return self

    def _read(self, initial_timeout=2):
        """Read available output from PTY."""
        buf = b''
        t = initial_timeout
        while True:
            r, _, _ = select.select([self.master_fd], [], [], t)
            if not r:
                break
            try:
                chunk = os.read(self.master_fd, 4096)
                if not chunk:
                    break
                buf += chunk
                t = 0.5  # shorter timeout for subsequent reads
            except OSError:
                break
        text = strip_ansi(buf.decode("utf-8", errors="replace"))
        self.all_output += text
        return text

    def _send(self, text):
        """Send a line to kpcli."""
        os.write(self.master_fd, (text + "\n").encode())
        time.sleep(0.5)

    def send_and_read(self, text, read_timeout=2):
        """Send a line and read the response."""
        self._send(text)
        return self._read(read_timeout)

    def close(self):
        if self.master_fd is not None:
            try:
                self._send("quit")
                time.sleep(0.3)
            except OSError:
                pass
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None
        if self.proc:
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        # Clean up lock file
        lock = self.db_path + ".lock"
        if os.path.exists(lock):
            try:
                os.remove(lock)
            except OSError:
                pass


# ── Parsers ──────────────────────────────────────────────────────────


def parse_ls(raw):
    groups = []
    entries = []
    section = None

    for line in raw.splitlines():
        line = line.strip()
        if line == "=== Groups ===":
            section = "groups"
            continue
        elif line == "=== Entries ===":
            section = "entries"
            continue
        elif line.startswith("==="):
            section = None
            continue

        if not line:
            continue

        if section == "groups" and line.endswith("/"):
            groups.append(line.rstrip("/"))
        elif section == "entries":
            m = re.match(r"^(\d+)\.\s+(.+?)(?:\s{2,}(\S.*))?\s*$", line)
            if m:
                entries.append({
                    "index": int(m.group(1)),
                    "title": m.group(2).strip(),
                    "url": (m.group(3) or "").strip(),
                })

    return {"groups": groups, "entries": entries}


def parse_show(raw):
    field_map = {
        "Title": "title", "Uname": "username", "Pass": "password",
        "URL": "url", "Notes": "notes", "Tags": "tags",
    }
    noise = {"please consider supporting", "github.com/sponsors", "kpcli:/>"}

    result = {}
    current_key = None
    multiline_buf = []

    for line in raw.splitlines():
        low = line.strip().lower()
        if any(n in low for n in noise):
            continue

        m = re.match(r"^\s*([\w#]+):\s?(.*)", line)
        if m and m.group(1) in field_map:
            if current_key == "notes" and multiline_buf:
                existing = result.get("notes", "")
                extra = "\n".join(multiline_buf)
                result["notes"] = (existing + "\n" + extra).strip()
                multiline_buf = []

            key = field_map[m.group(1)]
            result[key] = m.group(2).strip()
            current_key = key
        elif current_key == "notes" and line.strip():
            multiline_buf.append(line.strip())

    if current_key == "notes" and multiline_buf:
        existing = result.get("notes", "")
        extra = "\n".join(multiline_buf)
        result["notes"] = (existing + "\n" + extra).strip()

    return result if result else None


# ── Commands ─────────────────────────────────────────────────────────


def cmd_list(args):
    check_db(args.db)
    commands = []
    if args.path:
        commands.append(f"cd /{args.path}")
    commands.append("ls")
    raw = run_kpcli_command(args.db, args.password, commands)
    output_json(parse_ls(raw))


def cmd_get(args):
    check_db(args.db)
    path = args.path if args.path.startswith("/") else "/" + args.path
    raw = run_kpcli_command(args.db, args.password, [f"show -f {path}"])
    entry = parse_show(raw)
    if not entry:
        error(f"Entry not found: {args.path}")
    output_json(entry)


def _ensure_groups(db_path, password, group_path):
    """Create parent groups if they don't exist (separate PTY session)."""
    parts = group_path.split("/")
    sess = KpcliPTY(db_path)
    try:
        sess.open(password)
        for i in range(len(parts)):
            grp = "/" + "/".join(parts[: i + 1])
            out = sess.send_and_read(f"mkdir {grp}")
            if "[y/N]" in out:
                sess.send_and_read("y", read_timeout=3)  # save immediately
        sess.close()
    except Exception:
        sess.close()


def cmd_add(args):
    check_db(args.db)

    path = args.path
    if "/" in path:
        group, title = path.rsplit("/", 1)
    else:
        group, title = "", path

    new_path = f"/{group}/{title}" if group else f"/{title}"
    username = args.username or ""
    url = args.url or ""
    notes = args.notes or ""
    pw = args.value

    # Step 1: Create parent groups in a separate session
    if group:
        _ensure_groups(args.db, args.password, group)

    # Step 2: Create entry in a clean PTY session
    sess = KpcliPTY(args.db)
    try:
        sess.open(args.password)

        # new command (title auto-filled from path → first prompt is Username)
        sess.send_and_read(f"new {new_path}")

        # Prompts: Username → Password → Retype → URL → Tags → Strings(F) → Notes(.)
        sess.send_and_read(username)     # Username
        sess.send_and_read(pw)           # Password
        sess.send_and_read(pw)           # Retype to verify
        sess.send_and_read(url)          # URL
        sess.send_and_read("")           # Tags (empty)
        sess.send_and_read("F")          # Strings: (F)inish
        if notes:
            sess.send_and_read(notes)    # Notes content
        out = sess.send_and_read(".")    # Notes: end multi-line

        # Save prompt: "Do you want to save it now? [y/N]:"
        if "[y/N]" in out:
            sess.send_and_read("y", read_timeout=3)

        sess.close()

        clean = sess.all_output.lower()
        if "saved to" in clean:
            output_json({"status": "ok", "path": new_path})
        elif "mismatched" in clean:
            error("Password verification failed")
        elif "bad path" in clean:
            error(f"Bad path: {new_path}")
        else:
            # Check if notes prompt triggered save on session close
            output_json({"status": "ok", "path": new_path})

    except Exception as e:
        sess.close()
        error(f"Failed to add entry: {e}")


def cmd_delete(args):
    check_db(args.db)
    path = args.path if args.path.startswith("/") else "/" + args.path

    sess = KpcliPTY(args.db)
    try:
        sess.open(args.password)

        out = sess.send_and_read(f"rm {path}")

        if "[y/N]" in out:
            sess.send_and_read("y", read_timeout=3)
            sess.close()
            output_json({"status": "ok", "deleted": args.path})
        else:
            sess.close()
            if "see no entry" in out.lower() or "no such" in out.lower():
                error(f"Entry not found: {args.path}")
            error(f"Entry not found: {args.path}")

    except Exception as e:
        sess.close()
        error(f"Failed to delete entry: {e}")


# ── Main ─────────────────────────────────────────────────────────────


def add_common_args(p):
    p.add_argument("--db", required=True, help="Path to .kdbx database file")
    p.add_argument("--password", required=True, help="Master password")


def main():
    parser = argparse.ArgumentParser(
        description="Python3 wrapper around kpcli for KeePass KDBX v2.x"
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    p_list = sub.add_parser("list", help="List groups and entries")
    p_list.add_argument("path", nargs="?", default="", help="Group path")
    add_common_args(p_list)

    p_get = sub.add_parser("get", help="Get entry details")
    p_get.add_argument("path", help="Path to entry")
    add_common_args(p_get)

    p_add = sub.add_parser("add", help="Add a new entry")
    p_add.add_argument("path", help="Path (e.g. General/myentry)")
    p_add.add_argument("value", help="Password value")
    p_add.add_argument("--username", default="", help="Username")
    p_add.add_argument("--url", default="", help="URL")
    p_add.add_argument("--notes", default="", help="Notes")
    add_common_args(p_add)

    p_del = sub.add_parser("delete", help="Delete an entry")
    p_del.add_argument("path", help="Path to entry")
    add_common_args(p_del)

    args = parser.parse_args()
    {"list": cmd_list, "get": cmd_get, "add": cmd_add, "delete": cmd_delete}[args.command](args)


if __name__ == "__main__":
    main()
