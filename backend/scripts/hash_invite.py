from __future__ import annotations

import sys
from getpass import getpass

from app.core.security import hash_invite_code


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else getpass("请输入邀请码：")
    if len(code) < 8:
        raise SystemExit("邀请码至少需要 8 个字符")
    print(hash_invite_code(code))


if __name__ == "__main__":
    main()
