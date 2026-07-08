import sys


def main() -> None:
    total = 0
    for raw in sys.stdin.read().splitlines():
        raw = raw.strip()
        if raw:
            total += int(raw)
    print(total)


if __name__ == "__main__":
    main()
