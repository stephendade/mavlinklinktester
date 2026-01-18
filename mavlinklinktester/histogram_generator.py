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

Histogram generator for MAVLink link test statistics.
"""

import csv
from datetime import datetime


class HistogramGenerator:
    """Generates histogram CSV files from collected link statistics."""

    # Latency bins: 20ms intervals from 0 to 2000ms, plus >2000ms
    LATENCY_BINS = [(i, i + 20) for i in range(0, 2000, 20)] + [(2000, float('inf'))]

    def __init__(self, link_id, sanitized_connection, output_dir):
        self.link_id = link_id
        self.sanitized_connection = sanitized_connection
        self.output_dir = output_dir

        # Collected data
        self.latency_samples = []

        self.total_seconds = 0

    def add_latency_sample(self, latency_ms):
        """Add a latency sample."""
        if latency_ms is not None and latency_ms >= 0:
            self.latency_samples.append(latency_ms)

    def increment_total_seconds(self):
        """Increment total test duration."""
        self.total_seconds += 1

    def generate_histogram(self):
        """Generate and save histogram CSV file."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"{self.sanitized_connection}_histogram_{timestamp}.csv"
        filepath = f"{self.output_dir}/{filename}"

        with open(filepath, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)

            # Write metadata
            writer.writerow(['Total_Test_Duration_Seconds', self.total_seconds])
            writer.writerow(['Total_Latency_Samples', len(self.latency_samples)])
            writer.writerow([])  # Blank row

            # Write latency histogram (graphing format)
            writer.writerow(['Latency_Bin_Start_ms', 'Count'])

            latency_counts = self._calculate_latency_distribution()

            for (bin_start, bin_end), count in latency_counts.items():
                writer.writerow([bin_start, count])

        return filepath

    def _calculate_latency_distribution(self):
        """Calculate latency distribution across bins."""
        distribution = {bin_range: 0 for bin_range in self.LATENCY_BINS}

        for latency in self.latency_samples:
            for bin_start, bin_end in self.LATENCY_BINS:
                if bin_start <= latency < bin_end:
                    distribution[(bin_start, bin_end)] += 1
                    break

        return distribution
