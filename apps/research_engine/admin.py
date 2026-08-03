from __future__ import annotations

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.urls import reverse
from django.utils.html import format_html

from apps.research_engine.models import (
    Niche,
    ResearchInsight,
    SubredditTarget,
)


class SubredditTargetInline(admin.TabularInline):
    model = SubredditTarget
    extra = 0
    fields = (
        "subreddit_name",
        "target_keywords",
    )
    show_change_link = True


@admin.register(Niche)
class NicheAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "is_active",
        "subreddit_target_count",
        "research_insight_count",
    )
    list_filter = (
        "is_active",
    )
    search_fields = (
        "name",
        "description",
    )
    ordering = (
        "name",
    )
    list_editable = (
        "is_active",
    )
    inlines = (
        SubredditTargetInline,
    )

    @admin.display(
        description="Subreddit Targets",
        ordering="subreddit_target_total",
    )
    def subreddit_target_count(self, obj: Niche) -> int:
        return obj.subreddit_target_total

    @admin.display(
        description="Research Insights",
        ordering="research_insight_total",
    )
    def research_insight_count(self, obj: Niche) -> int:
        return obj.research_insight_total

    def get_queryset(
        self,
        request: HttpRequest,
    ) -> QuerySet[Niche]:
        queryset = super().get_queryset(request)

        return queryset.annotate(
            subreddit_target_total=Count(
                "subreddit_targets",
                distinct=True,
            ),
            research_insight_total=Count(
                "research_insights",
                distinct=True,
            ),
        )


@admin.register(SubredditTarget)
class SubredditTargetAdmin(admin.ModelAdmin):
    list_display = (
        "formatted_subreddit",
        "niche",
        "keyword_count",
        "keyword_preview",
    )
    list_filter = (
        "niche",
        "niche__is_active",
    )
    search_fields = (
        "subreddit_name",
        "niche__name",
        "target_keywords",
    )
    autocomplete_fields = (
        "niche",
    )
    ordering = (
        "niche__name",
        "subreddit_name",
    )
    list_select_related = (
        "niche",
    )
    list_per_page = 50

    @admin.display(
        description="Subreddit",
        ordering="subreddit_name",
    )
    def formatted_subreddit(
        self,
        obj: SubredditTarget,
    ) -> str:
        return f"r/{obj.subreddit_name}"

    @admin.display(
        description="Keyword Count",
    )
    def keyword_count(
        self,
        obj: SubredditTarget,
    ) -> int:
        if not isinstance(obj.target_keywords, list):
            return 0

        return len(
            [
                keyword
                for keyword in obj.target_keywords
                if isinstance(keyword, str) and keyword.strip()
            ]
        )

    @admin.display(
        description="Keyword Preview",
    )
    def keyword_preview(
        self,
        obj: SubredditTarget,
    ) -> str:
        if not isinstance(obj.target_keywords, list):
            return "—"

        keywords = [
            keyword.strip()
            for keyword in obj.target_keywords
            if isinstance(keyword, str) and keyword.strip()
        ]

        if not keywords:
            return "—"

        preview = ", ".join(keywords[:5])

        if len(keywords) > 5:
            preview = f"{preview}, …"

        return preview


@admin.register(ResearchInsight)
class ResearchInsightAdmin(admin.ModelAdmin):
    list_display = (
        "short_problem_summary",
        "niche",
        "short_content_gap",
        "created_at",
        "outline_action",
    )
    list_filter = (
        "niche",
        "created_at",
    )
    search_fields = (
        "problem_summary",
        "content_gap",
        "recommended_table_idea",
        "raw_extracted_text",
        "niche__name",
    )
    readonly_fields = (
        "created_at",
    )
    autocomplete_fields = (
        "niche",
    )
    date_hierarchy = "created_at"
    ordering = (
        "-created_at",
    )
    list_select_related = (
        "niche",
    )
    list_per_page = 50

    fieldsets = (
        (
            "Research Classification",
            {
                "fields": (
                    "niche",
                    "problem_summary",
                    "content_gap",
                    "recommended_table_idea",
                )
            },
        ),
        (
            "Extracted Evidence",
            {
                "fields": (
                    "raw_extracted_text",
                    "created_at",
                ),
                "classes": (
                    "collapse",
                ),
            },
        ),
    )

    @admin.display(
        description="Problem Summary",
        ordering="problem_summary",
    )
    def short_problem_summary(
        self,
        obj: ResearchInsight,
    ) -> str:
        text = obj.problem_summary.strip()

        if len(text) > 90:
            return f"{text[:87]}..."

        return text

    @admin.display(
        description="Content Gap",
        ordering="content_gap",
    )
    def short_content_gap(
        self,
        obj: ResearchInsight,
    ) -> str:
        text = obj.content_gap.strip()

        if not text:
            return "—"

        if len(text) > 80:
            return f"{text[:77]}..."

        return text

    @admin.display(
        description="SEO Outline",
    )
    def outline_action(
        self,
        obj: ResearchInsight,
    ) -> str:
        url = reverse(
            "research_engine:generate-insight-outline",
            kwargs={
                "insight_id": obj.pk,
            },
        )

        return format_html(
            '<a href="{}" target="_blank">Generate Outline</a>',
            url,
        )