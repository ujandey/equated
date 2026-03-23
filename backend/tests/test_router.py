"""
Tests — AI Router Unit Tests
"""

import pytest
from ai.classifier import ProblemClassifier, SubjectCategory, ComplexityLevel
from ai.router import ModelRouter, ModelProvider


class TestClassifier:
    def setup_method(self):
        self.classifier = ProblemClassifier()

    def test_math_classification(self):
        result = self.classifier.classify("Solve the equation 2x + 3 = 7")
        assert result.subject == SubjectCategory.MATH

    def test_physics_classification(self):
        result = self.classifier.classify("Calculate the force on a 5kg object with acceleration 10 m/s²")
        assert result.subject == SubjectCategory.PHYSICS

    def test_low_complexity(self):
        result = self.classifier.classify("What is 2 + 2?")
        assert result.complexity == ComplexityLevel.LOW

    def test_high_complexity(self):
        result = self.classifier.classify("Prove that the eigenvalue of this matrix converges")
        assert result.complexity == ComplexityLevel.HIGH

    def test_image_input(self):
        result = self.classifier.classify("", has_image=True)
        assert result.subject == SubjectCategory.IMAGE


class TestRouter:
    def setup_method(self):
        self.router = ModelRouter()
        self.classifier = ProblemClassifier()

    def test_low_complexity_routes_to_groq(self):
        classification = self.classifier.classify("What is 2 + 2?")
        decision = self.router.route(classification)
        assert decision.provider == ModelProvider.GROQ

    def test_high_complexity_routes_to_deepseek(self):
        classification = self.classifier.classify("Derive the Fourier transform of this function step by step")
        decision = self.router.route(classification)
        assert decision.provider == ModelProvider.DEEPSEEK

    def test_fallback_from_groq(self):
        fallback = self.router.get_fallback(ModelProvider.GROQ)
        assert fallback is not None
        assert fallback.provider == ModelProvider.DEEPSEEK

    def test_no_fallback_from_deepseek(self):
        fallback = self.router.get_fallback(ModelProvider.DEEPSEEK)
        assert fallback is None
