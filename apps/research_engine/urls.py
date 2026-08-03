from django.urls import path

from apps.research_engine import views


app_name = "research_engine"


urlpatterns = [
    path(
        "insights/<int:insight_id>/outline/",
        views.generate_insight_outline,
        name="generate-insight-outline",
    ),
]