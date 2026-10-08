"""Network-only clients for catalog sources."""

from collections.abc import Iterator

import httpx


DAV_PUBLIC_API = (
    "https://dichvucong.dav.gov.vn/"
    "api/services/app/soDangKy/GetAllPublicServerPaging"
)


def fetch_dav_drugbank_pages(
    url: str = DAV_PUBLIC_API,
    *,
    page_size: int = 10,
    # page_size: int = 500,
    timeout: float = 60.0,
) -> Iterator[bytes]:
    """Fetch the complete public DAV catalog page by page."""
    if page_size <= 0:
        raise ValueError("page_size must be positive")

    skip = 0
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        while True:
            response = client.post(
                url,
                json={
                    "filterText": "",
                    "SoDangKyThuoc": {},
                    "KichHoat": True,
                    "skipCount": skip,
                    "maxResultCount": page_size,
                    "sorting": None,
                },
            )
            response.raise_for_status()
            document = response.json()
            result = document.get("result", {})
            items = result.get("items", [])
            if not isinstance(items, list):
                raise ValueError("DAV response does not contain result.items")
            yield response.content

            skip += len(items)
            total = 10
            # total = result.get("totalCount")
            if not items or (isinstance(total, int) and skip >= total):
                break
