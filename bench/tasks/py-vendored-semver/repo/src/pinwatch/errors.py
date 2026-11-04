"""Errors that the command line reports as ``pinwatch: error: ...`` with exit status 2."""


class PinwatchError(Exception):
    """A problem with the input (a missing file, malformed JSON, a bad version or policy)."""
