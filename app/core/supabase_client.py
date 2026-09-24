"""Supabase client singleton for DrugTime API."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy-initialized Supabase client singleton
_supabase_client = None
_supabase_init_attempted = False


def get_supabase_client():
    """
    Returns a Supabase client instance, or None if credentials are not configured.
    Uses lazy initialization to avoid import-time failures in test environments.
    """
    global _supabase_client, _supabase_init_attempted

    if _supabase_init_attempted:
        return _supabase_client

    _supabase_init_attempted = True

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_ANON_KEY")

    if not supabase_url or not supabase_key:
        logger.warning(
            "SUPABASE_URL or SUPABASE_ANON_KEY not set. "
            "Supabase Auth integration disabled; using mock auth."
        )
        return None

    try:
        from supabase import create_client
        _supabase_client = create_client(supabase_url, supabase_key)
        logger.info("Supabase client initialized successfully.")
        return _supabase_client
    except Exception as e:
        logger.error("Failed to initialize Supabase client: %s", e)
        return None


def reset_supabase_client():
    """Reset the singleton for testing purposes."""
    global _supabase_client, _supabase_init_attempted
    _supabase_client = None
    _supabase_init_attempted = False
