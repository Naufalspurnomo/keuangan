from __future__ import annotations

import os
import subprocess
import sys

def test_application_module_imports_without_groq_credentials():
    environment = os.environ.copy()
    for key in ("GROQ_API_KEY", "GROQ_API_KEY_SECONDARY", "GROQ_API_KEYS"):
        environment.pop(key, None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import ai_helper; "
                "ai_helper.groq_client.chat.completions.create("
                "model='test', messages=[])"
            ),
        ],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "GROQ API key is missing" in result.stderr
