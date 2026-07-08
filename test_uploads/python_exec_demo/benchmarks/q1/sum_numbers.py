import sys


def main() -> None:
    values = [int(line.strip()) for line in sys.stdin.read().splitlines() if line.strip()]
    print(sum(values))


if __name__ == "__main__":
    main()
