from django.urls import path

from . import views

urlpatterns = [
    path(
        "casework/staff/recording-parts/<uuid:part_id>/audio/",
        views.staff_audio,
        name="recording_part_audio",
    ),
    path(
        "casework/staff/recording-transcripts/<uuid:transcript_id>/audio/",
        views.staff_audio,
        name="recording_transcript_audio",
    ),
    path(
        "casework/staff/recording-transcripts/<uuid:transcript_id>/segments/<int:index>/",
        views.staff_segment,
        name="recording_transcript_segment",
    ),
    path(
        "library-preview/publications/<uuid:publication_id>/recordings/",
        views.publication_detail,
        name="publication_recordings",
    ),
    path(
        "library-preview/recordings/<uuid:media_id>/audio/",
        views.public_audio,
        name="public_recording_audio",
    ),
    path(
        "library-preview/recordings/<uuid:media_id>/segments/<int:index>/",
        views.public_segment,
        name="public_recording_segment",
    ),
]
