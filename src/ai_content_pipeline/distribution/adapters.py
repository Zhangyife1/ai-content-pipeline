"""平台适配器：每个平台实现统一接口（认证/传图/发布/取数）。"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any

import httpx


class PublishError(RuntimeError):
    def __init__(self, message: str, error_type: str = "unknown") -> None:
        super().__init__(message)
        self.error_type = error_type


class PlatformAdapter(ABC):
    platform: str = "base"

    @abstractmethod
    async def authenticate(self) -> str:
        """获取平台访问 Token。"""

    @abstractmethod
    async def upload_image(self, image_path: str) -> str:
        """上传图片，返回平台可访问 URL。"""

    @abstractmethod
    async def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        """发布内容，返回平台文章 ID 与 URL。"""

    @abstractmethod
    async def get_stats(self, article_id: str) -> dict[str, Any]:
        """获取阅读/互动数据，用于效果回流。"""


class MockAdapter(PlatformAdapter):
    """Mock 适配器：本地 demo 与测试使用，不产生真实外部调用。"""

    platform = "mock"

    async def authenticate(self) -> str:
        return "mock_token"

    async def upload_image(self, image_path: str) -> str:
        return f"https://mock-image.example/{uuid.uuid4().hex[:8]}.png"

    async def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        article_id = uuid.uuid4().hex[:16]
        return {
            "platform": self.platform,
            "article_id": article_id,
            "url": f"https://mock.example/{article_id}",
            "status": "published",
        }

    async def get_stats(self, article_id: str) -> dict[str, Any]:
        return {
            "article_id": article_id,
            "views": 1200,
            "likes": 86,
            "comments": 12,
            "shares": 7,
        }


class WechatAdapter(PlatformAdapter):
    """微信公众号适配器（真实接入占位，按微信公众平台 API 实现）。"""

    platform = "wechat"

    def __init__(self, app_id: str = "", app_secret: str = "") -> None:
        self.app_id = app_id
        self.app_secret = app_secret

    async def authenticate(self) -> str:
        # GET https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=...&secret=...
        raise NotImplementedError("请在实现中接入微信 access_token 获取逻辑")

    async def upload_image(self, image_path: str) -> str:
        raise NotImplementedError("请在实现中接入微信永久素材上传逻辑")

    async def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("请在实现中接入 draft->publish 流程")

    async def get_stats(self, article_id: str) -> dict[str, Any]:
        raise NotImplementedError("请在实现中接入数据统计接口")


class ZhihuAdapter(PlatformAdapter):
    """知乎适配器（开放平台/爬虫数据回流需按合规要求实现）。"""

    platform = "zhihu"

    def __init__(self, cookie: str = "", base_url: str = "https://www.zhihu.com") -> None:
        self.cookie = cookie
        self.base_url = base_url
        self._client = httpx.AsyncClient(headers={"Cookie": cookie, "User-Agent": "Mozilla/5.0"})

    async def authenticate(self) -> str:
        if not self.cookie:
            raise PublishError("缺少知乎 Cookie", "auth")
        return self.cookie

    async def upload_image(self, image_path: str) -> str:
        # 知乎上传接口需要 signed token，真实接入时补充
        raise NotImplementedError("请在实现中接入知乎图片上传")

    async def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("请在实现中接入知乎专栏发布")

    async def get_stats(self, article_id: str) -> dict[str, Any]:
        raise NotImplementedError("请在实现中接入知乎数据接口")


class CmsAdapter(PlatformAdapter):
    """官网 CMS：JSON API 发布，需携带 SEO 元数据。"""

    platform = "cms"

    def __init__(self, base_url: str = "", api_key: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._client = httpx.AsyncClient(timeout=20.0)

    async def authenticate(self) -> str:
        return self.api_key

    async def upload_image(self, image_path: str) -> str:
        raise NotImplementedError("请在实现中接入 CMS 图床")

    async def publish(self, content: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url or not self.api_key:
            raise PublishError("CMS 适配器未配置 base_url/api_key", "config")
        resp = await self._client.post(
            f"{self.base_url}/api/posts",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=content,
        )
        resp.raise_for_status()
        data = resp.json()
        return {"platform": "cms", "article_id": data["id"], "url": data["url"]}


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        self._adapters[adapter.platform] = adapter

    def get(self, platform: str) -> PlatformAdapter:
        if platform not in self._adapters:
            raise KeyError(f"未注册平台适配器: {platform}")
        return self._adapters[platform]

    def platforms(self) -> list[str]:
        return list(self._adapters)


def default_registry(mode: str = "mock") -> AdapterRegistry:
    registry = AdapterRegistry()
    if mode == "mock":
        registry.register(MockAdapter())
    else:
        registry.register(WechatAdapter())
        registry.register(ZhihuAdapter())
        registry.register(CmsAdapter())
    return registry
