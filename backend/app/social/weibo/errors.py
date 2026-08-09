class WeiboError(Exception):
    """微博采集错误基类。"""


class WeiboSessionExpiredError(WeiboError):
    """专用账号登录态已失效。"""


class WeiboRateLimitedError(WeiboError):
    """微博拒绝请求，需要停止整轮并进入全局冷却。"""

    def __init__(self, message: str = "微博接口触发风控", retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


class WeiboTransientError(WeiboError):
    """可稍后重试的网络或上游错误。"""


class InvalidWeiboPayloadError(WeiboError):
    """上游返回结构不符合必要契约。"""


class InvalidWeiboProfileUrlError(ValueError):
    """主页链接不能安全解析为数字 UID。"""
