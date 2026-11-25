from enum import Enum
from typing import List

import pandas as pd
from typeguard import typechecked


class Currency(Enum):
    # Cryptocurrencies
    BTC = "BTC"
    XMR = "XMR"
    ZCASH = "ZCASH"
    ETH = "ETH"
    WBTC = "WBTC"
    LINK = "LINK"

    # ....coins
    RVN = "RVN"

    # Commodities
    GRAMS = "GRAMS"
    LITER = "LITER"

    # "Fiat"
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"

    # Physical assets
    GOLD = "GOLD"
    SILVER = "SILVER"
    CASH = "CASH"

    @classmethod
    @typechecked
    def get_2_digit_rounded(cls) -> List["Currency"]:
        return cls.get_fiat()

    @classmethod
    @typechecked
    def get_fiat(cls) -> List["Currency"]:
        return [cls.EUR, cls.USD, cls.GBP]

    @classmethod
    @typechecked
    def get_crypto(cls) -> List["Currency"]:
        return [cls.BTC, cls.XMR, cls.ZCASH, cls.ETH, cls.WBTC, cls.LINK]

    @classmethod
    @typechecked
    def get_physical(cls) -> List["Currency"]:
        return [cls.SILVER, cls.GOLD, cls.CASH]


def base_value_of_one_unit(*, source: str, rate: float) -> float:
    """Turn a stored quote into the base-currency value of one unit.

    Frankfurter quotes fiat as units per base unit (base EUR: USD 1.16 means
    1 EUR = 1.16 USD); CoinGecko quotes crypto as base per unit (BTC 98801
    means 1 BTC = 98801 EUR).  Callers multiply amounts by the result.
    """
    if "frankfurter" in str(source):
        return 1.0 / rate
    return rate


# Function to load latest rates from CSV
def load_latest_rates(base_currency="EUR"):
    csv_path = "exchange_rates.csv"
    if not pd.io.common.file_exists(csv_path):
        return {}

    df = pd.read_csv(csv_path)
    # Drop duplicate header rows that can appear from repeated CSV appends.
    df = df[df["datetime"] != "datetime"]
    df["datetime"] = pd.to_datetime(df["datetime"])
    # Get latest per currency
    latest = df.sort_values("datetime", ascending=False).drop_duplicates(
        "currency"
    )
    rates = {
        currency: base_value_of_one_unit(source=source, rate=float(rate))
        for currency, source, rate in zip(
            latest["currency"], latest["source"], latest["rate_to_base"]
        )
    }
    # Ensure base is 1
    rates[base_currency] = 1.0
    return rates
