"""Available Wave7 read-only service; selected only by the separate Wave7 profile."""
from django.urls import path

from apps.editorial_demo import views as editorial_views
from apps.reference import views as reference_views
from config.urls import urlpatterns as legacy_patterns


urlpatterns = [
    path('dev/wave7/api/batches', reference_views.api_workflow_batches, name='wave7_api_batches'),
    path('dev/wave7/api/items', reference_views.api_workflow_items, name='wave7_api_items'),
    path('dev/wave7/api/items/<str:ident>', reference_views.api_workflow_item, name='wave7_api_item'),
    path('dev/editorial-preview/persisted', editorial_views.persisted_review,
         name='wave7_editorial_review'),
    *legacy_patterns,
]
