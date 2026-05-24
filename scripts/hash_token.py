#!/usr/bin/env python3
"""Generate sha256 token hash for config. Usage: python scripts/hash_token.py 'raw-token'"""

import sys

from packvault.auth.tokens import hash_token


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: hash_token.py <raw-token>", file=sys.stderr)
        sys.exit(1)
    print(hash_token(sys.argv[1]))


if __name__ == "__main__":
    main()
