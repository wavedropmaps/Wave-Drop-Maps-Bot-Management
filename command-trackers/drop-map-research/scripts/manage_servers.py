"""
CLI for managing the tracked server list.
Usage:
  python manage_servers.py add "Server Name" ["search query"]
  python manage_servers.py remove "Server Name"
  python manage_servers.py list
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from db import init_db, add_server, remove_server, list_servers, set_invite_code, set_guild_id

def main():
    init_db()
    if len(sys.argv) < 2:
        print("Usage: manage_servers.py [add|remove|list|set-invite] ...")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "add":
        if len(sys.argv) < 3:
            print("Usage: manage_servers.py add \"Server Name\" [\"search query\"]")
            sys.exit(1)
        name = sys.argv[2]
        query = sys.argv[3] if len(sys.argv) > 3 else name
        add_server(name, query)

    elif cmd == "remove":
        if len(sys.argv) < 3:
            print("Usage: manage_servers.py remove \"Server Name\"")
            sys.exit(1)
        remove_server(sys.argv[2])

    elif cmd == "set-guild-id":
        if len(sys.argv) < 4:
            print("Usage: manage_servers.py set-guild-id \"Server Name\" GUILD_ID")
            sys.exit(1)
        set_guild_id(sys.argv[2], sys.argv[3])

    elif cmd == "set-invite":
        if len(sys.argv) < 4:
            print("Usage: manage_servers.py set-invite \"Server Name\" INVITE_CODE_OR_URL")
            print("  e.g. manage_servers.py set-invite \"Free Dropmaps\" abc1234")
            print("  e.g. manage_servers.py set-invite \"Free Dropmaps\" https://discord.gg/abc1234")
            sys.exit(1)
        name = sys.argv[2]
        raw  = sys.argv[3]
        # accept full URL or bare code
        code = raw.rstrip("/").split("/")[-1]
        set_invite_code(name, code)

    elif cmd == "list":
        servers = list_servers()
        print(f"\n{'NAME':<35} {'INVITE':<16} {'SEARCH QUERY':<26} STATUS")
        print("-" * 90)
        for s in servers:
            status = "active" if s["active"] else "inactive"
            invite = s["invite_code"] or "—"
            print(f"{s['name']:<35} {invite:<16} {s['search_query']:<26} {status}")

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

if __name__ == "__main__":
    main()
