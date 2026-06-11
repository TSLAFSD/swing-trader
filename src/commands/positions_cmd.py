"""Telegram position commands: /add /remove /positions (spec §9).

Mutations edit config/positions.yaml (single source of truth on main —
the commands workflow commits the change back). /remove records the date for
the rebuy cooldown. Every action sends a Korean Telegram confirmation.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

import yaml

from config import settings
from src.notify.telegram import send_message
from src.risk.positions import load_positions

logger = logging.getLogger(__name__)

REBUY_STATE_FILE = settings.DATA_ROOT / "state" / "rebuy.json"


def detect_market(ticker: str) -> str:
    """6-digit numeric = KR, alphabetic = US."""
    return "kr" if re.fullmatch(r"\d{6}", ticker) else "us"


def _read_yaml() -> dict:
    raw = yaml.safe_load(settings.POSITIONS_FILE.read_text(encoding="utf-8")) or {}
    raw.setdefault("positions", [])
    raw["positions"] = raw["positions"] or []
    return raw


def _write_yaml(data: dict) -> None:
    settings.POSITIONS_FILE.write_text(
        "# Owner's open positions — managed via Telegram /add /remove or by hand.\n"
        + yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _fmt(value: float, market: str) -> str:
    return f"{value:,.0f}원" if market == "kr" else f"${value:,.2f}"


def add_position(ticker: str, price: float, quantity: float) -> None:
    """/add {ticker} {price} {qty} — defaults: fixed exit, -5% stop, +15% target."""
    ticker = ticker.upper()
    market = detect_market(ticker)
    data = _read_yaml()
    if any(str(p["ticker"]).upper() == ticker for p in data["positions"]):
        send_message(f"⚠️ {ticker}은(는) 이미 보유 목록에 있습니다. 먼저 /remove 하세요.")
        return
    stop = round(price * (1 - settings.POSITION_DEFAULT_STOP_PCT / 100), 4)
    target = round(price * (1 + settings.POSITION_DEFAULT_TARGET_PCT / 100), 4)
    data["positions"].append(
        {
            "ticker": ticker, "market": market, "entry_date": str(date.today()),
            "entry_price": price, "quantity": quantity,
            "stop_loss": stop, "take_profit": target, "exit_mode": "fixed",
        }
    )
    _write_yaml(data)
    send_message(
        f"✅ 추가 완료: {ticker} ({'한국' if market == 'kr' else '미국'})\n"
        f"진입 {_fmt(price, market)} × {quantity:g}주\n"
        f"손절 {_fmt(stop, market)} (-{settings.POSITION_DEFAULT_STOP_PCT:.0f}%) · "
        f"목표 {_fmt(target, market)} (+{settings.POSITION_DEFAULT_TARGET_PCT:.0f}%)\n"
        f"다음 정규 스캔부터 청산 조건을 감시합니다."
    )


def remove_position(ticker: str) -> None:
    """/remove {ticker} — full reset; ticker rejoins the universe (+cooldown)."""
    ticker = ticker.upper()
    data = _read_yaml()
    before = len(data["positions"])
    data["positions"] = [p for p in data["positions"] if str(p["ticker"]).upper() != ticker]
    if len(data["positions"]) == before:
        send_message(f"⚠️ {ticker}은(는) 보유 목록에 없습니다. /positions 로 확인하세요.")
        return
    _write_yaml(data)
    REBUY_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(REBUY_STATE_FILE.read_text(encoding="utf-8")) if REBUY_STATE_FILE.exists() else {}
    state[ticker] = str(date.today())
    REBUY_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    cooldown = settings.REBUY_COOLDOWN_DAYS
    note = f"\n재매수 쿨다운 {cooldown}일 적용." if cooldown > 0 else ""
    send_message(f"✅ 제거 완료: {ticker} — 유니버스로 복귀하여 다시 시그널 대상이 됩니다.{note}")


def cooldown_blocked(tickers: list[str], today: date | None = None) -> set[str]:
    """Tickers still inside the rebuy cooldown window (empty when disabled)."""
    if settings.REBUY_COOLDOWN_DAYS <= 0 or not REBUY_STATE_FILE.exists():
        return set()
    today = today or date.today()
    state = json.loads(REBUY_STATE_FILE.read_text(encoding="utf-8"))
    blocked = set()
    for t in tickers:
        removed = state.get(t.upper())
        if removed and (today - date.fromisoformat(removed)).days < settings.REBUY_COOLDOWN_DAYS:
            blocked.add(t)
    return blocked


def positions_report() -> None:
    """/positions — current holdings with last stored close (Telegram only)."""
    positions = load_positions()
    if not positions:
        send_message("💼 보유 종목이 없습니다. /add {티커} {가격} {수량} 으로 추가하세요.")
        return
    from src.data.store import ParquetStore

    store = ParquetStore()
    lines = ["💼 보유 현황"]
    for p in positions:
        df = store.load(p.market, tickers=[p.ticker])
        if df.empty:
            lines.append(f"· {p.ticker}: 저장 데이터 없음 (다음 스캔 후 갱신)")
            continue
        current = float(df.sort_values("date")["close"].iloc[-1])
        pnl = (current / p.entry_price - 1) * 100
        lines.append(
            f"· {p.ticker} {pnl:+.1f}% — 현재 {_fmt(current, p.market)} "
            f"(진입 {_fmt(p.entry_price, p.market)} × {p.quantity:g})"
        )
    send_message("\n".join(lines))
