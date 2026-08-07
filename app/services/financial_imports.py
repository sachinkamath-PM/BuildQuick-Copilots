from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from datetime import date
from io import StringIO
from pathlib import Path

from fastapi import HTTPException

from app.domain.models import FinancialAccount, FinancialTransaction


MAX_CSV_BYTES = 2 * 1024 * 1024
MAX_ACCOUNT_ROWS = 500
MAX_TRANSACTION_ROWS = 10_000
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ACCOUNT_COLUMNS = (
    "id",
    "name",
    "account_type",
    "owner",
    "balance",
    "previous_balance",
    "currency",
)
TRANSACTION_COLUMNS = ("id", "account_id", "date", "merchant", "category", "amount")


@dataclass(frozen=True)
class ParsedCSV:
    filename: str
    rows: list[dict[str, str]]
    extra_columns: list[str]


def parse_accounts(data: bytes, filename: str | None) -> tuple[list[FinancialAccount], list[str], str]:
    parsed = _parse_csv(data, filename, ACCOUNT_COLUMNS, MAX_ACCOUNT_ROWS)
    accounts: list[FinancialAccount] = []
    seen: set[str] = set()
    for number, row in enumerate(parsed.rows, start=2):
        account_id = _identifier(row["id"], "account id", number)
        if account_id in seen:
            _row_error(number, f"duplicate account id '{account_id}'")
        seen.add(account_id)
        account_type = row["account_type"].strip().lower()
        if account_type not in {"bank", "investment", "loan", "property"}:
            _row_error(number, "account_type must be bank, investment, loan, or property")
        balance = _number(row["balance"], "balance", number)
        previous = _number(row["previous_balance"], "previous_balance", number)
        if account_type == "loan" and (balance > 0 or previous > 0):
            _row_error(number, "loan balances must be zero or negative")
        if account_type != "loan" and (balance < 0 or previous < 0):
            _row_error(number, "non-loan balances must be zero or positive")
        currency = row["currency"].strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            _row_error(number, "currency must be a three-letter ISO code such as INR")
        if currency != "INR":
            _row_error(number, "the current Plutus analysis supports INR accounts only")
        accounts.append(
            FinancialAccount(
                id=account_id,
                name=_text(row["name"], "name", number, 120),
                account_type=account_type,
                owner=_text(row["owner"], "owner", number, 120),
                balance=balance,
                previous_balance=previous,
                currency=currency,
            )
        )
    currencies = {item.currency for item in accounts}
    if len(currencies) > 1:
        raise HTTPException(
            status_code=422,
            detail="Accounts must use one currency; currency conversion is not inferred",
        )
    return accounts, _warnings(parsed), parsed.filename


def parse_transactions(
    data: bytes, filename: str | None
) -> tuple[list[FinancialTransaction], list[str], str]:
    parsed = _parse_csv(data, filename, TRANSACTION_COLUMNS, MAX_TRANSACTION_ROWS)
    transactions: list[FinancialTransaction] = []
    seen: set[str] = set()
    for number, row in enumerate(parsed.rows, start=2):
        transaction_id = _identifier(row["id"], "transaction id", number)
        if transaction_id in seen:
            _row_error(number, f"duplicate transaction id '{transaction_id}'")
        seen.add(transaction_id)
        account_id = _identifier(row["account_id"], "account_id", number)
        raw_date = row["date"].strip()
        try:
            parsed_date = date.fromisoformat(raw_date)
        except ValueError:
            _row_error(number, "date must be YYYY-MM-DD")
        amount = _number(row["amount"], "amount", number)
        if amount <= 0:
            _row_error(number, "amount must be greater than zero")
        transactions.append(
            FinancialTransaction(
                id=transaction_id,
                account_id=account_id,
                date=parsed_date.isoformat(),
                merchant=_text(row["merchant"], "merchant", number, 160),
                category=_text(row["category"], "category", number, 100),
                amount=amount,
            )
        )
    return transactions, _warnings(parsed), parsed.filename


def _parse_csv(
    data: bytes,
    filename: str | None,
    required_columns: tuple[str, ...],
    max_rows: int,
) -> ParsedCSV:
    safe_name = Path(filename or "records.csv").name[:255]
    if Path(safe_name).suffix.lower() != ".csv":
        raise HTTPException(status_code=415, detail="Upload a CSV file")
    if not data:
        raise HTTPException(status_code=422, detail=f"{safe_name} is empty")
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV files are limited to 2 MB")
    if b"\x00" in data:
        raise HTTPException(status_code=422, detail=f"{safe_name} contains invalid null bytes")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="CSV files must use UTF-8 encoding") from exc
    try:
        reader = csv.DictReader(StringIO(text, newline=""))
        if reader.fieldnames is None:
            raise HTTPException(status_code=422, detail=f"{safe_name} needs a header row")
        normalised = [field.strip().lower() for field in reader.fieldnames]
        if len(normalised) != len(set(normalised)):
            raise HTTPException(status_code=422, detail=f"{safe_name} contains duplicate columns")
        missing = [column for column in required_columns if column not in normalised]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"{safe_name} is missing columns: {', '.join(missing)}",
            )
        reader.fieldnames = normalised
        rows = list(reader)
    except csv.Error as exc:
        raise HTTPException(status_code=422, detail=f"{safe_name} is not valid CSV") from exc
    if not rows:
        raise HTTPException(status_code=422, detail=f"{safe_name} has no data rows")
    if len(rows) > max_rows:
        raise HTTPException(status_code=413, detail=f"{safe_name} exceeds the {max_rows:,}-row limit")
    for number, row in enumerate(rows, start=2):
        if None in row:
            _row_error(number, "contains more fields than the header")
        if any(value is None for value in row.values()):
            _row_error(number, "contains fewer fields than the header")
        if any(len(value) > 2_000 for value in row.values()):
            _row_error(number, "contains a field longer than 2,000 characters")
    extras = [column for column in normalised if column not in required_columns]
    return ParsedCSV(filename=safe_name, rows=rows, extra_columns=extras)


def _warnings(parsed: ParsedCSV) -> list[str]:
    if not parsed.extra_columns:
        return []
    return [f"Ignored extra columns in {parsed.filename}: {', '.join(parsed.extra_columns)}"]


def _identifier(value: str, label: str, row: int) -> str:
    cleaned = value.strip()
    if not _SAFE_ID.fullmatch(cleaned):
        _row_error(row, f"{label} must use 1–80 letters, numbers, hyphens, or underscores")
    return cleaned


def _text(value: str, label: str, row: int, maximum: int) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        _row_error(row, f"{label} is required")
    if len(cleaned) > maximum:
        _row_error(row, f"{label} exceeds {maximum} characters")
    return cleaned


def _number(value: str, label: str, row: int) -> float:
    try:
        number = float(value.strip().replace(",", ""))
    except ValueError:
        _row_error(row, f"{label} must be a number without a currency symbol")
    if not math.isfinite(number):
        _row_error(row, f"{label} must be finite")
    return round(number, 2)


def _row_error(row: int, message: str) -> None:
    raise HTTPException(status_code=422, detail=f"CSV row {row}: {message}")


def accounts_template() -> str:
    return (
        ",".join(ACCOUNT_COLUMNS)
        + "\naccount-bank,Family Bank,bank,Family,500000,540000,INR\n"
    )


def transactions_template() -> str:
    return (
        ",".join(TRANSACTION_COLUMNS)
        + "\ntx-001,account-bank,2026-06-15,Example Merchant,Household,2500\n"
    )
