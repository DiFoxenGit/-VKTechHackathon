"""Bounded imports into full tables. No extraction, storage or model calls."""
import csv
import hashlib
import io
import json
import re
import zipfile
from decimal import DecimalException
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from .models import MAX_SAFE_INTEGER, Column, Dataset, DatasetRef, ImportResult, Notice
from .xlsx import read_workbook

MAX_BYTES = 20 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024
MAX_FILES = 256
MAX_ROWS = 100_000
MAX_COLUMNS = 256
MAX_CELLS = 1_000_000
SUPPORTED = {".csv", ".json", ".xlsx", ".txt", ".md"}


class ImportFailure(ValueError):
    def __init__(self, code, **params):
        self.notice = Notice(code=code, params=params)
        super().__init__(code)


def safe_archive(data):
    if len(data) > MAX_BYTES:
        raise ImportFailure("import.file_limit")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        members = archive.infolist()
        total = 0
        names = set()
        for item in members:
            # ZipInfo normalizes backslashes on Windows; validate the raw name.
            name = item.orig_filename
            parts = PurePosixPath(name).parts
            if (name.startswith(("/", "\\")) or "\\" in name or ":" in name or "\x00" in name
                    or ".." in parts or name in names or item.flag_bits & 1
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise ImportFailure("import.unsafe_archive", file=name)
            names.add(name)
            total += item.file_size
            if item.file_size > MAX_BYTES or total > MAX_EXPANDED:
                raise ImportFailure("import.archive_limit")
        if len(members) > MAX_FILES:
            raise ImportFailure("import.archive_limit")
        return archive
    except (zipfile.BadZipFile, NotImplementedError) as exc:
        raise ImportFailure("import.invalid_archive") from exc


def xml_root(data):
    if b"\x00" in data or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ImportFailure("import.unsafe_xml")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ImportFailure("import.invalid_xml") from exc


def table_dataset(data, filename, table, header, rows, row_ids, *, archive_path=None,
                  context="", warnings=()):
    if not header or len(header) > MAX_COLUMNS or len(rows) > MAX_ROWS:
        raise ImportFailure("import.table_limit")
    if len(header) * len(rows) > MAX_CELLS:
        raise ImportFailure("import.table_limit")
    if any(len(row) != len(header) for row in rows):
        raise ImportFailure("import.ragged_rows", table=str(table))
    if any(isinstance(v, (dict, list)) for row in rows for v in row):
        raise ImportFailure("import.nested_values", table=str(table))
    digest = hashlib.sha256(data).hexdigest()
    identity = hashlib.sha256(f"{digest}:{archive_path or ''}:{table}".encode()).hexdigest()[:24]
    names = [str(v).strip() if v is not None else "" for v in header]
    notes = list(warnings)
    if any(type(v) is int and abs(v) > MAX_SAFE_INTEGER for row in rows for v in row):
        rows = [[str(v) if type(v) is int and abs(v) > MAX_SAFE_INTEGER else v for v in row] for row in rows]
        notes.append(Notice(code="import.large_integer_as_text"))
    if len(set(names)) != len(names) or "" in names:
        notes.append(Notice(code="import.ambiguous_headers"))
    return Dataset(ref=DatasetRef(dataset_id=identity, source_sha256=digest,
                                  filename=filename, archive_path=archive_path, table=str(table)),
                   columns=[Column(id=f"c{i+1}", name=n or f"column_{i+1}") for i, n in enumerate(names)],
                   rows=rows, row_ids=row_ids, context=context, warnings=notes)


def csv_table(data, filename, archive_path):
    text = data.decode("utf-8-sig")
    offset, declared_separator = 0, None
    first, _, remaining = text.partition("\n")
    if re.fullmatch(r"sep=[,;\t|]\r?", first, re.I):
        declared_separator, text, offset = first[4], remaining, 1
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    options = {"delimiter": declared_separator} if declared_separator else {}
    reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect, strict=True, **options)
    records, ids = [], []
    while True:
        start = reader.line_num+1+offset
        try:
            row = next(reader)
        except StopIteration:
            break
        if not any(v.strip() for v in row):
            continue
        records.append(row)
        ids.append(start)
        if len(records) > MAX_ROWS + 1 or len(row) > MAX_COLUMNS:
            raise ImportFailure("import.table_limit")
        if max(0, len(records)-1) * len(row) > MAX_CELLS:
            raise ImportFailure("import.table_limit")
    if len(records) < 2:
        raise ImportFailure("import.no_table")
    return [table_dataset(data, filename, "1", records[0], records[1:], ids[1:], archive_path=archive_path)]


def json_tables(data, filename, archive_path):
    def reject_constant(value):
        raise ImportFailure("import.nonfinite_number", value=value)
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ImportFailure("import.duplicate_json_keys", key=key)
            result[key] = value
        return result
    value = json.loads(data.decode("utf-8-sig"), parse_constant=reject_constant,
                       parse_float=str, object_pairs_hook=unique_object)
    if isinstance(value, list) and value and all(isinstance(r, dict) for r in value):
        keys = list(dict.fromkeys(k for row in value for k in row))
        rows = [[row.get(k) for k in keys] for row in value]
        notes = [Notice(code="import.missing_json_keys")] if any(set(r) != set(keys) for r in value) else []
    elif isinstance(value, dict) and set(value) == {"columns", "rows"}:
        keys, rows, notes = value["columns"], value["rows"], []
        if not isinstance(keys, list) or not isinstance(rows, list) or not all(isinstance(r, list) for r in rows):
            raise ImportFailure("import.ambiguous_json")
    else:
        raise ImportFailure("import.ambiguous_json")
    return [table_dataset(data, filename, "1", keys, rows, list(range(1, len(rows)+1)),
                          archive_path=archive_path, warnings=notes)]


def _text_cells(line, delimiter):
    content = line.strip()
    if delimiter == "|":
        content = content[1:] if content.startswith("|") else content
        content = content[:-1] if content.endswith("|") else content
        return [v.strip().replace(r"\|", "|") for v in re.split(r"(?<!\\)\|", content)]
    return [v.strip() for v in next(csv.reader([content], delimiter=delimiter))]


def _header_like(cells):
    # A comma in a prose sentence is not evidence of a table header.
    return len(cells) >= 2 and all(c and len(c) <= 64 and len(c.split()) <= 4
                                  and re.search(r"[A-Za-zА-Яа-яЁё]", c)
                                  and not re.search(r"[.:`{}]", c) for c in cells)


def text_tables(data, filename, archive_path):
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    result, i, fence = [], 0, None
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith(("```", "~~~")):
            if fence is None:
                fence = line[3:].strip().lower()
            else:
                fence = None
            i += 1
            continue
        if fence is not None and fence not in {"csv", "tsv", "text", "txt", "markdown", "md"}:
            i += 1
            continue
        delimiter = next((d for d in ("|", "\t", ";", ",") if d in line), None)
        if delimiter is None or i+1 >= len(lines):
            i += 1
            continue
        header = _text_cells(line, delimiter)
        following = _text_cells(lines[i+1], delimiter)
        markdown = delimiter == "|" and len(header) == len(following) and all(re.fullmatch(r":?-{3,}:?", c) for c in following)
        if not markdown and (delimiter == "|" or not _header_like(header) or len(following) != len(header)):
            i += 1
            continue
        start, rows, ids = i, [], []
        i += 2 if markdown else 1
        while i < len(lines) and delimiter in lines[i] and lines[i].strip() and not lines[i].lstrip().startswith(("#", "```", "~~~")):
            row = _text_cells(lines[i], delimiter)
            if len(row) != len(header):
                raise ImportFailure("import.ragged_rows", line=i+1)
            rows.append(row)
            ids.append(i+1)
            i += 1
        if rows:
            result.append(table_dataset(data, filename, str(len(result)+1), header, rows, ids,
                                        archive_path=archive_path, context=text))
        if i == start:
            i += 1
    if not result:
        raise ImportFailure("import.no_table")
    return result


def _single(data, filename, archive_path=None, rejected=None):
    if len(data) > MAX_BYTES:
        raise ImportFailure("import.file_limit")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".csv":
        return csv_table(data, filename, archive_path)
    if suffix == ".json":
        return json_tables(data, filename, archive_path)
    if suffix == ".xlsx":
        return read_workbook(data, filename, archive_path, rejected)
    if suffix in {".txt", ".md"}:
        return text_tables(data, filename, archive_path)
    raise ImportFailure("import.unsupported", file=filename)


def import_datasets(data: bytes, filename: str) -> ImportResult:
    """All supported files/tables, plus explicit rejections. Caller persists results."""
    result = ImportResult()
    try:
        if PurePosixPath(filename).suffix.lower() != ".zip":
            result.datasets = _single(data, filename, rejected=result.rejected)
        else:
            with safe_archive(data) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    try:
                        tables = _single(archive.read(member), member.filename, member.filename, result.rejected)
                        if sum(len(d.rows)*len(d.columns) for d in result.datasets+tables) > MAX_CELLS:
                            raise ImportFailure("import.table_limit")
                        result.datasets.extend(tables)
                    except (ImportFailure, ValueError, UnicodeError, csv.Error, KeyError, IndexError,
                            TypeError, OverflowError, zipfile.BadZipFile, NotImplementedError, DecimalException, RecursionError) as exc:
                        notice = exc.notice if isinstance(exc, ImportFailure) else Notice(code="import.invalid_data")
                        result.rejected.append(notice.model_copy(update={"params": {**notice.params, "file": member.filename}}))
    except (ImportFailure, ValueError, UnicodeError, csv.Error, KeyError, IndexError,
            TypeError, OverflowError, zipfile.BadZipFile, NotImplementedError, DecimalException, RecursionError) as exc:
        result.rejected.append(exc.notice if isinstance(exc, ImportFailure) else Notice(code="import.invalid_data"))
    if sum(len(d.rows)*len(d.columns) for d in result.datasets) > MAX_CELLS:
        result.datasets.clear()
        result.rejected.append(Notice(code="import.table_limit"))
    return result
