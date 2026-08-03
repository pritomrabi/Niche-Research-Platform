from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from django.conf import settings
from google import genai
from google.genai import types

from apps.research_engine.models import ResearchInsight


logger = logging.getLogger(__name__)


class ArticleOutlineError(Exception):
    """Raised when an SEO outline cannot be generated."""


ARTICLE_OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
        },
        "search_intent": {
            "type": "string",
        },
        "primary_keyword": {
            "type": "string",
        },
        "secondary_keywords": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
        "meta_description": {
            "type": "string",
        },
        "outline_markdown": {
            "type": "string",
            "description": (
                "A complete Markdown article outline containing H1, H2, "
                "H3 headings, writer notes, and at least one Markdown table."
            ),
        },
        "faq_questions": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "title",
        "search_intent",
        "primary_keyword",
        "secondary_keywords",
        "meta_description",
        "outline_markdown",
        "faq_questions",
    ],
}


def _required_setting(name: str) -> str:
    value = getattr(settings, name, "")

    if value is None or not str(value).strip():
        raise ArticleOutlineError(
            f"Django setting '{name}' is missing or empty."
        )

    return str(value).strip()


@lru_cache(maxsize=1)
def get_outline_gemini_client() -> genai.Client:
    return genai.Client(
        api_key=_required_setting("GEMINI_API_KEY"),
    )


def _validate_outline(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ArticleOutlineError(
            "Gemini returned a non-object outline response."
        )

    required_fields = {
        "title",
        "search_intent",
        "primary_keyword",
        "secondary_keywords",
        "meta_description",
        "outline_markdown",
        "faq_questions",
    }

    missing_fields = required_fields - set(data.keys())

    if missing_fields:
        missing_text = ", ".join(
            sorted(missing_fields)
        )

        raise ArticleOutlineError(
            f"Gemini outline is missing: {missing_text}."
        )

    if not isinstance(data["secondary_keywords"], list):
        raise ArticleOutlineError(
            "secondary_keywords must be a list."
        )

    if not isinstance(data["faq_questions"], list):
        raise ArticleOutlineError(
            "faq_questions must be a list."
        )

    if not str(data["outline_markdown"]).strip():
        raise ArticleOutlineError(
            "Gemini returned an empty Markdown outline."
        )

    return data


def generate_article_outline(
    insight: ResearchInsight,
) -> dict[str, Any]:
    if not isinstance(insight, ResearchInsight):
        raise TypeError(
            "insight must be a ResearchInsight instance."
        )

    prompt = f"""
You are a senior SEO content strategist.

Create an evidence-conscious article outline from this saved research
insight.

Niche:
{insight.niche.name}

Problem:
{insight.problem_summary}

Content gap:
{insight.content_gap}

Recommended structured resource:
{insight.recommended_table_idea}

Evidence summary:
{insight.raw_extracted_text}

Rules:
- Do not claim that the evidence proves market demand.
- Do not invent statistics, prices, survey results, or user quotations.
- Build the outline around solving the stated problem.
- Use one clear search intent.
- Produce one H1 title.
- Include logically ordered H2 and H3 sections.
- Include writer instructions under each major section.
- Include at least one valid Markdown table template.
- The table must directly support the recommended structured-resource idea.
- Add 4 to 6 specific FAQ questions.
- Keep the meta description at or below 155 characters.
- Return strict JSON matching the supplied schema.
""".strip()

    client = get_outline_gemini_client()

    try:
        response = client.models.generate_content(
            model=_required_setting("GEMINI_MODEL"),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                max_output_tokens=getattr(
                    settings,
                    "GEMINI_MAX_OUTPUT_TOKENS",
                    4096,
                ),
                response_mime_type="application/json",
                response_json_schema=ARTICLE_OUTLINE_SCHEMA,
            ),
        )

        parsed = getattr(response, "parsed", None)

        if parsed is None:
            response_text = str(
                getattr(response, "text", "") or ""
            ).strip()

            if not response_text:
                raise ArticleOutlineError(
                    "Gemini returned an empty outline response."
                )

            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError as exc:
                raise ArticleOutlineError(
                    "Gemini returned invalid outline JSON."
                ) from exc

        return _validate_outline(parsed)

    except ArticleOutlineError:
        raise

    except Exception as exc:
        logger.exception(
            "Article outline generation failed for insight_id=%s",
            insight.pk,
        )

        raise ArticleOutlineError(
            f"Article outline generation failed: {exc}"
        ) from exc