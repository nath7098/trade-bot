from datetime import UTC, datetime

import pytest

from tradebot.config import Timeframe
from tradebot.data.calendar import last_completed_bar

D = Timeframe.DAY


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        # Mercredi 10 janv. 2024, 18h UTC = 13h New York : séance en cours -> veille.
        (datetime(2024, 1, 10, 18, tzinfo=UTC), datetime(2024, 1, 9, 5, tzinfo=UTC)),
        # Même jour, 21h30 UTC = 16h30 New York : séance close -> ce jour.
        (datetime(2024, 1, 10, 21, 30, tzinfo=UTC), datetime(2024, 1, 10, 5, tzinfo=UTC)),
        # Samedi -> vendredi.
        (datetime(2024, 1, 13, 12, tzinfo=UTC), datetime(2024, 1, 12, 5, tzinfo=UTC)),
        # Lendemain de Noël avant l'ouverture -> 24 déc. (séance courte, close 13h).
        (datetime(2024, 12, 26, 12, tzinfo=UTC), datetime(2024, 12, 24, 5, tzinfo=UTC)),
        # Été (UTC-4) : minuit New York = 4h UTC.
        (datetime(2024, 7, 2, 12, tzinfo=UTC), datetime(2024, 7, 1, 4, tzinfo=UTC)),
    ],
)
def test_last_completed_daily_bar(now: datetime, expected: datetime) -> None:
    assert last_completed_bar(D, now) == expected


def test_last_completed_hourly_bar() -> None:
    now = datetime(2024, 1, 10, 15, 20, tzinfo=UTC)
    assert last_completed_bar(Timeframe.HOUR, now) == datetime(2024, 1, 10, 14, tzinfo=UTC)
