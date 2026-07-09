"""验证 9000 在 PostgreSQL DATABASE_URL 下可创建 FastAPI app。"""

from __future__ import annotations

import argparse
import os
import sys

from app.database_url import parse_database_url


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()

    runtime = parse_database_url(args.database_url)
    if runtime.backend != "postgresql":
        print("SMOKE_FAILED: DATABASE_URL 必须是 PostgreSQL")
        return 2

    os.environ["DATABASE_URL"] = args.database_url

    # DATABASE_URL 必须在 app.main 导入前设置；本 smoke 不进入 lifespan，避免启动调度器和本机热键。
    from app.main import create_app

    app = create_app()
    route_paths = {route.path for route in app.routes}
    if "/" not in route_paths:
        print("SMOKE_FAILED: root route missing")
        return 1

    print(f"database_url={runtime.safe_url}")
    print("SMOKE_PASS: 9000 PostgreSQL DATABASE_URL app startup ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
