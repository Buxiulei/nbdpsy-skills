#!/usr/bin/env python3
"""Test build_manifest.py stderr output and core logic."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def test_stderr_output_complete():
    """Test that stderr reports each shot and summary line."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)

        # Create shots.json with 2 shots
        shots_data = {
            "video": {"ratio": "9:16"},
            "shots": [
                {"index": 1, "narration_text": "Test 1", "duration": 5},
                {"index": 2, "narration_text": "Test 2", "duration": 5},
            ]
        }
        (workdir / "shots.json").write_text(json.dumps(shots_data), encoding="utf-8")

        # Create shot-01.mp4 and narr-01.mp3 only
        (workdir / "shot-01.mp4").touch()
        (workdir / "narr-01.mp3").touch()

        # Run build_manifest.py
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "build_manifest.py"),
             "--workdir", str(workdir)],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        stderr = result.stderr
        stdout = result.stdout

        # Check stderr has shot reports
        assert "镜01" in stderr, f"Missing shot 01 report in stderr:\n{stderr}"
        assert "镜02" in stderr, f"Missing shot 02 report in stderr:\n{stderr}"

        # Check stderr has summary
        assert "清单完成" in stderr or "manifest 已写入" in stderr, \
            f"Missing summary in stderr:\n{stderr}"

        # Check stdout is valid JSON
        report = json.loads(stdout)
        assert report["ok"] == False, "Should fail (missing shot-02.mp4 and narr-02.mp3)"
        assert len(report["missing"]) == 2, f"Expected 2 missing files, got {len(report['missing'])}"

        print("✓ stderr_output_complete passed")


def test_stderr_output_success():
    """Test stderr output when all files exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)

        # Create shots.json with 1 shot
        shots_data = {
            "video": {"ratio": "9:16"},
            "shots": [
                {"index": 1, "narration_text": "Test", "duration": 5},
            ]
        }
        (workdir / "shots.json").write_text(json.dumps(shots_data), encoding="utf-8")

        # Create all required files
        (workdir / "shot-01.mp4").touch()
        (workdir / "narr-01.mp3").touch()

        # Run build_manifest.py
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "build_manifest.py"),
             "--workdir", str(workdir)],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        stderr = result.stderr
        stdout = result.stdout

        # Check stderr has success message
        assert "manifest 已写入" in stderr, f"Missing success message in stderr:\n{stderr}"
        assert "镜01" in stderr, f"Missing shot 01 report in stderr:\n{stderr}"

        # Check stdout is valid JSON with manifest path
        report = json.loads(stdout)
        assert report["ok"] == True, f"Should succeed, got: {report}"
        assert report["manifest"] is not None, "Should have manifest path"

        print("✓ stderr_output_success passed")


def test_stdout_is_pure_json():
    """Test that stdout contains only JSON (no stderr leakage)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workdir = Path(tmpdir)

        shots_data = {
            "video": {"ratio": "9:16"},
            "shots": [
                {"index": 1, "narration_text": "Test", "duration": 5},
            ]
        }
        (workdir / "shots.json").write_text(json.dumps(shots_data), encoding="utf-8")
        (workdir / "shot-01.mp4").touch()
        (workdir / "narr-01.mp3").touch()

        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent.parent / "scripts" / "build_manifest.py"),
             "--workdir", str(workdir)],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )

        stdout = result.stdout.strip()

        # stdout should be valid JSON (no stderr pollution)
        try:
            json.loads(stdout)
        except json.JSONDecodeError as e:
            raise AssertionError(f"stdout is not valid JSON:\n{stdout}\nError: {e}")

        print("✓ stdout_is_pure_json passed")


if __name__ == "__main__":
    test_stderr_output_complete()
    test_stderr_output_success()
    test_stdout_is_pure_json()
    print("\nAll tests passed!")
