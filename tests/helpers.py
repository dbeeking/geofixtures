"""Importable adapters for tests that run in a worker process."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from geofixtures import Capability, ObservationBundle, Rejection
from geofixtures.adapters.reference import ReferenceAdapter


class Base:
    name = "helper"

    def supports(self, case):
        return Capability(True)

    def environment(self):
        return {}


class Sleeper(Base):
    """Leaves a marker file if it runs past its sleep."""

    def __init__(self, marker, seconds=0.5):
        self.marker = str(marker)
        self.seconds = seconds

    def execute(self, context):
        time.sleep(self.seconds)
        Path(self.marker).write_text("still running")
        return ObservationBundle()


class ChildStarter(Base):
    """Starts a long-running child, as an adapter that shells out to pdal would."""

    def __init__(self, pid_file):
        self.pid_file = str(pid_file)

    def execute(self, context):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(self.pid_file).write_text(str(child.pid))
        time.sleep(60)
        return ObservationBundle()


class BackgroundChild(Base):
    """Returns normally and leaves a child behind."""

    def __init__(self, pid_file):
        self.pid_file = str(pid_file)

    def execute(self, context):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(self.pid_file).write_text(str(child.pid))
        return ReferenceAdapter().execute(context)


class IgnoresTerm(Base):
    def execute(self, context):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(60)
        return ObservationBundle()


class Crashes(Base):
    def execute(self, context):
        os._exit(7)


class KilledBySignal(Base):
    """Dies the way a native crash does. SIGKILL avoids the macOS crash dialog."""

    def execute(self, context):
        os.kill(os.getpid(), signal.SIGKILL)
        return ObservationBundle()


class Raises(Base):
    def execute(self, context):
        raise RuntimeError("boom")


class Rejects(Base):
    def execute(self, context):
        return ObservationBundle(rejection=Rejection("AXIS_ORDER_SUSPECT", "swapped"))


class Noisy(Base):
    def execute(self, context):
        print("progress on stdout")
        print("progress on stderr", file=sys.stderr)
        return ReferenceAdapter().execute(context)


class ReportsNumpy(Base):
    """Returns numpy values and a path through the worker's JSON channel."""

    def execute(self, context):
        import numpy as np

        return ObservationBundle(
            values={
                "overlap_pairs": np.array(["A|B"]),
                "overlap_area": np.float64(4.0),
                "union_area": np.float32(36.0),
                "overlap_geometry": "POLYGON ((400003 3800002, 400005 3800002, 400005 3800004, "
                "400003 3800004, 400003 3800002))",
            }
        )


class NotANumber(Base):
    def execute(self, context):
        values = {"overlap_pairs": ["A|B"], "overlap_area": float("nan"), "union_area": float("inf")}
        return ObservationBundle(values={**values, "overlap_geometry": "POINT (0 0)"})


class BadValue(Base):
    def execute(self, context):
        return ObservationBundle(values={"overlap_area": object()})


class Connects(Base):
    def execute(self, context):
        import socket

        with socket.socket() as connection:
            connection.connect(("192.0.2.1", 80))
        return ObservationBundle()
