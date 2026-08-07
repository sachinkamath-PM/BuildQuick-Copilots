from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from fastapi import HTTPException

from app.domain.models import NousSource


MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 100_000
MAX_SOURCE_FILES = 5
MAX_CSV_ROWS = 5_000
SUPPORTED_SOURCE_EXTENSIONS = {".txt", ".csv", ".json"}


@dataclass(frozen=True)
class SourceUpload:
    filename: str
    data: bytes


def parse_sources(uploads: list[SourceUpload]) -> list[NousSource]:
    if not uploads:
        raise HTTPException(status_code=422, detail="Choose at least one source file")
    if len(uploads) > MAX_SOURCE_FILES:
        raise HTTPException(status_code=413, detail=f"Import at most {MAX_SOURCE_FILES} files at once")
    sources: list[NousSource] = []
    seen: set[str] = set()
    for upload in uploads:
        source = _parse_source(upload)
        if source.id in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate source content: {source.filename}")
        seen.add(source.id)
        sources.append(source)
    return sources


def _parse_source(upload: SourceUpload) -> NousSource:
    filename = Path(upload.filename or "source").name[:255]
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SOURCE_EXTENSIONS:
        raise HTTPException(status_code=415, detail=f"{filename}: upload TXT, CSV, or JSON")
    if not upload.data:
        raise HTTPException(status_code=422, detail=f"{filename} is empty")
    if len(upload.data) > MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail=f"{filename} exceeds the 2 MB limit")
    if b"\x00" in upload.data:
        raise HTTPException(status_code=422, detail=f"{filename} contains invalid null bytes")
    try:
        decoded = upload.data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"{filename} must use UTF-8 encoding") from exc

    if suffix == ".csv":
        content, record_count = _csv_content(decoded, filename)
        source_type = "csv_dataset"
    elif suffix == ".json":
        content, record_count = _json_content(decoded, filename)
        source_type = "json_dataset"
    else:
        content = decoded.strip()
        record_count = len([line for line in content.splitlines() if line.strip()]) or 1
        source_type = "text_document"
    if not content:
        raise HTTPException(status_code=422, detail=f"{filename} contains no readable content")
    if len(content) > MAX_SOURCE_CHARACTERS:
        raise HTTPException(
            status_code=413,
            detail=f"{filename} exceeds the {MAX_SOURCE_CHARACTERS:,}-character extraction limit",
        )
    digest = hashlib.sha256(upload.data).hexdigest()[:16]
    label = " ".join(Path(filename).stem.replace("_", " ").replace("-", " ").split()) or filename
    return NousSource(
        id=f"source-{digest}",
        label=label[:200],
        source_type=source_type,
        content=content,
        filename=filename,
        record_count=record_count,
        byte_size=len(upload.data),
    )


def _csv_content(text: str, filename: str) -> tuple[str, int]:
    try:
        reader = csv.DictReader(StringIO(text, newline=""))
        if not reader.fieldnames:
            raise HTTPException(status_code=422, detail=f"{filename} needs a CSV header row")
        headers = [header.strip() for header in reader.fieldnames]
        if any(not header for header in headers) or len(headers) != len(set(headers)):
            raise HTTPException(status_code=422, detail=f"{filename} has invalid or duplicate CSV headers")
        reader.fieldnames = headers
        rows = list(reader)
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"{filename} is not valid CSV") from exc
    if not rows:
        raise HTTPException(status_code=422, detail=f"{filename} has no data rows")
    if len(rows) > MAX_CSV_ROWS:
        raise HTTPException(status_code=413, detail=f"{filename} exceeds the {MAX_CSV_ROWS:,}-row limit")
    lines: list[str] = []
    for number, row in enumerate(rows, start=2):
        if None in row or any(value is None for value in row.values()):
            raise HTTPException(status_code=422, detail=f"{filename} row {number} does not match its header")
        values = []
        for header in headers:
            value = " ".join(row[header].split())
            if len(value) > 2_000:
                raise HTTPException(status_code=422, detail=f"{filename} row {number} contains an oversized field")
            if value:
                values.append(f"{header}: {value}")
        if values:
            lines.append(" | ".join(values))
    return "\n".join(lines), len(rows)


def _json_content(text: str, filename: str) -> tuple[str, int]:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail=f"{filename} is not valid JSON") from exc
    if not isinstance(value, (dict, list)):
        raise HTTPException(status_code=422, detail=f"{filename} must contain a JSON object or array")
    record_count = len(value) if isinstance(value, list) else 1
    try:
        content = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, RecursionError) as exc:
        raise HTTPException(status_code=422, detail=f"{filename} could not be normalised") from exc
    return content, record_count
