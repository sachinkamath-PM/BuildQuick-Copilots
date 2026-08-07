from __future__ import annotations

import argparse

from app.services.store import store


def main() -> None:
    parser = argparse.ArgumentParser(description="BuildQuick Copilots maintenance")
    parser.add_argument("command", choices=("migrate", "cleanup-guests", "readiness"))
    args = parser.parse_args()
    if args.command == "migrate":
        store.migrate()
        print("Database migrations applied.")
    elif args.command == "cleanup-guests":
        print(f"Deleted {store.delete_expired_guest_workspaces()} expired guest workspace(s).")
    else:
        store.ping()
        print("Database is ready.")


if __name__ == "__main__":
    main()
