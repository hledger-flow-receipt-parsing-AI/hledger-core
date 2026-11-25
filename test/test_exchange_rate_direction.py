"""Exchange rates must all mean "value of one unit in the base currency".

Frankfurter quotes fiat the other way round (base EUR: USD 1.25 means
1 EUR = 1.25 USD), while CoinGecko quotes crypto as base per unit
(BTC 50000 means 1 BTC = 50000 EUR).  hledger-plot multiplies amounts by
these rates, so fiat came out inverted: with GBP 0.8 per EUR, GBP 10 became
EUR 8 instead of EUR 12.50.  The stored CSV keeps each API's raw quote; loading or
fetching must hand out base-per-unit values for both.
"""

from pathlib import Path
from typing import Any, Dict

import pytest

import hledger_core.Currencies.fetch_rates as fetch_rates
from hledger_core.Currency import load_latest_rates

FRANKFURTER = "https://api.frankfurter.app/latest?base=EUR"
COINGECKO = "https://api.coingecko.com/api/v3/simple/price"


def test_loaded_fiat_and_crypto_rates_are_base_per_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "exchange_rates.csv").write_text(
        "datetime,source,currency,rate_to_base\n"
        f"2025-10-28T13:00:00,{FRANKFURTER},USD,1.25\n"
        f"2025-10-28T13:00:00,{FRANKFURTER},GBP,0.8\n"
        f"2025-10-28T13:00:00,{COINGECKO},BTC,50000.0\n"
        "2025-10-28T13:00:00,Base,EUR,1.0\n"
    )
    monkeypatch.chdir(tmp_path)

    rates = load_latest_rates("EUR")

    assert rates["USD"] == pytest.approx(0.8)
    assert rates["GBP"] == pytest.approx(1.25)
    assert rates["BTC"] == pytest.approx(50000.0)
    assert rates["EUR"] == 1.0


class _Response:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


def test_fetched_fiat_and_crypto_rates_are_base_per_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(url: str, params: Any = None) -> _Response:
        if url.endswith("/currencies"):
            return _Response({"USD": "US Dollar", "GBP": "Pound"})
        if "frankfurter" in url:
            return _Response({"rates": {"USD": 1.25, "GBP": 0.8}})
        return _Response({"bitcoin": {"eur": 50000.0}})

    monkeypatch.setattr(fetch_rates.requests, "get", fake_get)

    rates, _when = fetch_rates.fetch_exchange_rates(base_currency="EUR")

    assert rates["USD"] == pytest.approx(0.8)
    assert rates["GBP"] == pytest.approx(1.25)
    assert rates["BTC"] == pytest.approx(50000.0)
    assert rates["EUR"] == 1.0
