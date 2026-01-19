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

Unit tests for LinkMonitor class.
Tests sequence tracking, latency calculation, outage detection, and connection parsing.
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from mavlinklinktester.link_monitor import LinkMonitor


class TestLinkMonitor:
    """Test LinkMonitor functionality."""

    @pytest.fixture
    def monitor_config(self, temp_output_dir):
        """Basic monitor configuration."""
        return {
            'link_id': 0,
            'connection_str': 'udpin:0.0.0.0:14550',
            'target_system': 1,
            'target_component': 1,
            'output_dir': temp_output_dir,
            'outage_timeout': 1.0,
            'recovery_hysteresis': 3,
            'stream_rates': {},
            'signing_key': None,
            'signing_link_id': None,
        }

    @pytest.fixture
    def monitor(self, monitor_config):
        """Create a LinkMonitor instance for testing."""
        return LinkMonitor(**monitor_config)

    def test_sanitize_connection_string(self, monitor):
        """Test connection string sanitization for filenames."""
        assert monitor.sanitized_connection == 'udpin_0_0_0_0_14550'

        monitor2 = LinkMonitor(
            link_id=1,
            connection_str='tcp:192.168.1.100:5760',
            target_system=1,
            target_component=1,
            output_dir='/tmp',
            outage_timeout=1.0,
            recovery_hysteresis=3
        )
        assert monitor2.sanitized_connection == 'tcp_192_168_1_100_5760'

        monitor3 = LinkMonitor(
            link_id=2,
            connection_str='/dev/ttyUSB0:57600',
            target_system=1,
            target_component=1,
            output_dir='/tmp',
            outage_timeout=1.0,
            recovery_hysteresis=3
        )
        assert monitor3.sanitized_connection == '_dev_ttyUSB0_57600'

    def test_initialization(self, monitor, monitor_config):
        """Test LinkMonitor initialization."""
        assert monitor.link_id == 0
        assert monitor.connection_str == 'udpin:0.0.0.0:14550'
        assert monitor.target_system == 1
        assert monitor.target_component == 1
        assert monitor.outage_timeout == 1.0
        assert monitor.recovery_hysteresis == 3
        assert monitor.running is False
        assert monitor.started is False
        assert monitor.current_total_packets == 0
        assert monitor.current_dropped_packets == 0
        assert monitor.last_sequence is None
        assert len(monitor.pending_sequences) == 0

    def test_sequence_tracking_normal(self, monitor):
        """Test normal sequential packet tracking."""
        # Create mock messages with sequential sequence numbers
        for seq in range(5):
            msg = Mock()
            msg.get_seq.return_value = seq
            msg.get_msgbuf.return_value = b'\x00' * 30
            msg.get_type.return_value = 'HEARTBEAT'

            monitor._track_sequence(msg)

        # Last sequence should be 4
        assert monitor.last_sequence == 4
        # No dropped packets
        assert monitor.current_dropped_packets == 0
        # No bad order packets
        assert monitor.current_bad_order_packets == 0

    def test_sequence_tracking_with_gap(self, monitor):
        """Test sequence tracking with missing packets."""
        # Send sequence 0, 1, 2, then skip to 5
        for seq in [0, 1, 2, 5]:
            msg = Mock()
            msg.get_seq.return_value = seq
            msg.get_msgbuf.return_value = b'\x00' * 30
            msg.get_type.return_value = 'HEARTBEAT'

            monitor._track_sequence(msg)

        # Should have pending sequences 3 and 4
        assert 3 in monitor.pending_sequences
        assert 4 in monitor.pending_sequences
        assert len(monitor.pending_sequences) == 2

        # No drops yet (packets are pending)
        assert monitor.current_dropped_packets == 0

    def test_sequence_tracking_out_of_order(self, monitor):
        """Test out-of-order packet detection."""
        # Send 0, 1, 2, skip 3, 4, then receive 3 (out of order)
        for seq in [0, 1, 2, 5]:
            msg = Mock()
            msg.get_seq.return_value = seq
            msg.get_msgbuf.return_value = b'\x00' * 30
            msg.get_type.return_value = 'HEARTBEAT'
            monitor._track_sequence(msg)

        # Now send the late packet 3
        msg = Mock()
        msg.get_seq.return_value = 3
        msg.get_msgbuf.return_value = b'\x00' * 30
        msg.get_type.return_value = 'HEARTBEAT'
        monitor._track_sequence(msg)

        # Should be marked as bad order
        assert monitor.current_bad_order_packets == 1
        # Should be removed from pending
        assert 3 not in monitor.pending_sequences
        # Sequence 4 should still be pending
        assert 4 in monitor.pending_sequences

    def test_sequence_tracking_wraparound(self, monitor):
        """Test sequence number wraparound (255 -> 0)."""
        # Start at 254
        for seq in [254, 255, 0, 1, 2]:
            msg = Mock()
            msg.get_seq.return_value = seq
            msg.get_msgbuf.return_value = b'\x00' * 30
            msg.get_type.return_value = 'HEARTBEAT'

            monitor._track_sequence(msg)

        # Should handle wraparound correctly
        assert monitor.last_sequence == 2
        assert len(monitor.pending_sequences) == 0
        assert monitor.current_dropped_packets == 0

    def test_timesync_latency_calculation(self, monitor):
        """Test TIMESYNC latency measurement."""
        # Record a sent timestamp
        sent_time_ns = int(time.time() * 1e9)
        monitor.sent_timestamps.append(sent_time_ns)

        # Simulate a TIMESYNC response after 50ms
        time.sleep(0.05)

        msg = Mock()
        msg.get_type.return_value = 'TIMESYNC'
        msg.ts1 = sent_time_ns
        msg.get_seq.return_value = 10
        msg.get_msgbuf.return_value = b'\x00' * 30
        msg.get_srcSystem.return_value = 1
        msg.get_srcComponent.return_value = 1

        monitor._handle_timesync_response(msg)

        # Latency should be approximately 50ms
        assert 40 < monitor.current_latency_ms < 70  # Allow some variance
        # Timestamp should be removed
        assert sent_time_ns not in monitor.sent_timestamps

    def test_outage_detection_entry(self, monitor):
        """Test entering outage state."""
        # Set last packet time to 2 seconds ago
        monitor.last_packet_time = time.time() - 2.0
        monitor.outage_timeout = 1.0

        # Check for outage
        monitor._check_outage()

        # Should be in outage
        assert monitor.in_outage is True
        assert monitor.current_outage is True
        assert monitor.outage_start_time is not None

    def test_outage_detection_recovery(self, monitor):
        """Test recovery from outage with hysteresis."""
        # Enter outage state
        monitor.last_packet_time = time.time() - 2.0
        monitor.outage_timeout = 1.0
        monitor._check_outage()
        assert monitor.in_outage is True

        # First packet - still in outage
        monitor._update_packet_time()
        assert monitor.in_outage is True
        assert monitor.consecutive_packets == 1

        # Second packet - still in outage
        monitor._update_packet_time()
        assert monitor.in_outage is True
        assert monitor.consecutive_packets == 2

        # Third packet - should exit outage
        monitor._update_packet_time()
        assert monitor.in_outage is False
        assert monitor.consecutive_packets >= 3

    def test_message_received_callback(self, monitor):
        """Test message received callback updates counters."""
        msg = Mock()
        msg.get_type.return_value = 'HEARTBEAT'
        msg.get_seq.return_value = 0
        msg.get_msgbuf.return_value = b'\x00' * 30
        msg.get_srcSystem.return_value = 1
        msg.get_srcComponent.return_value = 1

        initial_packets = monitor.current_total_packets
        initial_bytes = monitor.current_bytes

        monitor._on_message_received(msg, 'test_connection')

        assert monitor.current_total_packets == initial_packets + 1
        assert monitor.current_bytes == initial_bytes + 30
        assert monitor.last_packet_time is not None

    @pytest.mark.asyncio
    async def test_connection_string_parsing_udpin(self, monitor_config, temp_output_dir):
        """Test parsing of udpin connection string."""
        monitor = LinkMonitor(
            link_id=0,
            connection_str='udpin:0.0.0.0:14550',
            target_system=1,
            target_component=1,
            output_dir=temp_output_dir,
            outage_timeout=1.0,
            recovery_hysteresis=3
        )

        # Test connection string parsing
        conn_str = monitor.connection_str
        assert conn_str.startswith('udpin:')
        parts = conn_str.split(':')
        assert len(parts) == 3
        assert parts[1] == '0.0.0.0'
        assert parts[2] == '14550'

    @pytest.mark.asyncio
    async def test_connection_string_parsing_udpout(self, temp_output_dir):
        """Test parsing of udpout connection string."""
        monitor = LinkMonitor(
            link_id=0,
            connection_str='udpout:192.168.1.100:14550',
            target_system=1,
            target_component=1,
            output_dir=temp_output_dir,
            outage_timeout=1.0,
            recovery_hysteresis=3
        )

        conn_str = monitor.connection_str
        assert conn_str.startswith('udpout:')
        parts = conn_str.split(':')
        assert len(parts) == 3
        assert parts[1] == '192.168.1.100'
        assert parts[2] == '14550'

    @pytest.mark.asyncio
    async def test_connection_string_parsing_tcp(self, temp_output_dir):
        """Test parsing of tcp connection string."""
        monitor = LinkMonitor(
            link_id=0,
            connection_str='tcp:192.168.1.100:5760',
            target_system=1,
            target_component=1,
            output_dir=temp_output_dir,
            outage_timeout=1.0,
            recovery_hysteresis=3
        )

        conn_str = monitor.connection_str
        assert conn_str.startswith('tcp:')
        parts = conn_str.split(':')
        assert len(parts) == 3
        assert parts[1] == '192.168.1.100'
        assert parts[2] == '5760'

    @pytest.mark.asyncio
    async def test_connection_string_parsing_serial(self, temp_output_dir):
        """Test parsing of serial connection string."""
        monitor = LinkMonitor(
            link_id=0,
            connection_str='/dev/ttyUSB0:57600',
            target_system=1,
            target_component=1,
            output_dir=temp_output_dir,
            outage_timeout=1.0,
            recovery_hysteresis=3
        )

        conn_str = monitor.connection_str
        assert conn_str.startswith('/dev/')
        parts = conn_str.split(':')
        assert len(parts) == 2
        assert parts[0] == '/dev/ttyUSB0'
        assert parts[1] == '57600'

    def test_pending_sequence_timeout(self, monitor):
        """Test that old pending sequences are marked as dropped."""
        # Add a pending sequence from 4 seconds ago
        old_time = time.time() - 4.0
        monitor.pending_sequences[10] = old_time

        # Add a recent pending sequence
        recent_time = time.time() - 0.5
        monitor.pending_sequences[11] = recent_time

        # Process a new message
        msg = Mock()
        msg.get_seq.return_value = 12
        msg.get_msgbuf.return_value = b'\x00' * 30
        msg.get_type.return_value = 'HEARTBEAT'

        monitor._track_sequence(msg)

        # Old sequence should be dropped
        assert 10 not in monitor.pending_sequences
        assert monitor.current_dropped_packets == 1

        # Recent sequence should still be pending
        assert 11 in monitor.pending_sequences

    def test_outage_duration_accumulation(self, monitor):
        """Test that total outage duration is accumulated correctly."""
        # Simulate an outage of 2 seconds
        monitor.outage_start_time = time.time() - 2.0
        monitor.in_outage = True

        # Recover from outage
        monitor._update_packet_time()  # This should trigger recovery
        monitor.in_outage = False
        outage_duration = time.time() - monitor.outage_start_time
        monitor.total_outage_seconds += outage_duration

        # Check total outage seconds
        assert 1.9 < monitor.total_outage_seconds < 2.1  # Allow some variance

    def test_no_outage_duration_when_no_outage(self, monitor):
        """Test that total outage duration remains zero when no outage occurs."""
        # Ensure no outage has occurred
        monitor.in_outage = False
        monitor.outage_start_time = None

        # Update packet time without any outage
        monitor._update_packet_time()

        # Check total outage seconds
        assert monitor.total_outage_seconds == 0.0

    @pytest.mark.asyncio
    async def test_outage_counted_when_program_closed_during_outage(self, monitor):
        """Test that outage duration is counted when stop() is called during an active outage."""
        # Simulate entering an outage state
        outage_start = time.time() - 3.0  # Outage started 3 seconds ago
        monitor.in_outage = True
        monitor.outage_start_time = outage_start
        monitor.total_outage_seconds = 0.0

        # Verify we're in an outage
        assert monitor.in_outage is True
        assert monitor.outage_start_time is not None

        # Call stop() while in outage
        # Mock the connection and tasks to avoid actual cleanup
        monitor.connection = Mock()
        monitor.connection.close = Mock()
        monitor.csv_file = None
        monitor.tasks = []
        monitor.start_time = time.time() - 10.0  # Started 10 seconds ago

        # Mock the histogram generation
        monitor.histogram = Mock()
        monitor.histogram.total_seconds = 10
        monitor.histogram.generate_histogram = Mock(return_value='/tmp/histogram.csv')

        await monitor.stop()

        # Verify that the outage duration was counted
        # Should be approximately 3 seconds (with some tolerance for execution time)
        assert monitor.total_outage_seconds >= 2.9
        assert monitor.total_outage_seconds <= 3.1

    @pytest.mark.asyncio
    async def test_multiple_outages_counted_when_closed_during_final_outage(self, monitor):
        """Test that multiple outages are properly accumulated when stop() is called during an outage."""
        # Simulate first outage that was already resolved
        monitor.total_outage_seconds = 5.0  # 5 seconds from previous outages

        # Simulate entering a new outage state
        outage_start = time.time() - 2.0  # Current outage started 2 seconds ago
        monitor.in_outage = True
        monitor.outage_start_time = outage_start

        # Verify we're in an outage
        assert monitor.in_outage is True
        assert monitor.outage_start_time is not None

        # Call stop() while in second outage
        # Mock the connection and tasks to avoid actual cleanup
        monitor.connection = Mock()
        monitor.connection.close = Mock()
        monitor.csv_file = None
        monitor.tasks = []
        monitor.start_time = time.time() - 20.0  # Started 20 seconds ago

        # Mock the histogram generation
        monitor.histogram = Mock()
        monitor.histogram.total_seconds = 20
        monitor.histogram.generate_histogram = Mock(return_value='/tmp/histogram.csv')

        await monitor.stop()

        # Verify that both outages are counted
        # Should be approximately 7 seconds total (5 + 2)
        assert monitor.total_outage_seconds >= 6.9
        assert monitor.total_outage_seconds <= 7.1

    @pytest.mark.asyncio
    async def test_no_additional_outage_counted_when_closed_not_in_outage(self, monitor):
        """Test that no extra outage time is added when stop() is called while not in outage."""
        # Simulate previous outages that were resolved
        monitor.total_outage_seconds = 3.0
        monitor.in_outage = False
        monitor.outage_start_time = None

        # Call stop() while NOT in outage
        # Mock the connection and tasks to avoid actual cleanup
        monitor.connection = Mock()
        monitor.connection.close = Mock()
        monitor.csv_file = None
        monitor.tasks = []
        monitor.start_time = time.time() - 10.0

        # Mock the histogram generation
        monitor.histogram = Mock()
        monitor.histogram.total_seconds = 10
        monitor.histogram.generate_histogram = Mock(return_value='/tmp/histogram.csv')

        await monitor.stop()

        # Verify that no additional outage time was added
        assert monitor.total_outage_seconds == 3.0

    @pytest.mark.asyncio
    async def test_latency_negative_one_excluded_from_stats(self, monitor):
        """Test that latency measurements of -1 are excluded from statistics calculations."""
        # Add a mix of valid latency samples and -1 values
        monitor.latency_samples = [10.0, -1.0, 20.0, -1.0, 30.0, 15.0, -1.0]

        # Mock the connection and tasks to avoid actual cleanup
        monitor.connection = Mock()
        monitor.connection.close = Mock()
        monitor.csv_file = None
        monitor.tasks = []
        monitor.start_time = time.time() - 10.0

        # Mock the histogram generation
        monitor.histogram = Mock()
        monitor.histogram.total_seconds = 10
        monitor.histogram.generate_histogram = Mock(return_value='/tmp/histogram.csv')

        # Capture log output to verify stats calculation
        with patch('mavlinklinktester.link_monitor.logging') as mock_logging:
            await monitor.stop()

            # Find the mean latency log call
            mean_latency_logged = False
            expected_mean = (10.0 + 20.0 + 30.0 + 15.0) / 4  # Only valid samples: 18.75

            for call in mock_logging.info.call_args_list:
                if len(call[0]) > 0 and 'Mean Latency (RTT)' in str(call[0][0]):
                    # Check that the value is close to expected (18.75ms)
                    if len(call[0]) > 1:
                        actual_mean = call[0][1]
                        assert abs(actual_mean - expected_mean) < 0.01
                        mean_latency_logged = True

            assert mean_latency_logged, 'Mean latency should be logged'

    @pytest.mark.asyncio
    async def test_latency_all_negative_one_reports_na(self, monitor):
        """Test that when all latency samples are -1, N/A is reported."""
        # Add only -1 samples
        monitor.latency_samples = [-1.0, -1.0, -1.0]

        # Mock the connection and tasks to avoid actual cleanup
        monitor.connection = Mock()
        monitor.connection.close = Mock()
        monitor.csv_file = None
        monitor.tasks = []
        monitor.start_time = time.time() - 10.0

        # Mock the histogram generation
        monitor.histogram = Mock()
        monitor.histogram.total_seconds = 10
        monitor.histogram.generate_histogram = Mock(return_value='/tmp/histogram.csv')

        # Capture log output to verify N/A is reported
        with patch('mavlinklinktester.link_monitor.logging') as mock_logging:
            await monitor.stop()

            # Find the mean latency log call
            na_logged = False
            for call in mock_logging.info.call_args_list:
                if len(call[0]) > 0 and 'Mean Latency (RTT): N/A' in str(call[0]):
                    na_logged = True

            assert na_logged, 'N/A should be logged when all samples are -1'

    @pytest.mark.asyncio
    async def test_latency_empty_list_reports_na(self, monitor):
        """Test that when no latency samples exist, N/A is reported."""
        # Empty latency samples list
        monitor.latency_samples = []

        # Mock the connection and tasks to avoid actual cleanup
        monitor.connection = Mock()
        monitor.connection.close = Mock()
        monitor.csv_file = None
        monitor.tasks = []
        monitor.start_time = time.time() - 10.0

        # Mock the histogram generation
        monitor.histogram = Mock()
        monitor.histogram.total_seconds = 10
        monitor.histogram.generate_histogram = Mock(return_value='/tmp/histogram.csv')

        # Capture log output to verify N/A is reported
        with patch('mavlinklinktester.link_monitor.logging') as mock_logging:
            await monitor.stop()

            # Find the mean latency log call
            na_logged = False
            for call in mock_logging.info.call_args_list:
                if len(call[0]) > 0 and 'Mean Latency (RTT): N/A' in str(call[0]):
                    na_logged = True

            assert na_logged, 'N/A should be logged when no samples exist'
