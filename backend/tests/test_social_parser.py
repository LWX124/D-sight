import datetime as dt
import json

import pytest

from app.social.wechat.errors import (
    SessionExpiredError,
    TransientMpError,
    check_base_resp,
)
from app.social.wechat.parser import RawArticle, html_to_text, parse_appmsgpublish


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
        {"aid": "111_1", "title": "文章A", "digest": "摘要A", "cover": "http://c/a.jpg",
         "link": "https://mp.weixin.qq.com/s/AAA", "create_time": 1751000000},
        {"aid": "111_2", "title": "文章B", "digest": "", "cover": "",
         "link": "https://mp.weixin.qq.com/s/BBB", "create_time": 1751000100},
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
    data = {"base_resp": {"ret": 0}, "publish_page": json.dumps({"publish_list": [], "total_count": 0})}
    assert parse_appmsgpublish(data) == []


def test_check_base_resp_missing_raises_transient():
    with pytest.raises(TransientMpError):
        check_base_resp({"x": 1})


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
