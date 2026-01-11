#!/usr/bin/env python3
"""
The Python-async Ground Station (PaGS), a mavlink ground station for
autonomous vehicles.
Copyright (C) 2019  Stephen Dade
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
"""

'''TCPLink tests
Can send and recieve data (client/server)
If a link fails (disconnected) the link should not crash.
'''

import asyncio
import pytest
import subprocess
import serial_asyncio

from src.connection.seriallink import SerialConnection
from src.connection.tcplink import TCPConnection
from src.mavlink.pymavutil import getpymavlinkpackage


class TestSerialLink:

    """
    Class to test SerialLink
    Requires a specifc serial virtual port (socat for Linux, com2tcp for Windows)
    """

    @pytest.fixture(autouse=True)
    def setup(self):
        """Set up some data that is reused in many tests"""
        self.dialect = 'ardupilotmega'
        self.version = 2.0
        self.ip = '127.0.0.1'
        self.port = 15001
        self.baud = 115200
        self.cname = 'tcpclient:127.0.0.1:15001'
        self.sname = None

        # the serial <-> tcp server process. Will vary depending on OS
        # Based on
        # https://github.com/Apollon77/SupportingFiles/blob/master/README_SERIAL_TESTING.md
        self.serialServer = subprocess.Popen(
            [
                'socat',
                '-D',
                '-x',
                '-s',
                'pty,link=/tmp/virtualcom0,ispeed=115200,ospeed=115200,raw,waitslave',
                'tcp:127.0.0.1:15001'],
            stdout=subprocess.PIPE)
        self.sname = 'serial:/tmp/virtualcom0:115200'
        self.sPort = '/tmp/virtualcom0'

        self.mod = getpymavlinkpackage(self.dialect, self.version)
        self.mav = self.mod.MAVLink(
            self, srcSystem=0, srcComponent=0, use_native=False)
        self.cnum = 0
        self.snum = 0
        
        yield
        
        # Teardown
        if self.serialServer:
            self.serialServer.terminate()

    def newpacketcallback(self, pkt, strconnection):
        """Callback when a link has a new packet"""
        if pkt.get_type() == 'HEARTBEAT':
            if strconnection == self.cname:
                self.cnum += 1
            elif strconnection == self.sname:
                self.snum += 1

    @pytest.mark.asyncio
    async def test_link_serial(self):
        """Test passing data over a serial connections"""

        # server = SerialConnection
        server = SerialConnection(rxcallback=self.newpacketcallback,
                                  dialect=self.dialect, mavversion=self.version,
                                  srcsystem=0, srccomp=0, name=self.sname, link_id=0,
                                  target_system=0, target_component=0)

        client = TCPConnection(rxcallback=self.newpacketcallback,
                               dialect=self.dialect, mavversion=self.version,
                               srcsystem=0, srccomp=0, server=True, name=self.cname, link_id=0,
                               target_system=0, target_component=0)

        await asyncio.sleep(0.10)

        loop = asyncio.get_event_loop()
        await serial_asyncio.create_serial_connection(loop, lambda: server, self.sPort, self.baud)
        await loop.create_server(lambda: client, self.ip, self.port)

        # wait for 1.00 sec
        await asyncio.sleep(1.0)

        # send a mavlink packet each way:
        pkt = self.mod.MAVLink_heartbeat_message(
            5, 4, 0, 0, 0, int(self.version))
        client.send_data(pkt.pack(self.mav, force_mavlink1=False))
        server.send_data(pkt.pack(self.mav, force_mavlink1=False))

        # wait for 0.30 sec
        await asyncio.sleep(0.30)

        client.close()
        server.close()

        # Assert the packets were sent
        assert self.cnum == 1
        assert self.snum == 1
