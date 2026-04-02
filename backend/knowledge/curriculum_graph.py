"""Shim that loads the repository-level curriculum graph module."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


_ROOT_MODULE_PATH = Path(__file__).resolve().parents[2] / "knowledge" / "curriculum_graph.py"
_SPEC = spec_from_file_location("shared_curriculum_graph", _ROOT_MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load curriculum graph module from {_ROOT_MODULE_PATH}")

_MODULE = module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

load_curriculum = _MODULE.load_curriculum
get_prerequisites = _MODULE.get_prerequisites
find_knowledge_gaps = _MODULE.find_knowledge_gaps
suggest_next_topic = _MODULE.suggest_next_topic
EXAMPLE_QUERIES = _MODULE.EXAMPLE_QUERIES
TopicNode = _MODULE.TopicNode
