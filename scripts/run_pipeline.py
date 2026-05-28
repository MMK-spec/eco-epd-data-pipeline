"""Andmetöövoog.

Skript pärib API-st EPD andmed, salvestab selle `staging`
kihti, ehitab `mart` kihis otsustamiseks sobivad tabelid ning käivitab
kvaliteedikontrollid.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import requests

