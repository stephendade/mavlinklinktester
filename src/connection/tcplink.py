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

Module for defining tcp connections to mavlink
"""
import logging
import socket
from typing import Any

from .mavconnection import MAVConnection


class TCPConnection(MAVConnection):
    """
    A MAVLink TCP connection (server or client)
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
        self.transport: Any = None

    def connection_made(self, transport) -> None:
        logging.debug('Connection made %s', self.name)
        self.transport = transport
        if self.transport is not None:
            sock = self.transport.get_extra_info('socket')
            sock.setsockopt(socket.SOL_TCP, socket.TCP_NODELAY, 1)

    def data_received(self, data) -> None:
        logging.debug('Rx packet %s', self.name)
        self.processPackets(data)

    def send_data(self, data: bytes) -> None:
        """Send a bytes through the link"""
        try:
            if self.transport is None:
                logging.debug('Tx send error (no transport) %s', self.name)
                if self.closecallback is not None:
                    self.closecallback(self.name)
                return
            self.transport.write(data)
            logging.debug('Tx packet %s', self.name)
        except AttributeError:
            # no transport - no current connection
            logging.debug('Tx send error %s', self.name)
            if self.closecallback is not None:
                self.closecallback(self.name)
            return

    def close(self):
        if self.transport is not None:
            self.transport.close()
