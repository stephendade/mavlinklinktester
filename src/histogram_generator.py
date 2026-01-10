"""
Histogram generator for MAVLink link test statistics.
Creates Excel-compatible CSV files with latency and packet drop distributions.
"""

import csv
from datetime import datetime


class HistogramGenerator:
    """Generates histogram CSV files from collected link statistics."""

    # Latency bins: 20ms intervals from 0 to 2000ms, plus >2000ms
    LATENCY_BINS = [(i, i+20) for i in range(0, 2000, 20)] + [(2000, float('inf'))]

    def __init__(self, link_id, sanitized_connection, output_dir):
        self.link_id = link_id
        self.sanitized_connection = sanitized_connection
        self.output_dir = output_dir

        # Collected data
        self.latency_samples = []
        self.drops_per_sec_samples = []

        # Outage tracking
        self.outage_events = []  # List of (start_time, duration)
        self.total_outage_seconds = 0
        self.longest_outage_duration = 0
        self.total_seconds = 0

    def add_latency_sample(self, latency_ms):
        """Add a latency sample."""
        if latency_ms is not None and latency_ms >= 0:
            self.latency_samples.append(latency_ms)

    def add_drops_per_sec_sample(self, drops_per_sec):
        """Add a dropped packets per second sample."""
        self.drops_per_sec_samples.append(drops_per_sec)

    def record_outage_event(self, duration_seconds):
        """Record an outage event."""
        self.outage_events.append(duration_seconds)
        self.total_outage_seconds += duration_seconds
        if duration_seconds > self.longest_outage_duration:
            self.longest_outage_duration = duration_seconds

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

    def _calculate_drops_distribution(self):
        """Calculate dropped packets per second distribution."""
        distribution = {}

        for drops in self.drops_per_sec_samples:
            if drops not in distribution:
                distribution[drops] = 0
            distribution[drops] += 1

        return distribution
