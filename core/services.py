"""Geschäftslogik für Testauswahl und automatische Bewertung."""

import secrets
import string
from decimal import Decimal
from django.contrib.auth.hashers import make_password
from django.db import transaction
from .models import Question, QuestionPool, TestQuestion, TestSession


class TestGenerationError(ValueError):
    """Fachlicher Fehler, wenn die angeforderte Fragenanzahl unmöglich ist."""


def generate_test(question_count, creator, question_pool):
    """Wählt Fragen ausschließlich aus dem gewählten Prüfungstyp aus.

    Ohne explizite Anzahl wird zufällig eine Zahl innerhalb der Spanne des Pools gewählt.
    """
    if not isinstance(question_pool, QuestionPool):
        raise TestGenerationError("Wähle zuerst einen gültigen Fragenpool aus.")
    pool = list(Question.objects.filter(question_pool=question_pool))
    pinned = [question for question in pool if question.is_pinned]
    other = [question for question in pool if not question.is_pinned]
    if not pool:
        raise TestGenerationError("Dieser Fragenpool enthält noch keine Fragen.")
    if question_count is None:
        lowest = max(question_pool.minimum_test_questions, len(pinned), 1)
        highest = min(question_pool.maximum_test_questions, len(pool))
        if lowest > highest:
            raise TestGenerationError(
                "Die Fragenzahl-Spanne dieses Pools passt nicht zu seinen verankerten Fragen "
                "und seiner Größe. Bitte Minimum und Maximum des Pools anpassen."
            )
        question_count = secrets.SystemRandom().randint(lowest, highest)
    if question_count < 1 or question_count < len(pinned) or question_count > len(pool):
        raise TestGenerationError(
            "Die Anzahl muss alle verankerten Fragen enthalten und darf den gewählten Pool nicht überschreiten."
        )
    selected = pinned + secrets.SystemRandom().sample(
        other, question_count - len(pinned)
    )
    otp = "".join(secrets.choice(string.digits) for _ in range(6))
    with transaction.atomic():
        test = TestSession.objects.create(
            otp_hash=make_password(otp), created_by=creator, question_pool=question_pool
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
