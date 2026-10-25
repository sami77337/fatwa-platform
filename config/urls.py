from django.urls import include, path

from apps.editorial_demo import views as editorial_views
from apps.public_site import views as public_views
from apps.reference import views

urlpatterns = [
    path("dev/research-bridge", include("apps.research_bridge.urls")),
    path("dev/editorial-search", include("apps.editorial_search.urls")),
    path("dev/editorial-dashboard", include("apps.editorial_dashboard.urls")),
    path("dev/editorial-export", include("apps.editorial_export.urls")),
    path("dev/editorial-followup", include("apps.editorial_followup.urls")),
    path("dev/reference-triage", include("apps.reference_triage.urls")),
    path("dev/editorial-queue", include("apps.editorial_queue.urls")),
    path("dev/editorial-workbench", include("apps.editorial_workbench.urls")),
    path("dev/editorial-preview", editorial_views.preview, name="editorial_demo"),
    path("dev/editorial-preview/style.css", editorial_views.stylesheet, name="editorial_demo_style"),
    path("dev/editorial-preview/pipeline", editorial_views.pipeline_preview, name="editorial_pipeline"),
    path(
        "dev/editorial-preview/pipeline/<str:ident>",
        editorial_views.pipeline_preview,
        name="editorial_pipeline_detail",
    ),
    path("dev/editorial-preview/revision-compare", editorial_views.revision_compare,
         name="editorial_revision_compare"),
    path("dev/editorial-preview/revision-compare.css", editorial_views.revision_compare_stylesheet,
         name="editorial_revision_compare_style"),
    path("dev/editorial-preview/revision-history", editorial_views.revision_history,
         name="editorial_revision_history"),
    path("dev/editorial-preview/<str:ident>", editorial_views.preview, name="editorial_demo_detail"),
    path("", public_views.home, name="home"),
    path("help", public_views.help_page, name="public_help"),
    path("fiqh", views.catalog, name="catalog"),
    path("fiqh/nodes/<int:ident>", views.catalog, name="heading"),
    path("fiqh/nodes/<int:ident>/children", views.branch, name="branch"),
    path("healthz", views.health, name="health"),
    path("readyz", views.ready, name="ready"),
    path("api/v1/status", views.status, name="status"),
    path("api/v1/fiqh/books", views.api_books, name="api_books"),
    path("api/v1/fiqh/roots", views.api_roots, name="api_roots"),
    path("api/v1/fiqh/search", views.api_search, name="api_search"),
    path("api/v1/fiqh/nodes/<int:ident>", views.api_node, name="api_node"),
    path("api/v1/fiqh/nodes/<int:ident>/children", views.api_children, name="api_children"),
    path("assets/<path:asset>", views.public_asset, name="public_asset"),
]
