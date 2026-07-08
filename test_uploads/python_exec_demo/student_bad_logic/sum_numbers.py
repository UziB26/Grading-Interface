import sys


def main() -> None:
    values = [int(line.strip()) for line in sys.stdin.read().splitlines() if line.strip()]
    # Wrong on purpose: computes average instead of sum.
    print(sum(values) // len(values))


if __name__ == "__main__":
    main()
