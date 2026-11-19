"""Alias physical common folder to its installed Python package name."""
import sys
import g15_common
sys.modules.setdefault('common', g15_common)
