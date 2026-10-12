"""pytest collects the unit suites only.

The *_browser.py files are stand-alone Playwright scripts (python3 tests/x_browser.py):
they start servers and patch providers at import time, so collecting them would
run that setup and, in test_aria_claude_voice_browser, replace the Gemini
provider's streaming for every suite imported after it (the Gemini parsing
tests then saw no request). They are run on their own, never through pytest."""
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
collect_ignore = [os.path.basename(p) for p in glob.glob(os.path.join(HERE, "*_browser.py"))] + ["deriv_replay_server.py"]
