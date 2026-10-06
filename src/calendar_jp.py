import datetime as dt
import jpholiday


def is_business_day(d: dt.date) -> bool:
    if d.weekday() >= 5 or jpholiday.is_holiday(d):
        return False
    return not ((d.month, d.day) in {(12, 31), (1, 2), (1, 3)})  # 東証休業日
