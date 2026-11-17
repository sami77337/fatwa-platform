from django.db import models


class ThrottleBucket(models.Model):
    """Shared synthetic HTTP throttling only; never stores a case or capability."""

    key = models.CharField(max_length=64, primary_key=True)
    window = models.BigIntegerField()
    requests = models.PositiveIntegerField()
