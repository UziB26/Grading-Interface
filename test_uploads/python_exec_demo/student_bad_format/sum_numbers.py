import sys


def main() -> None:
    values = [int(line.strip()) for line in sys.stdin.read().splitlines() if line.strip()]
    # Logic is correct but output format is intentionally different.
    print(f"TOTAL={sum(values)}")


if __name__ == "__main__":
    main()
