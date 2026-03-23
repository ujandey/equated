-- ==============================================================
-- SEED DATA — Pre-Solved Problem Library
-- Common STEM problems served instantly at zero API cost
-- ==============================================================

-- ── Pre-solved math problems ────────────────────────
INSERT INTO cache_entries (query, solution, metadata) VALUES
(
  'solve 2x + 3 = 7',
  '{"problem_interpretation": "Solve the linear equation 2x + 3 = 7 for x", "concept_used": "Linear Equations", "steps": [{"step": 1, "rule": "Subtract 3 from both sides", "explanation": "2x + 3 - 3 = 7 - 3 → 2x = 4"}, {"step": 2, "rule": "Divide both sides by 2", "explanation": "2x/2 = 4/2 → x = 2"}], "final_answer": "x = 2", "quick_summary": "Isolate x by subtracting 3 then dividing by 2."}',
  '{"subject": "math", "complexity": "low", "pre_solved": true}'
),
(
  'differentiate x^3 + 2x',
  '{"problem_interpretation": "Find the derivative of f(x) = x³ + 2x", "concept_used": "Power Rule of Differentiation", "steps": [{"step": 1, "rule": "d/dx(x^n) = n·x^(n-1)", "explanation": "d/dx(x³) = 3x²"}, {"step": 2, "rule": "d/dx(2x) = 2", "explanation": "Derivative of 2x is 2"}, {"step": 3, "rule": "Sum rule", "explanation": "f''(x) = 3x² + 2"}], "final_answer": "f''(x) = 3x² + 2", "quick_summary": "Apply the power rule to each term and sum."}',
  '{"subject": "math", "complexity": "low", "pre_solved": true}'
),
(
  'integrate 2x dx',
  '{"problem_interpretation": "Find the indefinite integral of 2x with respect to x", "concept_used": "Power Rule of Integration", "steps": [{"step": 1, "rule": "∫x^n dx = x^(n+1)/(n+1) + C", "explanation": "∫2x dx = 2 · x²/2 + C"}, {"step": 2, "rule": "Simplify", "explanation": "= x² + C"}], "final_answer": "x² + C", "quick_summary": "Apply the reverse power rule: increase exponent by 1, divide by new exponent."}',
  '{"subject": "math", "complexity": "low", "pre_solved": true}'
);

-- ── Pre-solved physics problems ─────────────────────
INSERT INTO cache_entries (query, solution, metadata) VALUES
(
  'calculate force mass 5kg acceleration 10',
  '{"problem_interpretation": "Calculate the force on a body with mass 5 kg and acceleration 10 m/s²", "concept_used": "Newton''s Second Law: F = ma", "steps": [{"step": 1, "rule": "F = m × a", "explanation": "F = 5 kg × 10 m/s²"}, {"step": 2, "rule": "Calculate", "explanation": "F = 50 N"}], "final_answer": "F = 50 N", "quick_summary": "Force equals mass times acceleration: 5 × 10 = 50 Newtons."}',
  '{"subject": "physics", "complexity": "low", "pre_solved": true}'
);
