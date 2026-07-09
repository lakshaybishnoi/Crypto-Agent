from __future__ import annotations

from crypto_agent.core.models import Asset


STABLECOIN_SYMBOLS = frozenset(
    {
        "busd",
        "dai",
        "fdusd",
        "frax",
        "gusd",
        "lusd",
        "pyusd",
        "susd",
        "tusd",
        "usdc",
        "usdd",
        "usde",
        "usdp",
        "usdt",
        "usds",
        "usd1",
        "usdn",
        "ustc",
    }
)

STABLECOIN_IDS = frozenset(
    {
        "binance-usd",
        "dai",
        "first-digital-usd",
        "frax",
        "gemini-dollar",
        "liquity-usd",
        "paypal-usd",
        "susd",
        "true-usd",
        "tether",
        "usdd",
        "usde",
        "usd-coin",
        "usdp",
        "usds",
        "usual-usd",
        "terrausd",
    }
)


def is_stablecoin(asset: Asset | str) -> bool:
    if isinstance(asset, Asset):
        symbol = asset.symbol
        asset_id = asset.id
        name = asset.name
    else:
        symbol = str(asset)
        asset_id = ""
        name = ""

    normalized_symbol = symbol.strip().lower()
    normalized_id = asset_id.strip().lower()
    normalized_name = name.strip().lower()

    if normalized_symbol in STABLECOIN_SYMBOLS:
        return True
    if normalized_id in STABLECOIN_IDS:
        return True
    return "stablecoin" in normalized_name or normalized_name.endswith(" usd")
