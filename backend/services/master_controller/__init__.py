"""
Master Controller Package

This package manages the high-level orchestration of validation, solving, explanation,
routing, and student state updates. It serves as the primary entry point for queries.
"""

from .query_normalizer import query_normalizer
from .intent_classifier import intent_classifier_service, QueryIntent
from .validation_gates import validation_gates_service
from .response_assembler import response_assembler_service, ControllerResponse, ControllerResult, DecisionTrace
from .fallback_handler import controller_fallback_handler
from .controller import master_controller

__all__ = [
    "query_normalizer",
    "intent_classifier_service",
    "validation_gates_service",
    "response_assembler_service",
    "controller_fallback_handler",
    "master_controller",
    "ControllerResponse",
    "ControllerResult",
    "DecisionTrace",
    "QueryIntent",
]
