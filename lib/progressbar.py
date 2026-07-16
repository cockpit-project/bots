# Copyright (C) 2026 Red Hat, Inc.
# SPDX-License-Identifier: GPL-3.0-or-later

import collections
import colorsys
import os
import sys
import threading
import time
from typing import Self

from lib.ansi import CLEAR_LINE, IS_TTY, RESET, USE_COLOR


def _format_size(size: float) -> str:
    for unit in ('B', 'kB', 'MB', 'GB'):
        if size < 1000:
            return f'{size:.1f} {unit}'
        size /= 1000
    return f'{size:.1f} TB'


class RateTracker:
    """Tracks download rate using a sliding window of recent samples."""

    def __init__(self, start_time: float, start_offset: int) -> None:
        self.start_time = start_time
        self.start_offset = start_offset
        self.window: collections.deque[tuple[float, int]] = collections.deque(maxlen=100)

    @staticmethod
    def _format_rate(bytes_per_sec: float) -> str:
        return f'{_format_size(bytes_per_sec)}/s'

    @staticmethod
    def _format_duration(seconds: float) -> str:
        if seconds < 60:
            return f'{int(seconds)}s'
        if seconds < 3600:
            return f'{int(seconds // 60)}m{int(seconds % 60):02d}s'
        return f'{int(seconds // 3600)}h{int(seconds % 3600 // 60):02d}m'

    def sample(self, now: float, offset: int) -> None:
        self.window.append((now, offset))

    def format_progress(self, now: float, offset: int, total: int) -> list[str]:
        progress = f'{_format_size(offset)}/{_format_size(total)}'
        try:
            oldest_time, oldest_bytes = self.window[0]
            rate = (offset - oldest_bytes) / (now - oldest_time)
            return [progress, self._format_rate(rate), f'ETA {self._format_duration((total - offset) / rate)}']
        except (IndexError, ZeroDivisionError):
            return [progress, 'ETA 🤷']

    def format_final(self, now: float, offset: int, total: int) -> list[str]:
        elapsed = now - self.start_time
        downloaded = offset - self.start_offset
        rate = downloaded / elapsed if elapsed > 0 else 0
        parts = [_format_size(downloaded)]
        if self.start_offset:
            parts.append(f'(of {_format_size(total)})')
        parts.extend([f'in {self._format_duration(elapsed)}', f'({self._format_rate(rate)})'])
        return parts


class ProgressBar(threading.Thread):
    def __init__(self, total: int) -> None:
        super().__init__()
        self.total = total
        self.offset = 0
        self.status: RateTracker | str | None = None
        self._done = threading.Event()
        self._percent_shown = 0.0

    def track_rate(self) -> None:
        self.status = RateTracker(start_time=time.monotonic(), start_offset=self.offset)

    def update(self, n: int) -> None:
        self.offset += n

        # on tty the thread does updates; on non-tty we do it here
        if not IS_TTY and self.total:
            while self._percent_shown <= self.offset * 100 / self.total:
                if self._percent_shown == 100:
                    sys.stderr.write('\n')  # before the summary line
                elif self._percent_shown % 10 == 0:
                    sys.stderr.write(f' {self._percent_shown:.0f}% ')  # every 10%
                else:
                    sys.stderr.write('.')  # every 2.5%
                sys.stderr.flush()

                # We show one update (either a "." or a "n%") per 2.5% of
                # progress, getting us output like "0% ... 10% ... 20% ...
                # etc".  This number should be cleanly representable in
                # floating point (so we don't get errors) and should also
                # divide into 10 and 100 (so we hit each `% 10 == 0` exactly,
                # and also the `== 100` at the end).
                self._percent_shown += 2.5

    @staticmethod
    def _bar_color(i: int, width: int) -> str:
        ryb = i / max(1, width - 1) * 300  # from 0° (red) to 300° (purple) RYB hue

        # This color space conversion brought to you by Chromatic!
        # https://lis.codeberg.page/chromatic/
        rgb_hue = ryb / 2 if ryb < 120 else (ryb - 120) * 1.5 + 60 if ryb < 240 else ryb

        r, g, b = colorsys.hsv_to_rgb(rgb_hue / 360, 0.4, 1.0)
        return f'\033[38;2;{r * 255:.0f};{g * 255:.0f};{b * 255:.0f}m'

    def _render(self, final: bool = False) -> None:
        if not self.total:
            return

        parts: list[str] = [f'{self.offset * 100 // self.total:3d}%']
        now = time.monotonic()

        match self.status:
            case RateTracker() as rt if final:
                parts.extend(rt.format_final(now, self.offset, self.total))
            case RateTracker() as rt:
                rt.sample(now, self.offset)
                parts.extend(rt.format_progress(now, self.offset, self.total))
            case str(message):
                progress = f'{_format_size(self.offset)}/{_format_size(self.total)}'
                parts.extend([progress, f'[{message}]'])
            case None:
                pass

        try:
            width = max(0, os.get_terminal_size(sys.stderr.fileno()).columns - 60)
        except OSError:
            width = 0  # not a tty?  no progress bar!

        bar = ('█' * (self.offset * width // self.total)).ljust(width, '░')
        if USE_COLOR:
            bar = ''.join(self._bar_color(i, width) + g for i, g in enumerate(bar))

        sys.stderr.write(f'{CLEAR_LINE}  {bar}{RESET} {" ".join(parts)}')
        if final:
            sys.stderr.write('\n')
        sys.stderr.flush()

    def run(self) -> None:
        while not self._done.wait(0.1):
            self._render()

    def __enter__(self) -> Self:
        if IS_TTY:
            self.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._done.set()
        if self.is_alive():
            self.join()
        self._render(final=True)
