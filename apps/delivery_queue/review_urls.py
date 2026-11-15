"""Never included by public URL configurations."""
from django.urls import path
from . import review_http

urlpatterns = [
    path('review/operator/login/', review_http.operator_login, name='pg_operator_login'),
    path('review/operator/postgres/', review_http.report_page, name='pg_operator_report'),
    path('review/operator/postgres.json', review_http.report_json, name='pg_operator_report_json'),
    path('review/operator/queue.css', review_http.stylesheet, name='pg_operator_report_css'),
]
