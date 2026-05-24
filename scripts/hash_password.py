#!/usr/bin/env python3
"""Generate argon2 password hash for config. Usage: python scripts/hash_password.py 'secret'"""

import sys

from packvault.auth.passwords import hash_password


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: hash_password.py <password>", file=sys.stderr)
        sys.exit(1)
    print(hash_password(sys.argv[1]))


if __name__ == "__main__":
    main()
