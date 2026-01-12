"""
The MAVLink Link Loss and Latency Tester (mavlinklinktester)
Copyright (C) 2026  Stephen Dade

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.

Module to hold helper functions for interfacing with the pymavlink library
"""
from importlib import import_module


def getpymavlinkpackage(dialect: str, version: float):
    """
    Return an import to the specified mavlink dialect and version
    """
    pkg = 'pymavlink.dialects.'
    if version == 1.0:
        pkg += 'v10.'
    elif version == 2.0:
        pkg += 'v20.'
    else:
        raise ValueError('Incorrect mavlink version (must be 1.0 or 2.0)')
    pkg += dialect

    mod = None
    try:
        mod = import_module(pkg)
    except ImportError:
        raise ValueError('Incorrect mavlink dialect')
    return mod
