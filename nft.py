from __future__ import annotations

import html
import re
from dataclasses import dataclass

import aiohttp

NFT_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:t\.me|telegram\.me)/nft/([A-Za-z0-9_-]{1,128})",
    re.IGNORECASE,
)
SLUG_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


class NFTLookupError(RuntimeError):
    """Не удалось получить данные NFT."""


@dataclass(frozen=True, slots=True)
class NFTMetadata:
    slug: str
    url: str
    title: str
    image_url: str | None
    description: str | None
    owner_label: str | None


def parse_nft_link(text: str) -> str | None:
    match = NFT_URL_RE.search(text)
    if not match:
        return None
    slug = match.group(1)
    return slug if SLUG_RE.match(slug) else None


def canonical_nft_url(slug: str) -> str:
    if not SLUG_RE.match(slug):
        raise NFTLookupError("Некорректная ссылка на NFT.")
    return f"https://t.me/nft/{slug}"


def _meta(html_text: str, property_name: str) -> str | None:
    # Атрибуты в meta могут идти в любом порядке.
    pattern = re.compile(
        r"<meta\b(?=[^>]*\bproperty=[\"']"
        + re.escape(property_name)
        + r"[\"'])[^>]*\bcontent=[\"'](.*?)[\"'][^>]*>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html_text)
    if not match:
        pattern = re.compile(
            r"<meta\b(?=[^>]*\bcontent=[\"'](.*?)[\"'])[^>]*\bproperty=[\"']"
            + re.escape(property_name)
            + r"[\"'][^>]*>",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html_text)
    return html.unescape(match.group(1)).strip() if match else None


def _strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _owner(html_text: str) -> str | None:
    match = re.search(
        r"<tr>\s*<th>\s*Owner\s*</th>\s*<td>(.*?)</td>\s*</tr>",
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    owner = _strip_tags(match.group(1))
    return owner or None


class NFTResolver:
    def __init__(self, session: aiohttp.ClientSession, timeout_seconds: float = 12.0) -> None:
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def resolve(self, url: str) -> NFTMetadata:
        slug = parse_nft_link(url)
        if not slug:
            raise NFTLookupError(
                "Нужна ссылка вида https://t.me/nft/Name-123. "
                "Обычные ссылки и ссылки на TON-кошельки не поддерживаются."
            )

        canonical = canonical_nft_url(slug)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "ru,en;q=0.8",
        }

        try:
            async with self._session.get(
                canonical,
                headers=headers,
                timeout=self._timeout,
                allow_redirects=True,
            ) as response:
                if response.status != 200:
                    raise NFTLookupError(
                        f"Telegram вернул HTTP {response.status} для NFT."
                    )
                page = await response.text(errors="ignore")
        except aiohttp.ClientError as exc:
            raise NFTLookupError("Не удалось получить страницу NFT из Telegram.") from exc
        except TimeoutError as exc:
            raise NFTLookupError("Telegram слишком долго отвечает. Попробуйте позже.") from exc

        if "tgme_page_gift" not in page:
            raise NFTLookupError(
                "NFT не найден по ссылке. Проверьте, что это существующий t.me/nft/..."
            )

        title = _meta(page, "og:title")
        if not title:
            title_match = re.search(r"<title>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
            title = _strip_tags(title_match.group(1)) if title_match else slug

        image_url = _meta(page, "og:image")
        if image_url and image_url.startswith("//"):
            image_url = "https:" + image_url
        if image_url and not image_url.startswith(("https://", "http://")):
            image_url = None

        description = _meta(page, "og:description")
        if description:
            description = description.strip()[:500]

        return NFTMetadata(
            slug=slug,
            url=canonical,
            title=title.strip()[:200] or slug,
            image_url=image_url,
            description=description or None,
            owner_label=_owner(page),
        )
