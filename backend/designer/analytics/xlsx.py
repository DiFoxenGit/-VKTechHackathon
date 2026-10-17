"""Read ordinary OOXML worksheets, dates and cached formulas without executing them."""
import posixpath
import re
from datetime import datetime, timedelta
from decimal import Decimal

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


def read_workbook(data, filename, archive_path):
    # Late import avoids a dependency cycle while keeping limits in one module.
    from .importing import (safe_archive, xml_root, table_dataset, ImportFailure,
                            MAX_ROWS, MAX_COLUMNS, MAX_CELLS)
    from .models import Notice
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
        date_styles = set()
        if "xl/styles.xml" in names:
            root = xml_root(archive.read("xl/styles.xml"))
            formats = {int(n.get("numFmtId")): n.get("formatCode", "") for n in root.findall("s:numFmts/s:numFmt", NS)}
            for i, xf in enumerate(root.findall("s:cellXfs/s:xf", NS)):
                fmt = int(xf.get("numFmtId", "0"))
                code = re.sub(r'"[^"]*"|\[[^]]*\]|\\.', "", formats.get(fmt, ""))
                if 14 <= fmt <= 22 or 45 <= fmt <= 47 or re.search(r"[yd]", code, re.I):
                    date_styles.add(i)
        props = workbook.find("s:workbookPr", NS)
        epoch = datetime(1904, 1, 1) if props is not None and props.get("date1904") in {"1", "true"} else datetime(1899, 12, 30)
        result = []
        for sheet in workbook.findall("s:sheets/s:sheet", NS):
            path = relations.get(sheet.get(REL))
            if path is None:
                raise ImportFailure("import.external_sheet")
            root = xml_root(archive.read(path))
            records, row_ids, warnings = [], [], []
            for row in root.findall("s:sheetData/s:row", NS):
                row_id = int(row.get("r", "0"))
                if row_id <= 0 or len(records) > MAX_ROWS:
                    raise ImportFailure("import.table_limit")
                values = {}
                for cell in row.findall("s:c", NS):
                    index = _column(cell.get("r", ""))
                    if index in values or int(re.search(r"\d+$", cell.get("r", ""))[0]) != row_id:
                        raise ImportFailure("import.invalid_xml")
                    if index >= MAX_COLUMNS:
                        raise ImportFailure("import.table_limit")
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
                        if int(cell.get("s", "0")) in date_styles:
                            if epoch.year == 1899 and 60 <= numeric < 61:
                                value = None
                                warnings.append(Notice(code="import.invalid_excel_date", params={"cell": cell.get("r")}))
                            else:
                                adjusted = numeric+1 if epoch.year == 1899 and numeric < 60 else numeric
                                value = (epoch + timedelta(days=float(adjusted))).isoformat()
                        else:
                            value = int(numeric) if numeric == numeric.to_integral_value() else raw
                    else:
                        value = raw
                    if cell.find("s:f", NS) is not None and raw is None:
                        warnings.append(Notice(code="import.formula_without_cache", params={"cell": cell.get("r")}))
                    values[index] = value
                if not values or all(v is None or v == "" for v in values.values()):
                    continue
                records.append(values)
                row_ids.append(row_id)
                if len(records) * (max(values)+1) > MAX_CELLS:
                    raise ImportFailure("import.table_limit")
            if not records:
                continue
            if len(records) < 2:
                # A nonempty sheet cannot silently disappear from the import.
                raise ImportFailure("import.no_table", sheet=sheet.get("name", path))
            width = max(max(r) for r in records)+1
            matrix = [[r.get(c) for c in range(width)] for r in records]
            result.append(table_dataset(data, filename, sheet.get("name", path), matrix[0], matrix[1:], row_ids[1:],
                                        archive_path=archive_path, warnings=warnings))
        if not result:
            raise ImportFailure("import.no_table")
        return result
