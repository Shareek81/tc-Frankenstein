import asyncio
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from integrations.simulator import AttackSimulatorControl


class AttackSimulatorControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.stop_path = self.root / "AttackSim.stop"
        self.control = AttackSimulatorControl(stop_path=self.stop_path)

    async def test_stop_request_is_idempotent(self):
        await self.control.request_stop()
        await self.control.request_stop()
        self.assertTrue(self.stop_path.is_file())

    async def test_missing_directory_propagates_error(self):
        control = AttackSimulatorControl(stop_path=self.root / "missing" / "AttackSim.stop")
        with self.assertRaises(OSError):
            await control.request_stop()

    async def test_real_script_stops_and_can_restart(self):
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            self.skipTest("PowerShell is not installed")
        script = Path(__file__).resolve().parents[2] / "TheChaosMonkey" / "AttackSim.ps1"
        log_path = self.root / "events.log"
        log_path.write_text("existing history\n", encoding="utf-8")
        environment = {
            **os.environ, "ATTACK_SIM_STOP_PATH": str(self.stop_path.resolve()),
            "PIPENV_DONT_LOAD_ENV": "1",
        }
        for arguments in (["-StopPath", str(self.stop_path)], []):
            await self.control.request_stop()
            process = await asyncio.create_subprocess_exec(
                executable, "-NoProfile", "-NonInteractive", "-File", str(script),
                "-LogPath", str(log_path), *arguments, env=environment,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                async with asyncio.timeout(10):
                    while True:
                        line = await process.stdout.readline()
                        self.assertTrue(line, "Simulator exited before generating a log")
                        if b"Generated Threat:" in line:
                            break
                self.assertFalse(self.stop_path.exists())
                await self.control.request_stop()
                output, error = await asyncio.wait_for(process.communicate(), timeout=8)
                self.assertEqual(process.returncode, 0, error.decode(errors="replace"))
                self.assertIn(b"Attack simulation stopped.", output)
                self.assertTrue(log_path.read_text(encoding="utf-8").startswith("existing history\n"))
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.communicate()


if __name__ == "__main__":
    unittest.main()