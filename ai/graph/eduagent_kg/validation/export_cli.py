import argparse
import json
from pathlib import Path

from eduagent_kg.schemas.enums import ReviewStatus
from eduagent_kg.schemas.review import ReviewQueue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export pending review items as JSON.")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    queue = ReviewQueue.model_validate_json(args.queue.read_text(encoding="utf-8"))
    pending = [
        item.model_dump(mode="json") for item in queue.items
        if item.status == ReviewStatus.CANDIDATE
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(pending, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pending_items": len(pending), "output": str(args.output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
