"""Named service links only; no guessed sibling paths or external identifiers."""

from dataclasses import dataclass
from urllib.parse import urlencode

from django.urls import NoReverseMatch, Resolver404, resolve, reverse


@dataclass(frozen=True, slots=True)
class ServiceLink:
    label: str
    scope: str
    url: str | None


def service_url(name: str, *, key: str | None = None, params=None, anchor="") -> str | None:
    try:
        url = reverse(name, args=[key] if key is not None else None)
        # A named route shadowed by a catch-all is not a connected destination.
        if resolve(url).view_name != name:
            return None
    except (NoReverseMatch, Resolver404):
        return None
    return url + ("?" + urlencode(params) if params else "") + ("#" + anchor if anchor else "")


def service_links(*, key=None, revision=None, q="") -> tuple[ServiceLink, ...]:
    detail = "detail" if key else "index"
    return (
        ServiceLink(
            "قائمة التحرير",
            "السجل الأصلي دون تحديد مراجعة" if key else "كل السجلات",
            service_url(f"editorial_queue:{detail}", key=key),
        ),
        ServiceLink(
            "البحث التحريري",
            "البحث في المجموعة كاملة",
            service_url("editorial_search:index", params={"q": q} if q else None),
        ),
        ServiceLink(
            "مساحة التحرير",
            "المراجعة المحددة" if revision else "استلام السجل",
            service_url(
                f"editorial_workbench:{detail}",
                key=key,
                params={"revision": revision.number} if revision else None,
                anchor="snapshot" if revision else "",
            ),
        ),
        ServiceLink(
            "جسر البحث",
            "إحالات السجل الأصلية أو الحالية؛ لا يحدد مراجعة تاريخية",
            service_url(f"research_bridge:{detail}", key=key),
        ),
        ServiceLink(
            "التصدير التحريري",
            "المجموعة كاملة؛ ليس تصدير المراجعة المحددة",
            service_url("editorial_export:index"),
        ),
    )
