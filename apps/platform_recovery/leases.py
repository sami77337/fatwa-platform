"""Execution-bound reentrancy markers; copied contexts cannot outlive a real lock."""

import asyncio
import os
import threading
from dataclasses import dataclass


def execution():
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return os.getpid(), threading.get_ident(), id(task) if task is not None else None


@dataclass
class Lease:
    root: str
    owner: tuple
    active: bool = True

    def matches(self, root):
        return self.active and self.root == str(root) and self.owner == execution()
