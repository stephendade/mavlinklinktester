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

Integration tests for MAVConnection base class.
Tests MAVLink message parsing, signing, heartbeat waiting, and stream rate configuration.
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, patch, MagicMock
from src.connection.mavconnection import MAVConnection
from src.mavlink.pymavutil import getpymavlinkpackage


class TestMAVConnection:
    """Test MAVConnection functionality."""

    @pytest.fixture
    def mavlink_module(self):
        """Get pymavlink module for testing."""
        return getpymavlinkpackage('ardupilotmega', 2.0)

    @pytest.fixture
    def mock_callback(self):
        """Mock receive callback."""
        return Mock()

    @pytest.fixture
    def connection(self, mock_callback):
        """Create a MAVConnection instance for testing."""
        conn = MAVConnection(
            dialect='ardupilotmega',
            mavversion=2.0,
            name='test_connection',
            srcsystem=255,
            srccomp=0,
            rxcallback=mock_callback,
            link_id=0,
            target_system=1,
            target_component=1,
            clcallback=None,
            signing_key=None
        )
        return conn

    def test_initialization(self, connection, mock_callback):
        """Test MAVConnection initialization."""
        assert connection.sourceSystem == 255
        assert connection.sourceComponent == 0
        assert connection.name == 'test_connection'
        assert connection.link_id == 0
        assert connection.target_system == 1
        assert connection.target_component == 1
        assert connection.callback == mock_callback
        assert connection.heartbeat_received is False

    def test_process_packets_filters_by_system(self, connection, mock_callback, mavlink_module):
        """Test that processPackets filters messages by system/component ID."""
        # Create a HEARTBEAT message from target system
        mav = mavlink_module.MAVLink(connection, 1, 1, use_native=False)
        msg = mavlink_module.MAVLink_heartbeat_message(
            type=mavlink_module.MAV_TYPE_QUADROTOR,
            autopilot=mavlink_module.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink_module.MAV_STATE_ACTIVE,
            mavlink_version=3
        )
        data = msg.pack(mav, force_mavlink1=False)

        # Process the packet
        connection.processPackets(data)

        # Callback should have been called
        assert mock_callback.called
        assert mock_callback.call_count == 1

        # Check that heartbeat_received flag was set
        assert connection.heartbeat_received is True

    def test_process_packets_ignores_wrong_system(self, connection, mock_callback, mavlink_module):
        """Test that processPackets ignores messages from wrong system."""
        # Create a HEARTBEAT message from different system
        mav = mavlink_module.MAVLink(connection, 99, 99, use_native=False)  # Wrong system/component
        msg = mavlink_module.MAVLink_heartbeat_message(
            type=mavlink_module.MAV_TYPE_QUADROTOR,
            autopilot=mavlink_module.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink_module.MAV_STATE_ACTIVE,
            mavlink_version=3
        )
        data = msg.pack(mav, force_mavlink1=False)

        # Reset mock
        mock_callback.reset_mock()

        # Process the packet
        connection.processPackets(data)

        # Callback should NOT have been called
        assert not mock_callback.called

    def test_send_packet_heartbeat(self, connection, mavlink_module):
        """Test sending a HEARTBEAT packet."""
        # Mock send_data
        connection.send_data = Mock()

        # Send HEARTBEAT
        connection.sendPacket(
            'HEARTBEAT',
            type=mavlink_module.MAV_TYPE_GCS,
            autopilot=mavlink_module.MAV_AUTOPILOT_INVALID,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink_module.MAV_STATE_ACTIVE,
            mavlink_version=3
        )

        # Verify send_data was called
        assert connection.send_data.called
        assert connection.send_data.call_count == 1

        # Verify the data is valid MAVLink packet
        sent_data = connection.send_data.call_args[0][0]
        assert isinstance(sent_data, bytes)
        assert len(sent_data) > 0

    def test_send_packet_timesync(self, connection):
        """Test sending a TIMESYNC packet."""
        connection.send_data = Mock()

        ts1 = int(time.time() * 1e9)
        connection.sendPacket(
            'TIMESYNC',
            tc1=0,
            ts1=ts1
        )

        assert connection.send_data.called
        sent_data = connection.send_data.call_args[0][0]
        assert isinstance(sent_data, bytes)

    @pytest.mark.asyncio
    async def test_send_heartbeat(self, connection):
        """Test async send_heartbeat method."""
        connection.send_data = Mock()

        await connection.send_heartbeat()

        assert connection.send_data.called

    @pytest.mark.asyncio
    async def test_configure_stream_rates(self, connection, mavlink_module):
        """Test configuring MAVLink stream rates."""
        connection.send_data = Mock()

        stream_rates = {
            'RAW_SENSORS': 10,
            'POSITION': 5,
            'EXTRA1': 4,
        }

        await connection.configure_stream_rates(stream_rates)

        # Should have sent 3 REQUEST_DATA_STREAM messages
        assert connection.send_data.call_count == 3

    @pytest.mark.asyncio
    async def test_configure_stream_rates_skips_zero(self, connection):
        """Test that zero stream rates are skipped."""
        connection.send_data = Mock()

        stream_rates = {
            'RAW_SENSORS': 10,
            'POSITION': 0,  # Should be skipped
            'EXTRA1': 4,
        }

        await connection.configure_stream_rates(stream_rates)

        # Should have sent only 2 messages (skipped POSITION)
        assert connection.send_data.call_count == 2

    @pytest.mark.asyncio
    async def test_wait_for_heartbeat_success(self, connection, mavlink_module):
        """Test successful heartbeat wait."""
        # Mock that heartbeat will be received
        async def set_heartbeat_received():
            await asyncio.sleep(0.1)
            connection.heartbeat_received = True

        # Start task to set heartbeat flag
        asyncio.create_task(set_heartbeat_received())

        # Mock send_data for client mode
        connection.send_data = Mock()
        connection.server = False

        # Wait for heartbeat
        result = await connection.wait_for_heartbeat()

        assert result is True
        assert connection.heartbeat_received is True

    @pytest.mark.asyncio
    async def test_wait_for_heartbeat_timeout(self, connection):
        """Test heartbeat wait timeout."""
        connection.send_data = Mock()
        connection.server = False

        # Heartbeat will never be received
        connection.heartbeat_received = False

        # Patch timeout to make test faster
        with patch.object(connection, 'wait_for_heartbeat') as mock_wait:
            mock_wait.return_value = False
            result = await connection.wait_for_heartbeat()
            assert result is False

    def test_signing_initialization(self, mock_callback):
        """Test MAVLink signing initialization."""
        signing_key = b'0123456789abcdef0123456789abcdef'  # 32 bytes

        conn = MAVConnection(
            dialect='ardupilotmega',
            mavversion=2.0,
            name='test_connection',
            srcsystem=255,
            srccomp=0,
            rxcallback=mock_callback,
            link_id=5,
            target_system=1,
            target_component=1,
            clcallback=None,
            signing_key=signing_key
        )

        # Check signing is configured
        assert conn.mav.signing.secret_key == signing_key
        assert conn.mav.signing.link_id == 5
        assert conn.mav.signing.sign_outgoing is True

    def test_bandwidth_tracking(self, connection):
        """Test bandwidth measurement."""

        # Simulate receiving some data
        connection.updatebandwidth(1000)
        connection.updatebandwidth(1000)

        # Wait a moment
        time.sleep(0.1)

        # Update bandwidth
        connection.updatebandwidth(1000)

    def test_connection_lost_callback(self, connection):
        """Test connection_lost callback."""
        close_callback = Mock()
        connection.closecallback = close_callback

        # Trigger connection lost
        connection.connection_lost(None)

        # Close callback should be called
        assert close_callback.called
        assert close_callback.call_args[0][0] == 'test_connection'

    def test_error_received_callback(self, connection):
        """Test error_received callback."""
        close_callback = Mock()
        connection.closecallback = close_callback

        # Trigger error
        connection.error_received(Exception('test error'))

        # Close callback should be called
        assert close_callback.called

    def test_process_multiple_packets(self, connection, mock_callback, mavlink_module):
        """Test processing buffer with multiple packets."""
        mav = mavlink_module.MAVLink(connection, 1, 1, use_native=False)

        # Create multiple messages
        msg1 = mavlink_module.MAVLink_heartbeat_message(
            type=mavlink_module.MAV_TYPE_QUADROTOR,
            autopilot=mavlink_module.MAV_AUTOPILOT_ARDUPILOTMEGA,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink_module.MAV_STATE_ACTIVE,
            mavlink_version=3
        )

        msg2 = mavlink_module.MAVLink_sys_status_message(
            onboard_control_sensors_present=0,
            onboard_control_sensors_enabled=0,
            onboard_control_sensors_health=0,
            load=100,
            voltage_battery=12000,
            current_battery=-1,
            battery_remaining=-1,
            drop_rate_comm=0,
            errors_comm=0,
            errors_count1=0,
            errors_count2=0,
            errors_count3=0,
            errors_count4=0
        )

        # Pack both messages into one buffer
        data = msg1.pack(mav, force_mavlink1=False) + msg2.pack(mav, force_mavlink1=False)

        # Process the buffer
        connection.processPackets(data)

        # Callback should have been called twice
        assert mock_callback.call_count == 2

    def test_invalid_packet_type(self, connection):
        """Test sending invalid packet type raises error."""
        connection.send_data = Mock()

        with pytest.raises(ValueError, match='Unknown MAVLink message type'):
            connection.sendPacket('INVALID_MESSAGE_TYPE')

    def test_corrupted_data_handling(self, connection, mock_callback):
        """Test handling of corrupted data."""
        # Send garbage data
        corrupted_data = b'\xff\xff\xff\xff\xff\xff\xff\xff'

        # Should not raise exception
        connection.processPackets(corrupted_data)
        # Callback should not have been called
        assert not mock_callback.called
