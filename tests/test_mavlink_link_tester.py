"""
Integration tests for MAVLinkTester orchestrator class.
Tests multi-monitor management, signal handling, and overall orchestration.
"""
import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from src.mavlink_link_tester import MAVLinkTester
import argparse


class TestMAVLinkTester:
    """Test MAVLinkTester orchestrator functionality."""

    @pytest.fixture
    def basic_args(self, temp_output_dir):
        """Create basic argument namespace for testing."""
        args = argparse.Namespace()
        args.connections = ['udpin:0.0.0.0:14550']
        args.system_id = 1
        args.component_id = 1
        args.duration = None
        args.outage_timeout = 1.0
        args.recovery_hysteresis = 3
        args.output_dir = temp_output_dir
        args.rate_raw_sensors = 4
        args.rate_extended_status = 4
        args.rate_rc_channels = 4
        args.rate_position = 4
        args.rate_extra1 = 4
        args.rate_extra2 = 4
        args.rate_extra3 = 4
        args.signing_key = None
        args.signing_link_id = None
        return args

    @pytest.fixture
    def tester(self, basic_args):
        """Create MAVLinkTester instance for testing."""
        return MAVLinkTester(basic_args)

    def test_initialization(self, tester, basic_args):
        """Test MAVLinkTester initialization."""
        assert tester.args == basic_args
        assert len(tester.monitors) == 0
        assert tester.running is False
        assert tester.stopping is False
        assert tester.loop is None

    def test_signal_handler(self, tester):
        """Test signal handler sets running flag to False."""
        tester.running = True
        tester._signal_handler(2)  # SIGINT
        assert tester.running is False

    @pytest.mark.asyncio
    async def test_start_with_single_connection(self, basic_args, temp_output_dir):
        """Test starting tester with a single connection."""
        tester = MAVLinkTester(basic_args)

        # Mock LinkMonitor.start to return True immediately
        with patch('src.mavlink_link_tester.LinkMonitor') as MockLinkMonitor:
            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock(return_value=True)
            mock_monitor.stop = AsyncMock(return_value='/tmp/test_histogram.csv')
            mock_monitor.csv_filepath = f'{temp_output_dir}/test_metrics.csv'
            MockLinkMonitor.return_value = mock_monitor

            # Start and immediately stop
            start_task = asyncio.create_task(tester.start())
            await asyncio.sleep(0.5)
            tester.running = False
            await start_task

            # Verify monitor was created
            assert MockLinkMonitor.called

    @pytest.mark.asyncio
    async def test_start_with_multiple_connections(self, temp_output_dir):
        """Test starting tester with multiple connections."""
        args = argparse.Namespace()
        args.connections = ['udpin:0.0.0.0:14550', 'udpout:192.168.1.100:14551']
        args.system_id = 1
        args.component_id = 1
        args.duration = None
        args.outage_timeout = 1.0
        args.recovery_hysteresis = 3
        args.output_dir = temp_output_dir
        args.rate_raw_sensors = 4
        args.rate_extended_status = 4
        args.rate_rc_channels = 4
        args.rate_position = 4
        args.rate_extra1 = 4
        args.rate_extra2 = 4
        args.rate_extra3 = 4
        args.signing_key = None
        args.signing_link_id = None

        tester = MAVLinkTester(args)

        with patch('src.mavlink_link_tester.LinkMonitor') as MockLinkMonitor:
            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock(return_value=True)
            mock_monitor.stop = AsyncMock(return_value='/tmp/test_histogram.csv')
            mock_monitor.csv_filepath = f'{temp_output_dir}/test_metrics.csv'
            MockLinkMonitor.return_value = mock_monitor

            # Start and immediately stop
            start_task = asyncio.create_task(tester.start())
            await asyncio.sleep(0.5)
            tester.running = False
            await start_task

            # Verify monitors were created for each connection
            assert MockLinkMonitor.call_count == 2

    @pytest.mark.asyncio
    async def test_duration_based_testing(self, temp_output_dir):
        """Test that tester stops after specified duration."""
        args = argparse.Namespace()
        args.connections = ['udpin:0.0.0.0:14550']
        args.system_id = 1
        args.component_id = 1
        args.duration = 1  # 1 second duration
        args.outage_timeout = 1.0
        args.recovery_hysteresis = 3
        args.output_dir = temp_output_dir
        args.rate_raw_sensors = 4
        args.rate_extended_status = 4
        args.rate_rc_channels = 4
        args.rate_position = 4
        args.rate_extra1 = 4
        args.rate_extra2 = 4
        args.rate_extra3 = 4
        args.signing_key = None
        args.signing_link_id = None

        tester = MAVLinkTester(args)

        with patch('src.mavlink_link_tester.LinkMonitor') as MockLinkMonitor:
            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock(return_value=True)
            mock_monitor.stop = AsyncMock(return_value='/tmp/test_histogram.csv')
            mock_monitor.csv_filepath = f'{temp_output_dir}/test_metrics.csv'
            MockLinkMonitor.return_value = mock_monitor

            # Start with duration
            start_time = asyncio.get_event_loop().time()
            await tester.start()
            elapsed = asyncio.get_event_loop().time() - start_time

            # Should have stopped around 1 second (allow some overhead)
            assert 0.5 < elapsed < 2.0

    @pytest.mark.asyncio
    async def test_failed_monitor_start(self, basic_args):
        """Test handling of failed monitor start."""
        tester = MAVLinkTester(basic_args)

        with patch('src.mavlink_link_tester.LinkMonitor') as MockLinkMonitor:
            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock(return_value=False)  # Simulate failure
            MockLinkMonitor.return_value = mock_monitor

            # Start should handle failure gracefully
            await tester.start()

            # No monitors should have been added
            assert len(tester.monitors) == 0

    @pytest.mark.asyncio
    async def test_stop_calls_all_monitors(self, basic_args):
        """Test that stop() calls stop on all monitors."""
        tester = MAVLinkTester(basic_args)

        # Create mock monitors
        mock_monitor1 = AsyncMock()
        mock_monitor1.stop = AsyncMock(return_value='/tmp/hist1.csv')
        mock_monitor1.csv_filepath = '/tmp/metrics1.csv'

        mock_monitor2 = AsyncMock()
        mock_monitor2.stop = AsyncMock(return_value='/tmp/hist2.csv')
        mock_monitor2.csv_filepath = '/tmp/metrics2.csv'

        tester.monitors = [mock_monitor1, mock_monitor2]
        tester.running = True

        # Stop tester
        await tester.stop()

        # Both monitors should be stopped
        assert mock_monitor1.stop.called
        assert mock_monitor2.stop.called

    @pytest.mark.asyncio
    async def test_stop_idempotent(self, tester):
        """Test that stop() can be called multiple times safely."""
        tester.running = False
        tester.stopping = False

        # First stop
        await tester.stop()

        # Second stop should be no-op
        await tester.stop()

    def test_stream_rate_configuration(self, temp_output_dir):
        """Test that stream rates are properly configured."""
        args = argparse.Namespace()
        args.connections = ['udpin:0.0.0.0:14550']
        args.system_id = 1
        args.component_id = 1
        args.duration = None
        args.outage_timeout = 1.0
        args.recovery_hysteresis = 3
        args.output_dir = temp_output_dir
        args.rate_raw_sensors = 10
        args.rate_extended_status = 5
        args.rate_rc_channels = 8
        args.rate_position = 6
        args.rate_extra1 = 7
        args.rate_extra2 = 9
        args.rate_extra3 = 11
        args.signing_key = None
        args.signing_link_id = None

        tester = MAVLinkTester(args)

        # Verify args are set correctly
        assert tester.args.rate_raw_sensors == 10
        assert tester.args.rate_extended_status == 5
        assert tester.args.rate_rc_channels == 8
        assert tester.args.rate_position == 6
        assert tester.args.rate_extra1 == 7
        assert tester.args.rate_extra2 == 9
        assert tester.args.rate_extra3 == 11

    def test_signing_configuration(self, temp_output_dir):
        """Test MAVLink signing configuration."""
        args = argparse.Namespace()
        args.connections = ['udpin:0.0.0.0:14550']
        args.system_id = 1
        args.component_id = 1
        args.duration = None
        args.outage_timeout = 1.0
        args.recovery_hysteresis = 3
        args.output_dir = temp_output_dir
        args.rate_raw_sensors = 4
        args.rate_extended_status = 4
        args.rate_rc_channels = 4
        args.rate_position = 4
        args.rate_extra1 = 4
        args.rate_extra2 = 4
        args.rate_extra3 = 4
        args.signing_key = b'0123456789abcdef0123456789abcdef'
        args.signing_link_id = 5

        tester = MAVLinkTester(args)

        # Verify signing args are set
        assert tester.args.signing_key == b'0123456789abcdef0123456789abcdef'
        assert tester.args.signing_link_id == 5

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_handling(self, basic_args):
        """Test handling of KeyboardInterrupt."""
        tester = MAVLinkTester(basic_args)

        with patch('src.mavlink_link_tester.LinkMonitor') as MockLinkMonitor:
            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock(return_value=True)
            mock_monitor.stop = AsyncMock(return_value='/tmp/test_histogram.csv')
            mock_monitor.csv_filepath = '/tmp/test_metrics.csv'
            MockLinkMonitor.return_value = mock_monitor

            # Simulate KeyboardInterrupt after start
            async def interrupt_after_start():
                await asyncio.sleep(0.3)
                tester.running = False

            asyncio.create_task(interrupt_after_start())

            # Should handle gracefully
            await tester.start()

            # Monitor should have been stopped
            assert mock_monitor.stop.called

    @pytest.mark.asyncio
    async def test_no_successful_monitors(self, basic_args):
        """Test behavior when no monitors start successfully."""
        tester = MAVLinkTester(basic_args)

        with patch('src.mavlink_link_tester.LinkMonitor') as MockLinkMonitor:
            mock_monitor = AsyncMock()
            mock_monitor.start = AsyncMock(return_value=False)  # All fail
            MockLinkMonitor.return_value = mock_monitor

            # Should exit gracefully
            await tester.start()

            # No monitors should be in the list
            assert len(tester.monitors) == 0
            assert tester.running is False

    def test_output_directory_configuration(self, basic_args):
        """Test output directory configuration."""
        assert basic_args.output_dir is not None
        assert isinstance(basic_args.output_dir, str)

    @pytest.mark.asyncio
    async def test_concurrent_monitor_stop(self, basic_args):
        """Test that monitors are stopped concurrently."""
        tester = MAVLinkTester(basic_args)

        # Create multiple mock monitors with delays
        monitors = []
        for i in range(3):
            mock_monitor = AsyncMock()

            async def delayed_stop():
                await asyncio.sleep(0.1)
                return f'/tmp/hist{i}.csv'

            mock_monitor.stop = AsyncMock(side_effect=delayed_stop)
            mock_monitor.csv_filepath = f'/tmp/metrics{i}.csv'
            monitors.append(mock_monitor)

        tester.monitors = monitors
        tester.running = True

        # Stop all monitors
        start_time = asyncio.get_event_loop().time()
        await tester.stop()
        elapsed = asyncio.get_event_loop().time() - start_time

        # Should take ~0.1s (concurrent), not ~0.3s (sequential)
        assert elapsed < 0.25  # Allow some overhead

        # All monitors should be stopped
        for monitor in monitors:
            assert monitor.stop.called
