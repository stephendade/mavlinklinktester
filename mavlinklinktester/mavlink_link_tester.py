#!/usr/bin/env python3
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

Main entry point for MAVLink Link Loss and Latency Tester
"""

import argparse
import asyncio
import logging
import signal
import time

from mavlinklinktester.link_monitor import LinkMonitor


class MAVLinkTester:
    """Main orchestrator for MAVLink link testing."""

    def __init__(self, args):
        self.args = args
        self.monitors = []
        self.running = False
        self.stopping = False
        self.loop = None

    def _signal_handler(self, _signum):
        """Handle shutdown signals."""
        logging.info('Received shutdown signal, stopping gracefully...')
        self.running = False

    async def start(self):
        """Start all link monitors."""
        self.loop = asyncio.get_running_loop()

        # Set up signal handlers for async
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                def make_handler(signal_num: int):
                    return lambda: self._signal_handler(signal_num)
                self.loop.add_signal_handler(sig, make_handler(sig))
        except NotImplementedError:
            # On Windows, add_signal_handler is not implemented
            # Signal handling will work via KeyboardInterrupt exception
            pass

        # If --all-rates is set, override individual rates
        if self.args.all_rates != -1:
            self.args.rate_raw_sensors = self.args.all_rates
            self.args.rate_extended_status = self.args.all_rates
            self.args.rate_rc_channels = self.args.all_rates
            self.args.rate_position = self.args.all_rates
            self.args.rate_extra1 = self.args.all_rates
            self.args.rate_extra2 = self.args.all_rates
            self.args.rate_extra3 = self.args.all_rates

        logging.info('MAVLink Link Tester')
        logging.info('Target: System %s, Component %s', self.args.system_id, self.args.component_id)
        logging.info('Links: %s', len(self.args.connections))
        logging.info('Output directory: %s', self.args.output_dir)
        logging.info('Stream rates - RAW_SENSORS: %sHz, '
                     'EXTENDED_STATUS: %sHz, '
                     'RC_CHANNELS: %sHz, '
                     'POSITION: %sHz, '
                     'EXTRA1: %sHz, '
                     'EXTRA2: %sHz, '
                     'EXTRA3: %sHz',
                     self.args.rate_raw_sensors, self.args.rate_extended_status,
                     self.args.rate_rc_channels, self.args.rate_position,
                     self.args.rate_extra1, self.args.rate_extra2, self.args.rate_extra3)
        logging.info('Outage timeout: %ss', self.args.outage_timeout)
        logging.info('Recovery hysteresis: %s packets', self.args.recovery_hysteresis)
        if self.args.signing_key is not None:
            link_id_str = str(self.args.signing_link_id) if self.args.signing_link_id is not None else 'auto'
            logging.info('MAVLink signing: Enabled (link_id=%s)', link_id_str)
        if self.args.duration:
            logging.info('Test duration: %ss', self.args.duration)
        else:
            logging.info('Test duration: Indefinite (until Ctrl+C)')

        # Create and start monitors for each link
        for idx, connection_str in enumerate(self.args.connections):
            monitor = LinkMonitor(
                link_id=idx,
                connection_str=connection_str,
                target_system=self.args.system_id,
                target_component=self.args.component_id,
                output_dir=self.args.output_dir,
                outage_timeout=self.args.outage_timeout,
                recovery_hysteresis=self.args.recovery_hysteresis,
                stream_rates={
                    'RAW_SENSORS': self.args.rate_raw_sensors,
                    'EXTENDED_STATUS': self.args.rate_extended_status,
                    'RC_CHANNELS': self.args.rate_rc_channels,
                    'POSITION': self.args.rate_position,
                    'EXTRA1': self.args.rate_extra1,
                    'EXTRA2': self.args.rate_extra2,
                    'EXTRA3': self.args.rate_extra3
                },
                signing_key=self.args.signing_key,
                signing_link_id=self.args.signing_link_id
            )

            if await monitor.start():
                self.monitors.append(monitor)
            else:
                logging.error('Failed to start monitor for %s', connection_str)

        if not self.monitors:
            logging.error('No monitors started successfully. Exiting.')
            return

        self.running = True

        # Main loop
        start_time = time.time()
        try:
            while self.running:
                # Check if duration expired
                if self.args.duration:
                    elapsed = time.time() - start_time
                    if elapsed >= self.args.duration:
                        logging.info('Test duration (%ss) completed.', self.args.duration)
                        break

                await asyncio.sleep(1)
        except (asyncio.CancelledError, KeyboardInterrupt):
            logging.info('Cancelled.')
        finally:
            await self.stop()

    async def stop(self):
        """Stop all monitors and generate final reports."""
        if self.stopping or (not self.running and not self.monitors):
            return

        self.stopping = True
        self.running = False

        logging.info('=' * 80)
        logging.info('Stopping monitors and generating reports...')
        logging.info('=' * 80)

        # Stop all monitors concurrently
        stop_tasks = [monitor.stop() for monitor in self.monitors]
        histogram_paths = await asyncio.gather(*stop_tasks, return_exceptions=True)

        # Print summary
        logging.info('=' * 80)
        logging.info('Total links tested: %s', len(self.monitors))
        logging.info('Generated files:')
        for monitor in self.monitors:
            logging.info('  Metrics CSV: %s', monitor.csv_filepath)
        for path in histogram_paths:
            if isinstance(path, str):
                logging.info('  Histogram CSV: %s', path)


async def async_main(args):
    """Async main entry point."""
    tester = MAVLinkTester(args)
    await tester.start()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='MAVLink Link Loss and Latency Tester',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test single UDP link
  %(prog)s --system-id 1 --component-id 1 udp:127.0.0.1:14550

  # Test single TCP server link
  %(prog)s --system-id 1 --component-id 1 tcpin:127.0.0.1:14550

  # Test multiple links simultaneously
  %(prog)s --system-id 1 --component-id 1 udp:127.0.0.1:14550 udp:127.0.0.1:14551

  # Test with custom duration
  %(prog)s --system-id 1 --component-id 1 --duration 300 udp:127.0.0.1:14550

  # Test serial connection
  %(prog)s --system-id 1 --component-id 1 /dev/ttyUSB0:57600

  # Test with stream rates enabled
  %(prog)s --system-id 1 --component-id 1 --all-rates 4 /dev/ttyACM0:115200

  # Test with MAVLink 2.0 signing enabled
  %(prog)s --system-id 1 --component-id 1 --signing-passphrase mysecretkey /dev/ttyACM0:115200
        """
    )

    parser.add_argument('connections', nargs='+', metavar='CONNECTION',
                        help='MAVLink connection strings (e.g., udp:127.0.0.1:14550, /dev/ttyUSB0:57600)')

    parser.add_argument('--system-id', type=int, required=True,
                        help='Target system ID (autopilot)')

    parser.add_argument('--component-id', type=int, required=True,
                        help='Target component ID (autopilot)')

    parser.add_argument('--duration', type=int, default=None,
                        help='Test duration in seconds (default: run indefinitely)')

    parser.add_argument('--outage-timeout', type=float, default=1.0,
                        help='Outage detection timeout in seconds (default: 1.0)')

    parser.add_argument('--recovery-hysteresis', type=int, default=3,
                        help='Number of consecutive packets required to exit outage (default: 3)')

    parser.add_argument('--output-dir', type=str, default='output',
                        help='Output directory for CSV files (default: output)')

    # Stream rate control arguments
    parser.add_argument('--all-rates', type=int, default=4,
                        help='Set all stream rates in Hz (-1 to use individual rates)')

    parser.add_argument('--rate-raw-sensors', type=int, default=4,
                        help='RAW_SENSORS stream rate in Hz (default: 4)')

    parser.add_argument('--rate-extended-status', type=int, default=4,
                        help='EXTENDED_STATUS stream rate in Hz (default: 4)')

    parser.add_argument('--rate-rc-channels', type=int, default=4,
                        help='RC_CHANNELS stream rate in Hz (default: 4)')

    parser.add_argument('--rate-position', type=int, default=4,
                        help='POSITION stream rate in Hz (default: 4)')

    parser.add_argument('--rate-extra1', type=int, default=4,
                        help='EXTRA1 stream rate in Hz (default: 4)')

    parser.add_argument('--rate-extra2', type=int, default=4,
                        help='EXTRA2 stream rate in Hz (default: 4)')

    parser.add_argument('--rate-extra3', type=int, default=4,
                        help='EXTRA3 stream rate in Hz (default: 4)')

    # MAVLink signing arguments
    parser.add_argument('--signing-passphrase', type=str, default=None,
                        help='MAVLink 2.0 signing passphrase (will be hashed with SHA-256)')

    parser.add_argument('--signing-link-id', type=int, default=None,
                        help='MAVLink 2.0 signing link ID (default: use monitor link_id)')

    args = parser.parse_args()

    logging.basicConfig(format='%(message)s', level=logging.INFO)

    # Convert passphrase to signing key if provided
    # Uses SHA-256 hashing like MAVProxy
    # See: https://github.com/ArduPilot/MAVProxy/blob/master/MAVProxy/modules/mavproxy_signing.py
    if args.signing_passphrase is not None:
        import hashlib
        h = hashlib.sha256()
        h.update(args.signing_passphrase.encode('ascii'))
        args.signing_key = h.digest()
    else:
        args.signing_key = None

    # Run async main
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logging.info('Interrupted by user.')


if __name__ == '__main__':
    main()
