from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from battle_app.env import _load_env_file


class BattleAppEnvTest(unittest.TestCase):
    def test_load_env_file_reads_simple_pairs_without_overriding_existing_env(self):
        old_env = {
            "GCG_TEST_ENV_KEEP": os.environ.get("GCG_TEST_ENV_KEEP"),
            "GCG_TEST_ENV_NEW": os.environ.get("GCG_TEST_ENV_NEW"),
        }
        try:
            os.environ["GCG_TEST_ENV_KEEP"] = "shell-value"
            os.environ.pop("GCG_TEST_ENV_NEW", None)
            with tempfile.TemporaryDirectory(prefix="gcg_battle_env_") as tmpdir:
                env_path = Path(tmpdir) / ".env"
                env_path.write_text(
                    "\n".join(
                        [
                            "# comment",
                            "GCG_TEST_ENV_KEEP=file-value",
                            "GCG_TEST_ENV_NEW='loaded-value'",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

                _load_env_file(env_path)

            self.assertEqual(os.environ["GCG_TEST_ENV_KEEP"], "shell-value")
            self.assertEqual(os.environ["GCG_TEST_ENV_NEW"], "loaded-value")
        finally:
            for key, value in old_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
