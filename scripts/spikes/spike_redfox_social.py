"""RedFox 社媒内容采集 spike：验证字段覆盖率和金融聚合接口可用性。

基于浏览 https://redfox.hk/apis 得到的真实 API 结构：

BASE URL: https://redfox.hk
认证方式: 请求头 REDFOX_API_KEY 或 X-API-KEY
所有接口均为 POST

已确认的端点路径：
  公众号: /story/api/gzhData/searchUser, /story/api/gzhData/queryWorkList, ...
  小红书: /story/api/xhsUser/searchUser, /story/api/xhsUser/searchArticle, ...
  B站:   /story/api/bili/data/accountSearch, /story/api/bili/data/accountWorkList, ...
  无金融聚合榜接口。

使用方式：
  REDFOX_API_KEY=xxx python3 scripts/spikes/spike_redfox_social.py
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import httpx
except ImportError:
    print("ERROR: httpx 未安装，运行: pip install httpx")
    sys.exit(1)

API_KEY = os.getenv("REDFOX_API_KEY", "")
BASE_URL = "https://redfox.hk"

if not API_KEY:
    print("ERROR: 请设置 REDFOX_API_KEY 环境变量")
    sys.exit(1)

HEADERS = {
    "REDFOX_API_KEY": API_KEY,
    "Content-Type": "application/json",
}

call_log = []


def api_call(path: str, body: dict = None) -> dict:
    url = f"{BASE_URL}{path}"
    start = time.monotonic()
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=HEADERS, json=body or {})
            elapsed_ms = int((time.monotonic() - start) * 1000)
            record = {"method": "POST", "path": path, "body": body,
                      "status": resp.status_code, "elapsed_ms": elapsed_ms,
                      "response_size": len(resp.content)}
            call_log.append(record)
            print(f"  [{resp.status_code}] POST {path} ({elapsed_ms}ms, {len(resp.content)} bytes)")
            if resp.status_code >= 400:
                record["error"] = resp.text[:500]
                return {"_error": resp.status_code, "_body": resp.text[:1000]}
            data = resp.json()
            if data.get("code") != 2000:
                record["api_error"] = data.get("msg")
                return {"_error": data.get("code"), "_body": data.get("msg")}
            return data
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        call_log.append({"method": "POST", "path": path, "status": "exception", "error": str(e), "elapsed_ms": elapsed_ms})
        return {"_error": "exception", "_body": str(e)}


def test_wechat():
    print("\n===== 公众号 =====")
    results = {}

    # 1. 搜索账号
    print("\n  --- 搜索账号 (gzhData/searchUser) ---")
    r = api_call("/story/api/gzhData/searchUser", {"keyword": "财经", "offset": 0})
    lst = []
    if "_error" in r:
        results["search_account"] = {"ok": False, "error": str(r.get("_body", r.get("_error")))}
    else:
        lst = r.get("data", {}).get("list", [])
        results["search_account"] = {"ok": True, "count": len(lst),
            "fields": list(lst[0].keys()) if lst else [], "sample": lst[0] if lst else None}
        if lst:
            print(f"    结果数: {len(lst)}, 字段: {list(lst[0].keys())}")
            print(f"    样本: {json.dumps(lst[0], ensure_ascii=False)[:400]}")

    # 2. 账号作品列表
    print("\n  --- 账号作品列表 (gzhData/queryWorkList) ---")
    if lst:
        acc = lst[0]
        biz = acc.get("account")
        print(f"    账号: {acc.get('accountName', '?')} (account={biz})")
        if biz:
            r2 = api_call("/story/api/gzhData/queryWorkList", {"account": biz, "offset": 0, "sortType": "_2"})
            if "_error" in r2:
                results["article_list"] = {"ok": False, "error": str(r2.get("_body", r2.get("_error")))}
            else:
                articles = r2.get("data", {}).get("list", [])
                results["article_list"] = {"ok": True, "count": len(articles),
                    "fields": list(articles[0].keys()) if articles else [], "sample": articles[0] if articles else None}
                if articles:
                    print(f"    作品数: {len(articles)}, 字段: {list(articles[0].keys())}")
                    print(f"    样本: {json.dumps(articles[0], ensure_ascii=False)[:500]}")

    return results


def test_xiaohongshu():
    print("\n===== 小红书 =====")
    results = {}

    # 1. 搜索账号 (xhsUser/searchUser)
    print("\n  --- 搜索账号 (xhsUser/searchUser) ---")
    r = api_call("/story/api/xhsUser/searchUser", {"keyword": "金融", "offset": 0})
    lst = []
    if "_error" in r:
        results["search_account"] = {"ok": False, "error": str(r.get("_body", r.get("_error")))}
    else:
        lst = r.get("data", {}).get("list", [])
        results["search_account"] = {"ok": True, "count": len(lst),
            "fields": list(lst[0].keys()) if lst else [], "sample": lst[0] if lst else None}
        if lst:
            print(f"    结果数: {len(lst)}, 字段: {list(lst[0].keys())}")
            print(f"    样本: {json.dumps(lst[0], ensure_ascii=False)[:400]}")

    # 2. 账号详情 (xhsUser/queryAccountDetail)
    print("\n  --- 账号详情 (xhsUser/queryAccountDetail) ---")
    if lst:
        acc = lst[0]
        account_id = acc.get("accountId")
        user_id = acc.get("userId")
        print(f"    账号: {acc.get('accountName', '?')} (accountId={account_id})")
        body = {}
        if account_id:
            body["accountId"] = account_id
        if user_id:
            body["userId"] = user_id
        if body:
            r2 = api_call("/story/api/xhsUser/queryAccountDetail", body)
            if "_error" not in r2:
                detail = r2.get("data", {})
                results["account_detail"] = {"ok": True, "fields": list(detail.keys()) if isinstance(detail, dict) else [],
                    "sample": detail if isinstance(detail, dict) else None}
                if isinstance(detail, dict):
                    print(f"    字段: {list(detail.keys())}")
                    print(f"    总作品数: {detail.get('accountTotalWorks')}, 粉丝: {detail.get('accountFans')}")

    # 3. 搜索作品 (xhsUser/searchArticle)
    print("\n  --- 搜索作品 (xhsUser/searchArticle) ---")
    r3 = api_call("/story/api/xhsUser/searchArticle", {"keyword": "金融", "offset": 0})
    articles = []
    if "_error" not in r3:
        articles = r3.get("data", {}).get("list", [])
        results["search_article"] = {"ok": True, "count": len(articles),
            "fields": list(articles[0].keys()) if articles else [], "sample": articles[0] if articles else None}
        if articles:
            print(f"    作品数: {len(articles)}, 字段: {list(articles[0].keys())}")

    # 4. 作品详情 (xhsUser/queryWorkDetail)
    print("\n  --- 作品详情 (xhsUser/queryWorkDetail) ---")
    if articles:
        work_id = articles[0].get("workId")
        if work_id:
            r4 = api_call("/story/api/xhsUser/queryWorkDetail", {"workId": work_id})
            if "_error" not in r4:
                detail = r4.get("data", {})
                results["article_detail"] = {"ok": True, "fields": list(detail.keys()) if isinstance(detail, dict) else [],
                    "sample": detail if isinstance(detail, dict) else None}
                if isinstance(detail, dict):
                    print(f"    字段: {list(detail.keys())}")

    # 5. 标记无账号作品列表接口
    results["has_account_item_list"] = False
    print("\n  ⚠️ 小红书无账号作品列表接口（无法订阅特定账号获取全部作品）")

    return results


def test_bilibili():
    print("\n===== 哔哩哔哩 =====")
    results = {}

    # 1. 搜索账号 (bili/data/accountSearch)
    print("\n  --- 搜索账号 (bili/data/accountSearch) ---")
    r = api_call("/story/api/bili/data/accountSearch", {"keyword": "财经", "page": "1", "pageSize": 5})
    account_list = []
    if "_error" in r:
        results["search_account"] = {"ok": False, "error": str(r.get("_body", r.get("_error")))}
    else:
        data = r.get("data", {})
        account_list = data.get("accountList", [])
        results["search_account"] = {"ok": True, "count": len(account_list),
            "fields": list(account_list[0].keys()) if account_list else [], "sample": account_list[0] if account_list else None}
        if account_list:
            print(f"    结果数: {len(account_list)}, 总数: {data.get('total')}")
            print(f"    字段: {list(account_list[0].keys())}")
            print(f"    样本: {json.dumps(account_list[0], ensure_ascii=False)[:400]}")

    # 2. 账号作品列表 (bili/data/accountWorkList)
    print("\n  --- 账号作品列表 (bili/data/accountWorkList) ---")
    if account_list:
        acc = account_list[0]
        mid = acc.get("mid")
        print(f"    账号: {acc.get('name', '?')} (mid={mid})")
        if mid:
            r2 = api_call("/story/api/bili/data/accountWorkList", {"mid": str(mid), "page": "1", "pageSize": 5})
            if "_error" in r2:
                results["video_list"] = {"ok": False, "error": str(r2.get("_body", r2.get("_error")))}
            else:
                data2 = r2.get("data", {})
                videos = data2.get("workList", [])
                results["video_list"] = {"ok": True, "count": len(videos),
                    "fields": list(videos[0].keys()) if videos else [], "sample": videos[0] if videos else None}
                if videos:
                    print(f"    作品数: {len(videos)}, 总数: {data2.get('total')}")
                    print(f"    字段: {list(videos[0].keys())}")
                    print(f"    样本: {json.dumps(videos[0], ensure_ascii=False)[:500]}")

    return results


def main():
    print("=" * 60)
    print("RedFox 社媒内容采集 Spike")
    print(f"时间: {datetime.now(timezone.utc).isoformat()}")
    print(f"API Key: {API_KEY[:8]}...{API_KEY[-4:]}")
    print("=" * 60)

    wechat = test_wechat()
    xhs = test_xiaohongshu()
    bili = test_bilibili()

    _save_report({"wechat": wechat, "xiaohongshu": xhs, "bilibili": bili})

    print("\n" + "=" * 60)
    print("Phase 0 门禁结论")
    print("=" * 60)

    checks = {
        "公众号-搜索账号": wechat.get("search_account", {}).get("ok", False),
        "公众号-作品列表": wechat.get("article_list", {}).get("ok", False),
        "小红书-搜索账号": xhs.get("search_account", {}).get("ok", False),
        "小红书-账号详情": xhs.get("account_detail", {}).get("ok", False),
        "小红书-搜索作品": xhs.get("search_article", {}).get("ok", False),
        "小红书-作品详情": xhs.get("article_detail", {}).get("ok", False),
        "小红书-账号作品列表": xhs.get("has_account_item_list", False),
        "B站-搜索账号": bili.get("search_account", {}).get("ok", False),
        "B站-作品列表": bili.get("video_list", {}).get("ok", False),
    }

    for name, ok in checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")

    passed = sum(1 for v in checks.values() if v)
    total = len(checks)
    print(f"\n  通过: {passed}/{total}")

    if not checks["小红书-账号作品列表"]:
        print("\n  ⚠️ 关键发现：小红书无账号作品列表接口")
        print("    → 订阅动态：小红书只能通过搜索关键词发现内容，无法订阅特定账号")
        print("    → AIHot：可通过搜索接口采集金融内容，但无法做逐账号定时同步")
        print("    → 建议：小红书订阅功能降级为搜索发现，不作为核心订阅平台")


def _save_report(results: dict):
    out_dir = Path("scripts/spikes")
    out_file = out_dir / "spike_redfox_social_raw.json"
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    print(f"\n原始结果已写入 {out_file}")

    log_file = out_dir / "spike_redfox_call_log.json"
    log_file.write_text(json.dumps(call_log, ensure_ascii=False, indent=2))
    print(f"调用日志已写入 {log_file}")

    total_calls = len(call_log)
    success_calls = sum(1 for c in call_log if isinstance(c.get("status"), int) and c["status"] < 400)
    failed_calls = total_calls - success_calls
    estimated_cost = total_calls * 0.02

    print(f"\n===== 调用统计 =====")
    print(f"  总调用: {total_calls}")
    print(f"  成功: {success_calls}")
    print(f"  失败: {failed_calls}")
    print(f"  估算费用: ¥{estimated_cost:.2f} (按 ¥0.02/次起)")


if __name__ == "__main__":
    main()
