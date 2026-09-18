"""Independent supervised financial consumer; its ACK loop never waits for a model."""
import json
import os
from pathlib import Path
import signal
import threading
import time

from smartlect.events import Ledger, consume
from smartlect.maintenance import purge_expired


def worker_health():
    try:
        status = json.loads(Path(os.environ["SMARTLECT_WORKER_STATUS_FILE"]).read_text())
        status["connected"] = bool(status["connected"] and 0 <= time.time() - status["observed_at"] < 5)
        return status
    except (OSError, ValueError, KeyError):
        return {"connected": False, "error": "worker_unavailable"}


def main():
    ledger = Ledger()
    ledger.initialize()
    stop = threading.Event()
    status = {"connected": False, "error": "starting"}
    path = Path(os.environ["SMARTLECT_WORKER_STATUS_FILE"])
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    for event in (signal.SIGTERM, signal.SIGINT):
        signal.signal(event, lambda *_: stop.set())
    consumer = threading.Thread(target=consume, args=(ledger, stop, status), daemon=True)
    consumer.start()
    maintenance = None
    next_maintenance = 0.0
    try:
        while not stop.is_set():
            if time.monotonic() >= next_maintenance and (maintenance is None or not maintenance.is_alive()):
                maintenance = threading.Thread(target=purge_expired, name='smartlect-retention', daemon=True)
                maintenance.start()
                next_maintenance = time.monotonic() + 86400
            snapshot = {**status, "pid": os.getpid(), "observed_at": time.time()}
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(snapshot))
            temporary.chmod(0o600)
            temporary.replace(path)
            stop.wait(0.5)
    finally:
        stop.set()
        consumer.join(timeout=7)
        path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
