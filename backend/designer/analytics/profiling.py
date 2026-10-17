"""Conservative, reproducible typing and profiling; raw cells remain untouched."""
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from statistics import quantiles

from .models import ColumnProfile, Notice, Profile

MISSING = {"", "null", "none", "na", "n/a", "nan", "—", "-"}
IDENTIFIER = re.compile(r"(^|[\s_])(id|code|код|артикул|номер|индекс)([\s_]|$)", re.I)


def missing(value):
    return value is None or isinstance(value, str) and value.strip().lower() in MISSING


def number(value):
    if missing(value) or isinstance(value, bool):
        return None
    text = str(value).strip().replace("−", "-")
    # Space-separated groups must be thousands, not two independent numbers.
    if re.search(r"[\s\u00a0\u202f]", text):
        if not re.fullmatch(r"[+-]?\d{1,3}(?:[\s\u00a0\u202f]\d{3})+(?:[.,]\d+)?", text):
            return None
        text = re.sub(r"[\s\u00a0\u202f]", "", text)
    if not re.fullmatch(r"[+-]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][+-]?\d+)?", text):
        return None
    try:
        result = Decimal(text.replace(",", "."))
        supported = (result.is_finite() and abs(result) < Decimal("1e100")
                     and (result == 0 or abs(result) >= Decimal("1e-100"))
                     and len(result.as_tuple().digits) <= 50)
        return result if supported else None
    except InvalidOperation:
        return None


def date_value(value, year=False):
    if year and re.fullmatch(r"\d{4}", str(value)):
        try:
            return date(int(value), 1, 1).isoformat()
        except ValueError:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", text):
            return date.fromisoformat(text+"-01").isoformat()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", text):
            return datetime.fromisoformat(text).date().isoformat() if "T" in text else date.fromisoformat(text).isoformat()
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", text):
            return datetime.strptime(text, "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None
    return None


def _unit(name):
    match = re.search(r"\[([^]]+)\]|\(([^)]+)\)", name)
    return (match.group(1) or match.group(2)).strip() if match else "%" if "%" in name else ""


def normalized_values(dataset, column, kind):
    index = next(i for i, c in enumerate(dataset.columns) if c.id == column)
    result = []
    for row in dataset.rows:
        value = row[index]
        result.append(None if missing(value) else number(value) if kind == "number"
                      else date_value(value, year=bool(re.fullmatch(r"year|год", dataset.columns[index].name, re.I)))
                      if kind == "date" else str(value).strip())
    return result


def profile_dataset(dataset, column_types=None):
    overrides = column_types or {}
    if set(overrides) - {c.id for c in dataset.columns}:
        raise ValueError("unknown column type override")
    columns, warnings = [], list(dataset.warnings)
    for index, column in enumerate(dataset.columns):
        raw = [r[index] for r in dataset.rows]
        populated = [v for v in raw if not missing(v)]
        numerics = [number(v) for v in populated]
        dates = [date_value(v, year=bool(re.fullmatch(r"year|год", column.name, re.I))) for v in populated]
        distinct = len({str(v).strip() for v in populated})
        if not populated:
            kind = "empty"
        elif all(v is not None for v in dates):
            kind = "date"
        elif all(v is not None for v in numerics):
            kind = "number"
        elif any(v is not None for v in numerics+dates):
            kind = "ambiguous"
        else:
            kind = "text" if any(len(str(v)) > 100 for v in populated) else "category"
        kind = overrides.get(column.id, kind)
        if kind in {"number", "date"}:
            parsed = numerics if kind == "number" else dates
            if populated and any(v is None for v in parsed):
                kind = "ambiguous"
        role = ("identifier" if IDENTIFIER.search(column.name) and column.id not in overrides else "metric" if kind == "number"
                else "time" if kind == "date" else "dimension" if kind == "category" else "unknown")
        entry = ColumnProfile(id=column.id, name=column.name, kind=kind, role=role,
                              unit=_unit(column.name), missing=len(raw)-len(populated), distinct=distinct)
        if kind == "ambiguous":
            warnings.append(Notice(code="profile.ambiguous_type", params={"column": column.id}))
        if kind == "number" and role == "metric" and len(populated) >= 4:
            q1, _, q3 = quantiles(numerics, n=4, method="inclusive")
            spread = q3-q1
            entry.outlier_row_ids = [row_id for row_id, v in zip(dataset.row_ids, raw)
                                     if number(v) is not None and (number(v) < q1-Decimal('1.5')*spread
                                                                  or number(v) > q3+Decimal('1.5')*spread)]
            if entry.outlier_row_ids:
                warnings.append(Notice(code="profile.outliers_retained", params={"column": column.id}))
        if kind == "date" and populated:
            ordered = sorted(set(dates))
            entry.period = [ordered[0], ordered[-1]]
            if len(ordered) >= 2:
                days = [(date.fromisoformat(b)-date.fromisoformat(a)).days for a, b in zip(ordered, ordered[1:])]
                months = [int(v[:4])*12+int(v[5:7]) for v in ordered]
                if all(v == 1 for v in days):
                    entry.periodicity = "daily"
                elif all(b-a == 1 for a, b in zip(months, months[1:])):
                    entry.periodicity = "monthly"
                elif all(b-a == 12 for a, b in zip(months, months[1:])):
                    entry.periodicity = "yearly"
                else:
                    entry.periodicity = "irregular"
        columns.append(entry)
    # A possible hierarchy is an observed many-to-one functional dependency,
    # not a claim about the business meaning of two arbitrary labels.
    hierarchies = []
    dimensions = [c for c in columns if c.role == "dimension"]
    pairs_checked = 0
    for parent in dimensions:
        if parent.distinct < 2:
            continue
        for child in dimensions:
            if child.distinct <= parent.distinct:
                continue
            pairs_checked += 1
            if pairs_checked > 128:
                continue
            pi = next(i for i, c in enumerate(dataset.columns) if c.id == parent.id)
            ci = next(i for i, c in enumerate(dataset.columns) if c.id == child.id)
            mapping = {}
            for row in dataset.rows:
                if not missing(row[pi]) and not missing(row[ci]):
                    mapping.setdefault(str(row[ci]), set()).add(str(row[pi]))
            if mapping and all(len(v) == 1 for v in mapping.values()):
                hierarchies.append([parent.id, child.id])
    if pairs_checked > 128:
        warnings.append(Notice(code="profile.hierarchy_limit"))
    return Profile(row_count=len(dataset.rows), column_count=len(columns), columns=columns,
                   hierarchies=hierarchies, dimension_count=sum(c.role in {"time", "dimension"} for c in columns),
                   metric_count=sum(c.role == "metric" for c in columns), warnings=warnings)
