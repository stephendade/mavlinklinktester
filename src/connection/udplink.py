"""
The MAVLink Link Loss and Latency Tester (mave2e)
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

Module for defining udp connections to mavlink
"""
import logging

from connection.mavconnection import MAVConnection


class UDPConnection(MAVConnection):
    """
    A MAVLink UDP connection (server or client)
    """
    def __init__(self, dialect: str, mavversion: float, name: str,
                 srcsystem: int, srccomp: int, rxcallback, server: bool, link_id: int,
                 target_system: int, target_component: int,
                 clcallback=None, signing_key=None) -> None:
        MAVConnection.__init__(self, dialect, mavversion, name,
                               srcsystem, srccomp, rxcallback, link_id,
                               target_system, target_component,
                               clcallback, signing_key)
        self.server = server
        self.transport = None

        if self.server:
            self.addr = None
        else:
            self.addr = (name.split(':')[1], int(name.split(':')[2]))

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data, addr) -> None:
        """A packet is recieved by this link"""
        logging.debug("Rx packet %s", self.name)
        if self.server:
            self.addr = addr
        self.processPackets(data)

    def send_data(self, data: bytes) -> None:
        """Send a buffer of bytes to the other side of the link"""
        try:
            logging.debug("Tx packet %s", self.name)
            if self.server:
                # Server mode: send to the last known client address
                if self.addr:
                    self.transport.sendto(data, self.addr)
                else:
                    logging.debug("No remote to tx to %s", self.name)
            else:
                # Client mode: transport is already connected, send without address
                self.transport.sendto(data)
        except AttributeError:
            # no transport - no current connection
            if self.closecallback:
                self.closecallback(self.name)

    def close(self):
        if self.transport:
            self.transport.close()
