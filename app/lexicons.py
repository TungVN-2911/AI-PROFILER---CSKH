"""Shared word lists for deterministic content checks.

Patterns use word boundaries and are matched case-insensitively on Unicode text (vi + en).
"""

from __future__ import annotations

import re

# Attributes that must never be inferred from images or written about a person:
# ethnicity, religion, health/body, sexual orientation, politics, family role/relationships,
# and appearance-based gender/age guesses.
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
        "cả nhà", "các bé", "bé nhà", "con cái", "các con", "em bé", "con nhỏ",
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
        for m in pattern.finditer(text):
            # "người yêu chạy bộ / thích / cái đẹp …" means "a person who loves …". It means "a lover" only
            # at the end of a phrase or before possessive / relationship words ("người yêu của bạn", "người yêu cũ").
            if m.group(0).casefold() == "người yêu" and not _LOVER_CONTEXT.match(text, m.end()):
                continue
            hits.append((category, m.group(0)))
    return hits


_LOVER_CONTEXT = re.compile(
    r"\s*(?:$|[.,!?;:…)\]\"”])|\s+(?:của|cũ|mới|mình|tôi|tớ|em|anh|chị|bạn|ấy|đó|này|kia|sắp cưới)(?!\w)",
    re.IGNORECASE,
)


# --- Zero-sales ---------------------------------------------------------------------------------
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
    # "đ" / "củ" are units only when no letter follows ("thứ 3 đã", "3 củ khoai" are not prices).
    r"(?:\d[\d.,]*\s*(?:k(?![a-zà-ỹ])|đ(?![a-zà-ỹ])|₫|vnd|vnđ|nghìn|ngàn|triệu|tr(?![a-zà-ỹ])|củ(?!\s*[a-zà-ỹ])|usd|\$|%))"
    r"|(?:[$€£]\s*\d)",
    re.IGNORECASE,
)
URL_PATTERN = re.compile(
    r"https?://|www\.|\b[\w-]+\.(?:com|vn|net|org|io|shop|store|me|ly|co|info|biz)\b", re.IGNORECASE
)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?84|0)(?:[\s.\-]?\d){8,10}(?!\d)")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
HASHTAG_PATTERN = re.compile(r"(?<![\w&])#\w+")

# --- Presumption of the customer's current situation ---------------------------------------------
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


# --- Brand & product domain ---------------------------------------------------------------------
# The rapport sequence must never name the brand or steer toward what it sells. Edit these lists to reuse the
# agent for another brand.
BRAND_PATTERN = re.compile(
    r"(?<!\w)(?:d\s*[.\-_]?\s*r\s*[.\-_]?\s*b\s*e\s*e|doctor\s*bee|bác\s*sĩ\s*bee)(?!\w)",
    re.IGNORECASE,
)

# Hair/scalp problems and hair-care products: never allowed, even when the customer mentions them.
PRODUCT_TOPIC_HARD: tuple[str, ...] = (
    # vi
    "rụng tóc", "tóc rụng", "gãy rụng", "mọc tóc", "kích mọc tóc", "kích thích mọc tóc", "tóc thưa", "tóc mỏng",
    "tóc yếu", "tóc gãy", "tóc khô xơ", "hói", "hói đầu", "nang tóc", "chân tóc", "da đầu", "gàu", "nấm da đầu",
    "dầu gội", "dầu xả", "gội đầu", "serum", "tinh dầu bưởi", "xịt mọc tóc", "xịt dưỡng tóc", "dưỡng tóc",
    "phục hồi tóc", "phục hồi nang tóc", "ủ tóc", "hấp tóc", "chăm sóc tóc", "sản phẩm tóc",
    # en
    "hair loss", "hair fall", "hair growth", "thinning hair", "bald", "balding", "scalp", "dandruff", "follicle",
    "follicles", "shampoo", "conditioner", "hair serum", "hair care", "haircare",
)

# Generic beauty / pharma words: allowed only when the customer wrote them in a cited fact (e.g. works as a pharmacist).
PRODUCT_TOPIC_SOFT: tuple[str, ...] = (
    "tóc", "mái tóc", "kiểu tóc", "làm đẹp", "chăm sóc da", "skincare", "mỹ phẩm", "dược mỹ phẩm", "dược phẩm",
    "dược sĩ", "điều trị", "chữa trị", "trị liệu", "cosmetic", "cosmetics", "beauty", "pharmacist",
)

_PRODUCT_HARD_PATTERN = _compile(PRODUCT_TOPIC_HARD)
_PRODUCT_SOFT_PATTERN = _compile(PRODUCT_TOPIC_SOFT)


def find_brand_mentions(text: str) -> list[str]:
    return _find_terms(BRAND_PATTERN, text)


def find_product_terms(text: str) -> tuple[list[str], list[str]]:
    """(hard terms, soft terms) found in `text`."""
    return _find_terms(_PRODUCT_HARD_PATTERN, text), _find_terms(_PRODUCT_SOFT_PATTERN, text)


def has_blocked_topic(text: str) -> bool:
    """True when `text` names the brand or a hard product-domain term (unusable in any message)."""
    return bool(find_brand_mentions(text) or find_product_terms(text)[0])
