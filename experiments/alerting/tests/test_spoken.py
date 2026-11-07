"""Tests for the spoken message and the local speech preview."""

from pathlib import Path
import shutil
import sys

import pytest

from alerting.models import load_case
from alerting.spoken import (
    MAX_WORDS,
    call_text,
    number_words,
    spoken_eta,
    spoken_turbines,
    word_count,
)
from alerting.tts_preview import (
    PIPER_VOICE,
    VOICES_DIR,
    duration_seconds,
    synthesize_piper,
    synthesize_say,
)

EXAMPLES = sorted((Path(__file__).parent.parent / "examples").glob("*.json"))


@pytest.mark.parametrize(
    ("number", "masculine", "feminine"),
    [
        (0, "zero", "zero"),
        (1, "unu", "una"),
        (2, "doi", "două"),
        (7, "șapte", "șapte"),
        (11, "unsprezece", "unsprezece"),
        (12, "doisprezece", "douăsprezece"),
        (14, "paisprezece", "paisprezece"),
        (16, "șaisprezece", "șaisprezece"),
        (18, "optsprezece", "optsprezece"),
        (20, "douăzeci", "douăzeci"),
        (21, "douăzeci și unu", "douăzeci și una"),
        (22, "douăzeci și doi", "douăzeci și două"),
        (60, "șaizeci", "șaizeci"),
        (100, "o sută", "o sută"),
        (105, "o sută cinci", "o sută cinci"),
        (212, "două sute doisprezece", "două sute douăsprezece"),
        (1000, "o mie", "o mie"),
        (2500, "două mii cinci sute", "două mii cinci sute"),
        (21000, "douăzeci și una de mii", "douăzeci și una de mii"),
    ],
)
def test_number_words(number: int, masculine: str, feminine: str) -> None:
    assert number_words(number) == masculine
    assert number_words(number, feminine=True) == feminine


def test_number_words_refuses_out_of_range() -> None:
    with pytest.raises(ValueError):
        number_words(-1)
    with pytest.raises(ValueError):
        number_words(1_000_000)


@pytest.mark.parametrize(
    ("hours", "expected"),
    [
        (0.5, "mai puțin de o oră"),
        (1.2, "aproximativ o oră"),
        (2, "aproximativ două ore"),
        (12, "aproximativ douăsprezece ore"),
        (18, "aproximativ optsprezece ore"),
        (22.9, "aproximativ douăzeci și două de ore"),
        (47, "aproximativ patruzeci și șapte de ore"),
        (48, "aproximativ două zile"),
        (96, "aproximativ patru zile"),
    ],
)
def test_spoken_eta_uses_feminine_forms(hours: float, expected: str) -> None:
    assert spoken_eta(hours) == expected


@pytest.mark.parametrize(
    ("numbers", "expected"),
    [
        ([7], ("turbina șapte", False)),
        ([2], ("turbina doi", False)),
        ([11, 12], ("turbinele unsprezece și doisprezece", True)),
        ([2, 5, 9], ("turbinele doi, cinci și nouă", True)),
        ([11, 1, 2, 3], ("turbina unsprezece și încă trei turbine", True)),
        ([11, 1], ("turbinele unsprezece și unu", True)),
    ],
)
def test_spoken_turbines(numbers: list[int], expected: tuple[str, bool]) -> None:
    assert spoken_turbines(numbers) == expected


def test_call_text_matches_the_agreed_example() -> None:
    case = load_case(EXAMPLES[2])
    assert call_text(case.alert, case.decision) == (
        "Bună ziua. Sunt sistemul de monitorizare al parcului Dealul Țarinii. "
        "Turbina șapte are risc ridicat de defecțiune în aproximativ optsprezece ore. "
        "Detaliile sunt în e-mailul trimis acum. Verificați e-mailul, vă rog."
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda path: path.name[:2])
def test_every_example_fits_the_word_limit_with_no_digits(path: Path) -> None:
    case = load_case(path)
    text = call_text(case.alert, case.decision)
    assert word_count(text) <= MAX_WORDS
    assert not any(character.isdigit() for character in text)


def test_plural_verb_follows_the_turbines() -> None:
    case = load_case(EXAMPLES[3])
    assert "Turbinele unsprezece și doisprezece au risc critic" in call_text(
        case.alert, case.decision
    )


def test_too_long_a_message_is_refused() -> None:
    case = load_case(EXAMPLES[2])
    alert = case.alert.model_copy(update={"park": " ".join(["Vânt"] * 20)})
    with pytest.raises(ValueError, match="words"):
        call_text(alert, case.decision)


def test_many_turbines_still_fit() -> None:
    case = load_case(EXAMPLES[3])
    many = [
        {"turbine_id": f"T{number}", "probability": 0.9 - number / 100} for number in range(1, 30)
    ]
    alert = case.alert.model_validate(case.alert.model_dump() | {"turbines": many})
    assert word_count(call_text(alert, case.decision)) <= MAX_WORDS


def test_word_count_treats_hyphenated_words_as_one() -> None:
    assert word_count("Verificați e-mailul, vă rog.") == 4


@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("say") is None, reason="needs macOS say"
)
def test_say_writes_a_wav_file(tmp_path: Path) -> None:
    path = synthesize_say("Turbina șapte.", tmp_path / "ioana.wav")
    assert duration_seconds(path) > 0.3


@pytest.mark.skipif(
    not (VOICES_DIR / f"{PIPER_VOICE}.onnx").is_file(), reason="Piper voice not downloaded"
)
def test_piper_writes_a_wav_file(tmp_path: Path) -> None:
    path = synthesize_piper("Turbina șapte.", tmp_path / "piper.wav")
    assert duration_seconds(path) > 0.3


def test_missing_piper_voice_says_how_to_get_it(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="download_voices"):
        synthesize_piper("x", tmp_path / "x.wav", voice="ro_RO-nobody-low")
