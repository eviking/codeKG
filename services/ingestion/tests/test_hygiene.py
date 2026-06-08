"""
Unit tests for the hygiene scoring functions (services/ingestion/kg/hygiene.py).

Coverage scope:
  - Per-dimension scoring helpers (_score_size, _score_blast, _score_coupling, _score_docs)
  - _class_score composition of all four dimensions
  - _letter_grade boundaries (A>=80, B>=65, C>=50, D>=35, F<35)
  - Score is always in range 0–100

All tests run in pure Python — no Neo4j, no Docker. The Neo4j-calling
compute_hygiene() function is NOT tested here (it would require a driver mock);
this suite covers the scoring logic in isolation.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SVC_ROOT = str(Path(__file__).parent.parent)
if _SVC_ROOT not in sys.path:
    sys.path.insert(0, _SVC_ROOT)

from kg.hygiene import (
    _score_size,
    _score_blast,
    _score_coupling,
    _score_docs,
    _class_score,
    _letter_grade,
)


class TestSizeScoring:
    """Exercises size scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_small_class_full_score(self):
        """
        A class with <=10 methods should receive the maximum size score of 25.
        Small classes are the ideal and should not lose any hygiene points.
        """
        assert _score_size(5) == 25
        assert _score_size(10) == 25

    def test_medium_class_partial_score(self):
        """
        A class with 11-20 methods should receive a reduced score (18).
        Partial scores reflect manageable but growing classes.
        """
        assert _score_size(15) == 18
        assert _score_size(20) == 18

    def test_large_class_low_score(self):
        """
        A class with 21-30 methods should receive a score of 10.
        This is a significant penalty that pushes the class toward a lower grade.
        """
        assert _score_size(25) == 10
        assert _score_size(30) == 10

    def test_god_class_zero_score(self):
        """
        A class with >60 methods should receive zero size score.
        God classes are the worst case and should be flagged clearly.
        """
        assert _score_size(61) == 0
        assert _score_size(200) == 0


class TestBlastScoring:
    """Exercises blast scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_no_dependents_full_score(self):
        """
        A class with zero dependents (blast_size=0) should receive 25 — it's safe
        to change without affecting anything else.
        """
        assert _score_blast(0) == 25

    def test_moderate_blast_partial_score(self):
        """
        A class with 6-20 dependents should receive 12 points.
        This reflects a class that's shared but not critically central.
        """
        assert _score_blast(6) == 12
        assert _score_blast(20) == 12

    def test_high_blast_zero_score(self):
        """
        A class with >100 dependents receives zero blast score.
        These are high-risk classes that agents should approach with caution.
        """
        assert _score_blast(101) == 0


class TestCouplingScoring:
    """Exercises coupling scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_low_coupling_full_score(self):
        """
        A coupling score below 0.10 should receive 25 points.
        Low coupling is the structural ideal.
        """
        assert _score_coupling(0.05) == 25
        assert _score_coupling(0.0) == 25

    def test_high_coupling_zero_score(self):
        """
        A coupling score >= 0.50 should receive zero points.
        Highly coupled classes are difficult to change safely.
        """
        assert _score_coupling(0.5) == 0
        assert _score_coupling(0.9) == 0


class TestDocsScoring:
    """Exercises docs scoring behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_with_docstring_scores_25(self):
        """
        A class with a docstring present should receive the full 25-point docs score.
        Documentation is the easiest hygiene dimension to improve.
        """
        assert _score_docs(True) == 25

    def test_without_docstring_scores_0(self):
        """
        A class without any docstring should receive zero docs points.
        Missing docs are the most common hygiene issue and heavily penalised.
        """
        assert _score_docs(False) == 0


class TestClassScore:
    """Exercises class score behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_perfect_class_scores_100(self):
        """
        A tiny, undepended-on, loosely-coupled, documented class should score 100.
        This is the target state that the hygiene system rewards.
        """
        score = _class_score(method_count=5, blast_size=0, coupling=0.05, has_doc=True)
        assert score == 100

    def test_god_class_scores_low(self):
        """
        A class with many methods, high blast, high coupling, and no docs should
        score very low (likely 0). This ensures bad classes are clearly identified.
        """
        score = _class_score(method_count=100, blast_size=200, coupling=0.8, has_doc=False)
        assert score <= 10

    def test_score_clamped_to_valid_range(self):
        """
        The class score must always be in range 0-100 regardless of inputs.
        Out-of-range scores would break grade assignment and display.
        """
        score = _class_score(method_count=0, blast_size=0, coupling=0.0, has_doc=True)
        assert 0 <= score <= 100

        score = _class_score(method_count=999, blast_size=999, coupling=1.0, has_doc=False)
        assert 0 <= score <= 100


class TestLetterGrade:
    """Exercises letter grade behavior in the hygiene test module. Watch out for the mocked boundaries and bootstrap setup in this suite, because many tests patch module-level globals before imports happen."""

    def test_grade_a_boundary(self):
        """Score >= 80 must return 'A'. Grade A signals a healthy, maintainable class."""
        assert _letter_grade(80) == "A"
        assert _letter_grade(95) == "A"
        assert _letter_grade(100) == "A"

    def test_grade_b_boundary(self):
        """Score >= 65 and < 80 must return 'B'. Grade B is acceptable quality."""
        assert _letter_grade(65) == "B"
        assert _letter_grade(79) == "B"

    def test_grade_c_boundary(self):
        """Score >= 50 and < 65 must return 'C'. Grade C signals moderate hygiene debt."""
        assert _letter_grade(50) == "C"
        assert _letter_grade(64) == "C"

    def test_grade_d_boundary(self):
        """Score >= 35 and < 50 must return 'D'. Grade D signals significant hygiene debt."""
        assert _letter_grade(35) == "D"
        assert _letter_grade(49) == "D"

    def test_grade_f_boundary(self):
        """Score < 35 must return 'F'. Grade F classes need urgent attention."""
        assert _letter_grade(34) == "F"
        assert _letter_grade(0) == "F"
