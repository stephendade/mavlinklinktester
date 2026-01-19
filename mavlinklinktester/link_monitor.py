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

Link monitor for MAVLink connection testing.
Handles TIMESYNC latency measurement, packet monitoring, and sequence tracking.
Uses asyncio for concurrent operations with MAVConnection classes.
"""

import asyncio
import csv
import logging
import os
import time
from datetime import datetime
from typing import Optional, Union

import serial_asyncio

from mavlinklinktester.connection.seriallink import SerialConnection
from mavlinklinktester.connection.tcplink import TCPConnection
from mavlinklinktester.connection.udplink import UDPConnection
from mavlinklinktester.histogram_generator import HistogramGenerator


class LinkMonitor:
    """Monitors a single MAVLink link for latency, packet loss, and outages."""

    def __init__(self, link_id, connection_str, target_system, target_component,
                 output_dir, outage_timeout=1.0, recovery_hysteresis=3, stream_rates=None,
                 signing_key=None, signing_link_id=None):
        """Initialize LinkMonitor with connection parameters."""
        self.link_id = link_id
        self.connection_str = connection_str
        self.sanitized_connection = self._sanitize_connection_string(connection_str)
        self.target_system = target_system
        self.target_component = target_component
        self.output_dir = output_dir
        self.outage_timeout = outage_timeout
        self.recovery_hysteresis = recovery_hysteresis
        self.stream_rates = stream_rates or {}
        self.signing_key = signing_key
        self.signing_link_id = signing_link_id

        # MAVConnection instance
        self.connection: Optional[Union[UDPConnection, TCPConnection, SerialConnection]] = None
        self.connection_type = None  # 'udpout', 'udpin', 'tcp', or 'serial'
        self.heartbeat_received = False

        # Running flag
        self.running = False
        self.started = False  # Set to True after successful start

        # Current second metrics
        self.current_latency_ms = 0.0
        self.current_total_packets = 0
        self.current_dropped_packets = 0
        self.current_bad_order_packets = 0
        self.current_bytes = 0
        self.current_outage = False

        # Cumulative metrics for final summary
        self.total_packets = 0
        self.total_dropped_packets = 0
        self.total_bad_order_packets = 0
        self.latency_samples = []
        self.total_outage_seconds = 0.0

        # Sequence tracking
        self.last_sequence = None
        self.pending_sequences = {}  # {seq: timestamp} - sequences we're waiting for

        # TIMESYNC tracking for latency measurement
        self.sent_timestamps = []

        # Packet tracking for outage detection
        self.last_packet_time = None
        self.consecutive_packets = 0
        self.in_outage = False
        self.outage_start_time = None

        # Histogram data
        self.histogram = HistogramGenerator(link_id, self.sanitized_connection, output_dir)

        # CSV output
        self.csv_filepath = None
        self.csv_file = None
        self.csv_writer = None
        self.start_time = time.time()

        # Async tasks
        self.tasks = []

    def _sanitize_connection_string(self, conn_str):
        """Sanitize connection string for use in filenames."""
        sanitized = conn_str.replace(':', '_').replace('.', '_').replace('/', '_')
        return sanitized

    def _on_message_received(self, msg, name):
        """Callback for when a MAVLink message is received."""

        # Track all packets
        self.current_total_packets += 1

        # Track bytes (MAVLink message length)
        self.current_bytes += len(msg.get_msgbuf())

        # Update last packet time for outage detection
        self._update_packet_time()

        # Handle specific message types
        msg_type = msg.get_type()

        if msg_type == 'TIMESYNC':
            self._handle_timesync_response(msg)

        # Track sequence number for this message
        self._track_sequence(msg)

    def _on_connection_lost(self, name):
        """Callback for when connection is lost."""
        # Only handle connection loss after we've successfully started
        if self.started and self.running:
            logging.error('[%s] Connection lost: %s', self.link_id, name)
            self.running = False

    async def start(self):
        """Start the link monitor."""
        logging.info('[%s] Starting monitor for %s', self.link_id, self.connection_str)

        # Parse connection string and create appropriate MAVConnection
        try:
            conn_str = self.connection_str
            loop = asyncio.get_event_loop()

            if conn_str.startswith('udpout:'):
                # UDP output format: udpout:host:port
                parts = conn_str.split(':')
                if len(parts) != 3:
                    raise ValueError(f'Invalid udpout format: {conn_str}')
                host = parts[1]
                port = int(parts[2])

                logging.info('[%s] Connecting to UDP %s:%s', self.link_id, host, port)
                self.connection_type = 'udpout'

                # Create UDP connection (client mode)
                udp_conn = UDPConnection(
                    dialect='ardupilotmega',
                    mavversion=2.0,
                    name=conn_str,
                    srcsystem=255,  # GCS system ID
                    srccomp=0,  # GCS component ID
                    rxcallback=self._on_message_received,
                    server=False,
                    clcallback=self._on_connection_lost,
                    signing_key=self.signing_key,
                    link_id=self.signing_link_id if self.signing_link_id is not None else self.link_id,
                    target_system=self.target_system,
                    target_component=self.target_component
                )

                # Create datagram endpoint
                await loop.create_datagram_endpoint(
                    lambda: udp_conn,
                    remote_addr=(host, port)
                )

                self.connection = udp_conn

            elif conn_str.startswith('udpin:'):
                # UDP input format: udpin:bind_address:port
                parts = conn_str.split(':')
                if len(parts) != 3:
                    raise ValueError(f'Invalid udpin format: {conn_str}')
                bind_addr = parts[1]
                port = int(parts[2])

                logging.info('[%s] Binding UDP socket on %s:%s', self.link_id, bind_addr, port)
                self.connection_type = 'udpin'

                # Create UDP connection (server mode)
                udpin_conn = UDPConnection(
                    dialect='ardupilotmega',
                    mavversion=2.0,
                    name=conn_str,
                    srcsystem=255,
                    srccomp=0,
                    rxcallback=self._on_message_received,
                    server=True,
                    clcallback=self._on_connection_lost,
                    signing_key=self.signing_key,
                    link_id=self.signing_link_id if self.signing_link_id is not None else self.link_id,
                    target_system=self.target_system,
                    target_component=self.target_component
                )

                # Bind to local address
                await loop.create_datagram_endpoint(
                    lambda: udpin_conn,
                    local_addr=(bind_addr, port)
                )

                self.connection = udpin_conn

            elif conn_str.startswith('tcp:'):
                # TCP format: tcp:host:port
                parts = conn_str.split(':')
                if len(parts) != 3:
                    raise ValueError(f'Invalid tcp format: {conn_str}')
                host = parts[1]
                port = int(parts[2])

                logging.info('[%s] Connecting to TCP %s:%s', self.link_id, host, port)
                self.connection_type = 'tcp'

                # Create TCP connection
                tcp_conn = TCPConnection(
                    dialect='ardupilotmega',
                    mavversion=2.0,
                    name=conn_str,
                    srcsystem=255,
                    srccomp=0,
                    rxcallback=self._on_message_received,
                    server=False,
                    clcallback=self._on_connection_lost,
                    signing_key=self.signing_key,
                    link_id=self.signing_link_id if self.signing_link_id is not None else self.link_id,
                    target_system=self.target_system,
                    target_component=self.target_component
                )

                # Create TCP connection
                await loop.create_connection(
                    lambda: tcp_conn,
                    host, port
                )

                self.connection = tcp_conn

            elif conn_str.startswith('tcpin:'):
                # TCP format: tcp:host:port
                parts = conn_str.split(':')
                if len(parts) != 3:
                    raise ValueError(f'Invalid tcp format: {conn_str}')
                host = parts[1]
                port = int(parts[2])

                logging.info('[%s] Creating TCP server on %s:%s', self.link_id, host, port)
                self.connection_type = 'tcpin'

                # Create TCP connection
                tcp_conn = TCPConnection(
                    dialect='ardupilotmega',
                    mavversion=2.0,
                    name=conn_str,
                    srcsystem=255,
                    srccomp=0,
                    rxcallback=self._on_message_received,
                    server=True,
                    clcallback=self._on_connection_lost,
                    signing_key=self.signing_key,
                    link_id=self.signing_link_id if self.signing_link_id is not None else self.link_id,
                    target_system=self.target_system,
                    target_component=self.target_component
                )

                # Create TCP connection
                await loop.create_server(
                    lambda: tcp_conn,
                    host, port
                )

                self.connection = tcp_conn

            elif conn_str.startswith('/dev/'):
                # Serial port format: /dev/ttyXXX:baudrate
                parts = conn_str.split(':')
                if len(parts) != 2:
                    raise ValueError(f'Invalid serial format: {conn_str}')
                device = parts[0]
                baud = int(parts[1])

                logging.info('[%s] Opening serial port %s at %s baud', self.link_id, device, baud)
                self.connection_type = 'serial'

                # Create serial connection
                self.connection = SerialConnection(
                    dialect='ardupilotmega',
                    mavversion=2.0,
                    name=conn_str,
                    srcsystem=255,
                    srccomp=0,
                    rxcallback=self._on_message_received,
                    clcallback=self._on_connection_lost,
                    signing_key=self.signing_key,
                    link_id=self.signing_link_id if self.signing_link_id is not None else self.link_id,
                    target_system=self.target_system,
                    target_component=self.target_component
                )

                # For serial, we'll need to use pyserial with asyncio
                await serial_asyncio.create_serial_connection(
                    loop,
                    lambda: self.connection,
                    device,
                    baudrate=baud
                )
            else:
                raise ValueError(f'Unsupported connection type: {conn_str}')

            self.running = True

            # MAVLink signing is configured in the connection constructor
            if self.signing_key is not None:
                link_id = self.signing_link_id if self.signing_link_id is not None else self.link_id
                logging.info('[%s] MAVLink signing enabled (link_id=%s)', self.link_id, link_id)

            # Wait for heartbeat from target
            logging.info('[%s] Waiting for heartbeat...', self.link_id)
            heartbeat_received = await self.connection.wait_for_heartbeat()

            if not heartbeat_received:
                logging.error('[%s] Timeout waiting for heartbeat from '
                              'system %s, component %s', self.link_id, self.target_system, self.target_component)
                self.running = False
                return False

            logging.info('[%s] Connected to system '
                         '%s, component %s', self.link_id, self.target_system, self.target_component)

        except Exception as e:
            logging.error('[%s] Failed to connect: %s', self.link_id, e)
            import traceback
            traceback.print_exc()
            return False

        # Set up CSV output
        self.start_time = time.time()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Ensure output directory exists
        os.makedirs(self.output_dir, exist_ok=True)

        self.csv_filepath = os.path.join(
            self.output_dir,
            f'{self.sanitized_connection}_metrics_{timestamp}.csv')
        self.csv_file = open(self.csv_filepath, 'w', newline='')
        self.csv_writer = csv.writer(self.csv_file)
        self.csv_writer.writerow(['elapsed_seconds', 'total_packets', 'dropped_packets',
                                 'latency_ms', 'bad_order_packets', 'bytes', 'link_outage'])
        self.csv_file.flush()

        # Configure stream rates
        await self.connection.configure_stream_rates(self.stream_rates)

        # Start async tasks (no receiver loop - MAVConnection handles reception via callbacks)
        self.tasks = [
            asyncio.create_task(self._timesync_loop()),
            asyncio.create_task(self._heartbeat_loop()),
            asyncio.create_task(self._metrics_loop())
        ]

        # Mark as successfully started
        self.started = True

        return True

    def _track_sequence(self, msg):
        """Track MAVLink message sequence numbers."""
        seq = msg.get_seq()
        current_time = time.time()

        # Check if this sequence was in our pending list (arrived out of order)
        if seq in self.pending_sequences:
            # Packet arrived out of order - remove from pending, don't count as drop
            del self.pending_sequences[seq]
            self.current_bad_order_packets += 1
            return  # Don't update last_sequence for out-of-order packets

        # Clean up old pending sequences (older than 3 seconds) - count them as truly dropped
        timeout_threshold = current_time - 3.0
        for pending_seq, pending_time in list(self.pending_sequences.items()):
            if pending_time < timeout_threshold:
                self.current_dropped_packets += 1
                del self.pending_sequences[pending_seq]

        if self.last_sequence is not None:
            expected_seq = (self.last_sequence + 1) % 256

            if seq != expected_seq:
                # Check if this is going backwards (out of order)
                if seq < self.last_sequence:
                    backward_distance = self.last_sequence - seq
                    if backward_distance < 128:  # Not a wrap-around
                        # Out of order packet that wasn't in pending - very late arrival
                        self.current_bad_order_packets += 1
                        return  # Don't update last_sequence

                # Gap detected - add missing sequences to pending list
                if seq > expected_seq:
                    # Forward gap
                    missing_count = seq - expected_seq
                    for i in range(missing_count):
                        missing_seq = (expected_seq + i) % 256
                        self.pending_sequences[missing_seq] = current_time
                else:
                    # Wrap-around gap (255 -> 0)
                    missing_count = (256 - self.last_sequence - 1) + seq
                    for i in range(missing_count):
                        missing_seq = (expected_seq + i) % 256
                        self.pending_sequences[missing_seq] = current_time

        self.last_sequence = seq

    def _handle_timesync_response(self, msg):
        """Handle incoming TIMESYNC messages and calculate latency."""
        # Check if this is a response to our request (ts1 should match one we sent)
        if msg.ts1 in self.sent_timestamps:
            # Calculate round-trip time
            now_ns = time.time() * 1e9
            rtt_ms = (now_ns - msg.ts1) * 1e-6  # Convert to milliseconds

            self.current_latency_ms = rtt_ms
            self.histogram.add_latency_sample(rtt_ms)
            self.latency_samples.append(rtt_ms)

            # Remove the processed timestamp
            self.sent_timestamps.remove(msg.ts1)

    def _update_packet_time(self):
        """Update last packet time for outage detection (called on any received packet)."""
        current_time = time.time()
        self.last_packet_time = current_time

        if self.in_outage:
            # Require multiple consecutive packets to exit outage
            self.consecutive_packets += 1
            if self.consecutive_packets >= self.recovery_hysteresis:
                # Exit outage state - record the outage event
                if self.outage_start_time:
                    outage_duration = current_time - self.outage_start_time
                    self.total_outage_seconds = self.total_outage_seconds + outage_duration
                self.in_outage = False
                self.outage_start_time = None
        else:
            self.consecutive_packets = 0

    def _check_outage(self):
        """Check if link is in outage state and update current_outage flag."""
        if self.last_packet_time is None:
            return

        time_since_packet = time.time() - self.last_packet_time

        if time_since_packet > self.outage_timeout:
            if not self.in_outage:
                # Enter outage state
                self.in_outage = True
                self.outage_start_time = time.time()
                self.consecutive_packets = 0
            # Always set current_outage while in timeout
            self.current_outage = True
        else:
            # Packet is recent, but check if still in hysteresis recovery
            if self.in_outage:
                # Still in outage until hysteresis recovery completes
                self.current_outage = True
            else:
                # Normal operation
                self.current_outage = False

    async def stop(self):
        """Stop the link monitor."""
        logging.info('[%s] Stopping monitor...', self.link_id)
        self.running = False

        # If still in outage, record the outage time
        if self.in_outage:
            # Exit outage state - record the outage event
            if self.outage_start_time:
                outage_duration = time.time() - self.outage_start_time
                self.total_outage_seconds = self.total_outage_seconds + outage_duration

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Wait for all tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)

        # Close connection
        if self.connection:
            self.connection.close()

        # Close CSV file
        if self.csv_file:
            self.csv_file.close()

        # Generate histogram
        logging.info('[%s] Generating histogram...', self.link_id)

        # Set the actual elapsed time in the histogram
        if self.start_time:
            actual_elapsed = time.time() - self.start_time
            self.histogram.total_seconds = int(round(actual_elapsed))

        histogram_path = self.histogram.generate_histogram()

        # Print final summary
        logging.info('[%s] Final Summary:', self.link_id)
        logging.info('  Total Packets: %s', self.total_packets)

        if self.total_packets > 0:
            drop_percent = (self.total_dropped_packets / self.total_packets) * 100
            badorder_percent = (self.total_bad_order_packets / self.total_packets) * 100
            logging.info('  Total Drops: %s (%.2f%%)', self.total_dropped_packets, drop_percent)
            logging.info('  Total Bad Order: %s (%.2f%%)', self.total_bad_order_packets, badorder_percent)
        else:
            logging.info('  Total Drops: %s', self.total_dropped_packets)
            logging.info('  Total Bad Order: %s', self.total_bad_order_packets)

        if self.latency_samples:
            mean_latency = sum(self.latency_samples) / len(self.latency_samples)
            logging.info('  Mean Latency: %.2fms', mean_latency)
            median_latency = sorted(self.latency_samples)[len(self.latency_samples) // 2]
            logging.info('  Median Latency: %.2fms', median_latency)
        else:
            logging.info('  Mean Latency: N/A')
            logging.info('  Median Latency: N/A')

        # Add outage information
        total_outage_seconds = self.total_outage_seconds
        logging.info('  Total Outage Time: %.2fs (%.2f%%)', total_outage_seconds,
                     (total_outage_seconds / self.histogram.total_seconds) * 100)
        return histogram_path

    async def _timesync_loop(self):
        """Send TIMESYNC messages at 1Hz for latency measurement."""
        while self.running:
            try:
                # Get current time in nanoseconds
                now_ns = int(time.time() * 1e9)

                # Store the sent timestamp for matching responses
                self.sent_timestamps.append(now_ns)
                # Keep only last 10 timestamps to avoid memory growth
                if len(self.sent_timestamps) > 10:
                    self.sent_timestamps.pop(0)

                # Send TIMESYNC message (tc1=0, ts1=our timestamp)
                if self.connection is not None:
                    self.connection.sendPacket(
                        'TIMESYNC',
                        tc1=0,      # tc1 (not used in basic implementation)
                        ts1=now_ns  # ts1 = our timestamp
                    )

                await asyncio.sleep(1.0)  # Send TIMESYNC every second
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.running:
                    logging.error('[%s] TIMESYNC error: %s', self.link_id, e)
                    import traceback
                    traceback.print_exc()

    async def _heartbeat_loop(self):
        """Send HEARTBEAT messages at 1Hz to maintain the connection."""
        while self.running:
            try:
                if self.connection is not None:
                    await self.connection.send_heartbeat()
                await asyncio.sleep(1.0)  # Send HEARTBEAT every second
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.running:
                    logging.error('[%s] HEARTBEAT send error: %s', self.link_id, e)

    async def _metrics_loop(self):
        """Write metrics to CSV every second."""
        next_wake = time.time() + 1.0
        while self.running:
            try:
                # Sleep until next wake time
                sleep_time = next_wake - time.time()
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                next_wake += 1.0

                # Check for outage
                self._check_outage()

                # Calculate elapsed time
                elapsed = time.time() - self.start_time

                # Write current metrics
                if self.csv_writer is not None:
                    self.csv_writer.writerow([
                        int(round(elapsed)),
                        self.current_total_packets,
                        self.current_dropped_packets,
                        int(round(self.current_latency_ms)),
                        self.current_bad_order_packets,
                        self.current_bytes,
                        1 if self.current_outage else 0
                    ])
                if self.csv_file is not None:
                    self.csv_file.flush()

                # Update histogram
                self.histogram.increment_total_seconds()

                # Print status to console
                status = 'OUTAGE' if self.current_outage else 'OK'
                logging.info(
                    '[%s] %4ds | Latency: %3dms | Pkts: %3d | Drops: %3d | BadOrder: %3d | Bytes: %5d | %s',
                    self.link_id, int(round(elapsed)), int(round(self.current_latency_ms)),
                    self.current_total_packets, self.current_dropped_packets,
                    self.current_bad_order_packets, self.current_bytes, status
                )

                # Accumulate totals for final summary
                self.total_packets += self.current_total_packets
                self.total_dropped_packets += self.current_dropped_packets
                self.total_bad_order_packets += self.current_bad_order_packets

                # Reset per-second counters
                self.current_total_packets = 0
                self.current_dropped_packets = 0
                self.current_bad_order_packets = 0
                self.current_bytes = 0
            except asyncio.CancelledError:
                break
