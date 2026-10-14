"""Fetch only the pinned public handbook documents referenced by the evaluation set."""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "seed/eval/support/handbook-manifest.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Check the local snapshot without network access")
    parser.add_argument("--destination", type=Path, default=ROOT / ".corpus/handbook")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def fetch(doc):
        relative = PurePosixPath(doc["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe document path")
        target = args.destination / relative
        valid = target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == doc["sha256"]
        if valid:
            return "cached"
        if args.verify_only:
            raise ValueError("Missing or changed source: " + doc["path"])
        expected_prefix = "https://gitlab.com/gitlab-com/content-sites/handbook/-/raw/" + manifest["commit"] + "/content/handbook/"
        if not doc["url"].startswith(expected_prefix):
            raise ValueError("Source URL is outside the pinned official handbook")
        body = subprocess.run(
            ["curl", "--fail", "--silent", "--show-error", "--location", "--proto", "=https", "--proto-redir", "=https", "--max-time", "45", doc["url"]],
            check=True, capture_output=True,
        ).stdout
        if hashlib.sha256(body).hexdigest() != doc["sha256"]:
            raise ValueError("Downloaded source hash mismatch: " + doc["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        return "downloaded"

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(fetch, manifest["documents"]))
    print(json.dumps({"commit": manifest["commit"], "documents": len(results), "downloaded": results.count("downloaded"), "verified": len(results)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
