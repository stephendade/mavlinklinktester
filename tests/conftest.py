"""
Shared pytest fixtures for mavlinklinktester tests.
"""
import pytest
import tempfile
import os
from unittest.mock import Mock, MagicMock
from src.mavlink.pymavutil import getpymavlinkpackage


@pytest.fixture
def temp_output_dir():
    """Create a temporary directory for test output files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_pymavlink_module():
    """Mock pymavlink module for testing without actual MAVLink dependency."""
    mod = getpymavlinkpackage('ardupilotmega', 2.0)
    return mod


@pytest.fixture
def mock_heartbeat_message(mock_pymavlink_module):
    """Create a mock HEARTBEAT message."""
    msg = Mock()
    msg.get_type.return_value = 'HEARTBEAT'
    msg.get_srcSystem.return_value = 1
    msg.get_srcComponent.return_value = 1
    msg.get_seq.return_value = 0
    msg.get_msgbuf.return_value = b'\xfd\x09\x00\x00\x00\x01\x01\x00\x00\x00' * 3  # 30 bytes
    return msg


@pytest.fixture
def mock_timesync_message():
    """Create a mock TIMESYNC message."""
    msg = Mock()
    msg.get_type.return_value = 'TIMESYNC'
    msg.get_srcSystem.return_value = 1
    msg.get_srcComponent.return_value = 1
    msg.get_seq.return_value = 1
    msg.get_msgbuf.return_value = b'\xfd\x10\x00\x00\x00\x01\x01\x6f\x00\x00' * 3  # 30 bytes
    msg.tc1 = 0
    msg.ts1 = 1000000000  # 1 second in nanoseconds
    return msg


@pytest.fixture
def mock_udp_transport():
    """Mock asyncio UDP transport."""
    transport = Mock()
    transport.sendto = Mock()
    transport.close = Mock()
    return transport


@pytest.fixture
def mock_tcp_transport():
    """Mock asyncio TCP transport."""
    transport = Mock()
    transport.write = Mock()
    transport.close = Mock()
    transport.get_extra_info = Mock(return_value=Mock())
    return transport


@pytest.fixture
def mock_serial_transport():
    """Mock asyncio serial transport."""
    transport = Mock()
    transport.write = Mock()
    transport.close = Mock()
    return transport


@pytest.fixture
def sample_connection_strings():
    """Sample connection strings for testing."""
    return {
        'udpin': 'udpin:0.0.0.0:14550',
        'udpout': 'udpout:192.168.1.100:14550',
        'tcp': 'tcp:192.168.1.100:5760',
        'serial': '/dev/ttyUSB0:57600',
    }


@pytest.fixture
def mock_mavlink_connection():
    """Mock MAVConnection for testing."""
    from src.connection.mavconnection import MAVConnection

    conn = Mock(spec=MAVConnection)
    conn.name = 'mock_connection'
    conn.heartbeat_received = False
    conn.sendPacket = Mock()
    conn.send_heartbeat = Mock()
    conn.configure_stream_rates = Mock()
    conn.wait_for_heartbeat = Mock(return_value=True)
    conn.close = Mock()

    return conn


@pytest.fixture
def mock_histogram_generator():
    """Mock HistogramGenerator for testing."""
    from src.histogram_generator import HistogramGenerator

    gen = Mock(spec=HistogramGenerator)
    gen.add_latency_sample = Mock()
    gen.add_drops_per_sec_sample = Mock()
    gen.record_outage_event = Mock()
    gen.increment_total_seconds = Mock()
    gen.generate_histogram = Mock(return_value='/tmp/test_histogram.csv')

    return gen
