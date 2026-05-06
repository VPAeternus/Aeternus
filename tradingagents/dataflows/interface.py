import os
from typing import Annotated

# Import from vendor-specific modules
from .local import get_YFin_data, get_finnhub_news, get_finnhub_company_insider_sentiment, get_finnhub_company_insider_transactions, get_simfin_balance_sheet, get_simfin_cashflow, get_simfin_income_statements
from .y_finance import get_YFin_data_online, get_stock_stats_indicators_window, get_balance_sheet as get_yfinance_balance_sheet, get_cashflow as get_yfinance_cashflow, get_income_statement as get_yfinance_income_statement, get_insider_transactions as get_yfinance_insider_transactions
from .google import get_google_news
from .alpha_vantage import (
    get_stock as get_alpha_vantage_stock,
    get_indicator as get_alpha_vantage_indicator,
    get_insider_transactions as get_alpha_vantage_insider_transactions,
    get_news as get_alpha_vantage_news,
    get_global_news as get_alpha_vantage_global_news
)
from .alpha_vantage_common import AlphaVantageRateLimitError

# Configuration and routing logic
from .config import get_config

# Tools organized by category
TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV stock price data",
        "tools": [
            "get_stock_data"
        ]
    },
    "technical_indicators": {
        "description": "Technical analysis indicators",
        "tools": [
            "get_indicators"
        ]
    },
    "news_data": {
        "description": "News (public/insiders, original/processed)",
        "tools": [
            "get_news",
            "get_global_news",
            "get_insider_sentiment",
            "get_insider_transactions",
        ]
    }
}

VENDOR_LIST = [
    "local",
    "yfinance",
    "google",
]

# Vendors that produced non-retryable errors in this process are skipped for the same method.
_DISABLED_VENDOR_METHODS = set()

# Process-level response cache: (method, args, kwargs_tuple) → result
# Prevents duplicate API calls for the same data within a process run.
_VENDOR_RESPONSE_CACHE: dict = {}

# Mapping of methods to their vendor-specific implementations
VENDOR_METHODS = {
    # core_stock_apis
    "get_stock_data": {
        "alpha_vantage": get_alpha_vantage_stock,
        "yfinance": get_YFin_data_online,
        "local": get_YFin_data,
    },
    # technical_indicators
    "get_indicators": {
        "alpha_vantage": get_alpha_vantage_indicator,
        "yfinance": get_stock_stats_indicators_window,
        "local": get_stock_stats_indicators_window
    },
    # news_data
    "get_news": {
        "alpha_vantage": get_alpha_vantage_news,
        "google": get_google_news,
        # Keep lightweight network source first to reduce repeated local file errors.
        "local": [get_google_news, get_finnhub_news],
    },
    "get_global_news": {
        "alpha_vantage": get_alpha_vantage_global_news,
    },
    "get_insider_sentiment": {
        "local": get_finnhub_company_insider_sentiment
    },
    "get_insider_transactions": {
        "alpha_vantage": get_alpha_vantage_insider_transactions,
        "yfinance": get_yfinance_insider_transactions,
        "local": get_finnhub_company_insider_transactions,
    },
}


def _is_valid_key(key: str) -> bool:
    if not key:
        return False
    return not (key.startswith("your_") or "your_" in key)


def _backend_api_key_available() -> bool:
    cfg = get_config()
    backend_url = str(cfg.get("backend_url", "")).lower()
    if "x.ai" in backend_url:
        return _is_valid_key(os.environ.get("XAI_API_KEY", ""))
    if "minimaxi" in backend_url or "minimax" in backend_url:
        return _is_valid_key(os.environ.get("MINIMAX_API_KEY", ""))
    if "google" in backend_url:
        return _is_valid_key(os.environ.get("GOOGLE_API_KEY", ""))
    if "anthropic" in backend_url:
        return _is_valid_key(os.environ.get("ANTHROPIC_API_KEY", ""))
    return _is_valid_key(os.environ.get("OPENAI_API_KEY", ""))


def _vendor_precheck(vendor: str) -> str:
    return ""


def _is_non_retryable_vendor_error(vendor: str, err: Exception) -> bool:
    if _is_rate_limited_error(err):
        # Treat provider throttling as non-retryable for this process run.
        # This prevents repeatedly hammering the same vendor for every symbol.
        return True

    return False


def _is_rate_limited_error(err: Exception) -> bool:
    status = getattr(err, "status_code", None)
    if status == 429:
        return True

    response = getattr(err, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True

    msg = str(err).lower()
    rate_limit_markers = (
        "429",
        "too many requests",
        "rate limit",
        "retry limit",
        "ratelimit",
        "creditsdepleted",
    )
    return any(marker in msg for marker in rate_limit_markers)

def get_category_for_method(method: str) -> str:
    """Get the category that contains the specified method."""
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")

def get_vendor(category: str, method: str = None) -> str:
    """Get the configured vendor for a data category or specific tool method.
    Tool-level configuration takes precedence over category-level.
    """
    config = get_config()

    # Check tool-level configuration first (if method provided)
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]

    # Fall back to category-level configuration
    return config.get("data_vendors", {}).get(category, "default")

def route_to_vendor(method: str, *args, **kwargs):
    """Route method calls to appropriate vendor implementation with fallback support."""
    _cache_key = (method, args, tuple(sorted(kwargs.items())))
    if _cache_key in _VENDOR_RESPONSE_CACHE:
        print(f"CACHE_HIT: {method} args={args[:1]} (process-level cache)")
        return _VENDOR_RESPONSE_CACHE[_cache_key]
    category = get_category_for_method(method)
    vendor_config = get_vendor(category, method)

    # Handle comma-separated vendors
    primary_vendors = [v.strip() for v in vendor_config.split(',')]

    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")

    # Get all available vendors for this method for fallback
    all_available_vendors = list(VENDOR_METHODS[method].keys())
    
    # Create fallback vendor list: primary vendors first, then remaining vendors as fallbacks
    fallback_vendors = primary_vendors.copy()
    for vendor in all_available_vendors:
        if vendor not in fallback_vendors:
            fallback_vendors.append(vendor)

    # Debug: Print fallback ordering
    primary_str = " → ".join(primary_vendors)
    fallback_str = " → ".join(fallback_vendors)
    print(f"DEBUG: {method} - Primary: [{primary_str}] | Full fallback order: [{fallback_str}]")

    # Track results and execution state
    results = []
    vendor_attempt_count = 0
    any_primary_vendor_attempted = False
    successful_vendor = None

    for vendor in fallback_vendors:
        if (method, vendor) in _DISABLED_VENDOR_METHODS:
            print(f"INFO: Skipping vendor '{vendor}' for '{method}' (disabled for this process)")
            continue

        if vendor not in VENDOR_METHODS[method]:
            if vendor in primary_vendors:
                print(f"INFO: Vendor '{vendor}' not supported for method '{method}', falling back to next vendor")
            continue

        precheck_reason = _vendor_precheck(vendor)
        if precheck_reason:
            print(f"INFO: Skipping vendor '{vendor}' for '{method}': {precheck_reason}")
            continue

        vendor_impl = VENDOR_METHODS[method][vendor]
        is_primary_vendor = vendor in primary_vendors
        vendor_attempt_count += 1

        # Track if we attempted any primary vendor
        if is_primary_vendor:
            any_primary_vendor_attempted = True

        # Debug: Print current attempt
        vendor_type = "PRIMARY" if is_primary_vendor else "FALLBACK"
        print(f"DEBUG: Attempting {vendor_type} vendor '{vendor}' for {method} (attempt #{vendor_attempt_count})")

        # Handle list of methods for a vendor
        if isinstance(vendor_impl, list):
            vendor_methods = [(impl, vendor) for impl in vendor_impl]
            print(f"DEBUG: Vendor '{vendor}' has multiple implementations: {len(vendor_methods)} functions")
        else:
            vendor_methods = [(vendor_impl, vendor)]

        # Run methods for this vendor
        vendor_results = []
        for impl_func, vendor_name in vendor_methods:
            try:
                print(f"DEBUG: Calling {impl_func.__name__} from vendor '{vendor_name}'...")
                result = impl_func(*args, **kwargs)
                vendor_results.append(result)
                print(f"SUCCESS: {impl_func.__name__} from vendor '{vendor_name}' completed successfully")
                    
            except AlphaVantageRateLimitError as e:
                if vendor == "alpha_vantage":
                    print(f"RATE_LIMIT: Alpha Vantage rate limit exceeded, falling back to next available vendor")
                    print(f"DEBUG: Rate limit details: {e}")
                # Continue to next vendor for fallback
                continue
            except Exception as e:
                # Log error but continue with other implementations
                print(f"FAILED: {impl_func.__name__} from vendor '{vendor_name}' failed: {e}")
                if _is_rate_limited_error(e):
                    print(
                        f"RATE_LIMIT: Vendor '{vendor}' is rate-limited for '{method}', "
                        "disabling for the rest of this run"
                    )
                if _is_non_retryable_vendor_error(vendor, e):
                    _DISABLED_VENDOR_METHODS.add((method, vendor))
                    print(
                        f"INFO: Disabling vendor '{vendor}' for method '{method}' "
                        f"for this process due to non-retryable error"
                    )
                continue

        # Add this vendor's results
        if vendor_results:
            results.extend(vendor_results)
            successful_vendor = vendor
            result_summary = f"Got {len(vendor_results)} result(s)"
            print(f"SUCCESS: Vendor '{vendor}' succeeded - {result_summary}")
            
            # Stopping logic: Stop after first successful vendor for single-vendor configs
            # Multiple vendor configs (comma-separated) may want to collect from multiple sources
            if len(primary_vendors) == 1:
                print(f"DEBUG: Stopping after successful vendor '{vendor}' (single-vendor config)")
                break
        else:
            print(f"FAILED: Vendor '{vendor}' produced no results")

    # Final result summary
    if not results:
        print(f"FAILURE: All {vendor_attempt_count} vendor attempts failed for method '{method}'")
        raise RuntimeError(f"All vendor implementations failed for method '{method}'")
    else:
        print(f"FINAL: Method '{method}' completed with {len(results)} result(s) from {vendor_attempt_count} vendor attempt(s)")

    # Store in process-level cache before returning
    _final = results[0] if len(results) == 1 else '\n'.join(str(r) for r in results)
    _VENDOR_RESPONSE_CACHE[_cache_key] = _final
    return _final
