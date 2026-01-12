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

Can import any generate dialect from pymavlink, rasing an exception
if that dialet does not exist

"""

import pytest

from src.mavlink.pymavutil import getpymavlinkpackage


class TestGetpymavlinkpackage:

    """
    Class to test getpymavlinkpackage
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up some data that is reused in many tests"""
        self.dialects = ['ardupilotmega', 'common', 'standard', 'minimal']
        self.versions = [1.0, 2.0]

    def test_goodimports(self):
        """Test importing known good modules"""
        for dialect in self.dialects:
            for version in self.versions:
                mod = getpymavlinkpackage(dialect, version)
                assert mod is not None

    def test_badimports(self):
        """test a bad import, ie one that does not exist"""
        try:
            mod = getpymavlinkpackage('bad', 1.0)
        except ValueError as e:
            assert str(e) == 'Incorrect mavlink dialect'
            assert 'mod' not in locals()

        try:
            mod = getpymavlinkpackage('common', 1.5)
        except ValueError as e:
            assert str(e) == 'Incorrect mavlink version (must be 1.0 or 2.0)'
            assert 'mod' not in locals()
