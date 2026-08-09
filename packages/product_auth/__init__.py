"""Minimal product-local bearer authentication middleware."""

from .middleware import install_bearer_auth

__all__ = ["install_bearer_auth"]
