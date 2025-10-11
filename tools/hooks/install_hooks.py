import subprocess
import sys


def main() -> None:
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "pre-commit"], check=True)
        subprocess.run(["pre-commit", "install"], check=True)
        print("✅ pre-commit установлен и активирован.")
    except Exception as exc:  # pragma: no cover - defensive fallback
        print("⚠️ pre-commit недоступен, используйте fallback Git hooks:", exc)
        # при желании можно записать .git/hooks/pre-commit вручную


if __name__ == "__main__":
    main()
