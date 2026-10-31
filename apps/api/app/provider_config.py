"""One explicit provider choice for status, inference and cache identities."""
import os


def provider_name():
    return os.getenv("TRANSLATOR_PROVIDER", "mock").strip().lower()
