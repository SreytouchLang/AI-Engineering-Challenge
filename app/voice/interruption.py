from __future__ import annotations


class InterruptionController:
    """Tracks buffered outbound audio so barge-in can clear it safely."""

    def __init__(self) -> None:
        self.pending_marks: set[str] = set()
        self.current_playback_mark: str | None = None
        self.clear_events = 0

    def register_outbound_audio(self, mark_name: str) -> None:
        self.pending_marks.add(mark_name)
        self.current_playback_mark = mark_name

    def should_clear_for_barge_in(self) -> bool:
        return bool(self.pending_marks)

    def acknowledge_mark(self, mark_name: str) -> None:
        self.pending_marks.discard(mark_name)
        if self.current_playback_mark == mark_name:
            self.current_playback_mark = None

    def clear(self) -> None:
        self.pending_marks.clear()
        self.current_playback_mark = None
        self.clear_events += 1
