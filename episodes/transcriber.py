import logging
import os
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File

from .models import Episode
from .observability import observe_step
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_transcription_provider

logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT = 300  # 5 minutes — must fit within Q_CLUSTER['timeout']

# Tiers ordered from highest to lowest quality.
# Each tuple: (channels, sample_rate, bitrate_kbps)
RESIZE_TIERS = (
    (1, 44100, 128),
    (1, 32000, 96),
    (1, 22050, 64),
    (1, 16000, 48),
    (1, 16000, 32),
)

RESIZE_SAFETY_MARGIN = 1.10  # 10% overhead for MP3 container/framing


def _select_resize_tier(duration_seconds, max_size_bytes):
    """Pick the gentlest resize tier whose estimated output fits under max_size_bytes.

    Returns the tier index (into RESIZE_TIERS) or None if no tier fits.
    If duration_seconds is None, returns the last (most aggressive) tier.
    """
    if duration_seconds is None:
        return len(RESIZE_TIERS) - 1

    for i, (_channels, _sr, bitrate_kbps) in enumerate(RESIZE_TIERS):
        estimated = (bitrate_kbps * 1000 / 8) * duration_seconds * RESIZE_SAFETY_MARGIN
        if estimated <= max_size_bytes:
            return i

    return None


def _resize_if_needed(episode):
    """Downsample audio with ffmpeg if it exceeds the max file size.

    Returns True if the file was resized (so audio_file needs saving).
    """
    max_size = getattr(settings, "RAGTIME_MAX_AUDIO_SIZE", 25 * 1024 * 1024)
    if episode.audio_file.size <= max_size:
        return False

    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed or not on PATH")

    tier_idx = _select_resize_tier(
        getattr(episode, "duration", None), max_size
    )
    if tier_idx is None:
        # No tier fits the estimate — try the most aggressive as last resort.
        tier_idx = len(RESIZE_TIERS) - 1

    input_path = episode.audio_file.path
    output_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            output_path = tmp.name

        # Try selected tier, then progressively more aggressive tiers.
        for idx in range(tier_idx, len(RESIZE_TIERS)):
            channels, sample_rate, bitrate_kbps = RESIZE_TIERS[idx]
            bitrate_str = f"{bitrate_kbps}k"
            logger.info(
                "Episode %s: trying resize tier %d (ac=%d ar=%d b:a=%s)",
                episode.pk, idx, channels, sample_rate, bitrate_str,
            )

            try:
                result = subprocess.run(
                    [
                        "ffmpeg",
                        "-hide_banner", "-loglevel", "error",
                        "-i", input_path,
                        "-ac", str(channels),
                        "-ar", str(sample_rate),
                        "-b:a", bitrate_str,
                        "-y",
                        output_path,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=FFMPEG_TIMEOUT,
                )
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f"ffmpeg timed out during audio resize ({FFMPEG_TIMEOUT}s)"
                )

            if result.returncode != 0:
                stderr = result.stderr.decode(errors="replace")
                raise RuntimeError(
                    f"ffmpeg failed (exit {result.returncode}): {stderr[:500]}"
                )

            output_size = os.path.getsize(output_path)
            if output_size <= max_size:
                break

            logger.info(
                "Episode %s: tier %d output %.1fMB still exceeds limit, trying next tier",
                episode.pk, idx, output_size / (1024 * 1024),
            )
        else:
            raise RuntimeError(
                f"Audio file exceeds {max_size / (1024 * 1024):.1f}MB limit after resizing "
                f"with all tiers ({output_size / (1024 * 1024):.1f}MB)"
            )

        filename = f"{episode.pk}.mp3"
        with open(output_path, "rb") as f:
            episode.audio_file.save(filename, File(f), save=False)

        logger.info("Episode %s audio resized to %.1fMB", episode.pk, output_size / (1024 * 1024))
        return True

    finally:
        if output_path:
            try:
                os.unlink(output_path)
            except OSError:
                pass


@observe_step("transcribe_episode")
def transcribe_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.TRANSCRIBING:
        logger.warning(
            "Episode %s has status '%s', expected 'transcribing'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.TRANSCRIBING)

    if not episode.audio_file:
        episode.error_message = "No audio file to transcribe"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.TRANSCRIBING, "No audio file to transcribe")
        return

    try:
        resized = _resize_if_needed(episode)
        if resized:
            episode.save(update_fields=["audio_file", "updated_at"])

        provider = get_transcription_provider()
        language = episode.language or None
        result = provider.transcribe(episode.audio_file.path, language=language)

        episode.transcript_json = result
        episode.transcript = result.get("text", "")
        complete_step(episode, Episode.Status.TRANSCRIBING)
        episode.status = Episode.Status.SUMMARIZING
        episode.save(
            update_fields=["status", "transcript", "transcript_json", "updated_at"]
        )
    except Exception as exc:
        logger.exception("Failed to transcribe episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.TRANSCRIBING, str(exc), exc=exc)
