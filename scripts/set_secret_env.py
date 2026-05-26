import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/set_secret_env.py ENV_NAME")
        return 2

    name = sys.argv[1]
    value = os.environ.get("SECRET_VALUE", "").strip()
    if not value:
        print("No secret value provided.")
        return 1

    path = Path(".env.local")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    updated = False

    for line in lines:
        if line.startswith(f"{name}="):
            out.append(f"{name}={value}")
            updated = True
        else:
            out.append(line)

    if not updated:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{name}={value}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{name} saved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
