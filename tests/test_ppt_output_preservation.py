import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pptx import Presentation

from workflows.ppt import generate_ppt
from workflows.webui import server


class PptOutputPreservationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "thesis_presentation.pptx"
        deck = Presentation()
        deck.save(self.output)
        self.original = self.output.read_bytes()

    def test_rejected_missing_source_preserves_previous_deck(self):
        with patch.object(server, "OUTPUT_PPTX", self.output), patch.object(server.RUNNER, "start") as start:
            ok, _ = server.run_ppt_command(source="missing-test-thesis.md")

        self.assertFalse(ok)
        start.assert_not_called()
        self.assertEqual(self.output.read_bytes(), self.original)

    def test_rejected_busy_request_preserves_previous_deck(self):
        with patch.object(server, "OUTPUT_PPTX", self.output), patch.object(
            server.RUNNER, "start", return_value=(False, "已有任务正在运行")
        ) as start:
            ok, _ = server.run_ppt_command()

        self.assertFalse(ok)
        self.assertEqual(start.call_args.args[0][:2], [sys.executable, server.PPT_GENERATOR])
        self.assertEqual(self.output.read_bytes(), self.original)

    def test_partial_write_failure_preserves_previous_deck(self):
        def fail(path):
            path.write_bytes(b"incomplete")
            self.assertEqual(self.output.read_bytes(), self.original)
            raise OSError("simulated write failure")

        with self.assertRaisesRegex(OSError, "simulated write failure"):
            generate_ppt.save_presentation_atomically(Mock(save=fail), self.output)

        self.assertEqual(self.output.read_bytes(), self.original)
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_success_replaces_previous_deck(self):
        deck = Presentation()
        deck.slides.add_slide(deck.slide_layouts[6])
        generate_ppt.save_presentation_atomically(deck, self.output)

        self.assertEqual(len(Presentation(self.output).slides), 1)
        self.assertEqual(list(self.output.parent.iterdir()), [self.output])

    def test_termination_while_saving_preserves_previous_deck(self):
        script = """
import sys
import time
from pathlib import Path
from workflows.ppt.generate_ppt import save_presentation_atomically

class SlowDeck:
    def save(self, path):
        path.write_bytes(b"incomplete")
        Path(sys.argv[2]).touch()
        time.sleep(60)

save_presentation_atomically(SlowDeck(), Path(sys.argv[1]))
"""
        ready = self.output.with_suffix(".ready")
        runner = server.Runner()
        ok, _ = runner.start([sys.executable, "-c", script, str(self.output), str(ready)])
        self.assertTrue(ok)
        self.addCleanup(runner.process.stdout.close)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and runner.running() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            self.assertTrue(runner.stop())
            self.assertNotEqual(runner.process.wait(timeout=5), 0)
        finally:
            if runner.running():
                runner.process.kill()
                runner.process.wait(timeout=5)

        self.assertEqual(self.output.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()
