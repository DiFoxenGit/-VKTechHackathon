"""Read ordinary OOXML worksheets, dates and cached formulas without executing them."""
import posixpath
import re
from datetime import datetime, timedelta
from decimal import Decimal, localcontext

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def _column(ref):
    value = 0
    match = re.fullmatch(r"([A-Z]+)[1-9]\d*", ref)
    if match is None:
        raise ValueError("invalid XLSX coordinate")
    for c in match[1]:
        value = value * 26 + ord(c) - 64
    return value - 1


def read_workbook(data, filename, archive_path, rejected=None):
    # Late import avoids a dependency cycle while keeping limits in one module.
    from .importing import (safe_archive, xml_root, table_dataset, ImportFailure,
                            MAX_ROWS, MAX_COLUMNS, MAX_CELLS)
    from .models import Notice
    rejected = rejected if rejected is not None else []
    with safe_archive(data) as archive:
        names = set(archive.namelist())
        workbook = xml_root(archive.read("xl/workbook.xml"))
        links = xml_root(archive.read("xl/_rels/workbook.xml.rels"))
        relations = {}
        for link in links:
            if link.get("TargetMode") == "External":
                continue
            target = link.get("Target", "")
            path = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/"+target)
            if not path.startswith("xl/"):
                raise ImportFailure("import.unsafe_archive")
            relations[link.get("Id")] = path
        strings = []
        if "xl/sharedStrings.xml" in names:
            root = xml_root(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(si.itertext()) for si in root]
        date_styles, percent_styles, datetime_styles, time_styles = set(), set(), set(), set()
        if "xl/styles.xml" in names:
            root = xml_root(archive.read("xl/styles.xml"))
            formats = {int(n.get("numFmtId")): n.get("formatCode", "") for n in root.findall("s:numFmts/s:numFmt", NS)}
            for i, xf in enumerate(root.findall("s:cellXfs/s:xf", NS)):
                fmt = int(xf.get("numFmtId", "0"))
                code = re.sub(r'"[^"]*"|\[[^]]*\]|\\.', "", formats.get(fmt, ""))
                has_date = bool(re.search(r"[yd]", code, re.I))
                elapsed = re.sub(r'"[^"]*"|\\.', "", formats.get(fmt, ""))
                has_clock = bool(re.search(r"[hs]", code, re.I) or re.search(r"\[[hms]+\]", elapsed, re.I))
                if 14 <= fmt <= 17 or fmt == 22 or has_date:
                    date_styles.add(i)
                if fmt == 22 or has_date and has_clock:
                    datetime_styles.add(i)
                if 18 <= fmt <= 21 or 45 <= fmt <= 47 or has_clock and not has_date:
                    time_styles.add(i)
                if fmt in {9, 10} or "%" in code:
                    percent_styles.add(i)
        props = workbook.find("s:workbookPr", NS)
        epoch = datetime(1904, 1, 1) if props is not None and props.get("date1904") in {"1", "true"} else datetime(1899, 12, 30)
        result = []
        for sheet in workbook.findall("s:sheets/s:sheet", NS):
            path = relations.get(sheet.get(REL))
            if path is None:
                raise ImportFailure("import.external_sheet")
            root = xml_root(archive.read(path))
            records, row_ids, warnings, numeric_styles = [], [], [], {}
            for row in root.findall("s:sheetData/s:row", NS):
                row_id = int(row.get("r", "0"))
                if row_id <= 0 or len(records) > MAX_ROWS+20:
                    raise ImportFailure("import.table_limit")
                values, formula_row = {}, False
                for cell in row.findall("s:c", NS):
                    index = _column(cell.get("r", ""))
                    if index in values or int(re.search(r"\d+$", cell.get("r", ""))[0]) != row_id:
                        raise ImportFailure("import.invalid_xml")
                    if index >= MAX_COLUMNS:
                        raise ImportFailure("import.table_limit")
                    formula_row |= cell.find("s:f", NS) is not None or cell.get("t") == "e"
                    kind, v = cell.get("t"), cell.find("s:v", NS)
                    raw = v.text if v is not None else None
                    if kind == "inlineStr":
                        inline = cell.find("s:is", NS)
                        value = "".join(inline.itertext()) if inline is not None else ""
                    elif kind == "s" and raw is not None:
                        value = strings[int(raw)]
                    elif kind == "b" and raw is not None:
                        value = raw == "1"
                    elif kind == "e":
                        value = None
                        warnings.append(Notice(code="import.excel_error", params={"cell": cell.get("r")}))
                    elif raw is not None and kind not in {"str", "d"}:
                        numeric = Decimal(raw)
                        if not numeric.is_finite():
                            raise ImportFailure("import.nonfinite_number")
                        style = int(cell.get("s", "0"))
                        representation = ("date" if style in date_styles else "percent" if style in percent_styles
                                          else "day_fraction" if style in time_styles else "number")
                        numeric_styles.setdefault(index, set()).add(representation)
                        if len(numeric_styles[index]) > 1:
                            raise ImportFailure("import.inconsistent_cell_units", column=index+1)
                        if style in date_styles:
                            if epoch.year == 1899 and 60 <= numeric < 61:
                                value = None
                                warnings.append(Notice(code="import.invalid_excel_date", params={"cell": cell.get("r")}))
                            else:
                                adjusted = numeric+1 if epoch.year == 1899 and numeric < 60 else numeric
                                instant = epoch + timedelta(days=float(adjusted))
                                value = (instant.date().isoformat() if style not in datetime_styles
                                         and not (instant.hour or instant.minute or instant.second or instant.microsecond) else instant.isoformat())
                        elif style in percent_styles:
                            with localcontext() as decimal_context:
                                decimal_context.prec = 350
                                numeric *= 100
                            value = int(numeric) if numeric == numeric.to_integral_value() else str(numeric)
                        else:
                            value = (int(numeric) if numeric.adjusted() <= 100 and len(numeric.as_tuple().digits) <= 50
                                     and numeric == numeric.to_integral_value() else raw)
                    else:
                        value = raw
                    if cell.find("s:f", NS) is not None and raw is None:
                        warnings.append(Notice(code="import.formula_without_cache", params={"cell": cell.get("r")}))
                    values[index] = value
                if not values or not formula_row and all(v is None or v == "" for v in values.values()):
                    continue
                records.append(values)
                row_ids.append(row_id)
                # The final table enforces the data-cell limit after its header/preamble is identified.
                if len(records) * (max(values)+1) > MAX_CELLS+MAX_COLUMNS*21:
                    raise ImportFailure("import.table_limit")
            if len(records) < 2:
                rejected.append(Notice(code="import.empty_sheet", params={"file": filename, "sheet": sheet.get("name", path)}))
                continue
            width = max(max(r) for r in records)+1
            from .profiling import number, date_value
            header_index = 0
            for candidate, record in enumerate(records[:20]):
                populated = [v for v in record.values() if v is not None and v != ""]
                if len(populated) == 1 and (not isinstance(populated[0], str) or number(populated[0]) is not None
                                            or len(populated[0].split()) < 2):
                    break
                if len(populated) >= 2:
                    if all(isinstance(v, str) and number(v) is None and date_value(v) is None for v in populated):
                        header_index = candidate
                    break
            context = "\n".join(" | ".join(str(v) for v in r.values() if v is not None) for r in records[:header_index])
            if context:
                warnings.append(Notice(code="import.sheet_preamble", params={"header_row": row_ids[header_index]}))
            matrix = [[r.get(c) for c in range(width)] for r in records[header_index:]]
            if len(matrix) < 2:
                rejected.append(Notice(code="import.empty_sheet", params={"file": filename, "sheet": sheet.get("name", path)}))
                continue
            ds = table_dataset(data, filename, sheet.get("name", path), matrix[0], matrix[1:], row_ids[header_index+1:],
                               archive_path=archive_path, warnings=warnings, context=context)
            for index, representations in numeric_styles.items():
                from .profiling import _unit
                declared_unit = _unit(ds.columns[index].name)
                if representations == {"percent"}:
                    if declared_unit not in {"", "%"}:
                        raise ImportFailure("import.inconsistent_cell_units", column=index+1)
                    ds.columns[index].unit = "%"
                    ds.columns[index].normalization = "excel_percentage_points"
                    ds.warnings.append(Notice(code="import.percent_scaled", params={"column": ds.columns[index].id}))
                elif representations == {"day_fraction"}:
                    if declared_unit.lower() not in {"", "day", "days", "день", "дней", "сутки"}:
                        raise ImportFailure("import.inconsistent_cell_units", column=index+1)
                    ds.columns[index].unit = "day"
                    ds.columns[index].normalization = "excel_day_fraction"
                    ds.warnings.append(Notice(code="import.time_fraction", params={"column": ds.columns[index].id}))
            result.append(ds)
        if not result and not rejected:
            raise ImportFailure("import.no_table")
        return result
