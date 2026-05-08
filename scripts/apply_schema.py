from pathlib import Path
from sqlalchemy import create_engine, text
from app.core.config import get_settings

def split_sql(sql: str):
    parts = []
    buf = []
    in_single = False
    in_double = False
    for ch in sql:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == ';' and not in_single and not in_double:
            stmt = ''.join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
        else:
            buf.append(ch)
    tail = ''.join(buf).strip()
    if tail:
        parts.append(tail)
    return parts

def main():
    sql_path = Path('sql/2560_schema_v2.4.sql')
    if not sql_path.exists():
        raise FileNotFoundError(sql_path)
    engine = create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True, future=True)
    sql = sql_path.read_text(encoding='utf-8')
    statements = [s for s in split_sql(sql) if s.strip() and not s.strip().startswith('--')]
    with engine.begin() as conn:
        for stmt in statements:
            conn.execute(text(stmt))
    print(f'已执行 SQL 语句数量: {len(statements)}')

if __name__ == '__main__':
    main()
