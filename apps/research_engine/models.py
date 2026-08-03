from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class Niche(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True,
        help_text="The niche name, such as Travel, Decor, Local City, or Coupon Deals.",
    )
    description = models.TextField(
        blank=True,
        help_text="A short description of the niche and its research scope.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Controls whether this niche is available for research runs.",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Niche"
        verbose_name_plural = "Niches"

    def __str__(self) -> str:
        return self.name


class SubredditTarget(models.Model):
    niche = models.ForeignKey(
        Niche,
        on_delete=models.CASCADE,
        related_name="subreddit_targets",
    )
    subreddit_name = models.CharField(
        max_length=100,
        help_text="The subreddit name without the r/ prefix, for example: travel.",
    )
    target_keywords = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "A JSON list of keywords to search inside this subreddit, "
            'for example: ["airport transfer", "hidden fee", "travel scam"].'
        ),
    )

    class Meta:
        ordering = ["niche__name", "subreddit_name"]
        verbose_name = "Subreddit Target"
        verbose_name_plural = "Subreddit Targets"
        constraints = [
            models.UniqueConstraint(
                fields=["niche", "subreddit_name"],
                name="unique_subreddit_per_niche",
            ),
        ]
        indexes = [
            models.Index(
                fields=["niche", "subreddit_name"],
                name="research_subreddit_idx",
            ),
        ]

    def clean(self) -> None:
        super().clean()

        if not isinstance(self.target_keywords, list):
            raise ValidationError(
                {
                    "target_keywords": (
                        "Target keywords must be stored as a JSON list."
                    )
                }
            )

        invalid_keywords = [
            keyword
            for keyword in self.target_keywords
            if not isinstance(keyword, str) or not keyword.strip()
        ]

        if invalid_keywords:
            raise ValidationError(
                {
                    "target_keywords": (
                        "Every target keyword must be a non-empty string."
                    )
                }
            )

    def save(self, *args, **kwargs) -> None:
        self.subreddit_name = self.subreddit_name.strip()

        if self.subreddit_name.lower().startswith("r/"):
            self.subreddit_name = self.subreddit_name[2:]

        self.subreddit_name = slugify(
            self.subreddit_name,
            allow_unicode=True,
        )

        self.target_keywords = [
            keyword.strip()
            for keyword in self.target_keywords
            if isinstance(keyword, str) and keyword.strip()
        ]

        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"r/{self.subreddit_name} — {self.niche.name}"


class ResearchInsight(models.Model):
    niche = models.ForeignKey(
        Niche,
        on_delete=models.CASCADE,
        related_name="research_insights",
    )
    problem_summary = models.TextField(
        help_text="A concise summary of the user problem or pain point.",
    )
    content_gap = models.TextField(
        blank=True,
        help_text="The missing information, product, service, or solution gap.",
    )
    recommended_table_idea = models.TextField(
        blank=True,
        help_text=(
            "A recommended comparison table, checklist, directory, calculator, "
            "or structured solution idea based on the discovered problem."
        ),
    )
    raw_extracted_text = models.TextField(
        blank=True,
        help_text=(
            "The raw or cleaned discussion text used to generate this insight."
        ),
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Research Insight"
        verbose_name_plural = "Research Insights"
        indexes = [
            models.Index(
                fields=["niche", "-created_at"],
                name="research_niche_date_idx",
            ),
        ]

    def __str__(self) -> str:
        summary = self.problem_summary.strip()

        if len(summary) > 70:
            summary = f"{summary[:67]}..."

        return f"{self.niche.name}: {summary}"