# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only reconnection after ratbagd's expected exit-on-idle."""

import asyncio
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import pytest
from PySide6.QtGui import QGuiApplication

from qt_piper.backend import Backend, DBusTransport, MockTransport, RatbagError


@pytest.fixture(scope="session")
def app():
    return QGuiApplication.instance() or QGuiApplication([])


@pytest.fixture
def activating_bus(tmp_path):
    if not shutil.which("dbus-daemon"):
        pytest.skip("dbus-daemon unavailable")
    service_dir = tmp_path / "services"
    service_dir.mkdir()
    calls_log = tmp_path / "calls.jsonl"
    server = tmp_path / "server.py"
    test_dir = Path(__file__).resolve().parent
    server.write_text(f"""import asyncio, json, os, sys, time
sys.path[:0] = [{str(test_dir)!r}, {str(test_dir.parents[1])!r}]
from test_backend import start_fake_daemon

async def main():
    bus, _, _, calls = await start_fake_daemon(os.environ['DBUS_STARTER_ADDRESS'])
    count, last = 0, time.monotonic()
    try:
        while bus.connected:
            await asyncio.sleep(0.01)
            if len(calls) != count:
                count, last = len(calls), time.monotonic()
            if time.monotonic() - last > 0.5:
                bus.disconnect()
    finally:
        with open({str(calls_log)!r}, 'a') as output:
            output.write(json.dumps([call.member for call in calls]) + '\\n')
        try:
            await bus.wait_for_disconnect()
        except EOFError:
            pass

asyncio.run(main())
""")
    (service_dir / "org.freedesktop.ratbag1.service").write_text(
        "[D-BUS Service]\nName=org.freedesktop.ratbag1\nExec="
        + shlex.join([sys.executable, str(server)])
        + "\n"
    )
    transport = os.environ.get("PIPER_TEST_BUS_TRANSPORT", "tcp")
    listen = (
        "unix:tmpdir=/tmp"
        if transport == "unix"
        else "tcp:host=127.0.0.1,port=0,family=ipv4"
    )
    config = tmp_path / "bus.conf"
    config.write_text(f"""<busconfig><type>session</type><listen>{listen}</listen>
        <auth>ANONYMOUS</auth><allow_anonymous/>
        <servicedir>{service_dir}</servicedir>
        <policy context="default"><allow send_destination="*"/>
        <allow receive_sender="*"/><allow own="*"/></policy></busconfig>""")
    process = subprocess.Popen(
        [
            "dbus-daemon",
            "--config-file=" + str(config),
            "--nofork",
            "--print-address=1",
        ],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        address = process.stdout.readline().strip()
        assert address, "Private D-Bus daemon failed to start"
        yield address, calls_log
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdout.close()


def test_idle_service_reactivates_without_manual_refresh(activating_bus, app):
    async def scenario():
        from dbus_next.auth import AuthAnnonymous

        address, calls_log = activating_bus
        transport = DBusTransport(bus_address=address, auth=AuthAnnonymous())
        backend = Backend(transport=transport)

        async def wait(condition, timeout=5):
            until = time.monotonic() + timeout
            while not condition():
                app.processEvents()
                assert time.monotonic() < until, (backend.status, backend.error)
                await asyncio.sleep(0.002)
            app.processEvents()

        try:
            await wait(lambda: backend.connected and not backend.busy)
            assert backend.setReportRate(500)
            for _ in range(2):
                await wait(lambda: not backend.connected)
                assert transport.bus.connected  # Service exit, not bus loss.
                await wait(lambda: backend.connected and not backend.busy)
                assert backend.dirty
                assert backend.selectedProfile["reportRate"] == 500
                assert backend.status != "Disconnected"
                assert "disconnected" not in backend.error.lower()
            records = [json.loads(line) for line in calls_log.read_text().splitlines()]
            assert len(records) >= 2
            assert all(member == "GetAll" for calls in records for member in calls)
        finally:
            backend.close()

    asyncio.run(scenario())


class RecoverableTransport:
    """Synthetic reads with explicit availability and no write implementation."""

    def __init__(self, available=True):
        self.available = available
        self.on_event = None
        self.reads = 0
        self.closed = False
        self.fixture = MockTransport("all")

    async def snapshot(self):
        self.reads += 1
        if not self.available:
            raise RatbagError("Synthetic service unavailable")
        return await self.fixture.snapshot()

    async def close(self):
        self.closed = True


def wait_for(app, condition, timeout=3):
    until = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        assert time.monotonic() < until, "Qt operation timed out"
        time.sleep(0.002)
    app.processEvents()


def test_failed_read_retries_with_capped_backoff_and_stops_on_success(app):
    transport = RecoverableTransport(available=False)
    backend = Backend(transport=transport)
    try:
        wait_for(app, lambda: transport.reads == 1 and not backend.busy)
        assert backend._reconnect_timer.isActive()
        assert backend._reconnect_timer.interval() == 1000
        for expected in (2000, 4000, 8000, 16000, 30000, 30000):
            reads = transport.reads
            backend._reconnect_timer.start(1)
            wait_for(
                app, lambda reads=reads: transport.reads > reads and not backend.busy
            )
            assert backend._reconnect_timer.interval() == expected
        transport.available = True
        backend._reconnect_timer.start(1)
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert not backend._reconnect_timer.isActive()
        transport.available = False
        transport.on_event("disconnected")
        app.processEvents()
        assert backend._reconnect_timer.interval() == 1000
        assert backend._reconnect_timer.isActive()
    finally:
        backend.close()
    assert transport.closed
    assert not backend._reconnect_timer.isActive()
    reads = transport.reads
    app.processEvents()
    assert transport.reads == reads


def test_reconnect_never_retries_partial_apply_and_keeps_guard(app):
    transport = RecoverableTransport()
    backend = Backend(transport=transport)
    try:
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert backend.setReportRate(500)
        backend._partial_apply = True
        backend._partial_devices = {backend.selectedDevice["path"]}
        backend._commit_state = "failed"
        transport.on_event("disconnected")
        app.processEvents()
        backend._reconnect_timer.start(1)
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert backend._partial_apply
        assert backend.commitState == "failed"
        assert backend.dirty
        assert backend.selectedProfile["reportRate"] == 500
        backend.reset()
        assert backend.dirty  # Guard still prohibits unsafe discard.
        assert "partly failed" in backend.error
    finally:
        backend.close()


def test_mock_disconnect_stays_manual_and_recovery_updates_dirty_status(app):
    backend = Backend(mock=True)
    try:
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert backend.setReportRate(500)
        backend.simulateDisconnect()
        assert not backend._reconnect_timer.isActive()
        assert not backend.connected
        backend.simulateReconnect()
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert backend.dirty
        assert backend.status == "Unapplied changes"
        assert not backend.error
    finally:
        backend.close()


def test_old_snapshot_cannot_cancel_a_newer_disconnect(app):
    class DisconnectDuringSnapshot(RecoverableTransport):
        lose_connection = False

        async def snapshot(self):
            snapshot = await super().snapshot()
            if self.lose_connection:
                self.lose_connection = False
                self.available = False
                self.on_event("disconnected")
            return snapshot

    transport = DisconnectDuringSnapshot()
    backend = Backend(transport=transport)
    try:
        wait_for(app, lambda: backend.connected and not backend.busy)
        transport.lose_connection = True
        backend.refresh()
        wait_for(app, lambda: transport.reads == 2 and not backend.busy)
        assert not backend.connected
        assert backend._reconnect_timer.isActive()
        transport.available = True
        backend._reconnect_timer.start(1)
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert transport.reads == 3
    finally:
        backend.close()


def test_old_apply_result_cannot_cancel_disconnect_or_replay_writes(app):
    class DisconnectDuringApply(RecoverableTransport):
        writes = 0

        async def apply(self, operations):
            self.writes += 1
            snapshot = await self.fixture.apply(operations)
            self.available = False
            self.on_event("disconnected")
            return snapshot

    transport = DisconnectDuringApply()
    backend = Backend(transport=transport)
    try:
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert backend.setReportRate(500)
        backend.apply()
        wait_for(app, lambda: not backend.busy)
        assert not backend.connected
        assert backend._partial_apply
        assert backend.commitState == "failed"
        assert backend._reconnect_timer.isActive()
        transport.available = True
        backend._reconnect_timer.start(1)
        wait_for(app, lambda: backend.connected and not backend.busy)
        assert backend._partial_apply
        assert transport.writes == 1
    finally:
        backend.close()
