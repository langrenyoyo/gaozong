"""生产 PostgreSQL 备份脚本的最小回归覆盖。"""

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "production_pg_backup.sh"


def test_pg_dump_initializes_db_before_expanding_output_path() -> None:
    """set -u 下不得在同一 local 声明中提前展开尚未初始化的 db。"""
    script = SCRIPT.read_text(encoding="utf-8")
    assert 'local db="$1"\n  local out="$BACKUP_DIR/pg-${db}.dump"' in script
