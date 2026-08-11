"""Shared retention policy for large cached social-content fields."""

from datetime import timedelta

CONTENT_BODY_RETENTION = timedelta(days=90)
PROVIDER_RAW_RETENTION = timedelta(days=7)
