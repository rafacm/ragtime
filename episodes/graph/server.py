"""Django setup for LangGraph server.

LangGraph Studio loads graphs via Python imports. Since graph nodes
access Django ORM models, Django must be configured before the graph
module is imported.  This module is referenced in ``langgraph.json``
and ensures ``django.setup()`` runs first.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ragtime.settings")
django.setup()

# Re-export the compiled pipeline graph for LangGraph server
from episodes.graph.pipeline import pipeline as graph  # noqa: E402, F401
