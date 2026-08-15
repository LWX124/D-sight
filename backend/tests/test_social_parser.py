import datetime as dt
import json

import pytest

from app.social.wechat.errors import (
    SessionExpiredError,
    TransientMpError,
    check_base_resp,
)
from app.social.wechat.parser import html_to_text, parse_appmsgpublish


def test_check_base_resp_ok():
    assert check_base_resp({"base_resp": {"ret": 0}, "x": 1}) == {"base_resp": {"ret": 0}, "x": 1}


def test_check_base_resp_session_expired():
    with pytest.raises(SessionExpiredError):
        check_base_resp({"base_resp": {"ret": 200003, "err_msg": "invalid session"}})


def test_check_base_resp_transient():
    with pytest.raises(TransientMpError):
        check_base_resp({"base_resp": {"ret": 200013, "err_msg": "freq control"}})


def test_parse_appmsgpublish_double_json():
    appmsgex = [
        {
            "aid": "111_1",
            "title": "文章A",
            "digest": "摘要A",
            "cover": "http://c/a.jpg",
            "link": "https://mp.weixin.qq.com/s/AAA",
            "create_time": 1751000000,
        },
        {
            "aid": "111_2",
            "title": "文章B",
            "digest": "",
            "cover": "",
            "link": "https://mp.weixin.qq.com/s/BBB",
            "create_time": 1751000100,
        },
    ]
    publish_info = json.dumps({"appmsgex": appmsgex})
    publish_page = json.dumps({"publish_list": [{"publish_info": publish_info}], "total_count": 2})
    data = {"base_resp": {"ret": 0}, "publish_page": publish_page}

    arts = parse_appmsgpublish(data)
    assert [a.external_id for a in arts] == ["111_1", "111_2"]
    assert arts[0].title == "文章A"
    assert arts[0].url == "https://mp.weixin.qq.com/s/AAA"
    assert arts[0].published_at == dt.datetime.fromtimestamp(1751000000, tz=dt.UTC)
    assert arts[1].digest is None  # 空串归一为 None


def test_parse_appmsgpublish_empty_list():
    data = {
        "base_resp": {"ret": 0},
        "publish_page": json.dumps({"publish_list": [], "total_count": 0}),
    }
    assert parse_appmsgpublish(data) == []


def test_check_base_resp_missing_raises_transient():
    with pytest.raises(TransientMpError) as exc_info:
        check_base_resp({"fakeid": "provider-only-secret", "x": 1})
    assert "provider-only-secret" not in str(exc_info.value)


def test_parse_appmsgpublish_missing_publish_page():
    assert parse_appmsgpublish({"base_resp": {"ret": 0}}) == []


def test_html_to_text_extracts_js_content():
    html = """
    <html><body>
      <div id="js_content"><p>第一段。</p><p>第二段。</p><img src="x"/></div>
      <script>ignore()</script>
    </body></html>
    """
    text = html_to_text(html)
    assert "第一段。" in text
    assert "第二段。" in text
    assert "ignore" not in text


def test_html_to_text_restores_plaintext_paragraphs_from_redfox_spacing():
    content = (
        "第一段正文。    第二段正文。     第三段正文。       第四段正文。              第五段正文。"
    )

    assert html_to_text(content) == (
        "第一段正文。\n\n第二段正文。\n\n第三段正文。\n\n第四段正文。\n\n第五段正文。"
    )


def test_html_to_text_keeps_two_space_plaintext_runs_inline():
    content = "正文中的  两个空格不应分段。"

    assert html_to_text(content) == "正文中的 两个空格不应分段。"


def test_html_to_text_does_not_treat_financial_angle_token_as_markup():
    content = "估值指标<PE>仍应保留。"

    assert html_to_text(content) == content


def test_html_to_text_keeps_inline_html_within_block_paragraphs():
    html = (
        '<div id="js_content">'
        "<p>这是<strong>完整</strong>的第一句。</p>"
        "<p>这是第二句<em>的重点</em>。<br>补充说明。</p>"
        "</div>"
    )

    assert html_to_text(html) == ("这是完整的第一句。\n\n这是第二句的重点。\n补充说明。")


def test_html_to_text_treats_source_indentation_as_inline_html_whitespace():
    html = """
    <div id="js_content">
      <p>
        This is
        <strong>one sentence</strong>
        with inline markup.
      </p>
      <p>第二段。</p>
    </div>
    """

    assert html_to_text(html) == "This is one sentence with inline markup.\n\n第二段。"


def test_html_to_text_plaintext_normalization_is_idempotent_and_keeps_single_newlines():
    content = "第一段。\n\n第二段第一行。\n第二段第二行。"

    normalized = html_to_text(content)

    assert normalized == content
    assert html_to_text(normalized) == normalized
