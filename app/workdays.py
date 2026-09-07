"""근무일(평일이고 공휴일이 아닌 날) 계산.

신정·삼일절·어린이날·현충일·광복절·개천절·한글날·성탄절처럼 해마다 날짜가 똑같은
"고정 공휴일"은 그대로 계산하고, 설날·추석·부처님오신날처럼 음력 기준이라 해마다
날짜가 바뀌는 공휴일은 korean_lunar_calendar(한국천문연구원 기준 음력 변환)로
계산합니다. 정부가 그때그때 발표하는 대체공휴일까지는 규칙이 복잡하고 자주 바뀌어서
넣지 않았습니다.
"""

from __future__ import annotations

from datetime import date, timedelta

FIXED_HOLIDAYS_MMDD = {"01-01", "03-01", "05-05", "06-06", "08-15", "10-03", "10-09", "12-25"}

_lunar_holiday_cache: dict[int, set[str]] = {}


def _lunar_holidays_for_year(year: int) -> set[str]:
    """그 해의 설날 연휴(전날~다음날), 추석 연휴(전날~다음날), 부처님오신날을 계산합니다.
    변환 실패(라이브러리가 다루는 연도 범위를 벗어나는 등)는 조용히 빈 집합으로 넘어갑니다 —
    이 계산 하나 때문에 앱이 죽으면 안 되므로."""
    if year in _lunar_holiday_cache:
        return _lunar_holiday_cache[year]

    dates: set[str] = set()
    try:
        from korean_lunar_calendar import KoreanLunarCalendar

        cal = KoreanLunarCalendar()

        def add(lunar_month: int, lunar_day: int, span: int = 0) -> None:
            if not cal.setLunarDate(year, lunar_month, lunar_day, False):
                return
            solar = date.fromisoformat(cal.SolarIsoFormat())
            for offset in range(-span, span + 1):
                dates.add((solar + timedelta(days=offset)).isoformat())

        add(1, 1, span=1)  # 설날 연휴
        add(8, 15, span=1)  # 추석 연휴
        add(4, 8)  # 부처님오신날
    except Exception:
        dates = set()

    _lunar_holiday_cache[year] = dates
    return dates


def is_non_workday(day: date, extra_holidays: set[str] | None = None) -> bool:
    if day.weekday() >= 5:  # 5=토요일, 6=일요일
        return True
    if f"{day.month:02d}-{day.day:02d}" in FIXED_HOLIDAYS_MMDD:
        return True
    if day.isoformat() in _lunar_holidays_for_year(day.year):
        return True
    return bool(extra_holidays) and day.isoformat() in extra_holidays


def count_workdays(start: date, end: date, extra_holidays: set[str] | None = None) -> int:
    """start~end 사이(둘 다 포함) 근무일 수를 셉니다. start가 end보다 뒤여도 알아서 바꿔서 셉니다.
    extra_holidays는 사용자가 달력에서 직접 지정한 휴일(공휴일/연차) 날짜 집합입니다."""
    if start > end:
        start, end = end, start
    count = 0
    day = start
    while day <= end:
        if not is_non_workday(day, extra_holidays):
            count += 1
        day += timedelta(days=1)
    return count
