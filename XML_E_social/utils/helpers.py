import re
from typing import List, Optional
import xml.etree.ElementTree as ET


def localname(tag: str) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.split("}", 1)[-1]


def text_or_none(elem: Optional[ET.Element]) -> Optional[str]:
    if elem is None or elem.text is None:
        return None
    value = elem.text.strip()
    return value or None


def first_text_by_localname(root: ET.Element, name: str) -> Optional[str]:
    for el in root.iter():
        if localname(el.tag) == name:
            value = text_or_none(el)
            if value is not None:
                return value
    return None


def all_elements_by_localname(root: ET.Element, name: str) -> List[ET.Element]:
    return [el for el in root.iter() if localname(el.tag) == name]


def only_digits(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\D+", "", value)


def safe_float(value: Optional[str]) -> float:
    if value is None:
        return 0.0
    value = str(value).strip()
    if not value:
        return 0.0
    value = value.replace(" ", "")
    if "," in value and "." in value:
        value = value.replace(".", "").replace(",", ".")
    else:
        value = value.replace(",", ".")
    try:
        return float(value)
    except Exception:
        return 0.0


def decimal_br(value: float) -> str:
    try:
        s = f"{float(value):,.2f}"
    except Exception:
        return ""
    return s.replace(",", "X").replace(".", ",").replace("X", ".")
