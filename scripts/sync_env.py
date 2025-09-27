import os
from pathlib import Path

EXAMPLE = Path(".env.example")
ENV = Path(".env")

SAFE_OVERWRITE = {
    "TRIBUTE_LINK_BASIC","TRIBUTE_LINK_PRO",
    "TRIBUTE_WEB_BASIC","TRIBUTE_WEB_PRO",
    "SUB_BASIC_PRICE","SUB_PRO_PRICE",
    "PROMO_CODES","PROMO_PDF_URL",
    "DATABASE_URL","TRIBUTE_WEBHOOK_PATH",
    "WEB_HOST","WEB_PORT"
}

def load_kv(path: Path):
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    return data

def dump_kv(path: Path, data: dict):
    lines = [f"{k}={data[k]}" for k in data]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def main() -> int:
    if not EXAMPLE.exists():
        print("[ERROR] .env.example not found")
        return 1

    ex  = load_kv(EXAMPLE)
    cur = load_kv(ENV)

    merged = dict(cur)

    # 1) заполняем пустые/отсутствующие ключи из example
    for k, v in ex.items():
        if k not in merged or merged[k] == "":
            merged[k] = v

    # 2) безопасные ключи синхронизируем всегда из example (не секреты)
    for k in SAFE_OVERWRITE:
        if k in ex:
            merged[k] = ex[k]

    dump_kv(ENV, merged)
    print("[OK] .env synced with .env.example (safe overwrite keys applied)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
