import re
from dataclasses import dataclass


class UnsafeSqlError(ValueError):
    pass


@dataclass(frozen=True)
class WriteSqlDecision:
    sql: str
    statement_type: str
    target: str | None
    action: str
    reason: str = ""


def _statement_without_trailing_semicolon(sql: str) -> str:
    in_single = False
    in_double = False
    index = 0
    while index < len(sql):
        char = sql[index]
        next_char = sql[index + 1] if index + 1 < len(sql) else ""
        if in_single:
            if char == "'" and next_char == "'":
                index += 2
                continue
            if char == "'":
                in_single = False
            index += 1
            continue
        if in_double:
            if char == '"' and next_char == '"':
                index += 2
                continue
            if char == '"':
                in_double = False
            index += 1
            continue
        if char == "'":
            in_single = True
        elif char == '"':
            in_double = True
        elif char == "-" and next_char == "-":
            raise UnsafeSqlError("Comments are not allowed in IDE SQL.")
        elif char == "/" and next_char == "*":
            raise UnsafeSqlError("Comments are not allowed in IDE SQL.")
        elif char == "*" and next_char == "/":
            raise UnsafeSqlError("Comments are not allowed in IDE SQL.")
        elif char == ";":
            if sql[index + 1 :].strip():
                raise UnsafeSqlError("Only one statement is allowed.")
            return sql[:index].strip()
        index += 1
    return sql.strip()


def validate_read_only_sql(sql: str, limit: int = 100) -> str:
    stripped = sql.strip()
    if not stripped:
        raise UnsafeSqlError("SQL is required.")

    normalized = _statement_without_trailing_semicolon(stripped)
    first = normalized.split(None, 1)[0].lower()
    if first not in {"select", "with"}:
        raise UnsafeSqlError("Only SELECT and CTE queries are allowed.")

    lowered = re.sub(r"\s+", " ", normalized.lower())
    if first == "with" and re.search(
        r"\b(insert|update|delete|merge)\b[\s\S]*\breturning\b",
        lowered,
    ):
        raise UnsafeSqlError("Data-modifying CTEs are not allowed.")

    if not re.search(r"\blimit\s+\d+\b", lowered):
        normalized = f"{normalized} limit {max(1, min(limit, 500))}"
    return normalized


DENYLIST = re.compile(
    r"\b(drop\s+database|drop\s+schema|xp_cmdshell|pg_read_server_files|copy\s+.+\s+program|load_file)\b",
    re.IGNORECASE,
)


def _target_after(keyword: str, sql: str) -> str | None:
    match = re.search(rf"\b{keyword}\b\s+(?:if\s+(?:not\s+)?exists\s+)?([\"`\[]?[\w.]+[\"`\]]?)", sql, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip("\"`[]")


def validate_write_sql(sql: str) -> WriteSqlDecision:
    stripped = sql.strip()
    if not stripped:
        raise UnsafeSqlError("SQL is required.")
    normalized = _statement_without_trailing_semicolon(stripped)
    lowered = re.sub(r"\s+", " ", normalized.lower())
    if DENYLIST.search(lowered):
        raise UnsafeSqlError("This SQL operation is blocked by policy.")
    first = lowered.split(None, 1)[0]
    if first == "insert":
        return WriteSqlDecision(normalized, "INSERT", _target_after("into", normalized), "allow")
    if first == "update":
        target = _target_after("update", normalized)
        if re.search(r"\bwhere\b", lowered):
            return WriteSqlDecision(normalized, "UPDATE", target, "allow")
        return WriteSqlDecision(normalized, "UPDATE", target, "requires_approval", "UPDATE without WHERE")
    if first == "delete":
        target = _target_after("from", normalized)
        if re.search(r"\bwhere\b", lowered):
            return WriteSqlDecision(normalized, "DELETE", target, "allow")
        return WriteSqlDecision(normalized, "DELETE", target, "requires_approval", "DELETE without WHERE")
    if re.match(r"create\s+(?:or\s+replace\s+)?table\b", lowered):
        return WriteSqlDecision(normalized, "CREATE_TABLE", _target_after("table", normalized), "allow")
    if re.match(r"create\s+schema\b", lowered):
        return WriteSqlDecision(normalized, "CREATE_SCHEMA", _target_after("schema", normalized), "allow")
    sql_server_create = re.match(
        r"if\s+object_id\s*\(\s*N?'([^']+)'\s*,\s*N?'U'\s*\)\s+is\s+null\s+create\s+table\b",
        normalized,
        re.IGNORECASE,
    )
    if sql_server_create:
        return WriteSqlDecision(normalized, "CREATE_TABLE", sql_server_create.group(1), "allow")
    if re.match(r"create\s+(?:or\s+replace\s+)?view\b", lowered):
        return WriteSqlDecision(normalized, "CREATE_VIEW", _target_after("view", normalized), "allow")
    if re.match(r"create\s+index\b", lowered):
        return WriteSqlDecision(normalized, "CREATE_INDEX", _target_after("index", normalized), "allow")
    if re.match(r"alter\s+table\b", lowered):
        target = _target_after("table", normalized)
        if re.search(r"\bdrop\s+column\b", lowered):
            return WriteSqlDecision(normalized, "ALTER_TABLE_DROP_COLUMN", target, "requires_approval", "DROP COLUMN")
        if re.search(r"\badd\s+column\b", lowered):
            return WriteSqlDecision(normalized, "ALTER_TABLE_ADD_COLUMN", target, "allow")
    if first == "grant":
        return WriteSqlDecision(normalized, "GRANT", _target_after("on", normalized), "requires_approval", "Permission changes require approval")
    if re.match(r"drop\s+table\b", lowered):
        return WriteSqlDecision(normalized, "DROP_TABLE", _target_after("table", normalized), "requires_approval", "DROP TABLE")
    if re.match(r"drop\s+view\b", lowered):
        return WriteSqlDecision(normalized, "DROP_VIEW", _target_after("view", normalized), "requires_approval", "DROP VIEW")
    if first == "truncate":
        return WriteSqlDecision(normalized, "TRUNCATE", _target_after("table", normalized), "requires_approval", "TRUNCATE")
    raise UnsafeSqlError("Unsupported write SQL operation.")
