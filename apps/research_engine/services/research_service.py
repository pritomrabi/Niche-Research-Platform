from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Iterable

import praw
from django.conf import settings
from google import genai
from google.genai import types
from praw.exceptions import PRAWException
from prawcore.exceptions import (
    BadRequest,
    Forbidden,
    NotFound,
    OAuthException,
    RequestException,
    ResponseException,
    ServerError,
    TooManyRequests,
)

from apps.research_engine.models import SubredditTarget


logger = logging.getLogger(__name__)


class ResearchServiceError(Exception):
    """Base exception for research-service failures."""


class ResearchConfigurationError(ResearchServiceError):
    """Raised when API configuration is incomplete or disabled."""


class RedditCollectionError(ResearchServiceError):
    """Raised when Reddit content cannot be collected."""


class GeminiAnalysisError(ResearchServiceError):
    """Raised when Gemini cannot produce valid research findings."""


@dataclass(frozen=True)
class RedditCommentDocument:
    comment_id: str
    body: str
    score: int


@dataclass(frozen=True)
class RedditPostDocument:
    post_id: str
    subreddit: str
    title: str
    body: str
    score: int
    num_comments: int
    created_utc: float
    permalink: str
    matched_keyword: str
    comments: list[RedditCommentDocument]


@dataclass(frozen=True)
class ResearchFinding:
    problem_summary: str
    content_gap: str
    table_idea: str
    raw_extracted_text: str


RESEARCH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "problems": {
            "type": "array",
            "description": "Distinct user problems found in the discussions.",
            "items": {
                "type": "object",
                "properties": {
                    "problem_summary": {
                        "type": "string",
                        "description": (
                            "A concise and specific summary of one recurring "
                            "user problem."
                        ),
                    },
                    "evidence_text": {
                        "type": "string",
                        "description": (
                            "A short paraphrased evidence summary from the "
                            "provided discussion data. Do not quote usernames."
                        ),
                    },
                },
                "required": [
                    "problem_summary",
                    "evidence_text",
                ],
            },
        },
        "content_gaps": {
            "type": "array",
            "description": (
                "Content or information gaps corresponding by array position "
                "to the problems array."
            ),
            "items": {
                "type": "string",
            },
        },
        "table_ideas": {
            "type": "array",
            "description": (
                "Useful comparison table, checklist, calculator, directory, "
                "or structured resource ideas corresponding by array position "
                "to the problems array."
            ),
            "items": {
                "type": "string",
            },
        },
    },
    "required": [
        "problems",
        "content_gaps",
        "table_ideas",
    ],
}


def _required_setting(name: str) -> str:
    value = getattr(settings, name, "")

    if value is None or not str(value).strip():
        raise ResearchConfigurationError(
            f"Django setting '{name}' is missing or empty."
        )

    return str(value).strip()


def _validate_live_reddit_configuration() -> None:
    if not getattr(settings, "REDDIT_API_ENABLED", False):
        raise ResearchConfigurationError(
            "Reddit API access is disabled. Set REDDIT_API_ENABLED=True "
            "only after Reddit approves the application."
        )

    _required_setting("REDDIT_CLIENT_ID")
    _required_setting("REDDIT_CLIENT_SECRET")
    _required_setting("REDDIT_USER_AGENT")


def _validate_gemini_configuration() -> None:
    _required_setting("GEMINI_API_KEY")
    _required_setting("GEMINI_MODEL")


@lru_cache(maxsize=1)
def get_reddit_client() -> praw.Reddit:
    """
    Return one cached, read-only PRAW client.
    """
    _validate_live_reddit_configuration()

    client = praw.Reddit(
        client_id=_required_setting("REDDIT_CLIENT_ID"),
        client_secret=_required_setting("REDDIT_CLIENT_SECRET"),
        user_agent=_required_setting("REDDIT_USER_AGENT"),
        timeout=getattr(settings, "REDDIT_REQUEST_TIMEOUT", 20),
        check_for_async=False,
    )

    client.read_only = True

    return client


@lru_cache(maxsize=1)
def get_gemini_client() -> genai.Client:
    """
    Return one cached Google GenAI client.
    """
    _validate_gemini_configuration()

    return genai.Client(
        api_key=_required_setting("GEMINI_API_KEY"),
    )


def _normalize_keywords(keywords: Any) -> list[str]:
    if not isinstance(keywords, list):
        raise ResearchConfigurationError(
            "SubredditTarget.target_keywords must contain a JSON list."
        )

    normalized: list[str] = []
    seen: set[str] = set()

    for keyword in keywords:
        if not isinstance(keyword, str):
            continue

        cleaned = keyword.strip()

        if not cleaned:
            continue

        key = cleaned.casefold()

        if key not in seen:
            seen.add(key)
            normalized.append(cleaned)

    if not normalized:
        raise ResearchConfigurationError(
            "The subreddit target does not contain any usable keywords."
        )

    return normalized


def _safe_text(value: Any, max_length: int) -> str:
    text = str(value or "").replace("\x00", " ").strip()

    if len(text) > max_length:
        return f"{text[:max_length].rstrip()}…"

    return text


def _collect_post_comments(
    submission: Any,
    comments_per_post: int,
) -> list[RedditCommentDocument]:
    """
    Collect a limited number of useful comments from one submission.

    replace_more(limit=0) removes unresolved MoreComments placeholders
    instead of making many additional API requests.
    """
    submission.comment_sort = "top"
    submission.comment_limit = comments_per_post

    submission.comments.replace_more(limit=0)

    collected: list[RedditCommentDocument] = []

    for comment in submission.comments.list():
        body = _safe_text(getattr(comment, "body", ""), max_length=1500)

        if not body:
            continue

        if body in {"[deleted]", "[removed]"}:
            continue

        collected.append(
            RedditCommentDocument(
                comment_id=str(getattr(comment, "id", "")),
                body=body,
                score=int(getattr(comment, "score", 0) or 0),
            )
        )

    collected.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    return collected[:comments_per_post]


def fetch_reddit_discussions(
    subreddit_target: SubredditTarget,
    post_limit: int | None = None,
    comments_per_post: int | None = None,
) -> list[RedditPostDocument]:
    """
    Search one configured subreddit using all of its target keywords.

    The returned result contains at most `post_limit` unique submissions
    across all keyword searches, rather than 20 submissions per keyword.
    """
    if not isinstance(subreddit_target, SubredditTarget):
        raise TypeError(
            "subreddit_target must be a SubredditTarget instance."
        )

    reddit = get_reddit_client()

    keywords = _normalize_keywords(
        subreddit_target.target_keywords,
    )

    resolved_post_limit = (
        post_limit
        if post_limit is not None
        else getattr(settings, "REDDIT_POST_LIMIT", 20)
    )

    resolved_comments_per_post = (
        comments_per_post
        if comments_per_post is not None
        else getattr(settings, "REDDIT_COMMENTS_PER_POST", 10)
    )

    if resolved_post_limit < 1:
        raise ResearchConfigurationError(
            "REDDIT_POST_LIMIT must be greater than zero."
        )

    if resolved_comments_per_post < 0:
        raise ResearchConfigurationError(
            "REDDIT_COMMENTS_PER_POST cannot be negative."
        )

    subreddit_name = subreddit_target.subreddit_name.strip().removeprefix("r/")

    try:
        subreddit = reddit.subreddit(subreddit_name)

        submissions_by_id: dict[str, RedditPostDocument] = {}

        per_keyword_limit = max(
            resolved_post_limit,
            10,
        )

        for keyword in keywords:
            search_results = subreddit.search(
                query=keyword,
                sort="new",
                time_filter="month",
                syntax="lucene",
                limit=per_keyword_limit,
            )

            for submission in search_results:
                post_id = str(getattr(submission, "id", ""))

                if not post_id or post_id in submissions_by_id:
                    continue

                title = _safe_text(
                    getattr(submission, "title", ""),
                    max_length=500,
                )

                body = _safe_text(
                    getattr(submission, "selftext", ""),
                    max_length=5000,
                )

                if not title and not body:
                    continue

                if body in {"[deleted]", "[removed]"}:
                    body = ""

                comments = _collect_post_comments(
                    submission=submission,
                    comments_per_post=resolved_comments_per_post,
                )

                permalink = str(
                    getattr(submission, "permalink", "") or ""
                )

                if permalink.startswith("/"):
                    permalink = f"https://www.reddit.com{permalink}"

                submissions_by_id[post_id] = RedditPostDocument(
                    post_id=post_id,
                    subreddit=subreddit_name,
                    title=title,
                    body=body,
                    score=int(getattr(submission, "score", 0) or 0),
                    num_comments=int(
                        getattr(submission, "num_comments", 0) or 0
                    ),
                    created_utc=float(
                        getattr(submission, "created_utc", 0.0) or 0.0
                    ),
                    permalink=permalink,
                    matched_keyword=keyword,
                    comments=comments,
                )

        ordered_posts = sorted(
            submissions_by_id.values(),
            key=lambda item: (
                item.created_utc,
                item.score,
            ),
            reverse=True,
        )

        return ordered_posts[:resolved_post_limit]

    except Forbidden as exc:
        raise RedditCollectionError(
            f"Reddit denied access to r/{subreddit_name}. "
            "The subreddit may be private, restricted, or inaccessible."
        ) from exc

    except NotFound as exc:
        raise RedditCollectionError(
            f"Subreddit r/{subreddit_name} was not found."
        ) from exc

    except TooManyRequests as exc:
        raise RedditCollectionError(
            "Reddit rate limit exceeded. Wait before retrying."
        ) from exc

    except (OAuthException, BadRequest) as exc:
        raise RedditCollectionError(
            "Reddit rejected the API credentials or search request."
        ) from exc

    except (
        RequestException,
        ResponseException,
        ServerError,
    ) as exc:
        raise RedditCollectionError(
            f"Reddit network/API error: {exc}"
        ) from exc

    except PRAWException as exc:
        raise RedditCollectionError(
            f"PRAW failed while collecting Reddit discussions: {exc}"
        ) from exc

    except Exception as exc:
        logger.exception(
            "Unexpected Reddit collection failure for target_id=%s",
            subreddit_target.pk,
        )

        raise RedditCollectionError(
            f"Unexpected Reddit collection failure: {exc}"
        ) from exc


def _build_research_prompt(
    subreddit_target: SubredditTarget,
    documents: Iterable[RedditPostDocument],
) -> str:
    payload = [
        asdict(document)
        for document in documents
    ]

    return f"""
You are a product-research analyst.

Analyze the supplied public discussion data for the niche:
{str(subreddit_target.niche.name)}

Subreddit:
r/{subreddit_target.subreddit_name}

Research keywords:
{", ".join(_normalize_keywords(subreddit_target.target_keywords))}

Your task is to identify distinct, evidence-grounded problems people
actually describe.

Return:
1. problems
2. corresponding content gaps
3. corresponding table or structured-resource ideas

Strict rules:
- Use only the supplied data.
- Do not invent statistics, demand, willingness to pay, or market size.
- Do not infer sensitive personal characteristics.
- Do not identify or profile individual users.
- Do not repeat the same problem using different wording.
- Keep problems, content_gaps, and table_ideas aligned by array index.
- Every problem must have exactly one content gap and one table idea.
- The table idea may be a comparison table, checklist, calculator,
  directory, matrix, tracker, or decision guide.
- Evidence text must be paraphrased and must not contain usernames.
- Return between 1 and 10 high-quality findings.
- Return JSON matching the provided response schema.

Discussion data:
{payload}
""".strip()


def _validate_gemini_result(data: Any) -> list[ResearchFinding]:
    if not isinstance(data, dict):
        raise GeminiAnalysisError(
            "Gemini returned a non-object JSON response."
        )

    problems = data.get("problems")
    content_gaps = data.get("content_gaps")
    table_ideas = data.get("table_ideas")

    if not isinstance(problems, list):
        raise GeminiAnalysisError(
            "Gemini response field 'problems' is not a list."
        )

    if not isinstance(content_gaps, list):
        raise GeminiAnalysisError(
            "Gemini response field 'content_gaps' is not a list."
        )

    if not isinstance(table_ideas, list):
        raise GeminiAnalysisError(
            "Gemini response field 'table_ideas' is not a list."
        )

    if not problems:
        return []

    if not (
        len(problems)
        == len(content_gaps)
        == len(table_ideas)
    ):
        raise GeminiAnalysisError(
            "Gemini returned arrays with different lengths."
        )

    findings: list[ResearchFinding] = []

    for index, problem in enumerate(problems):
        if not isinstance(problem, dict):
            raise GeminiAnalysisError(
                f"Problem item at index {index} is not an object."
            )

        problem_summary = _safe_text(
            problem.get("problem_summary"),
            max_length=3000,
        )

        evidence_text = _safe_text(
            problem.get("evidence_text"),
            max_length=5000,
        )

        content_gap = _safe_text(
            content_gaps[index],
            max_length=3000,
        )

        table_idea = _safe_text(
            table_ideas[index],
            max_length=3000,
        )

        if not problem_summary:
            continue

        findings.append(
            ResearchFinding(
                problem_summary=problem_summary,
                content_gap=content_gap,
                table_idea=table_idea,
                raw_extracted_text=evidence_text,
            )
        )

    return findings


def analyze_discussions_with_gemini(
    subreddit_target: SubredditTarget,
    documents: list[RedditPostDocument],
) -> list[ResearchFinding]:
    """
    Convert collected Reddit discussions into structured findings.
    """
    if not documents:
        return []

    client = get_gemini_client()

    prompt = _build_research_prompt(
        subreddit_target=subreddit_target,
        documents=documents,
    )

    try:
        response = client.models.generate_content(
            model=_required_setting("GEMINI_MODEL"),
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=getattr(
                    settings,
                    "GEMINI_MAX_OUTPUT_TOKENS",
                    4096,
                ),
                response_mime_type="application/json",
                response_json_schema=RESEARCH_RESPONSE_SCHEMA,
            ),
        )

        parsed = getattr(response, "parsed", None)

        if parsed is None:
            response_text = str(
                getattr(response, "text", "") or ""
            ).strip()

            if not response_text:
                raise GeminiAnalysisError(
                    "Gemini returned an empty response."
                )

            import json

            try:
                parsed = json.loads(response_text)
            except json.JSONDecodeError as exc:
                raise GeminiAnalysisError(
                    "Gemini returned invalid JSON."
                ) from exc

        return _validate_gemini_result(parsed)

    except GeminiAnalysisError:
        raise

    except Exception as exc:
        logger.exception(
            "Gemini analysis failed for target_id=%s",
            subreddit_target.pk,
        )

        raise GeminiAnalysisError(
            f"Gemini analysis failed: {exc}"
        ) from exc


def run_target_research(
    subreddit_target: SubredditTarget,
) -> list[ResearchFinding]:
    """
    Execute the complete collection and analysis pipeline for one target.
    """
    documents = fetch_reddit_discussions(
        subreddit_target=subreddit_target,
    )

    if not documents:
        logger.info(
            "No Reddit discussions found for target_id=%s",
            subreddit_target.pk,
        )
        return []

    return analyze_discussions_with_gemini(
        subreddit_target=subreddit_target,
        documents=documents,
    )