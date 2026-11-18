"""Đổi số hiển thị trên Facebook (1,2K; 56.060; 3 triệu) thành số nguyên."""
import re

# Một số có thể kèm đơn vị rút gọn; nhóm 1 là toàn bộ số và đơn vị.
NUMBER = r"(\d[\d.,]*\s*(?:triệu|nghìn|ngàn|million|thousand|tr|[kmn])?)"

MULTIPLIERS = {
    "k": 1000, "n": 1000, "nghìn": 1000, "ngàn": 1000, "thousand": 1000,
    "m": 1000000, "tr": 1000000, "triệu": 1000000, "million": 1000000,
}


def parse_count(value):
    """Ví dụ: '1,2K' -> 1200; '56.060' -> 56060; văn bản không phải số -> None.

    Số có đơn vị rút gọn là số ước lượng nên được làm tròn.
    Số không có đơn vị: dấu chấm/phẩy là dấu ngăn hàng nghìn.
    """
    if not value:
        return None

    match = re.fullmatch(NUMBER, value.strip(), re.I)
    if not match:
        return None

    number_parts = re.fullmatch(r"([\d.,]+)\s*(.*)", match.group(1))
    number_text = number_parts.group(1)
    suffix = number_parts.group(2).lower()
    multiplier = MULTIPLIERS.get(suffix, 1)

    try:
        if multiplier == 1:
            return int(re.sub(r"[.,]", "", number_text))
        return round(float(number_text.replace(",", ".")) * multiplier)
    except ValueError:
        return None
