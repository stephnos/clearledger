"""All money movements use one database transaction, never floating-point arithmetic."""

import hashlib
import json
import sqlite3
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

MAX_AMOUNT = 1_000_000_000_000


