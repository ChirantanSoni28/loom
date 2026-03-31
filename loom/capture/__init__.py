"""Capture engine — buffers tool events, classifies them, and builds session notes."""

from loom.capture.buffer import BufferedEvent, buffer_event, clear_events, load_events
from loom.capture.classifier import EventType, classify_event
from loom.capture.engine import CaptureEngine
from loom.capture.note_builder import build_session_note

__all__ = [
    "BufferedEvent",
    "CaptureEngine",
    "EventType",
    "buffer_event",
    "build_session_note",
    "classify_event",
    "clear_events",
    "load_events",
]
