"""
# Speech preview

Renders the spoken message to audio files locally, to choose a voice by ear: macOS `say`
with the Romanian voice Ioana, and Piper with `ro_RO-mihai-medium`. Each file also gets a
copy degraded to what a phone line carries (8 kHz mu-law, via `afconvert`), since that is
how on-call will hear it.

This is a listening aid only. A Twilio call reads text with Twilio's own `<Say>` voices;
playing one of these files instead needs `<Play>` and a URL Twilio can download it from.

Piper (the `tts` dependency group) is imported inside the function that uses it: it pulls
in onnxruntime, which nothing else here needs.

The following can be imported from this module:
- `PIPER_VOICE`
- `VOICES_DIR`
- `duration_seconds`
- `synthesize_piper`
- `synthesize_say`
- `to_phone_quality`
"""

from pathlib import Path
import subprocess
import tempfile
import wave

from alerting.config import PACKAGE_ROOT

__all__ = [
    "PIPER_VOICE",
    "VOICES_DIR",
    "duration_seconds",
    "synthesize_piper",
    "synthesize_say",
    "to_phone_quality",
]

VOICES_DIR = PACKAGE_ROOT / "out" / "voices"
PIPER_VOICE = "ro_RO-mihai-medium"


def synthesize_say(text: str, path: Path, voice: str = "Ioana", rate: int | None = None) -> Path:
    """
    Speak `text` with macOS `say` into a 16-bit WAV file.

    :param text: The message.
    :param path: Output `.wav` file.
    :param voice: A `say -v '?'` voice name. Defaults to "Ioana" (ro_RO).
    :param rate: Words per minute. Defaults to None, meaning the voice's own rate.

    :returns: `path`.
    :raises subprocess.CalledProcessError: When `say` fails, e.g. the voice is missing.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8") as source:
        source.write(text)
        source.flush()
        command = ["say", "-v", voice, "-f", source.name, "-o", str(path)]
        command += ["--file-format=WAVE", "--data-format=LEI16@22050"]
        if rate is not None:
            command += ["-r", str(rate)]
        subprocess.run(command, check=True)
    return path


def synthesize_piper(
    text: str, path: Path, voice: str = PIPER_VOICE, length_scale: float = 1.0
) -> Path:
    """
    Speak `text` with Piper into a WAV file.

    :param text: The message.
    :param path: Output `.wav` file.
    :param voice: Voice name; `<voice>.onnx` and `<voice>.onnx.json` must be in `VOICES_DIR`.
    :param length_scale: Above 1 speaks slower, below 1 faster. Defaults to 1.0.

    :returns: `path`.
    :raises FileNotFoundError: When the voice has not been downloaded.
    """
    # onnxruntime is heavy and only this preview needs it.
    from piper import PiperVoice, SynthesisConfig

    model = VOICES_DIR / f"{voice}.onnx"
    if not model.is_file():
        raise FileNotFoundError(
            f"{model} missing: uv run python -m piper.download_voices {voice} "
            f"--data-dir {VOICES_DIR}"
        )
    piper_voice = PiperVoice.load(str(model))
    with wave.open(str(path), "wb") as wav_file:
        piper_voice.synthesize_wav(
            text, wav_file, syn_config=SynthesisConfig(length_scale=length_scale)
        )
    return path


def to_phone_quality(source: Path, target: Path) -> Path:
    """
    Convert a WAV file to 8 kHz mu-law, the quality of a phone line.

    :param source: Input `.wav` file.
    :param target: Output `.wav` file.

    :returns: `target`.
    :raises subprocess.CalledProcessError: When `afconvert` fails.
    """
    command = ["afconvert", "-f", "WAVE", "-d", "ulaw@8000", "-c", "1", str(source), str(target)]
    subprocess.run(command, check=True)
    return target


def duration_seconds(path: Path) -> float:
    """
    Length of a 16-bit PCM WAV file.

    :param path: The file.

    :returns: Seconds, rounded to one decimal.
    """
    with wave.open(str(path), "rb") as wav_file:
        return round(wav_file.getnframes() / wav_file.getframerate(), 1)
