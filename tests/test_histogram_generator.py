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

Unit tests for HistogramGenerator class.
Tests latency binning, drop distribution, and CSV generation.
"""
import pytest
import os
import csv
from mavlinklinktester.histogram_generator import HistogramGenerator


class TestHistogramGenerator:
    """Test HistogramGenerator functionality."""

    @pytest.fixture
    def generator(self, temp_output_dir):
        """Create a HistogramGenerator instance for testing."""
        return HistogramGenerator(
            link_id=0,
            sanitized_connection='udpin_0_0_0_0_14550',
            output_dir=temp_output_dir
        )

    def test_initialization(self, generator, temp_output_dir):
        """Test HistogramGenerator initialization."""
        assert generator.link_id == 0
        assert generator.sanitized_connection == 'udpin_0_0_0_0_14550'
        assert generator.output_dir == temp_output_dir
        assert len(generator.latency_samples) == 0
        assert generator.total_seconds == 0

    def test_latency_bins_definition(self):
        """Test that latency bins are correctly defined."""
        bins = HistogramGenerator.LATENCY_BINS

        # Should have 100 bins of 20ms each (0-2000ms) plus one for >2000ms
        assert len(bins) == 101

        # First bin should be 0-20ms
        assert bins[0] == (0, 20)

        # Last 20ms bin should be 1980-2000ms
        assert bins[-2] == (1980, 2000)

        # Final bin should be >2000ms
        assert bins[-1] == (2000, float('inf'))

    def test_add_latency_sample(self, generator):
        """Test adding latency samples."""
        generator.add_latency_sample(50.5)
        generator.add_latency_sample(150.2)
        generator.add_latency_sample(250.8)

        assert len(generator.latency_samples) == 3
        assert 50.5 in generator.latency_samples
        assert 150.2 in generator.latency_samples
        assert 250.8 in generator.latency_samples

    def test_add_latency_sample_ignores_negative(self, generator):
        """Test that negative latency samples are ignored."""
        generator.add_latency_sample(50.0)
        generator.add_latency_sample(-10.0)
        generator.add_latency_sample(None)

        assert len(generator.latency_samples) == 1
        assert generator.latency_samples[0] == 50.0

    def test_increment_total_seconds(self, generator):
        """Test incrementing total test duration."""
        assert generator.total_seconds == 0

        generator.increment_total_seconds()
        assert generator.total_seconds == 1

        for _ in range(10):
            generator.increment_total_seconds()
        assert generator.total_seconds == 11

    def test_calculate_latency_distribution(self, generator):
        """Test latency distribution calculation."""
        # Add samples in different bins
        generator.add_latency_sample(5)    # 0-20ms bin
        generator.add_latency_sample(15)   # 0-20ms bin
        generator.add_latency_sample(25)   # 20-40ms bin
        generator.add_latency_sample(150)  # 140-160ms bin
        generator.add_latency_sample(2500)  # >2000ms bin

        distribution = generator._calculate_latency_distribution()

        # Check 0-20ms bin
        assert distribution[(0, 20)] == 2

        # Check 20-40ms bin
        assert distribution[(20, 40)] == 1

        # Check 140-160ms bin
        assert distribution[(140, 160)] == 1

        # Check >2000ms bin
        assert distribution[(2000, float('inf'))] == 1

        # Check empty bin
        assert distribution[(60, 80)] == 0

    def test_generate_histogram(self, generator, temp_output_dir):
        """Test histogram CSV generation."""
        # Add some sample data
        for latency in [10, 25, 50, 100, 150, 200, 500, 1000]:
            generator.add_latency_sample(latency)

        generator.total_seconds = 100

        # Generate histogram
        filepath = generator.generate_histogram()

        # Check file was created
        assert os.path.exists(filepath)
        assert filepath.startswith(temp_output_dir)
        assert 'histogram' in filepath
        assert filepath.endswith('.csv')

        # Read and validate CSV content
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Check metadata rows
        assert rows[0][0] == 'Total_Test_Duration_Seconds'
        assert int(rows[0][1]) == 100

        assert rows[1][0] == 'Total_Latency_Samples'
        assert int(rows[1][1]) == 8

        # Check header row
        assert rows[3][0] == 'Latency_Bin_Start_ms'
        assert rows[3][1] == 'Count'

        # Check some data rows (should have 101 bins)
        data_rows = rows[4:]
        assert len(data_rows) == 101

    def test_histogram_filename_format(self, generator):
        """Test that histogram filename follows correct format."""
        generator.total_seconds = 10
        filepath = generator.generate_histogram()

        filename = os.path.basename(filepath)

        # Should contain sanitized connection string
        assert 'udpin_0_0_0_0_14550' in filename

        # Should contain 'histogram'
        assert 'histogram' in filename

        # Should contain timestamp in format YYYYMMDD_HHMMSS
        assert len(filename.split('_')) >= 6  # Multiple underscores for date/time

        # Should end with .csv
        assert filename.endswith('.csv')

    def test_latency_binning_edge_cases(self, generator):
        """Test latency binning at bin boundaries."""
        # Add samples at exact bin boundaries
        generator.add_latency_sample(0)     # First bin
        generator.add_latency_sample(20)    # Boundary (should go in 20-40)
        generator.add_latency_sample(40)    # Boundary (should go in 40-60)
        generator.add_latency_sample(2000)  # Boundary (should go in >2000)

        distribution = generator._calculate_latency_distribution()

        # 0 should be in 0-20 bin
        assert distribution[(0, 20)] == 1

        # 20 should be in 20-40 bin (boundaries are inclusive on left, exclusive on right)
        assert distribution[(20, 40)] == 1

        # 40 should be in 40-60 bin
        assert distribution[(40, 60)] == 1

        # 2000 should be in >2000 bin
        assert distribution[(2000, float('inf'))] == 1

    def test_large_latency_values(self, generator):
        """Test handling of very large latency values."""
        generator.add_latency_sample(5000)
        generator.add_latency_sample(10000)
        generator.add_latency_sample(100000)

        distribution = generator._calculate_latency_distribution()

        # All should be in the >2000ms bin
        assert distribution[(2000, float('inf'))] == 3

    def test_empty_histogram_generation(self, generator, temp_output_dir):
        """Test generating histogram with no data."""
        generator.total_seconds = 50

        filepath = generator.generate_histogram()

        # File should still be created
        assert os.path.exists(filepath)

        # Read and validate
        with open(filepath, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)

        # Should show 0 samples
        assert rows[1][0] == 'Total_Latency_Samples'
        assert int(rows[1][1]) == 0

        # Should still have all bins with 0 counts
        data_rows = rows[4:]
        assert len(data_rows) == 101

        # All counts should be 0
        for row in data_rows:
            assert int(row[1]) == 0
