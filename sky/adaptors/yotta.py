"""Yotta cloud adaptor."""

from sky.adaptors import common

runpod = common.LazyImport(
    'yotta',
    import_error_message='Failed to import dependencies for Yotta. '
    'Try running: pip install "skypilot[yotta]"')
