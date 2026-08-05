"""Schema.org JSON-LD 结构化数据：帮助搜索引擎理解页面语义（GEO）。"""

from __future__ import annotations

from ai_content_pipeline.models import GeneratedArticle


def organization_json_ld(name: str = "星尘 AI", url: str = "https://www.somaagent.com.cn") -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": name,
        "url": url,
    }


def article_json_ld(article: GeneratedArticle, url: str = "") -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": article.title,
        "description": article.summary,
        "datePublished": article.created_at.isoformat(),
        "mainEntityOfPage": url or f"https://www.somaagent.com.cn/content/{article.content_id}",
        "author": {"@type": "Organization", "name": "星尘 AI"},
    }


def faq_json_ld(pairs: list[dict[str, str]]) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": pair["question"],
                "acceptedAnswer": {"@type": "Answer", "text": pair["answer"]},
            }
            for pair in pairs
        ],
    }


def product_json_ld(name: str, description: str, price: float, currency: str = "CNY") -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": name,
        "description": description,
        "offers": {
            "@type": "Offer",
            "price": price,
            "priceCurrency": currency,
            "availability": "https://schema.org/InStock",
        },
    }

