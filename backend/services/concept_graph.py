"""
Services — Concept Graph

Loads a subject-matter dependency graph from data/concept_graph.json and exposes
prerequisite lookup, topological ordering, error/confusion metadata, and analogical
concept matching for the explanation path builder.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.diagnosis_engine import StudentProfile

_DEFAULT_GRAPH_PATH = Path(__file__).parent.parent / "data" / "concept_graph.json"


class ConceptGraph:
    """
    In-memory directed acyclic graph of STEM concepts.

    Each node stores: requires[], connects_to[], common_errors[],
    confusion_points[], curriculum[].
    """

    def __init__(self, data_path: str | Path = _DEFAULT_GRAPH_PATH) -> None:
        with open(data_path, encoding="utf-8") as fh:
            raw: list[dict[str, Any]] = json.load(fh)
        self.nodes: dict[str, dict[str, Any]] = {node["id"]: node for node in raw}

    # ------------------------------------------------------------------ #
    # Core graph queries                                                   #
    # ------------------------------------------------------------------ #

    def get_prerequisites(self, topic: str) -> list[str]:
        """
        Return all transitive prerequisites for *topic* in topological order
        (deepest dependency first, topic itself excluded).
        """
        visited: set[str] = set()
        result: list[str] = []
        self._dfs_prereqs(topic, visited, result)
        return [t for t in result if t != topic]

    def topological_sort(self, concepts: list[str]) -> list[str]:
        """
        Return *concepts* in dependency order using Kahn's algorithm.

        Prerequisites appear before the concepts that depend on them.
        Cycles (if any) are appended at the end without ordering guarantees.
        """
        concept_set = set(concepts)
        in_degree: dict[str, int] = {c: 0 for c in concepts}
        adj: dict[str, list[str]] = {c: [] for c in concepts}

        for concept in concepts:
            node = self.nodes.get(concept, {})
            for prereq in node.get("requires", []):
                if prereq in concept_set:
                    adj[prereq].append(concept)
                    in_degree[concept] += 1

        queue: deque[str] = deque(c for c in concepts if in_degree[c] == 0)
        sorted_list: list[str] = []
        while queue:
            node_id = queue.popleft()
            sorted_list.append(node_id)
            for neighbor in adj[node_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        remaining = [c for c in concepts if c not in sorted_list]
        return sorted_list + remaining

    def get_common_errors(self, topic: str) -> list[str]:
        """Return the list of documented common errors for *topic*."""
        return list(self.nodes.get(topic, {}).get("common_errors", []))

    def get_confusion_points(self, topic: str) -> list[str]:
        """Return the list of documented confusion points for *topic*."""
        return list(self.nodes.get(topic, {}).get("confusion_points", []))

    def find_analogous_concept(
        self, unknown: str, known_concepts: list[str]
    ) -> str | None:
        """
        Return the *known_concepts* entry most structurally analogous to *unknown*.

        Scoring heuristic:
        - Same subject as unknown: +3
        - Direct graph neighbour of unknown: +2
        - Shared prerequisite with unknown: +1 per shared prereq
        """
        if not known_concepts:
            return None

        unknown_node = self.nodes.get(unknown, {})
        unknown_subject = unknown_node.get("subject", "")
        unknown_prereqs = set(unknown_node.get("requires", []))
        unknown_neighbors = unknown_prereqs | set(unknown_node.get("connects_to", []))

        best: str | None = None
        best_score = -1

        for concept in known_concepts:
            node = self.nodes.get(concept, {})
            score = 0

            if node.get("subject") == unknown_subject:
                score += 3

            concept_all_neighbors = (
                set(node.get("requires", [])) | set(node.get("connects_to", []))
            )
            if concept in unknown_neighbors or unknown in concept_all_neighbors:
                score += 2

            concept_prereqs = set(node.get("requires", []))
            score += len(unknown_prereqs & concept_prereqs)

            if score > best_score:
                best_score = score
                best = concept

        return best

    def get_teaching_path(self, topic: str, student_profile: "StudentProfile") -> list[str]:
        """
        Return the topologically ordered list of concepts that a student needs
        before (and including) *topic*, excluding concepts they are already strong on.
        """
        prereqs = self.get_prerequisites(topic)
        all_concepts = prereqs + ([topic] if topic in self.nodes else [])
        strong_set = set(student_profile.strong)
        need_to_teach = [c for c in all_concepts if c not in strong_set]
        return self.topological_sort(need_to_teach)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _dfs_prereqs(
        self, topic: str, visited: set[str], result: list[str]
    ) -> None:
        """Post-order DFS — collects prerequisites before dependents."""
        if topic in visited:
            return
        visited.add(topic)
        for req in self.nodes.get(topic, {}).get("requires", []):
            self._dfs_prereqs(req, visited, result)
        result.append(topic)


# Module-level singleton — reused across the process lifetime.
_concept_graph_instance: ConceptGraph | None = None


def get_concept_graph() -> ConceptGraph:
    """Return the lazily-initialised module-level ConceptGraph singleton."""
    global _concept_graph_instance
    if _concept_graph_instance is None:
        _concept_graph_instance = ConceptGraph()
    return _concept_graph_instance
