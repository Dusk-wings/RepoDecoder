import re
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from openai import RateLimitError


class ModelFallbackCalculator:
    def _parse_duration_to_seconds(self, duration_str: str) -> float:
        """Converts strings like '86260s', '2m59.56s', or '1h12m4.2s' into total seconds."""
        total = 0.0
        for val, unit in re.findall(r"([\d.]+)(h|m|s)", duration_str.lower()):
            v = float(val)
            if unit == "h":
                total += v * 3600
            elif unit == "m":
                total += v * 60
            elif unit == "s":
                total += v
        return total

    def _seconds_until_gemini_midnight_pt(self) -> float:
        """Fallback calculation: exact seconds until 00:00 America/Los_Angeles."""
        pt = ZoneInfo("America/Los_Angeles")
        now_pt = datetime.now(pt)
        next_midnight_pt = (now_pt + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return round((next_midnight_pt - now_pt).total_seconds(), 2)

    @staticmethod
    def get_retry_details(err: RateLimitError) -> dict:
        obj = ModelFallbackCalculator()
        """
        Returns:
        {
            "limit_type": "RPD" | "RPM_OR_TPM",
            "wait_seconds": float
        }
        """
        headers = err.response.headers if getattr(err, "response", None) else {}

        # ---------------------------------------------------------
        # 1. GROQ HANDLING
        # ---------------------------------------------------------
        if "x-ratelimit-remaining-requests" in headers:
            remaining_rpd = headers.get("x-ratelimit-remaining-requests")
            is_rpd = remaining_rpd == "0"

            # Prefer 'retry-after' (already in seconds), fallback to 'x-ratelimit-reset-requests'
            if headers.get("retry-after"):
                wait_sec = float(headers["retry-after"])
            elif is_rpd and headers.get("x-ratelimit-reset-requests"):
                wait_sec = obj._parse_duration_to_seconds(headers["x-ratelimit-reset-requests"])
            elif headers.get("x-ratelimit-reset-tokens"):
                wait_sec = obj._parse_duration_to_seconds(headers["x-ratelimit-reset-tokens"])
            else:
                wait_sec = 5.0

            return {
                "limit_type": "RPD" if is_rpd else "RPM_OR_TPM",
                "wait_seconds": round(wait_sec, 2),
            }

        # ---------------------------------------------------------
        # 2. GEMINI HANDLING
        # ---------------------------------------------------------
        body = getattr(err, "body", None)
        if isinstance(body, list) and body:
            body = body[0]

        is_rpd = False
        wait_sec = None

        if isinstance(body, dict):
            error_obj = body.get("error", body)
            details = error_obj.get("details", [])

            for item in details:
                # Check if the violation is specifically Requests Per Day (RPD)
                if "QuotaFailure" in item.get("@type", ""):
                    for v in item.get("violations", []):
                        if "PerDay" in v.get("quotaId", ""):
                            is_rpd = True

                # Extract Google's exact RetryInfo.retryDelay (e.g., "86260s" or "34s")
                if "RetryInfo" in item.get("@type", ""):
                    delay_str = item.get("retryDelay", "")
                    if delay_str:
                        wait_sec = obj._parse_duration_to_seconds(delay_str)

        # Regex fallback on message text (e.g., "Please retry in 34.5s")
        if wait_sec is None:
            msg_match = re.search(r"retry in ([\d.]+)s", str(err), re.I)
            if msg_match:
                wait_sec = float(msg_match.group(1))

        # Final fallback if Gemini RPD hit but retryDelay wasn't parsed
        if wait_sec is None:
            wait_sec = obj._seconds_until_gemini_midnight_pt() if is_rpd else 600.0

        return {
            "limit_type": "RPD" if is_rpd else "RPM_OR_TPM",
            "wait_seconds": round(wait_sec, 2),
        }