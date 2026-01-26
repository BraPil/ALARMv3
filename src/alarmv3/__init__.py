"""
ALARMv3 - Automated Legacy App Refactoring and Modernization v3
Next Generation Code Intelligence Platform
"""

__version__ = "3.0.0"
__author__ = "BraPil"
__description__ = "Next Generation Code Intelligence Platform for Legacy Modernization"

from alarmv3.core import ALARMv3Engine
from alarmv3.config import Config

__all__ = ["ALARMv3Engine", "Config", "__version__"]
