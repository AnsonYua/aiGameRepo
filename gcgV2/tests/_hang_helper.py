#!/usr/bin/env python3
"""Test helper: sleeps forever ignoring argv."""
import sys
import time

if __name__ == "__main__":
    time.sleep(999)
    sys.exit(0)
