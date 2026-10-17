"""Bounded imports into full tables. No extraction, storage or model calls."""
import csv
import hashlib
import io
import json
import re
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from .models import Column, Dataset, DatasetRef, ImportResult, Notice
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
    if len(set(names)) != len(names) or "" in names:
        notes.append(Notice(code="import.ambiguous_headers"))
    return Dataset(ref=DatasetRef(dataset_id=identity, source_sha256=digest,
                                  filename=filename, archive_path=archive_path, table=str(table)),
                   columns=[Column(id=f"c{i+1}", name=n or f"column_{i+1}") for i, n in enumerate(names)],
                   rows=rows, row_ids=row_ids, context=context, warnings=notes)


def csv_table(data, filename, archive_path):
    text = data.decode("utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text, newline=""), dialect=dialect, strict=True)
    records, ids = [], []
    for row in reader:
        if not any(v.strip() for v in row):
            continue
        records.append(row)
        ids.append(reader.line_num)
        if len(records) > MAX_ROWS + 1 or len(row) > MAX_COLUMNS:
            raise ImportFailure("import.table_limit")
        if len(records) * len(row) > MAX_CELLS:
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


def text_tables(data, filename, archive_path):
    text = data.decode("utf-8-sig")
    lines = text.splitlines()
    blocks, block = [], []
    for i, line in enumerate(lines + [""]):
        # Deliberately conservative: a delimited block must have >=2 columns.
        delimiter = next((d for d in ("|", "\t", ";", ",") if d in line), None)
        if delimiter:
            content = line.strip()
            if delimiter == "|":
                content = content[1:] if content.startswith("|") else content
                content = content[:-1] if content.endswith("|") else content
            cells = next(csv.reader([content], delimiter=delimiter))
            cells = [v.strip() for v in cells]
            if block and delimiter == block[0][2] and len(cells) != len(block[0][1]):
                raise ImportFailure("import.ragged_rows")
            if block and delimiter != block[0][2]:
                blocks.append(block)
                block = []
            block.append((i+1, cells, delimiter))
        elif block:
            blocks.append(block)
            block = []
    result = []
    for b in blocks:
        content = [(i, r) for i, r, _ in b if not all(re.fullmatch(r":?-{3,}:?", c) for c in r)]
        if len(content) < 2 or len(content[0][1]) < 2:
            continue
        result.append(table_dataset(data, filename, str(len(result)+1), content[0][1],
                                    [r for _, r in content[1:]], [i for i, _ in content[1:]],
                                    archive_path=archive_path, context=text))
    if not result:
        raise ImportFailure("import.no_table")
    return result


def _single(data, filename, archive_path=None):
    if len(data) > MAX_BYTES:
        raise ImportFailure("import.file_limit")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix == ".csv":
        return csv_table(data, filename, archive_path)
    if suffix == ".json":
        return json_tables(data, filename, archive_path)
    if suffix == ".xlsx":
        return read_workbook(data, filename, archive_path)
    if suffix in {".txt", ".md"}:
        return text_tables(data, filename, archive_path)
    raise ImportFailure("import.unsupported", file=filename)


def import_datasets(data: bytes, filename: str) -> ImportResult:
    """All supported files/tables, plus explicit rejections. Caller persists results."""
    result = ImportResult()
    try:
        if PurePosixPath(filename).suffix.lower() != ".zip":
            result.datasets = _single(data, filename)
        else:
            with safe_archive(data) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    try:
                        result.datasets.extend(_single(archive.read(member), member.filename, member.filename))
                    except (ImportFailure, ValueError, UnicodeError, csv.Error, KeyError, IndexError,
                            TypeError, OverflowError, zipfile.BadZipFile, NotImplementedError) as exc:
                        notice = exc.notice if isinstance(exc, ImportFailure) else Notice(code="import.invalid_data")
                        result.rejected.append(notice.model_copy(update={"params": {**notice.params, "file": member.filename}}))
    except (ImportFailure, ValueError, UnicodeError, csv.Error, KeyError, IndexError,
            TypeError, OverflowError, zipfile.BadZipFile, NotImplementedError) as exc:
        result.rejected.append(exc.notice if isinstance(exc, ImportFailure) else Notice(code="import.invalid_data"))
    if sum(len(d.rows)*len(d.columns) for d in result.datasets) > MAX_CELLS:
        result.datasets.clear()
        result.rejected.append(Notice(code="import.table_limit"))
    return result
