"""
Deutsche Bank Vermögensanlage-Report PDF parser.

Extracts transactions (Umsätze) and holdings with cost basis
(Vermögensaufstellung mit Einstandskursen) from Deutsche Bank's
quarterly portfolio report PDF and returns DataFrames in the
canonical schemas defined in portfolio_sim.py.

Requires pdfplumber (not the host Python — run inside Docker):
    pip install pdfplumber

Usage:
    from pdf_parser import parse_db_pdf
    tx_df, hld_df = parse_db_pdf("/path/to/deutsche-bank-report.pdf")

See also: scripts/parse_db_pdf.py for the CLI wrapper.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from portfolio_sim import HOLDINGS_COLUMNS, TRANSACTION_COLUMNS

# pdfplumber is imported lazily inside parse_db_pdf() so that all pure-Python
# helper functions (and their unit tests) work without it installed.
# Install inside Docker: pip install pdfplumber

# ── Page-section identifiers ──────────────────────────────────────────────────

_UMSATZ_HEADER = "Umsätze vom"
_HOLDINGS_HEADER = "Einstandskursen"

# ── Transaction type mapping ──────────────────────────────────────────────────

_TX_TYPE_MAP: dict[str, str] = {
    "Kauf": "buy",
    "Verkauf": "sell",
    "Divid./Ausschütt.": "dividend",
    "Kapitaltransaktion": "split",
}

_TX_TYPES_PATTERN = "|".join(re.escape(k) for k in _TX_TYPE_MAP)

# ── Regular expressions ───────────────────────────────────────────────────────

# Primary transaction line: DD.MM.YYYY + 12-digit depot + known type
_TX_START_RE = re.compile(
    r"^\d{2}\.\d{2}\.\d{4}\s+"
    r"\d{12}\s+"
    r"(?:" + _TX_TYPES_PATTERN + r")"
    r"\s+"
)

# Full primary line capture
_TX_PRIMARY_RE = re.compile(
    r"^(\d{2}\.\d{2}\.\d{4})"  # date (Schlusstag)
    r"\s+(\d{12})\s+"  # depot number
    r"(" + _TX_TYPES_PATTERN + r")"  # Umsatzart
    r"\s+(-?\d+)\s+"  # Nominal/Stück (qty)
    r"(.+)$"  # rest: name WKN CCY [PRICE] AMOUNT
)

# ISIN: ISO 6166 — 2-letter country + 10 alphanumeric
_ISIN_RE = re.compile(r"\b([A-Z]{2}[A-Z0-9]{10})\b")

# German decimal number (optional thousands dots, mandatory comma decimal,
# optional annotation letter in parens)
_GERMAN_NUM_RE = re.compile(r"[-]?[\d\.]+,\d+(?:\([a-z]\))?")

# Holdings section: skip these header/footer patterns
_HOLDINGS_SKIP_RE = re.compile(
    r"^(?:Aktien|Anleihen|Fonds|ETF|Rohstoffe|Geldmarkt|Gesamtsumme"
    r"|Bitte|Depot|Erstellt|BittebeachtenSie|\d+/\d+|146713)"
)

# Holdings primary line: starts with a positive integer (share count)
_HLD_START_RE = re.compile(r"^\d+\s+\S")

# Holdings ISIN line: date then directly ISIN (no depot prefix)
_HLD_ISIN_LINE_RE = re.compile(
    r"^(\d{2}\.\d{2}\.\d{4})\s+"  # last booking date
    r"([A-Z]{2}[A-Z0-9]{10})\s+"  # ISIN
    r"([-\d\.,]+)\s+"  # gain_pct
    r"([\d\.,]+)"  # accrued interest
)

# Fast date-anchored check used inside _extract_holdings to avoid false-positive
# ISIN matches in company names (e.g. "ASMLHOLDINGN" looks like an ISIN to the
# generic _has_isin check).
_HLD_ISIN_LINE_QUICK_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}\s+[A-Z]{2}[A-Z0-9]{10}")


# ── Utility functions ─────────────────────────────────────────────────────────


def _parse_german_number(s: str) -> float:
    """
    Parse a German-format decimal number to float.

    Examples:
        "8.448,72"      → 8448.72
        "415,20000"     → 415.2
        "-2.117,87"     → -2117.87
        "140,23518(a)"  → 140.23518  (annotation stripped)
    """
    # Strip annotation suffixes like "(a)", "(b)"
    s = re.sub(r"\([a-z]\)", "", s).strip()
    # Remove thousands separator (dot), replace decimal comma with dot
    return float(s.replace(".", "").replace(",", "."))


def _parse_date(s: str) -> str:
    """Convert DD.MM.YYYY to ISO 8601 YYYY-MM-DD."""
    return datetime.strptime(s, "%d.%m.%Y").strftime("%Y-%m-%d")


def _jurisdiction_from_isin(isin: str) -> str:
    """Return the 2-letter ISO country code prefix of an ISIN."""
    return isin[:2] if isin and len(isin) >= 2 else ""


# ── Line classifiers ──────────────────────────────────────────────────────────


def _is_tx_start_line(line: str) -> bool:
    """Return True if the line is the start of a transaction block."""
    return bool(_TX_START_RE.match(line))


def _has_isin(line: str) -> bool:
    """Return True if the line contains a 12-character ISIN."""
    return bool(_ISIN_RE.search(line))


# ── ISIN line parser ──────────────────────────────────────────────────────────


def _parse_isin_line(line: str) -> dict[str, Any]:
    """
    Extract ISIN and optional FX rate from a transaction ISIN/settlement line.

    Formats observed:
        "DD.MM.YYYY 000000000000EUR <ISIN> EUR"           EUR security, no FX rate
        "DD.MM.YYYY 000000000000USD <ISIN> 1,16980 EUR"  non-EUR, has FX rate
        "DD.MM.YYYY <ISIN> EUR"                          Kapitaltransaktion (no depot)

    FX rate (Devisenkurs): units of non-EUR currency per 1 EUR.
    Consistent with ECB OBS_VALUE convention.
    """
    isin_match = _ISIN_RE.search(line)
    isin = isin_match.group(1) if isin_match else ""

    fx_rate: float | None = None
    if isin_match:
        after_isin = line[isin_match.end() :]
        fx_match = re.search(r"([\d]+,[\d]+)\s+[A-Z]{3}", after_isin)
        if fx_match:
            fx_rate = _parse_german_number(fx_match.group(1))

    return {"isin": isin, "fx_rate": fx_rate}


# ── Primary-line tokeniser ────────────────────────────────────────────────────


def _tokenise_rest(rest: str, tx_type_raw: str) -> dict[str, Any]:
    """
    Parse the trailing part of a primary transaction line (everything after qty).

    Trailing layout (right to left):
        buy / sell / Kapitaltransaktion:  ... NAME WKN CCY PRICE AMOUNT
        Divid./Ausschütt.:                ... NAME WKN CCY AMOUNT
    """
    tokens = rest.split()
    is_dividend = tx_type_raw == "Divid./Ausschütt."

    if is_dividend:
        # Pop: AMOUNT CCY WKN from right
        amount_str = tokens.pop()
        currency = tokens.pop()
        wkn = tokens.pop()
        price = 0.0
        amount = abs(_parse_german_number(amount_str))
    else:
        # Pop: AMOUNT PRICE CCY WKN from right
        amount_str = tokens.pop()
        price_str = tokens.pop()
        currency = tokens.pop()
        wkn = tokens.pop()
        price = _parse_german_number(price_str)
        amount = abs(_parse_german_number(amount_str))

    name_fragment = " ".join(tokens)
    return {
        "name_fragment": name_fragment,
        "wkn": wkn,
        "currency": currency,
        "price": price,
        "amount": amount,
    }


# ── Transaction block parser ──────────────────────────────────────────────────


def _parse_tx_block(block: list[str]) -> dict[str, Any] | None:
    """
    Parse a transaction text block (2–3 lines) into a raw record dict.

    Block structure:
        block[0]        — primary line: DATE DEPOT TYPE QTY NAME_PART1 WKN CCY [PRICE] AMOUNT
        block[1..n-2]   — optional name continuation lines
        block[-1]       — ISIN/settlement line

    For Kapitaltransaktion (split), the raw new_shares count is stored in
    ``_new_shares`` and ``quantity`` is left as 0.0. Call ``_derive_split_ratios``
    after collecting all raw records to compute the actual ratio.

    Returns None if the block cannot be parsed.
    """
    if len(block) < 2:
        return None

    primary = block[0]
    isin_line = block[-1]
    continuation_lines = block[1:-1]

    # Parse primary line
    m = _TX_PRIMARY_RE.match(primary)
    if not m:
        return None

    date_raw, depot, type_raw, qty_raw, rest = m.groups()
    date = _parse_date(date_raw)
    tx_type = _TX_TYPE_MAP[type_raw]
    qty_signed = int(qty_raw)

    try:
        fields = _tokenise_rest(rest, type_raw)
    except (IndexError, ValueError):
        return None

    # Reconstruct full asset name from primary fragment + continuations
    name_parts = [fields["name_fragment"]] + continuation_lines
    asset_name = " ".join(p.strip() for p in name_parts if p.strip())

    # Parse ISIN line
    isin_info = _parse_isin_line(isin_line)
    isin = isin_info["isin"]

    # Canonical quantity: abs for buy/sell; 0 for dividends; raw for split
    quantity = 0.0 if tx_type == "dividend" else float(abs(qty_signed))

    new_shares: float | None = None
    if tx_type == "split":
        new_shares = quantity
        quantity = 0.0  # ratio filled in by _derive_split_ratios

    return {
        "date": date,
        "isin": isin,
        "wkn": fields["wkn"],
        "asset_name": asset_name,
        "transaction_type": tx_type,
        "quantity": quantity,
        "price": fields["price"],
        "currency": fields["currency"],
        "amount": fields["amount"],
        "fees": 0.0,
        "tax_withheld": 0.0,
        "jurisdiction": _jurisdiction_from_isin(isin),
        "_new_shares": new_shares,  # internal; removed before output
    }


# ── Split ratio derivation ────────────────────────────────────────────────────


def _derive_split_ratios(raw_txns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Post-process raw transaction records to replace new_shares with split ratio.

    The Deutsche Bank PDF stores the number of new shares added by a split
    (e.g. 342 new shares for a 10-for-1 split on 38 existing shares). This function
    replays the transaction stream chronologically, tracks running share
    counts per ISIN, and computes ratio = (existing + new) / existing.

    After derivation, ``_new_shares`` is removed from all records.
    """
    sorted_txns = sorted(raw_txns, key=lambda r: r["date"])
    running: dict[str, float] = {}  # isin → current shares

    for rec in sorted_txns:
        isin = rec["isin"]
        tx_type = rec["transaction_type"]

        if tx_type == "buy":
            running[isin] = running.get(isin, 0.0) + rec["quantity"]
        elif tx_type == "sell":
            running[isin] = running.get(isin, 0.0) - rec["quantity"]
        elif tx_type == "split":
            new_shares = rec.get("_new_shares") or 0.0
            existing = running.get(isin, 0.0)
            if existing > 0 and new_shares > 0:
                ratio = (existing + new_shares) / existing
                rec["quantity"] = round(ratio, 6)
                running[isin] = existing + new_shares
            # If existing == 0 (split before any tracked buy), leave quantity=0

    # Strip internal field from all records
    for rec in sorted_txns:
        rec.pop("_new_shares", None)

    return sorted_txns


# ── Page-level collectors ─────────────────────────────────────────────────────


def _collect_tx_blocks(lines: list[str]) -> list[list[str]]:
    """
    Group text lines from a transaction page into per-transaction blocks.

    A block starts when a line matches _TX_START_RE.
    A block ends when a line containing an ISIN is found (inclusive).
    """
    blocks: list[list[str]] = []
    current: list[str] = []

    for line in lines:
        if _is_tx_start_line(line):
            if current:
                # Previous block was unclosed (shouldn't happen) — discard
                pass
            current = [line]
        elif _has_isin(line) and current:
            current.append(line)
            blocks.append(current)
            current = []
        elif current:
            current.append(line)  # name continuation

    return blocks


def _extract_page_body(page: Any) -> list[str]:
    """
    Extract non-empty text lines from a page, stripping header and footer.

    Deutsche Bank pages have 3 header lines and 4 footer lines.
    """
    text = page.extract_text() or ""
    all_lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    # Skip first 3 (title, section, column headers) and last 4 (legal footer)
    return all_lines[3:-4] if len(all_lines) > 7 else []


# ── Transaction extractor ─────────────────────────────────────────────────────


def _extract_transactions(pdf: Any) -> list[dict[str, Any]]:
    """
    Extract all transaction records from the Umsätze pages of the PDF.

    Returns a list of raw record dicts (before split-ratio derivation).
    """
    raw: list[dict[str, Any]] = []

    for page in pdf.pages:
        text = page.extract_text() or ""
        if _UMSATZ_HEADER not in text:
            continue

        body = _extract_page_body(page)
        blocks = _collect_tx_blocks(body)

        for block in blocks:
            rec = _parse_tx_block(block)
            if rec is not None:
                raw.append(rec)

    return _derive_split_ratios(raw)


# ── Holdings extractor ────────────────────────────────────────────────────────


def _parse_holdings_block(block: list[str], report_date: str) -> dict[str, Any] | None:
    """
    Parse a holdings-with-cost-basis text block into a record dict.

    Block structure:
        block[0]        — primary: QTY NAME_PART1 WKN COST_BASIS CCY CURRENT_PRICE GAIN MV PCT
        block[1..n-2]   — optional name continuation
        block[-1]       — ISIN line: LAST_BOOKING_DATE ISIN GAIN_PCT ACCRUED

    The primary line has 4 numeric trailing fields (cost_basis, current_price,
    gain_eur, market_value_eur; gain_pct is on the ISIN line).
    """
    if len(block) < 2:
        return None

    primary = block[0]
    isin_line = block[-1]
    continuation_lines = block[1:-1]

    # Parse ISIN line first
    hld_m = _HLD_ISIN_LINE_RE.match(isin_line)
    if not hld_m:
        # Try simpler match: just date + ISIN (no gain_pct / accrued columns)
        simple_m = re.match(r"^(\d{2}\.\d{2}\.\d{4})\s+([A-Z]{2}[A-Z0-9]{10})", isin_line)
        if not simple_m:
            return None
        isin = simple_m.group(2)
    else:
        isin = hld_m.group(2)

    # Parse primary line tokens right-to-left
    # Trailing: WKN COST_BASIS CCY CURRENT_PRICE GAIN_EUR MARKET_VALUE PCT
    tokens = primary.split()
    try:
        pct_str = tokens.pop()  # noqa: F841 — percentage, not stored
        market_value_str = tokens.pop()
        gain_eur_str = tokens.pop()  # noqa: F841 — gain_eur, not stored in canonical schema
        current_price_str = tokens.pop()
        currency = tokens.pop()
        cost_basis_str = tokens.pop()
        wkn = tokens.pop()
        qty_str = tokens[0]  # first token is quantity
        name_parts = tokens[1:]  # remaining are name fragment
    except IndexError:
        return None

    try:
        quantity = float(qty_str)
        cost_basis = _parse_german_number(cost_basis_str)
        current_price = _parse_german_number(current_price_str)
        market_value = _parse_german_number(market_value_str)
    except (ValueError, AttributeError):
        return None

    # Reconstruct asset name
    name_fragment = " ".join(name_parts)
    asset_name = " ".join([name_fragment] + [c.strip() for c in continuation_lines if c.strip()])

    return {
        "date": report_date,
        "isin": isin,
        "wkn": wkn,
        "asset_name": asset_name,
        "quantity": quantity,
        "price": current_price,
        "currency": currency,
        "market_value": market_value,
        "jurisdiction": _jurisdiction_from_isin(isin),
        "cost_basis_eur": cost_basis,  # extra column — outside canonical schema
    }


def _extract_report_date(pdf: Any) -> str:
    """
    Extract the report creation date from the footer of the first page.

    Falls back to today's date if not found.
    """
    text = pdf.pages[0].extract_text() or ""
    m = re.search(r"Erstelltam(\d{2}\.\d{2}\.\d{4})", text.replace(" ", ""))
    if m:
        return _parse_date(m.group(1))
    from datetime import date

    return date.today().isoformat()


def _extract_holdings(pdf: Any, report_date: str) -> list[dict[str, Any]]:
    """
    Extract holdings with cost basis from the Vermögensaufstellung pages.
    """
    records: list[dict[str, Any]] = []

    for page in pdf.pages:
        text = page.extract_text() or ""
        if _HOLDINGS_HEADER not in text:
            continue

        body = _extract_page_body(page)

        # Collect holdings blocks: starts with integer qty, ends with ISIN line
        current: list[str] = []
        for line in body:
            # Skip section headers and totals
            if _HOLDINGS_SKIP_RE.match(line):
                if current:
                    current = []
                continue

            if _HLD_START_RE.match(line) and not _HLD_ISIN_LINE_QUICK_RE.match(line):
                if current:
                    current = []
                current = [line]
            elif _HLD_ISIN_LINE_QUICK_RE.match(line) and current:
                current.append(line)
                rec = _parse_holdings_block(current, report_date)
                if rec is not None:
                    records.append(rec)
                current = []
            elif current:
                current.append(line)  # name continuation

    return records


# ── Public API ────────────────────────────────────────────────────────────────


def parse_db_pdf(pdf_path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Parse a Deutsche Bank Vermögensanlage-Report PDF.

    Returns:
        (tx_df, hld_df) — two DataFrames:

        tx_df:  Canonical transaction schema (TRANSACTION_COLUMNS).
                Split rows have ``quantity`` set to the derived ratio
                (e.g. 10.0 for a 10-for-1 split).
                fees and tax_withheld are 0.0 — not reported in this format.

        hld_df: Canonical holdings schema (HOLDINGS_COLUMNS) plus an extra
                ``cost_basis_eur`` column (Einstandskurs per share) which can
                be used to initialise lot-ledger entries directly.

    Raises:
        ImportError if pdfplumber is not installed.
        FileNotFoundError if the PDF path does not exist.
        ValueError if no transaction or holdings pages are found.
    """
    try:
        import pdfplumber  # noqa: PLC0415 — lazy import to keep module loadable without pdfplumber
    except ImportError as exc:
        raise ImportError(
            "pdfplumber is required for PDF parsing: pip install pdfplumber  "
            "(run inside Docker, not the host Python)"
        ) from exc

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    with pdfplumber.open(pdf_path) as pdf:
        report_date = _extract_report_date(pdf)
        tx_records = _extract_transactions(pdf)
        hld_records = _extract_holdings(pdf, report_date)

    if not tx_records:
        raise ValueError(
            f"No transactions found in {pdf_path}. Is this a Deutsche Bank Umsätze report?"
        )

    # Build transactions DataFrame
    tx_rows = []
    for rec in tx_records:
        tx_rows.append(
            {
                col: rec.get(
                    col,
                    "" if col in ("isin", "wkn", "asset_name", "currency", "jurisdiction") else 0.0,
                )
                for col in TRANSACTION_COLUMNS
            }
        )
    tx_df = pd.DataFrame(tx_rows, columns=TRANSACTION_COLUMNS)

    # Build holdings DataFrame (canonical columns + cost_basis_eur)
    hld_rows = []
    for rec in hld_records:
        row = {
            col: rec.get(
                col, "" if col in ("isin", "wkn", "asset_name", "currency", "jurisdiction") else 0.0
            )
            for col in HOLDINGS_COLUMNS
        }
        row["cost_basis_eur"] = rec.get("cost_basis_eur", 0.0)
        hld_rows.append(row)
    hld_df = pd.DataFrame(hld_rows, columns=HOLDINGS_COLUMNS + ["cost_basis_eur"])

    return tx_df, hld_df
