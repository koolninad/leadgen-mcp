"""Warmup quota progression logic.

Day range → daily quota:
  1-3:   3/day
  4-7:   10/day
  8-14:  25/day
  15-21: 50/day
  22-30: 75/day
  31+:   100/day
"""


def get_quota_for_day(warmup_day: int) -> int:
    """Return the daily send quota for a given warmup day."""
    if warmup_day <= 3:
        return 3
    if warmup_day <= 7:
        return 10
    if warmup_day <= 14:
        return 25
    if warmup_day <= 21:
        return 50
    if warmup_day <= 30:
        return 75
    return 100


def should_graduate(account: dict) -> bool:
    """Check if an account should move from warming to active."""
    return (
        account["warmup_day"] >= 30
        and account["bounce_rate"] < 2.0
        and account["reputation_score"] >= 60
    )


def should_demote(account: dict) -> bool:
    """Check if an active account should be demoted to cooling."""
    return (
        account["bounce_rate"] > 5.0
        or account["reputation_score"] < 30
    )


def should_reactivate(account: dict) -> bool:
    """Check if a cooling account can be reactivated."""
    return (
        account["bounce_rate"] < 2.0
        and account["reputation_score"] >= 50
    )
