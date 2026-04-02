"""
Curriculum Knowledge Graph

Represents STEM topics and prerequisite dependencies as an extensible
adjacency-list graph with alias matching, mastery decay, weighted gap
severity, and globally-aware topic recommendations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp
from typing import Any


MIN_ALIAS_CONFIDENCE = 0.62
DEFAULT_RECOMMENDATION_MASTERY = 0.68
MASTERY_DECAY_LAMBDA = 0.012


@dataclass(frozen=True)
class TopicNode:
    topic_id: str
    subject: str
    label: str
    prerequisites: tuple[str, ...]
    difficulty: int
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


def load_curriculum() -> dict[str, Any]:
    """
    Return the curriculum graph in adjacency-list form.

    Structure:
    {
        "topics": {topic_id: TopicNode},
        "adjacency": {prereq_topic_id: [dependent_topic_id, ...]},
        "subject_index": {subject: [topic_id, ...]},
        "alias_index": {normalized_alias: [topic_id, ...]},
    }
    """
    topics = _build_topic_nodes()
    adjacency: dict[str, list[str]] = {topic_id: [] for topic_id in topics}
    subject_index: dict[str, list[str]] = {}
    alias_index: dict[str, list[str]] = {}

    for topic_id, node in topics.items():
        subject_index.setdefault(node.subject, []).append(topic_id)
        for prereq in node.prerequisites:
            adjacency.setdefault(prereq, []).append(topic_id)

        alias_terms = {node.label, topic_id, *node.tags, *node.aliases}
        for alias in alias_terms:
            alias_index.setdefault(_normalize_topic_id(alias), []).append(topic_id)

    for dependent_ids in adjacency.values():
        dependent_ids.sort()
    for subject, topic_ids in subject_index.items():
        subject_index[subject] = sorted(
            topic_ids,
            key=lambda item: (topics[item].difficulty, topics[item].label),
        )
    for alias, topic_ids in alias_index.items():
        alias_index[alias] = sorted(set(topic_ids))

    return {
        "topics": topics,
        "adjacency": adjacency,
        "subject_index": subject_index,
        "alias_index": alias_index,
    }


def get_prerequisites(topic: str) -> list[str]:
    """Return transitive prerequisites for a topic in learning order."""
    graph = load_curriculum()
    resolution = _resolve_topic(graph, topic)
    if resolution["topic_id"] is None:
        return []

    prerequisite_ids = _collect_prerequisite_ids(graph, resolution["topic_id"])
    return [graph["topics"][prereq_id].label for prereq_id in prerequisite_ids]


def find_knowledge_gaps(topic: str, student_model: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Return weighted prerequisite gaps for the requested topic.

    Severity is continuous rather than binary:
    - 0.00 means no meaningful gap
    - 1.00 means severe prerequisite weakness
    """
    graph = load_curriculum()
    resolution = _resolve_topic(graph, topic)
    topic_id = resolution["topic_id"]
    if topic_id is None:
        return []

    target_node = graph["topics"][topic_id]
    mastery_lookup = _build_mastery_lookup(student_model, graph)
    gaps: list[dict[str, Any]] = []

    for prereq_id in _collect_prerequisite_ids(graph, topic_id):
        node = graph["topics"][prereq_id]
        mastery_info = mastery_lookup.get(prereq_id)
        effective_mastery = mastery_info["effective_mastery"] if mastery_info else 0.0
        raw_mastery = mastery_info["raw_mastery"] if mastery_info else None
        required_mastery = _required_mastery_for(target_node, node)
        severity = _gap_severity(effective_mastery, required_mastery)

        if severity < 0.03:
            continue

        gaps.append(
            {
                "topic_id": node.topic_id,
                "topic": node.label,
                "subject": node.subject,
                "mastery": round(raw_mastery, 2) if raw_mastery is not None else None,
                "effective_mastery": round(effective_mastery, 2),
                "required_mastery": round(required_mastery, 2),
                "gap": round(max(0.0, required_mastery - effective_mastery), 2),
                "severity": round(severity, 2),
                "severity_label": _severity_label(severity),
                "difficulty": node.difficulty,
                "stale": bool(mastery_info and mastery_info["decay_factor"] < 0.92),
            }
        )

    return sorted(gaps, key=lambda item: (-item["severity"], item["difficulty"], item["topic"]))


def suggest_next_topic(student_model: dict[str, Any]) -> dict[str, Any] | None:
    """
    Suggest the next best topic to study.

    Global strategy:
    - recover severe gaps in weak subjects first
    - avoid large difficulty jumps when mastery is fragile
    - prefer review when decay has made prior knowledge stale
    - otherwise choose the best unlocked next topic across the graph
    """
    graph = load_curriculum()
    mastery_lookup = _build_mastery_lookup(student_model, graph)
    weak_subjects = _weak_subject_priorities(student_model, graph)

    weak_area_recovery = _recommend_gap_recovery(graph, student_model, mastery_lookup, weak_subjects)
    if weak_area_recovery is not None:
        return weak_area_recovery

    stale_review = _recommend_stale_review(graph, mastery_lookup, weak_subjects)
    if stale_review is not None:
        return stale_review

    best: tuple[float, TopicNode, str] | None = None
    for node in graph["topics"].values():
        prereq_mastery = [
            mastery_lookup.get(prereq, _empty_mastery())["effective_mastery"]
            for prereq in node.prerequisites
        ]
        if any(value < _required_mastery_for(node, graph["topics"][prereq]) for prereq, value in zip(node.prerequisites, prereq_mastery)):
            continue

        topic_mastery = mastery_lookup.get(node.topic_id, _empty_mastery())
        current_mastery = topic_mastery["effective_mastery"]
        if current_mastery >= 0.86:
            continue

        score = _candidate_score(node, topic_mastery, weak_subjects)
        reason = _candidate_reason(node, topic_mastery, weak_subjects)
        candidate = (score, node, reason)
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is None:
        return None

    _, node, reason = best
    return _recommendation(node, mastery_lookup, reason)


EXAMPLE_QUERIES: dict[str, Any] = {
    "get_prerequisites('applications_of_derivatives')": [
        "Arithmetic",
        "Fractions",
        "Algebra basics",
        "Functions and graphs",
        "Limits",
        "Derivatives",
    ],
    "find_knowledge_gaps('applications_of_derivatives', student_model)": [
        {
            "topic": "Limits",
            "effective_mastery": 0.42,
            "required_mastery": 0.73,
            "severity": 0.42,
            "severity_label": "high",
        }
    ],
    "suggest_next_topic(student_model)": {
        "topic": "Introduction to integration",
        "subject": "math",
        "current_mastery": 0.0,
        "effective_mastery": 0.0,
        "difficulty": 3,
        "reason": "This topic strengthens the student's weakest active subject without a risky difficulty jump.",
    },
}


def _build_topic_nodes() -> dict[str, TopicNode]:
    topic_definitions = [
        TopicNode("arithmetic", "math", "Arithmetic", (), 1, ("numbers", "operations"), ("basic arithmetic",)),
        TopicNode("fractions", "math", "Fractions", ("arithmetic",), 1, ("ratios",), ()),
        TopicNode("algebra_basics", "math", "Algebra basics", ("fractions",), 2, ("variables", "equations"), ("intro algebra",)),
        TopicNode("functions_graphs", "math", "Functions and graphs", ("algebra_basics",), 2, ("functions", "graphs"), ("function basics",)),
        TopicNode("limits", "math", "Limits", ("functions_graphs",), 3, ("calculus",), ("limit basics",)),
        TopicNode("derivatives", "math", "Derivatives", ("limits",), 3, ("calculus", "rate_of_change"), ("differentiation",)),
        TopicNode("applications_of_derivatives", "math", "Applications of derivatives", ("derivatives",), 4, ("optimization", "curve_sketching"), ()),
        TopicNode("introduction_to_integration", "math", "Introduction to integration", ("derivatives",), 3, ("calculus", "area"), ("integration basics", "integral basics", "intro integration")),
        TopicNode("definite_integration", "math", "Definite integration", ("introduction_to_integration",), 4, ("calculus", "area_under_curve"), ("definite integrals",)),
        TopicNode("advanced_integration_techniques", "math", "Advanced integration techniques", ("definite_integration",), 5, ("calculus", "substitution", "parts"), ("integration techniques",)),
        TopicNode("vectors", "physics", "Vectors", ("algebra_basics",), 2, ("magnitude", "direction"), ()),
        TopicNode("kinematics", "physics", "Kinematics", ("arithmetic", "algebra_basics", "vectors"), 2, ("motion",), ()),
        TopicNode("newtons_laws", "physics", "Newton's laws", ("kinematics",), 3, ("forces", "dynamics"), ("newton laws",)),
        TopicNode("work_energy", "physics", "Work and energy", ("newtons_laws",), 3, ("energy",), ()),
        TopicNode("electrostatics", "physics", "Electrostatics", ("algebra_basics",), 4, ("charge", "field"), ()),
        TopicNode("atomic_structure", "chemistry", "Atomic structure", (), 1, ("atoms",), ()),
        TopicNode("periodic_table", "chemistry", "Periodic table", ("atomic_structure",), 2, ("elements",), ()),
        TopicNode("chemical_bonding", "chemistry", "Chemical bonding", ("atomic_structure", "periodic_table"), 3, ("ionic", "covalent"), ()),
        TopicNode("stoichiometry", "chemistry", "Stoichiometry", ("chemical_bonding", "fractions"), 4, ("moles", "reactions"), ()),
        TopicNode("acids_bases", "chemistry", "Acids and bases", ("chemical_bonding",), 3, ("ph",), ("acid base basics",)),
        TopicNode("programming_basics", "coding", "Programming basics", (), 1, ("syntax", "variables"), ("coding basics",)),
        TopicNode("control_flow", "coding", "Control flow", ("programming_basics",), 2, ("conditions", "loops"), ()),
        TopicNode("functions_coding", "coding", "Functions", ("control_flow",), 2, ("abstraction",), ("coding functions",)),
        TopicNode("data_structures", "coding", "Data structures", ("functions_coding",), 3, ("lists", "maps"), ()),
        TopicNode("algorithms_basics", "coding", "Algorithms basics", ("data_structures",), 4, ("search", "sort"), ("algorithms",)),
        TopicNode("cells", "biology", "Cells", (), 1, ("cell_theory",), ()),
        TopicNode("biomolecules", "biology", "Biomolecules", ("cells",), 2, ("proteins", "lipids", "carbs"), ()),
        TopicNode("genetics_basics", "biology", "Genetics basics", ("cells",), 3, ("dna", "inheritance"), ("genetics",)),
        TopicNode("photosynthesis", "biology", "Photosynthesis", ("cells", "biomolecules"), 3, ("plants", "energy"), ()),
        TopicNode("respiration", "biology", "Respiration", ("cells", "biomolecules"), 3, ("atp", "energy"), ("cellular respiration",)),
    ]
    return {node.topic_id: node for node in topic_definitions}


def _collect_prerequisite_ids(graph: dict[str, Any], topic_id: str) -> list[str]:
    ordered: list[str] = []
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        for prereq_id in graph["topics"][node_id].prerequisites:
            if prereq_id in visited:
                continue
            visit(prereq_id)
            visited.add(prereq_id)
            ordered.append(prereq_id)

    visit(topic_id)
    return ordered


def _build_mastery_lookup(student_model: dict[str, Any], graph: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
    graph = graph or load_curriculum()
    lookup: dict[str, dict[str, float]] = {}
    for topic in student_model.get("topics") or []:
        resolution = _resolve_topic(graph, topic.get("topic"))
        topic_id = resolution["topic_id"]
        if not topic_id:
            continue

        raw_mastery = _coerce_float(topic.get("mastery"), default=0.0)
        last_seen_at = topic.get("last_interacted_at")
        decay_factor = _mastery_decay_factor(last_seen_at)
        effective_mastery = raw_mastery * decay_factor
        lookup[topic_id] = {
            "raw_mastery": raw_mastery,
            "effective_mastery": effective_mastery,
            "decay_factor": decay_factor,
            "last_interacted_at": last_seen_at,
        }
    return lookup


def _recommend_gap_recovery(
    graph: dict[str, Any],
    student_model: dict[str, Any],
    mastery_lookup: dict[str, dict[str, float]],
    weak_subjects: dict[str, float],
) -> dict[str, Any] | None:
    best: tuple[float, dict[str, Any]] | None = None
    for weak in student_model.get("weak_areas") or []:
        weak_resolution = _resolve_topic(graph, weak.get("topic"))
        weak_id = weak_resolution["topic_id"]
        if weak_id is None:
            continue

        weak_node = graph["topics"][weak_id]
        for gap in find_knowledge_gaps(weak_id, student_model):
            gap_node = graph["topics"][gap["topic_id"]]
            score = (
                gap["severity"] * 2.2
                + weak_subjects.get(gap_node.subject, 0.0) * 0.9
                - abs(weak_node.difficulty - gap_node.difficulty) * 0.12
                - max(0, gap_node.difficulty - 4) * 0.25
            )
            reason = (
                "This topic repairs a high-severity prerequisite gap in the student's weakest active subject."
                if gap_node.subject == weak_node.subject
                else "This prerequisite repair unlocks progress on a current weak area."
            )
            recommendation = _recommendation(gap_node, mastery_lookup, reason)
            recommendation["gap_severity"] = gap["severity"]
            recommendation["recommended_for"] = weak_node.label
            if best is None or score > best[0]:
                best = (score, recommendation)

    return best[1] if best else None


def _candidate_score(
    node: TopicNode,
    topic_mastery: dict[str, float],
    weak_subjects: dict[str, float],
) -> float:
    current_mastery = topic_mastery["effective_mastery"]
    raw_mastery = topic_mastery["raw_mastery"]
    decay_factor = topic_mastery["decay_factor"]

    review_bonus = 0.45 if raw_mastery >= 0.65 and decay_factor < 0.8 else 0.0
    weak_subject_bonus = weak_subjects.get(node.subject, 0.0) * 0.8
    mastery_need = max(0.0, DEFAULT_RECOMMENDATION_MASTERY - current_mastery)
    difficulty_penalty = 0.0
    if current_mastery < 0.45:
        difficulty_penalty += max(0, node.difficulty - 3) * 0.6
    elif current_mastery < 0.65:
        difficulty_penalty += max(0, node.difficulty - 4) * 0.4

    return (
        mastery_need * 1.1
        + review_bonus
        + weak_subject_bonus
        - difficulty_penalty
        - (node.difficulty * 0.08)
    )


def _recommend_stale_review(
    graph: dict[str, Any],
    mastery_lookup: dict[str, dict[str, float]],
    weak_subjects: dict[str, float],
) -> dict[str, Any] | None:
    best: tuple[float, TopicNode, str] | None = None
    for topic_id, mastery_info in mastery_lookup.items():
        if mastery_info["raw_mastery"] < 0.7 or mastery_info["decay_factor"] >= 0.8:
            continue

        node = graph["topics"][topic_id]
        unlocked_dependents = [
            dependent_id
            for dependent_id in graph["adjacency"].get(topic_id, [])
            if all(
                mastery_lookup.get(prereq, _empty_mastery())["effective_mastery"] >= _required_mastery_for(graph["topics"][dependent_id], graph["topics"][prereq])
                for prereq in graph["topics"][dependent_id].prerequisites
                if prereq != topic_id
            )
        ]
        if not unlocked_dependents:
            continue

        score = (
            (1.0 - mastery_info["decay_factor"]) * 1.8
            + mastery_info["raw_mastery"] * 0.25
            + weak_subjects.get(node.subject, 0.0) * 0.6
        )
        reason = "This topic was previously learned, but decayed mastery suggests it should be revised before advancing."
        candidate = (score, node, reason)
        if best is None or score > best[0]:
            best = candidate

    if best is None:
        return None

    _, node, reason = best
    return _recommendation(node, mastery_lookup, reason)


def _candidate_reason(
    node: TopicNode,
    topic_mastery: dict[str, float],
    weak_subjects: dict[str, float],
) -> str:
    if topic_mastery["raw_mastery"] >= 0.65 and topic_mastery["decay_factor"] < 0.8:
        return "This topic was previously learned, but decayed mastery suggests it should be revised before advancing."
    if weak_subjects.get(node.subject, 0.0) >= 0.2:
        return "This topic strengthens the student's weakest active subject without a risky difficulty jump."
    return "All prerequisites are satisfied and this is the most accessible unlocked topic."


def _recommendation(
    node: TopicNode,
    mastery_lookup: dict[str, dict[str, float]],
    reason: str,
) -> dict[str, Any]:
    topic_mastery = mastery_lookup.get(node.topic_id, _empty_mastery())
    return {
        "topic": node.label,
        "subject": node.subject,
        "current_mastery": round(topic_mastery["raw_mastery"], 2),
        "effective_mastery": round(topic_mastery["effective_mastery"], 2),
        "difficulty": node.difficulty,
        "reason": reason,
    }


def _required_mastery_for(target_node: TopicNode, prereq_node: TopicNode) -> float:
    base = 0.55
    target_adjustment = max(0, target_node.difficulty - 2) * 0.06
    prereq_adjustment = max(0, prereq_node.difficulty - 2) * 0.03
    return min(0.88, base + target_adjustment + prereq_adjustment)


def _gap_severity(effective_mastery: float, required_mastery: float) -> float:
    gap = max(0.0, required_mastery - effective_mastery)
    if gap <= 0.0:
        return 0.0
    severity = gap / max(required_mastery, 0.01)
    if effective_mastery < 0.25:
        severity += 0.18
    elif effective_mastery < 0.45:
        severity += 0.08
    return min(1.0, severity)


def _severity_label(severity: float) -> str:
    if severity >= 0.75:
        return "critical"
    if severity >= 0.45:
        return "high"
    if severity >= 0.2:
        return "medium"
    return "low"


def _weak_subject_priorities(student_model: dict[str, Any], graph: dict[str, Any]) -> dict[str, float]:
    subject_scores: dict[str, list[float]] = {}
    mastery_lookup = _build_mastery_lookup(student_model, graph)

    for topic_id, mastery_info in mastery_lookup.items():
        subject = graph["topics"][topic_id].subject
        subject_scores.setdefault(subject, []).append(mastery_info["effective_mastery"])

    priorities: dict[str, float] = {}
    for weak in student_model.get("weak_areas") or []:
        resolution = _resolve_topic(graph, weak.get("topic"))
        topic_id = resolution["topic_id"]
        if topic_id is None:
            continue
        subject = graph["topics"][topic_id].subject
        priorities[subject] = priorities.get(subject, 0.0) + 0.25

    for subject, values in subject_scores.items():
        average = sum(values) / max(len(values), 1)
        priorities[subject] = priorities.get(subject, 0.0) + max(0.0, 0.72 - average)

    return priorities


def _mastery_decay_factor(last_seen_at: Any) -> float:
    if not last_seen_at:
        return 1.0

    try:
        if isinstance(last_seen_at, datetime):
            timestamp = last_seen_at
        else:
            normalized = str(last_seen_at).replace("Z", "+00:00")
            timestamp = datetime.fromisoformat(normalized)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 1.0

    age_days = max(0.0, (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds() / 86400)
    return max(0.35, exp(-MASTERY_DECAY_LAMBDA * age_days))


def _resolve_topic(graph: dict[str, Any], topic: Any) -> dict[str, Any]:
    query = _normalize_topic_id(topic)
    if not query:
        return {"topic_id": None, "confidence": 0.0, "matched_on": None}

    if query in graph["topics"]:
        return {"topic_id": query, "confidence": 1.0, "matched_on": "topic_id"}

    alias_hits = graph["alias_index"].get(query)
    if alias_hits:
        return {"topic_id": alias_hits[0], "confidence": 0.98, "matched_on": "alias"}

    best_topic_id = None
    best_score = 0.0
    for topic_id, node in graph["topics"].items():
        score = _topic_similarity(query, node)
        if score > best_score:
            best_score = score
            best_topic_id = topic_id

    if best_topic_id is None or best_score < MIN_ALIAS_CONFIDENCE:
        return {"topic_id": None, "confidence": round(best_score, 2), "matched_on": "unresolved"}

    return {"topic_id": best_topic_id, "confidence": round(best_score, 2), "matched_on": "fuzzy"}


def _topic_similarity(query: str, node: TopicNode) -> float:
    candidates = [node.label, node.topic_id, *node.tags, *node.aliases]
    query_tokens = set(_normalize_topic_id(query).split("_"))
    best = 0.0

    for candidate in candidates:
        normalized_candidate = _normalize_topic_id(candidate)
        candidate_tokens = set(normalized_candidate.split("_"))
        if not candidate_tokens:
            continue

        overlap = len(query_tokens & candidate_tokens)
        token_score = overlap / max(len(candidate_tokens), len(query_tokens), 1)
        prefix_bonus = 0.18 if normalized_candidate.startswith(query) or query.startswith(normalized_candidate) else 0.0
        exact_bonus = 0.35 if normalized_candidate == query else 0.0
        score = min(1.0, token_score + prefix_bonus + exact_bonus)
        best = max(best, score)

    return best


def _empty_mastery() -> dict[str, float]:
    return {
        "raw_mastery": 0.0,
        "effective_mastery": 0.0,
        "decay_factor": 1.0,
        "last_interacted_at": None,
    }


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_topic_id(topic: Any) -> str:
    text = str(topic or "").strip().lower()
    text = text.replace("&", "and")
    cleaned = []
    previous_was_separator = False
    for char in text:
        if char.isalnum():
            cleaned.append(char)
            previous_was_separator = False
        else:
            if not previous_was_separator:
                cleaned.append("_")
            previous_was_separator = True
    return "".join(cleaned).strip("_")
