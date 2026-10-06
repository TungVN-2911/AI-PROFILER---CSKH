"""Shared word lists for deterministic content checks (C-007).

Patterns use word boundaries and are matched case-insensitively on Unicode text (vi + en).
"""

from __future__ import annotations

import re

# Attributes that must never be inferred from images or written about a person:
# ethnicity, religion, health/body, sexual orientation, politics, family role/relationships,
# and appearance-based gender/age guesses (Decision D-3).
SENSITIVE_TERMS: dict[str, tuple[str, ...]] = {
    "ethnicity": (
        "asian", "caucasian", "african", "hispanic", "latino", "latina", "ethnic", "ethnicity", "race",
        "racial", "white person", "black person", "dân tộc", "sắc tộc", "chủng tộc",
    ),
    "religion": (
        "muslim", "christian", "buddhist", "catholic", "hindu", "jewish", "religious", "religion", "hijab",
        "theo đạo", "tôn giáo", "phật tử", "công giáo", "đạo hồi", "tín đồ",
    ),
    "health_body": (
        "pregnant", "pregnancy", "disabled", "disability", "illness", "sick", "overweight", "obese",
        "underweight", "wheelchair", "mang thai", "có bầu", "khuyết tật", "béo phì", "bệnh", "ốm",
    ),
    "orientation": ("gay", "lesbian", "homosexual", "bisexual", "lgbt", "lgbtq", "đồng tính", "song tính"),
    "politics": (
        "political", "politics", "communist", "democrat", "republican", "liberal", "conservative",
        "chính trị", "đảng viên",
    ),
    "family_relationship": (
        "mother", "father", "mom", "dad", "mum", "wife", "husband", "son", "daughter", "parent", "parents",
        "girlfriend", "boyfriend", "married", "spouse", "family", "mẹ", "bố", "ba của", "vợ", "chồng",
        "con trai", "con gái", "con của", "bố mẹ", "đã kết hôn", "người yêu", "gia đình",
    ),
    "gender_age_guess": (
        "man", "men", "woman", "women", "male", "female", "boy", "girl", "years old", "aged", "elderly",
        "teenager", "middle-aged", "đàn ông", "phụ nữ", "nam giới", "nữ giới", "cô gái", "chàng trai",
        "tuổi", "trung niên", "thiếu niên",
    ),
}


def _compile(terms: tuple[str, ...]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


_SENSITIVE_PATTERNS = {category: _compile(terms) for category, terms in SENSITIVE_TERMS.items()}


def find_sensitive(text: str) -> list[tuple[str, str]]:
    """Return (category, matched term) pairs for every sensitive term found in `text`."""
    hits: list[tuple[str, str]] = []
    for category, pattern in _SENSITIVE_PATTERNS.items():
        hits.extend((category, m.group(0)) for m in pattern.finditer(text))
    return hits


# --- Zero-sales (C-005) ---------------------------------------------------------------------
# Commercial vocabulary. A term is tolerated only when it appears verbatim in a cited fact
# (e.g. a bio saying "thiết kế sản phẩm"); prices, URLs, phones, e-mails and hashtags never are.
SALES_TERMS: tuple[str, ...] = (
    # en
    "buy", "buying", "purchase", "order now", "price", "prices", "pricing", "discount", "discounts", "promo",
    "promotion", "sale", "sales", "deal", "deals", "offer", "offers", "product", "products", "service package",
    "subscribe", "subscription", "register", "sign up", "free trial", "trial", "voucher", "coupon", "shipping",
    "checkout", "cart", "consultation", "consult", "quote", "investment", "insurance", "loan", "membership",
    "shop", "store", "brand", "dm me", "inbox me",
    # vi
    "mua", "mua hàng", "mua sắm", "đặt hàng", "đặt mua", "giá", "báo giá", "bảng giá", "giá cả", "giảm giá",
    "khuyến mãi", "khuyến mại", "ưu đãi", "săn sale", "sản phẩm", "dịch vụ", "gói dịch vụ", "gói cước",
    "tư vấn", "đăng ký", "đăng kí", "dùng thử", "trải nghiệm thử", "mã giảm", "miễn phí", "phí ship",
    "freeship", "giao hàng", "chốt đơn", "đơn hàng", "lên đơn", "inbox", "ib", "thanh toán", "chuyển khoản",
    "combo", "liệu trình", "khóa học", "bảo hiểm", "đầu tư", "trả góp", "hoa hồng", "cửa hàng", "hàng mới về",
    "chính hãng", "hotline", "zalo",
)

PRICE_PATTERN = re.compile(
    r"(?:\d[\d.,]*\s*(?:k(?![a-zà-ỹ])|đ|₫|vnd|vnđ|nghìn|ngàn|triệu|tr(?![a-zà-ỹ])|củ|usd|\$|%))"
    r"|(?:[$€£]\s*\d)",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(
    r"https?://|www\.|\b[\w-]+\.(?:com|vn|net|org|io|shop|store|me|ly|co|info|biz)\b", re.IGNORECASE
)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HASHTAG_PATTERN = re.compile(r"(?<![\w&])#\w+")

# --- Presumption of the customer's current situation (FR-012) ------------------------------
_PRONOUN = r"(?:bạn|anh|chị|em|cậu|bác|cô|chú)"
PRESUMPTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        rf"chắc(?: hẳn)?(?: là)? {_PRONOUN} (?:vừa|đang|đã|mới|cũng|hẳn)",
        r"chắc hẳn",
        rf"hôm nay {_PRONOUN} (?:đã|vừa|có|lại|chắc)",
        rf"{_PRONOUN} (?:đang|chắc đang) (?:mệt|bận|buồn|ở nhà|nghỉ ngơi|làm|ăn|xem|chuẩn bị)",
        rf"tối nay {_PRONOUN} (?:đang|sẽ|có|định)",
        rf"giờ này {_PRONOUN}",
        r"sau giờ làm", r"sau một ngày", r"tan làm", r"đi làm về", r"vừa về nhà", r"về đến nhà",
        r"mệt mỏi", r"căng thẳng", r"áp lực",
        r"\byou must be\b", r"\byou(?:'re| are) probably\b", r"\bafter (?:a long )?(?:day|work)\b",
        r"\blong day\b", r"\byou just got home\b", r"\btonight you\b",
    )
)


def _find_terms(pattern: re.Pattern[str], text: str) -> list[str]:
    return [m.group(0) for m in pattern.finditer(text)]


_SALES_PATTERN = _compile(SALES_TERMS)


def find_sales_terms(text: str) -> list[str]:
    return _find_terms(_SALES_PATTERN, text)


def find_presumptions(text: str) -> list[str]:
    return [m.group(0) for p in PRESUMPTION_PATTERNS for m in p.finditer(text)]
