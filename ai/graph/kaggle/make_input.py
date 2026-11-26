"""Bundle the graph code and a sections file into one zip to upload as a Kaggle dataset.

    python ai/graph/kaggle/make_input.py data/g3t1/sections_v2.jsonl

Writes data/kaggle/eduagent-kg-input.zip (Kaggle unzips datasets automatically).
"""

import sys
import zipfile
from pathlib import Path

GRAPH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = GRAPH_ROOT.parents[1]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sections = Path(sys.argv[1]).resolve()
    out = REPO_ROOT / "data" / "kaggle" / "eduagent-kg-input.zip"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((GRAPH_ROOT / "eduagent_kg").rglob("*.py")):
            archive.write(path, path.relative_to(GRAPH_ROOT).as_posix())
        archive.write(sections, f"sections/{sections.name}")
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
