"""
CLI helper to register a local git repository with the CodeKG watcher.

Usage:
  python scripts/register_repo.py --path /path/to/repo --id org/my-service

This updates repos/repos.json which the watcher reads to discover repositories.
"""
import argparse
import json
from pathlib import Path

REPOS_JSON = Path(__file__).parent.parent / "repos" / "repos.json"


def main():
    parser = argparse.ArgumentParser(description="Register a repo with CodeKG")
    parser.add_argument("--path", required=True, help="Absolute path to the git repo")
    parser.add_argument("--id", required=True, dest="repo_id", help="Repo ID slug, e.g. org/my-service")
    parser.add_argument("--remove", action="store_true", help="Remove this repo from the registry")
    args = parser.parse_args()

    REPOS_JSON.parent.mkdir(exist_ok=True)
    registry = json.loads(REPOS_JSON.read_text()) if REPOS_JSON.exists() else {}

    if args.remove:
        registry.pop(args.repo_id, None)
        print(f"Removed {args.repo_id}")
    else:
        registry[args.repo_id] = args.path
        print(f"Registered {args.repo_id} → {args.path}")

    REPOS_JSON.write_text(json.dumps(registry, indent=2))
    print(f"Registry saved to {REPOS_JSON}")


if __name__ == "__main__":
    main()
