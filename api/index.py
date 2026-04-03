"""Vercel entry point — imports the Flask app from web/app.py."""
import sys
import os

# Ensure project root is on the path so all local imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import app  # noqa: F401 — Vercel looks for 'app'
