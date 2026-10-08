"""Geschäftslogik für Testauswahl und automatische Bewertung."""

import secrets
import string
from decimal import ROUND_HALF_UP, Decimal
from django.contrib.auth.hashers import make_password
from django.db import transaction
from .models import Question, QuestionPool, TestQuestion, TestSession


class TestGenerationError(ValueError):
    """Fachlicher Fehler, wenn die angeforderte Fragenanzahl unmöglich ist."""


def generate_test(question_count, creator, question_pool):
    """Wählt Fragen ausschließlich aus dem gewählten Prüfungstyp aus.

    Ohne explizite Anzahl gilt die feste Fragenzahl des Pools.
    """
    if not isinstance(question_pool, QuestionPool):
        raise TestGenerationError("Wähle zuerst einen gültigen Fragenpool aus.")
    pool = list(Question.objects.filter(question_pool=question_pool))
    pinned = [question for question in pool if question.is_pinned]
    other = [question for question in pool if not question.is_pinned]
    if not pool:
        raise TestGenerationError("Dieser Fragenpool enthält noch keine Fragen.")
    if question_count is None:
        question_count = question_pool.test_question_count
    if question_count < 1 or question_count < len(pinned) or question_count > len(pool):
        raise TestGenerationError(
            f"Die feste Fragenzahl des Pools ({question_count}) muss alle verankerten Fragen "
            f"({len(pinned)}) enthalten und darf die Poolgröße ({len(pool)}) nicht überschreiten."
        )
    selected = pinned + secrets.SystemRandom().sample(
        other, question_count - len(pinned)
    )
    otp = "".join(secrets.choice(string.digits) for _ in range(6))
    with transaction.atomic():
        test = TestSession.objects.create(
            otp_hash=make_password(otp),
            created_by=creator,
            question_pool=question_pool,
            pass_percentage=question_pool.pass_percentage,
        )
        TestQuestion.objects.bulk_create(
            [
                TestQuestion(
                    test=test,
                    source_question=question,
                    position=position,
                    text=question.text,
                    question_type=question.question_type,
                    options=question.options,
                    points=question.points,
                    answer_key=question.answer_key,
                )
                for position, question in enumerate(selected, start=1)
            ]
        )
    return test, otp


def score_percentage(earned, possible):
    """Berechnet erreichte/maximale Punkte in Prozent, kaufmännisch auf ganze Zahlen gerundet."""
    if not possible:
        return 0
    value = Decimal(earned) / Decimal(possible) * 100
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def evaluate_result(test, earned, possible):
    """Liefert Prozentwert und Bestehensstatus anhand der bei Erstellung gültigen Grenze."""
    percent = score_percentage(earned, possible)
    threshold = (
        test.pass_percentage
        if test.pass_percentage is not None
        else test.question_pool.pass_percentage
    )
    return {"percent": percent, "pass_percentage": threshold, "passed": percent >= threshold}


def grade_answer(test_question, answer):
    """Bewertet Auswahl und normalisierte Kurzantworten; Freitext bleibt offen."""
    kind = test_question.question_type
    value = answer.get("value", "") if isinstance(answer, dict) else ""
    if kind == Question.Type.LONG:
        return None, True
    if kind in (Question.Type.SINGLE, Question.Type.MULTIPLE):
        submitted = {
            str(item)
            for item in (value if isinstance(value, list) else [value])
            if item != ""
        }
        expected = {
            str(index)
            for index, option in enumerate(test_question.options)
            if option.get("is_correct")
        }
        correct = submitted == expected
    else:
        expected = " ".join(test_question.answer_key.split()).casefold()
        correct = bool(expected) and " ".join(str(value).split()).casefold() == expected
    return (test_question.points if correct else Decimal("0")), False
