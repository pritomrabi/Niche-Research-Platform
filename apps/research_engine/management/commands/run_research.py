from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.research_engine.models import (
    Niche,
    ResearchInsight,
    SubredditTarget,
)
from apps.research_engine.services.research_service import (
    GeminiAnalysisError,
    RedditCollectionError,
    ResearchConfigurationError,
    run_target_research,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Collect Reddit discussions for active niches, analyze them with "
        "Gemini, and save ResearchInsight records."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--niche",
            type=str,
            default=None,
            help=(
                "Run only one niche by exact name or case-insensitive name."
            ),
        )

        parser.add_argument(
            "--target-id",
            type=int,
            default=None,
            help="Run only one SubredditTarget by database ID.",
        )

        parser.add_argument(
            "--continue-on-error",
            action="store_true",
            help=(
                "Continue processing other targets if one target fails."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Run collection and Gemini analysis without saving findings."
            ),
        )

    def handle(self, *args, **options) -> None:
        niche_name = options["niche"]
        target_id = options["target_id"]
        continue_on_error = options["continue_on_error"]
        dry_run = options["dry_run"]

        niches = Niche.objects.filter(
            is_active=True,
        ).order_by("name")

        if niche_name:
            niches = niches.filter(
                name__iexact=niche_name.strip(),
            )

        if not niches.exists():
            raise CommandError(
                "No matching active niches were found."
            )

        targets = (
            SubredditTarget.objects
            .select_related("niche")
            .filter(
                niche__in=niches,
                niche__is_active=True,
            )
            .order_by(
                "niche__name",
                "subreddit_name",
            )
        )

        if target_id is not None:
            targets = targets.filter(pk=target_id)

        if not targets.exists():
            raise CommandError(
                "No matching SubredditTarget records were found."
            )

        total_targets = targets.count()
        successful_targets = 0
        failed_targets = 0
        empty_targets = 0
        saved_insights = 0

        self.stdout.write(
            self.style.NOTICE(
                f"Starting research for {total_targets} target(s)."
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "Dry-run mode is enabled. No database records "
                    "will be created."
                )
            )

        for target in targets.iterator():
            label = (
                f"{target.niche.name} / "
                f"r/{target.subreddit_name}"
            )

            self.stdout.write(
                f"\nProcessing {label}..."
            )

            try:
                findings = run_target_research(target)

                if not findings:
                    empty_targets += 1

                    self.stdout.write(
                        self.style.WARNING(
                            f"No findings generated for {label}."
                        )
                    )
                    continue

                if dry_run:
                    successful_targets += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Generated {len(findings)} finding(s) "
                            f"for {label}; nothing saved."
                        )
                    )

                    for finding in findings:
                        self.stdout.write(
                            f"  - {finding.problem_summary}"
                        )

                    continue

                insight_objects = [
                    ResearchInsight(
                        niche=target.niche,
                        problem_summary=finding.problem_summary,
                        content_gap=finding.content_gap,
                        recommended_table_idea=finding.table_idea,
                        raw_extracted_text=(
                            f"Source: r/{target.subreddit_name}\n"
                            f"Evidence summary: "
                            f"{finding.raw_extracted_text}"
                        ),
                    )
                    for finding in findings
                ]

                with transaction.atomic():
                    created_objects = (
                        ResearchInsight.objects.bulk_create(
                            insight_objects,
                        )
                    )

                created_count = len(created_objects)

                saved_insights += created_count
                successful_targets += 1

                self.stdout.write(
                    self.style.SUCCESS(
                        f"Saved {created_count} insight(s) "
                        f"for {label}."
                    )
                )

            except (
                ResearchConfigurationError,
                RedditCollectionError,
                GeminiAnalysisError,
            ) as exc:
                failed_targets += 1

                logger.exception(
                    "Research target failed: target_id=%s",
                    target.pk,
                )

                message = f"{label} failed: {exc}"

                if continue_on_error:
                    self.stderr.write(
                        self.style.ERROR(message)
                    )
                    continue

                raise CommandError(message) from exc

            except Exception as exc:
                failed_targets += 1

                logger.exception(
                    "Unexpected research failure: target_id=%s",
                    target.pk,
                )

                message = (
                    f"Unexpected failure for {label}: {exc}"
                )

                if continue_on_error:
                    self.stderr.write(
                        self.style.ERROR(message)
                    )
                    continue

                raise CommandError(message) from exc

        self.stdout.write("\nResearch run completed.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Successful targets: {successful_targets}"
            )
        )

        self.stdout.write(
            f"Targets without findings: {empty_targets}"
        )

        self.stdout.write(
            f"Failed targets: {failed_targets}"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Insights saved: {saved_insights}"
            )
        )