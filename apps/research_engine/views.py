from __future__ import annotations

from django.contrib.admin.views.decorators import staff_member_required
from django.http import (
    HttpRequest,
    HttpResponse,
    JsonResponse,
)
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from apps.research_engine.models import ResearchInsight
from apps.research_engine.services.article_generator import (
    ArticleOutlineError,
    generate_article_outline,
)


@staff_member_required
@require_GET
def generate_insight_outline(
    request: HttpRequest,
    insight_id: int,
) -> HttpResponse:
    """
    Generate an SEO outline for one saved research insight.

    Add ?format=markdown to return plain Markdown.
    The default response is JSON.
    """
    insight = get_object_or_404(
        ResearchInsight.objects.select_related("niche"),
        pk=insight_id,
    )

    try:
        outline = generate_article_outline(insight)

    except ArticleOutlineError as exc:
        return JsonResponse(
            {
                "success": False,
                "insight_id": insight.pk,
                "error": str(exc),
            },
            status=502,
        )

    response_format = request.GET.get(
        "format",
        "json",
    ).strip().lower()

    if response_format == "markdown":
        markdown = str(
            outline.get("outline_markdown", "")
        )

        return HttpResponse(
            markdown,
            content_type="text/markdown; charset=utf-8",
        )

    return JsonResponse(
        {
            "success": True,
            "insight_id": insight.pk,
            "niche": insight.niche.name,
            "problem_summary": insight.problem_summary,
            "outline": outline,
        },
        json_dumps_params={
            "ensure_ascii": False,
            "indent": 2,
        },
    )