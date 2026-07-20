"""Stable Streamlit script entry point.

Streamlit executes this file as a script. Importing the application through the
installed package keeps package-relative imports inside ``ahs_copilot.ui.app``
valid in editable installs, wheels, and Docker images.
"""

from __future__ import annotations

from ahs_copilot.ui.app import main


if __name__ == "__main__":
    main()
