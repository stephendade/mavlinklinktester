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


Subclass for managing MAVLink connections
"""
import asyncio
import logging
import time


from ..mavlink.pymavutil import getpymavlinkpackage


class MAVConnection(asyncio.Protocol):
    """
    A base MAVLink connection class
    """
    def __init__(self, dialect: str, mavversion: float, name: str,
                 srcsystem: int, srccomp: int, rxcallback, link_id: int,
                 target_system: int, target_component: int,
                 clcallback=None, signing_key=None) -> None:
        self.sourceSystem = srcsystem
        self.sourceComponent = srccomp
        self.mod = getpymavlinkpackage(dialect, mavversion)
        self.mav = self.mod.MAVLink(self, self.sourceSystem,
                                    self.sourceComponent, use_native=False)
        self.mav.robust_parsing = True
        self.link_id = link_id
        self.target_system = target_system
        self.target_component = target_component
        self.heartbeat_received = False
        self.server = False

        # BW measures for RX, per sysid
        # bytes and time(sec) in measurement period
        self.bytesmeasure = (0, time.time())
        self.bytespersecond = 0

        self.callback = rxcallback
        self.closecallback = clcallback

        # Loss % per sysid

        # BW measures for TX, per sysid

        self.name = name

        # Set up MAVLink signing if configured
        if signing_key is not None:
            import hashlib
            # signing_key can be bytes or string
            if isinstance(signing_key, bytes):
                secret_key = signing_key
            else:
                secret_key = hashlib.sha256(signing_key.encode()).digest()
            self.mav.signing.link_id = self.link_id
            self.mav.signing.secret_key = secret_key
            self.mav.signing.sign_outgoing = True
            self.mav.signing.allow_unsigned_callback = None
            self.mav.signing.timestamp = int(time.time() * 1e5)
            logging.info('MAVLink signing enabled for %s (link_id=%d)', name, self.link_id)

    def processPackets(self, data):
        """
        When data is recieved on the device, process
        into mavlink packets
        """
        msgList = self.mav.parse_buffer(data)
        if msgList:
            for msg in msgList:
                if not (msg.get_srcSystem() == self.target_system and msg.get_srcComponent() == self.target_component):
                    continue
                if msg.get_type() == 'HEARTBEAT':
                    self.heartbeat_received = True
                if self.callback:
                    self.callback(msg, self.name)

    def connection_lost(self, exc):
        logging.debug('Connection Lost - %s', self.name)
        if self.closecallback:
            self.closecallback(self.name)

    def error_received(self, exc):
        """Handle a fatal error on the connection"""
        logging.debug('Error Received - %s - %s', self.name, str(exc))
        if self.closecallback:
            self.closecallback(self.name)

    def send_data(self, data: bytes) -> None:
        """Send data - implemented by subclasses."""
        raise NotImplementedError('Subclasses must implement send_data')

    def updatebandwidth(self, bytelen):
        """
        Update the bandwidth (bytes/sec) measurement by
        taking in the number of new bytes recieved,
        every 5 seconds
        """
        (bytesi, timei) = self.bytesmeasure
        if time.time() - timei > 5:
            # do an update if 5 seconds since last BW update
            self.bytespersecond = int(bytesi / (time.time() - timei))
            self.bytesmeasure = (bytelen, time.time())
        else:
            self.bytesmeasure = (bytesi + bytelen, timei)

    def sendPacket(self, pktType: str, **kwargs):
        """
        Send the packet a smarter way
        pktType is message type string (e.g., 'HEARTBEAT', 'TIMESYNC')
        """
        # Get the message class from the module
        msg_class_name = f'MAVLink_{pktType.lower()}_message'
        if not hasattr(self.mod, msg_class_name):
            raise ValueError(f"Unknown MAVLink message type: {pktType}")

        msg_class = getattr(self.mod, msg_class_name)

        # Create the message with provided kwargs
        pkt = msg_class(**kwargs)

        # Pack and send the message
        buf = pkt.pack(self.mav, force_mavlink1=False)
        self.mav.seq = (self.mav.seq + 1) % 256
        self.mav.total_packets_sent += 1
        self.mav.total_bytes_sent += len(buf)

        logging.debug('GCS sending %s', pkt.get_type())
        self.send_data(buf)

        # return the packed bytes for reference
        return buf

    async def send_heartbeat(self):
        """Send a HEARTBEAT message."""
        self.sendPacket(
            'HEARTBEAT',
            type=self.mod.MAV_TYPE_GCS,
            autopilot=self.mod.MAV_AUTOPILOT_INVALID,
            base_mode=0,
            custom_mode=0,
            system_status=self.mod.MAV_STATE_ACTIVE,
            mavlink_version=3
        )

    async def configure_stream_rates(self, stream_rates: dict):
        """Configure MAVLink stream rates using REQUEST_DATA_STREAM."""
        stream_map = {
            'RAW_SENSORS': self.mod.MAV_DATA_STREAM_RAW_SENSORS,
            'EXTENDED_STATUS': self.mod.MAV_DATA_STREAM_EXTENDED_STATUS,
            'RC_CHANNELS': self.mod.MAV_DATA_STREAM_RC_CHANNELS,
            'POSITION': self.mod.MAV_DATA_STREAM_POSITION,
            'EXTRA1': self.mod.MAV_DATA_STREAM_EXTRA1,
            'EXTRA2': self.mod.MAV_DATA_STREAM_EXTRA2,
            'EXTRA3': self.mod.MAV_DATA_STREAM_EXTRA3
        }

        for stream_name, stream_id in stream_map.items():
            rate = stream_rates.get(stream_name, 0)
            if rate > 0:
                try:
                    self.sendPacket(
                        'REQUEST_DATA_STREAM',
                        target_system=self.target_system,
                        target_component=self.target_component,
                        req_stream_id=stream_id,
                        req_message_rate=rate,  # rate in Hz
                        start_stop=1  # start streaming
                    )
                    logging.info(f'[{self.link_id}] Requested {stream_name} stream at {rate}Hz')
                except Exception as e:
                    logging.warning(f'[{self.link_id}] Warning: Failed to set {stream_name} rate: {e}')

    async def wait_for_heartbeat(self):
        """Wait for heartbeat from target system/component."""
        start_time = time.time()
        timeout = 10.0
        last_heartbeat_sent = 0.0

        # Store heartbeat flag
        self.heartbeat_received = False

        while time.time() - start_time < timeout:
            # For udpout and tcp (client modes), send heartbeat to establish connection
            # For udpin (server mode), don't send until we know the remote address
            if not self.server:
                current_time = time.time()
                if current_time - last_heartbeat_sent >= 1.0:
                    logging.info('[%s] Sending HEARTBEAT to target...', self.link_id)
                    await self.send_heartbeat()
                    last_heartbeat_sent = current_time

            # Check if heartbeat was received (set by _on_message_received callback)
            if self.heartbeat_received:
                logging.info('[%s] Heartbeat received from target.', self.link_id)
                return True

            await asyncio.sleep(0.1)

        return False
