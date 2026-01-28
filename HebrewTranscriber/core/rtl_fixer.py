"""
RTL Fixer - Fix Hebrew punctuation for proper RTL display.

Problem: Hebrew text is RTL but subtitle renderers often don't handle
punctuation correctly, causing it to appear on the wrong side.

Solution: Move ending punctuation to the beginning and flip brackets.
Based on SubtitlePipeline's RTL fixer algorithm.
"""

import re
from pathlib import Path
from typing import Optional, Callable, Tuple
from dataclasses import dataclass


# RTL marker added to files that have been processed
RTL_MARKER = "<!-- RTL_FIXED -->"

# Punctuation pairs that need to be flipped
PUNCTUATION_PAIRS = {
    '(': ')',
    ')': '(',
    '[': ']',
    ']': '[',
    '{': '}',
    '}': '{',
    '<': '>',
    '>': '<',
    '«': '»',
    '»': '«',
}

# Punctuation that should move from end to start
END_PUNCTUATION = set('.,!?;:')

# Characters that indicate the line is likely English/numbers
LATIN_CHARS = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ')


@dataclass
class RTLFixResult:
    """Result of fixing RTL in a file."""
    success: bool
    input_file: Path
    output_file: Optional[Path] = None
    lines_fixed: int = 0
    error: Optional[str] = None


def is_hebrew_line(text: str) -> bool:
    """Check if line contains Hebrew characters."""
    for char in text:
        if '\u0590' <= char <= '\u05FF':  # Hebrew Unicode range
            return True
    return False


def is_mostly_latin(text: str) -> bool:
    """Check if line is mostly Latin characters (don't flip these)."""
    latin_count = sum(1 for c in text if c in LATIN_CHARS)
    total_letters = sum(1 for c in text if c.isalpha())
    if total_letters == 0:
        return False
    return latin_count / total_letters > 0.7


def flip_bracket(char: str) -> str:
    """Flip a bracket character."""
    return PUNCTUATION_PAIRS.get(char, char)


def extract_tags(text: str) -> Tuple[str, str, str]:
    """
    Extract HTML-like tags from text.
    Returns (clean_text, prefix_tags, suffix_tags)
    """
    tag_pattern = r'(</?[ibuIBU]>|</?font[^>]*>)'

    prefix_tags = []
    suffix_tags = []

    # Extract prefix tags
    while True:
        match = re.match(tag_pattern, text)
        if match:
            prefix_tags.append(match.group(0))
            text = text[match.end():]
        else:
            break

    # Extract suffix tags
    while True:
        match = re.search(tag_pattern + r'$', text)
        if match:
            suffix_tags.insert(0, match.group(0))
            text = text[:match.start()]
        else:
            break

    return text, ''.join(prefix_tags), ''.join(suffix_tags)


def fix_rtl_line(line: str) -> str:
    """
    Fix RTL punctuation for a single line.

    Algorithm:
    1. Extract and preserve HTML tags
    2. Move ending punctuation to start
    3. Flip bracket directions
    4. Restore tags
    """
    if not line.strip():
        return line

    # Skip lines that are mostly Latin/English
    if is_mostly_latin(line):
        return line

    # Skip lines that don't contain Hebrew
    if not is_hebrew_line(line):
        return line

    # Extract tags
    text, prefix_tags, suffix_tags = extract_tags(line)

    if not text.strip():
        return line

    # Collect ending punctuation
    end_punct = []
    while text and text[-1] in END_PUNCTUATION:
        end_punct.insert(0, text[-1])
        text = text[:-1]

    # Collect starting punctuation (already there)
    start_punct = []
    while text and text[0] in END_PUNCTUATION:
        start_punct.append(text[0])
        text = text[1:]

    # Flip all brackets in the text
    result = []
    for char in text:
        result.append(flip_bracket(char))
    text = ''.join(result)

    # Rebuild: prefix_tags + end_punct (moved) + text + start_punct (moved) + suffix_tags
    fixed = prefix_tags + ''.join(end_punct) + text + ''.join(start_punct) + suffix_tags

    return fixed


def is_rtl_fixed(content: str) -> bool:
    """Check if file has already been RTL fixed."""
    return RTL_MARKER in content


def fix_rtl_subtitle(content: str, force: bool = False) -> Tuple[str, int, bool]:
    """
    Fix RTL in entire SRT content.

    Args:
        content: SRT file content
        force: Force fix even if already marked as fixed

    Returns:
        (fixed_content, lines_fixed, was_already_fixed)
    """
    # Check if already fixed
    if not force and is_rtl_fixed(content):
        return content, 0, True

    lines = content.split('\n')
    fixed_lines = []
    lines_fixed = 0

    # Track SRT format: number, timestamp, text, blank line
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check if this is a subtitle number (just digits)
        if line.strip().isdigit():
            fixed_lines.append(line)
            i += 1

            # Next should be timestamp
            if i < len(lines):
                fixed_lines.append(lines[i])  # Timestamp line
                i += 1

            # Now process text lines until blank line
            while i < len(lines) and lines[i].strip():
                original = lines[i]
                fixed = fix_rtl_line(original)
                fixed_lines.append(fixed)
                if fixed != original:
                    lines_fixed += 1
                i += 1

            # Add blank line if present
            if i < len(lines):
                fixed_lines.append(lines[i])
                i += 1
        else:
            # Not a subtitle block, keep as is
            fixed_lines.append(line)
            i += 1

    # Add RTL marker at the end
    result = '\n'.join(fixed_lines)
    if not result.endswith('\n'):
        result += '\n'
    result += RTL_MARKER + '\n'

    return result, lines_fixed, False


def fix_rtl_file(
    input_path: Path,
    output_path: Optional[Path] = None,
    log: Optional[Callable[[str], None]] = None,
    force: bool = False
) -> RTLFixResult:
    """
    Fix RTL in a single SRT file.

    Args:
        input_path: Input SRT file
        output_path: Output path (defaults to overwrite input)
        log: Optional logging callback
        force: Force fix even if already marked as fixed

    Returns:
        RTLFixResult
    """
    if log is None:
        log = lambda x: None

    if output_path is None:
        output_path = input_path  # Overwrite

    try:
        # Read file with encoding detection
        content = None
        for encoding in ['utf-8', 'utf-8-sig', 'cp1252', 'iso-8859-8']:
            try:
                with open(input_path, 'r', encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            return RTLFixResult(
                success=False,
                input_file=input_path,
                error="Could not decode file"
            )

        # Fix RTL
        fixed_content, lines_fixed, was_already_fixed = fix_rtl_subtitle(content, force=force)

        # If already fixed and not forcing, return success with 0 lines
        if was_already_fixed:
            return RTLFixResult(
                success=True,
                input_file=input_path,
                output_file=output_path,
                lines_fixed=0
            )

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(fixed_content)

        return RTLFixResult(
            success=True,
            input_file=input_path,
            output_file=output_path,
            lines_fixed=lines_fixed
        )

    except Exception as e:
        return RTLFixResult(
            success=False,
            input_file=input_path,
            error=str(e)
        )


def fix_rtl_folder(
    folder: Path,
    log: Optional[Callable[[str], None]] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    force: bool = False
) -> dict:
    """
    Fix RTL in all SRT files in a folder.
    Files are modified in place.

    Args:
        folder: Folder containing Hebrew SRT files
        log: Optional logging callback
        progress: Optional progress callback
        force: Force fix even for files already marked as fixed

    Returns:
        Dict with 'fixed', 'failed', 'skipped', 'total_lines_fixed'
    """
    if log is None:
        log = lambda x: None

    log("=== RTL Fix ===")

    # Find SRT files
    srt_files = sorted(folder.glob("*.srt"))
    if not srt_files:
        log("No SRT files found")
        return {'fixed': [], 'failed': [], 'skipped': [], 'total_lines_fixed': 0}

    log(f"Found {len(srt_files)} files to process")

    fixed = []
    failed = []
    skipped = []
    total_lines_fixed = 0

    for i, srt in enumerate(srt_files):
        result = fix_rtl_file(srt, srt, log, force=force)

        if result.success:
            if result.lines_fixed == 0:
                skipped.append(srt)
                log(f"⏭ {srt.name} (already RTL fixed)")
            else:
                fixed.append(srt)
                total_lines_fixed += result.lines_fixed
                log(f"✓ {srt.name} ({result.lines_fixed} lines fixed)")
        else:
            failed.append((srt.name, result.error))
            log(f"✗ {srt.name}: {result.error}")

        if progress:
            progress(i + 1, len(srt_files))

    log(f"\nFixed: {len(fixed)}, Skipped: {len(skipped)}, Failed: {len(failed)}")
    log(f"Total lines modified: {total_lines_fixed}")

    return {
        'fixed': fixed,
        'failed': failed,
        'skipped': skipped,
        'total_lines_fixed': total_lines_fixed
    }
