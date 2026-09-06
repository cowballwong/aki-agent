import sys
from pathlib import Path
out = Path("out"); out.mkdir(exist_ok=True)
(out / "hello.txt").write_text("ran with: " + " ".join(sys.argv[1:]), encoding="utf-8")
print("wrote", (out / "hello.txt").resolve())
