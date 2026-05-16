#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# Silence Intel Fortran's Ctrl+C stack-trace on Windows (Anaconda MKL ships
# libifcoremd.dll, which is pulled in via numpy/faiss/sentence-transformers).
# Must be set BEFORE any of those libraries are imported.
os.environ.setdefault("FOR_DISABLE_CONSOLE_CTRL_HANDLER", "1")


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'chatapp.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
