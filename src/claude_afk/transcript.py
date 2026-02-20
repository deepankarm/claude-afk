"""Claude Code JSONL transcript parsing."""

from __future__ import annotations

import json
import os


def get_session_name(transcript_path: str) -> str:
    """Extract a session name from the first user message in the transcript."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if entry.get("type") == "user":
                    content = entry.get("message", {}).get("content", "")
                    if isinstance(content, str):
                        return content.strip()[:80]
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                return block.get("text", "").strip()[:80]
                    return ""
    except OSError:
        pass
    return ""


def get_last_assistant_message(transcript_path: str) -> str:
    """Parse JSONL transcript and extract the last assistant message text."""
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    try:
        with open(transcript_path) as f:
            lines = f.readlines()
    except OSError:
        return ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if entry.get("type") == "assistant":
            content = entry.get("message", {}).get("content", [])
            texts = [b.get("text", "") for b in content if b.get("type") == "text"]
            result = "\n".join(texts).strip()
            if result:
                return result
    return ""
