"""Bibliometric Data Consolidation Tool."""

__version__ = "5.2.0"

from .application.models import WorkflowOptions, WorkflowPaths
from .application.workflow import AIWorkflow

__all__ = ["__version__", "AIWorkflow", "WorkflowOptions", "WorkflowPaths"]
