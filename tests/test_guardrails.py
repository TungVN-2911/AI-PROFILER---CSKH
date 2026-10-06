import copy

import pytest

from app.config import PROJECT_ROOT
from app.guardrails import EngagementDraft, check_entities, check_text, validate_draft
from app.intel import build_intelligence
from app.ledger import append_fact, build_ledger
from app.models import EpistemicStatus, RawProfile
from app.sources.provided import load_raw_profile

RICH = load_raw_profile(PROJECT_ROOT / "fixtures" / "profiles" / "minh_anh.json")
LEDGER = build_ledger(RICH)
# F1 name, F2 bio, F3 work, F4 education, F5-F7 interests, F8 city, F9-F11 posts, F12 alt text.

CLEAN = {
    "core_empathy_angle": {"text": "Niềm vui chạy bộ quanh Hồ Tây và những mẻ sourdough tự làm", "fact_ids": ["F9", "F10"]},
    "messages": [
        {"text": "Chào Minh Anh, chúc bạn một ngày nhẹ nhàng nhé!", "kind": "neutral", "fact_ids": ["F1"]},
        {"text": "Mình thấy bạn vừa hoàn thành 10km đầu tiên quanh Hồ Tây, chúc mừng bạn nha!", "kind": "grounded", "fact_ids": ["F9"]},
        {"text": "Bạn bắt đầu chạy bộ từ khi nào vậy?", "kind": "grounded", "fact_ids": ["F5"]},
        {"text": "Mẻ sourdough thứ 3 có vỏ giòn nghe hấp dẫn quá!", "kind": "grounded", "fact_ids": ["F10"]},
        {"text": "Bạn hay làm loại bánh nào nhất?", "kind": "grounded", "fact_ids": ["F6"]},
        {"text": "Cây trầu bà ra lá mới đúng là niềm vui nhỏ dễ thương.", "kind": "grounded", "fact_ids": ["F11"]},
        {"text": "Cuối tuần của bạn thường có gì vui không?", "kind": "neutral", "fact_ids": []},
        {"text": "Công việc thiết kế đồ họa có nhiều cảm hứng không bạn?", "kind": "grounded", "fact_ids": ["F3"]},
        {"text": "Một ly cà phê sáng có phải là cách bạn bắt đầu ngày mới không?", "kind": "grounded", "fact_ids": ["F2"]},
        {"text": "Rất vui được làm quen với bạn!", "kind": "neutral", "fact_ids": []},
    ],
    "evening_hook": {"text": "Không biết mẻ sourdough tiếp theo của bạn đã lên kế hoạch chưa?", "fact_ids": ["F10"]},
    "apparent_lifestyle": None,
}


def draft(mutate=None):
    data = copy.deepcopy(CLEAN)
    if mutate:
        mutate(data)
    return EngagementDraft.model_validate(data)


def codes(violations):
    return {v.code for v in violations}


def set_msg(i, text, kind=None, fact_ids=None):
    def mutate(d):
        d["messages"][i]["text"] = text
        if kind:
            d["messages"][i]["kind"] = kind
        if fact_ids is not None:
            d["messages"][i]["fact_ids"] = fact_ids
    return mutate


# --- Clean --------------------------------------------------------------------------------------


def test_clean_draft_has_no_violations():
    assert validate_draft(draft(), LEDGER) == []


def test_intel_lifestyle_passes_validation():
    intel = build_intelligence(LEDGER, reference_year=2026)
    d = draft(lambda d: d.update(apparent_lifestyle={"text": intel.apparent_lifestyle, "fact_ids": intel.lifestyle_fact_ids}))
    assert validate_draft(d, LEDGER) == []


def test_no_false_positive_on_fixture_vocabulary():
    for fact in LEDGER.facts:
        assert check_text(fact.statement, "fact") == [], fact.statement


# --- Citation rules -----------------------------------------------------------------------------


def test_unknown_fact_id():
    assert "UNKNOWN_FACT_ID" in codes(validate_draft(draft(set_msg(1, CLEAN["messages"][1]["text"], fact_ids=["F99"])), LEDGER))


def test_grounded_message_without_citation():
    assert "MISSING_CITATION" in codes(validate_draft(draft(set_msg(2, "Bạn bắt đầu chạy bộ từ khi nào vậy?", fact_ids=[])), LEDGER))


def test_hook_and_angle_must_cite_usable_fact():
    v = validate_draft(draft(lambda d: (d["evening_hook"].update(fact_ids=["F1"]), d["core_empathy_angle"].update(fact_ids=[]))), LEDGER)
    assert {(x.code, x.location) for x in v} >= {("MISSING_CITATION", "evening_hook"), ("MISSING_CITATION", "core_empathy_angle")}


def test_ai_vision_observation_may_ground_a_message_but_estimates_may_not():
    ledger, obs = append_fact(LEDGER, "visual_observation", "appears to show a bicycle", "vision:avatar", EpistemicStatus.INFERENCE, 0.9)
    ok = validate_draft(draft(set_msg(5, "Nhìn ảnh đại diện có vẻ bạn rất mê đạp xe!", fact_ids=[obs.id])), ledger)
    assert "NON_FACT_CITATION" not in codes(ok) and "MISSING_CITATION" not in codes(ok)
    ledger, est = append_fact(ledger, "perceived_age", "25-35", "vision:avatar:estimate", EpistemicStatus.INFERENCE, 0.9)
    bad = validate_draft(draft(set_msg(5, "Chúc bạn một ngày vui!", fact_ids=[est.id])), ledger)
    assert "NON_FACT_CITATION" in codes(bad)


def test_demographic_citation_rejected():
    profile = RawProfile.model_validate({**RICH.model_dump(mode="json"), "public_info": {**RICH.public_info.model_dump(), "birth_year": 1995}})
    ledger = build_ledger(profile)
    year_id = next(f.id for f in ledger.facts if f.category == "birth_year")
    v = validate_draft(draft(set_msg(5, "Một năm thật đáng nhớ!", fact_ids=[year_id])), ledger)
    assert "DEMOGRAPHIC_CITATION" in codes(v)


def test_neutral_message_citing_facts():
    assert "NEUTRAL_CITES_FACTS" in codes(validate_draft(draft(set_msg(0, "Chào bạn nhé!", kind="neutral", fact_ids=["F5"])), LEDGER))


def test_neutral_message_asserting_claim():
    assert "NEUTRAL_CLAIM" in codes(validate_draft(draft(set_msg(6, "Bạn thích đi biển vào cuối tuần.", kind="neutral", fact_ids=[])), LEDGER))


def test_ungrounded_number_and_entity():
    v = validate_draft(draft(set_msg(1, "Mình thấy bạn chạy 21km ở Đà Lạt, giỏi quá!", fact_ids=["F9"])), LEDGER)
    assert {"UNGROUNDED_NUMBER", "UNGROUNDED_ENTITY"} <= codes(v)


def test_too_few_grounded():
    def mutate(d):
        for m in d["messages"][1:6]:
            m.update(text=f"Chúc bạn vui vẻ lần {['một', 'hai', 'ba', 'bốn', 'năm'][d['messages'].index(m) - 1]}!", kind="neutral", fact_ids=[])
    assert "TOO_FEW_GROUNDED" in codes(validate_draft(draft(mutate), LEDGER))


def test_duplicate_message():
    assert "DUPLICATE_MESSAGE" in codes(validate_draft(draft(set_msg(9, CLEAN["messages"][0]["text"], fact_ids=["F1"])), LEDGER))


@pytest.mark.parametrize("n", [4, 11])
def test_message_count(n):
    def mutate(d):
        base = d["messages"]
        d["messages"] = [dict(base[i % len(base)], text=f"{base[i % len(base)]['text']} {'!' * (i + 1)}") for i in range(n)]
    v = validate_draft(draft(mutate), LEDGER)
    assert "MESSAGE_COUNT" in codes(v)


def test_lifestyle_must_be_labelled():
    v = validate_draft(draft(lambda d: d.update(apparent_lifestyle={"text": "Active runner", "fact_ids": ["F5"]})), LEDGER)
    assert "LIFESTYLE_LABEL" in codes(v)


# --- Zero sales / contact / presumption / sensitive ---------------------------------------------


@pytest.mark.parametrize(
    "text,code",
    [
        ("Bên mình đang có ưu đãi giảm giá cho bạn đó!", "SALES_TERM"),
        ("Bạn có muốn mua thử không?", "SALES_TERM"),
        ("Mình tư vấn miễn phí cho bạn nhé.", "SALES_TERM"),
        ("We have a great discount on our new product!", "SALES_TERM"),
        ("Only today: buy one get one.", "SALES_TERM"),
        ("Chỉ 199k thôi nè.", "PRICE"),
        ("Giá chỉ 1.500.000đ.", "PRICE"),
        ("Giảm 20% hôm nay.", "PRICE"),
        ("Xem thêm tại https://shop.example.vn nhé.", "URL"),
        ("Ghé www.example.com nha.", "URL"),
        ("Gọi mình qua 0912 345 678 nha.", "PHONE"),
        ("Liên hệ +84 912.345.678.", "PHONE"),
        ("Gửi mail cho mình: lan@example.com", "EMAIL"),
        ("Theo dõi #BrandRun2026 nhé!", "HASHTAG"),
    ],
)
def test_sales_and_contact_detectors(text, code):
    assert code in codes(check_text(text, "messages[0]"))
    assert code in codes(validate_draft(draft(set_msg(9, text, kind="neutral", fact_ids=[])), LEDGER))


@pytest.mark.parametrize(
    "text",
    [
        "Chắc bạn vừa đi làm về mệt lắm nhỉ, nghỉ ngơi chút nhé!",
        "Sau một ngày dài, mình mong bạn thư giãn với sourdough.",
        "Tối nay bạn sẽ nướng thêm sourdough đấy.",  # assertion; the question form is allowed
        "You must be tired after work, enjoy the sourdough!",
    ],
)
def test_presumption_in_hook(text):
    v = validate_draft(draft(lambda d: d["evening_hook"].update(text=text)), LEDGER)
    assert "PRESUMPTION" in {x.code for x in v if x.location == "evening_hook"}


@pytest.mark.parametrize("text", ["Là một người mẹ chắc bạn bận lắm.", "Phụ nữ hiện đại như bạn thật giỏi.", "You look like a young woman who loves running."])
def test_sensitive_terms(text):
    assert "SENSITIVE_TERM" in codes(check_text(text, "messages[0]"))


def test_sales_and_sensitive_terms_allowed_when_self_declared_in_cited_fact():
    profile = RawProfile.model_validate(
        {"facebook_url": RICH.facebook_url, "display_name": "A", "public_info": {"work": ["Thiết kế sản phẩm tại Lá Xanh"]}, "bio": "Mẹ bỉm sữa yêu bếp"}
    )
    ledger = build_ledger(profile)
    work_id = next(f.id for f in ledger.facts if f.category == "work")
    bio_id = next(f.id for f in ledger.facts if f.category == "bio")
    assert check_text("Công việc thiết kế sản phẩm có vui không?", "m", [ledger.get(work_id)]) == []
    assert check_text("Làm mẹ bỉm sữa mà vẫn mê bếp thì thật đáng nể!", "m", [ledger.get(bio_id)]) == []
    # Still forbidden without the citation.
    assert codes(check_text("Công việc thiết kế sản phẩm có vui không?", "m")) == {"SALES_TERM"}


def test_too_long_message():
    assert "TOO_LONG" in codes(check_text("a" * 401, "m"))


def test_agent_pronoun_em_is_not_a_claim_about_the_customer():
    ok = draft(set_msg(0, "Em chào chị Minh Anh, em rất vui được làm quen với chị ạ!", kind="neutral", fact_ids=["F1"]))
    assert validate_draft(ok, LEDGER) == []
    claim = draft(set_msg(6, "Chị thích đi biển vào cuối tuần.", kind="neutral", fact_ids=[]))
    assert "NEUTRAL_CLAIM" in codes(validate_draft(claim, LEDGER))


# --- Brand & product domain ---------------------------------------------------------------------


@pytest.mark.parametrize("text", ["Bên em là Dr.Bee nè chị", "Dr. Bee", "DrBee", "dr bee", "DR.BEE", "Dr-Bee", "Bác sĩ Bee", "Doctor Bee"])
def test_brand_spellings_are_blocked(text):
    assert "BRAND_MENTION" in codes(check_text(text, "m"))


def test_brand_blocked_even_when_customer_mentions_it():
    profile = RawProfile.model_validate({"facebook_url": RICH.facebook_url, "display_name": "A", "bio": "Fan cứng của Dr.Bee"})
    ledger = build_ledger(profile)
    bio = next(f for f in ledger.facts if f.category == "bio")
    assert "BRAND_MENTION" in codes(check_text("Chị là fan của Dr.Bee à?", "m", [bio]))


def test_bee_nickname_is_not_the_brand():
    assert check_text("Chào Bee, chúc ngày vui nhé!", "m") == []


@pytest.mark.parametrize(
    "text",
    ["Chị có bị rụng tóc không ạ?", "Da đầu dạo này thế nào chị?", "Dầu gội nào hợp với chị?",
     "Serum này hay lắm", "Lately hair loss is common", "Try a gentle shampoo"],
)
def test_hard_product_topics_blocked(text):
    assert "PRODUCT_TOPIC" in codes(check_text(text, "m"))


def test_hard_product_topic_blocked_even_when_cited():
    profile = RawProfile.model_validate(
        {"facebook_url": RICH.facebook_url, "display_name": "A", "public_posts": [{"text": "Dạo này rụng tóc nhiều quá"}]}
    )
    ledger = build_ledger(profile)
    post = next(f for f in ledger.facts if f.category == "post")
    assert "PRODUCT_TOPIC" in codes(check_text("Dạo này rụng tóc nhiều quá, chị ổn không?", "m", [post]))


def test_soft_product_terms_allowed_only_when_self_declared():
    profile = RawProfile.model_validate(
        {"facebook_url": RICH.facebook_url, "display_name": "A", "public_info": {"work": ["Dược sĩ tại Nhà thuốc Hòa Bình"]}}
    )
    ledger = build_ledger(profile)
    work = next(f for f in ledger.facts if f.category == "work")
    assert check_text("Công việc dược sĩ chắc nhiều điều thú vị nhỉ chị?", "m", [work]) == []
    assert "PRODUCT_TOPIC" in codes(check_text("Công việc dược sĩ chắc nhiều điều thú vị nhỉ chị?", "m"))
    assert "PRODUCT_TOPIC" in codes(check_text("Mái tóc của chị đẹp quá!", "m"))


def test_no_brand_or_product_false_positive_on_any_fixture():
    from app.config import PROJECT_ROOT as ROOT

    for path in (ROOT / "fixtures" / "profiles").glob("*.json"):
        for fact in build_ledger(load_raw_profile(path)).facts:
            assert not {v.code for v in check_text(fact.statement, "f")} & {"BRAND_MENTION", "PRODUCT_TOPIC"}, fact.statement


# --- Grounded family / work themes --------------------------------------------------------------


def _fact(category, statement, source="fixture:x"):
    from app.models import Fact

    return Fact(id="F90", category=category, statement=statement, source=source)


def test_family_topic_allowed_when_cited_fact_is_about_family():
    family_post = _fact("post", "Cuối tuần cả nhà cùng nấu cơm, các bé phụ rửa rau")
    assert check_text("Bữa cơm tối gia đình mình chắc ấm áp lắm, các bé ngoan quá!", "hook", [family_post]) == []
    assert "SENSITIVE_TERM" in codes(check_text("Các bé hôm nay đi học về có vui không chị?", "hook"))
    assert "SENSITIVE_TERM" in codes(check_text("Bữa cơm tối gia đình mình có món gì ngon?", "hook", [_fact("interest", "nấu ăn")]))


def test_work_evening_wish_allowed_only_with_a_work_fact():
    work = _fact("work", "Kế toán tại Công ty Hoa Mai")
    assert check_text("Chúc chị có phút thư giãn thật trọn vẹn sau giờ làm việc nhé!", "hook", [work]) == []
    assert "PRESUMPTION" in codes(check_text("Chúc chị có phút thư giãn thật trọn vẹn sau giờ làm việc nhé!", "hook"))
    # Mood presumptions stay forbidden even with a work fact.
    assert "PRESUMPTION" in codes(check_text("Chắc chị mệt mỏi lắm sau giờ làm việc.", "hook", [work]))


def test_post_date_from_source_is_grounded():
    post = _fact("post", "Hoàn thành 10km đầu tiên", source="fixture:public_posts[0]@2026-09-28")
    assert check_entities("Ngày 28/09 bạn chạy được 10km đầu tiên, giỏi quá!", "m", [post], None) == []
    assert codes(check_entities("Ngày 15/10 bạn chạy được 10km đầu tiên!", "m", [post], None)) == {"UNGROUNDED_NUMBER"}


# --- False positives seen in live Gemini drafts -------------------------------------------------


@pytest.mark.parametrize(
    "text,cited_work",
    [
        ("Mẻ bánh thứ 3 đã có vỏ giòn rồi!", False),          # "đ" of "đã" is not the currency
        ("Bạn là người yêu thích chạy bộ quá!", False),        # "người yêu thích" = a person who likes
        ("Tối nay bạn có định chạy bộ không?", False),         # a question, not a presumption
        ("Công việc bạn đang làm chắc nhiều sáng tạo.", True),  # grounded by the cited work fact
    ],
)
def test_live_false_positives_are_gone(text, cited_work):
    cited = [_fact("work", "Thiết kế đồ họa tại Studio Lá Xanh")] if cited_work else []
    assert check_text(text, "m", cited) == []


@pytest.mark.parametrize(
    "text,code",
    [
        ("Giá chỉ 3đ thôi", "PRICE"),
        ("Chỉ 1.500.000đ.", "PRICE"),
        ("Người yêu của bạn thật dễ thương", "SENSITIVE_TERM"),
        ("Tối nay bạn có hẹn với ai đó.", "PRESUMPTION"),
        ("Chắc hẳn bạn rất vui.", "PRESUMPTION"),
        ("Bạn đang làm gì đó?", "PRESUMPTION"),
    ],
)
def test_true_positives_still_detected(text, code):
    assert code in codes(check_text(text, "m"))


@pytest.mark.parametrize(
    "text,flagged",
    [
        ("Bạn là người yêu chạy bộ và làm bánh.", False),
        ("Một người yêu cái đẹp và sự tỉ mỉ.", False),
        ("Bạn đúng là người yêu thích chạy bộ!", False),
        ("Đi chơi cùng người yêu.", True),
        ("Người yêu của bạn thật dễ thương", True),
        ("Kể về người yêu cũ đi", True),
    ],
)
def test_nguoi_yeu_only_flagged_as_lover(text, flagged):
    assert ("SENSITIVE_TERM" in codes(check_text(text, "m"))) is flagged
