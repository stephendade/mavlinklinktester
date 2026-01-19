# AI Agent Guide for MAVLink Link Tester

This document provides guidance for AI agents (like GitHub Copilot, Claude, or other AI assistants) working on the MAVLink Link Tester project.

## Project Overview

**MAVLink Link Tester** is a Python tool for characterizing MAVLink connection reliability and latency. It monitors multiple MAVLink links concurrently, tracking packet loss, latency (RTT), out-of-order packets, and link outages.

### Key Capabilities
- Simultaneous testing of multiple MAVLink connections (UDP, TCP, Serial)
- Real-time latency measurement using TIMESYNC messages
- Packet loss and sequence tracking
- Link outage detection with configurable timeouts
- MAVLink 2.0 signing support
- CSV output with per-second metrics
- Histogram generation for statistical analysis

## Architecture

### Core Components

```
mavlinklinktester/
├── mavlink_link_tester.py    # Main entry point, CLI handling, multi-link coordination
├── link_monitor.py            # Single link monitoring (latency, packets, outages)
├── histogram_generator.py     # Statistical histogram generation
├── connection/
│   ├── mavconnection.py       # Base MAVLink connection class (asyncio Protocol)
│   ├── udplink.py            # UDP transport implementation
│   ├── tcplink.py            # TCP transport implementation
│   └── seriallink.py         # Serial transport implementation
└── mavlink/
    └── pymavutil.py          # MAVLink utilities (signing, message handling)
```

### Key Design Patterns

1. **Asyncio-based**: All I/O operations use Python's asyncio for concurrent operation
2. **Protocol Pattern**: Connection classes implement asyncio's Protocol interface
3. **Callback Pattern**: Message reception uses callbacks for non-blocking processing
4. **Per-second metrics**: Statistics are accumulated and reported every second

### Data Flow

```
MAVLinkLinkTester (main)
    └─> LinkMonitor (per connection)
        └─> MAVConnection (UDP/TCP/Serial)
            └─> asyncio Protocol callbacks
                └─> _on_message_received()
                    ├─> Sequence tracking
                    ├─> Latency measurement
                    └─> Outage detection
```

## Development Workflow

### Setup Development Environment

```bash
# Install with development dependencies
poetry install --with dev

# Activate virtual environment (optional)
poetry shell
```

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run specific test file
poetry run pytest tests/test_link_monitor.py

# Run with coverage
poetry run pytest --cov=mavlinklinktester --cov-report=html

# Run single test
poetry run pytest tests/test_link_monitor.py::TestLinkMonitor::test_outage_detection_entry -v
```

### Code Quality Checks

```bash
# Linting with flake8
poetry run flake8 mavlinklinktester/ tests/

# Type checking with mypy
poetry run mypy mavlinklinktester/

# Dead code detection with vulture
poetry run vulture mavlinklinktester/ --min-confidence 80
```

### Running the Tool

```bash
# Basic usage
poetry run mavlink-link-tester.py --system-id 1 --component-id 1 udpin:0.0.0.0:14550

# Multiple links
poetry run mavlink-link-tester.py --system-id 1 --component-id 1 \
    udpin:0.0.0.0:14550 \
    udpout:192.168.1.100:14551
```

## Key Implementation Details

### Latency Measurement

- Uses MAVLink TIMESYNC messages sent at 2Hz
- Calculates round-trip time (RTT) in milliseconds
- Stores value of -1.0 when no measurement available in current second
- **Important**: -1 values are filtered out when calculating statistics

### Sequence Tracking

- MAVLink messages have 8-bit sequence numbers (0-255, wraps around)
- Out-of-order packets are detected and tracked separately from drops
- Pending sequences older than 3 seconds are considered truly dropped
- Last sequence is tracked per connection

### Outage Detection

- Outage triggered when no packets received for `outage_timeout` seconds (default: 1.0s)
- Recovery requires `recovery_hysteresis` consecutive packets (default: 3)
- **Critical**: Outage duration is counted even if program stops during outage
- Total outage time is accumulated across multiple outage events

### MAVLink Signing

- Supports MAVLink 2.0 message signing for authenticated connections
- Uses SHA-256 hashing of passphrase
- Configurable per-link with `--signing-passphrase` and `--signing-link-id`

## Testing Guidelines

### Test Structure

Tests use pytest with asyncio support:
- Fixtures for common setup (monitor instances, temp directories)
- Mock objects for protocol components (connections, tasks)
- Async tests marked with `@pytest.mark.asyncio`

### Important Test Patterns

1. **Mocking connections**: Use `Mock()` for connection objects to avoid real I/O
2. **Time simulation**: Use `time.time()` offsets for testing time-based behavior
3. **Message mocking**: Create mock messages with `get_seq()`, `get_type()`, etc.
4. **Testing async methods**: Always use `await` and `@pytest.mark.asyncio`

### Example Test Pattern

```python
@pytest.mark.asyncio
async def test_something(self, monitor):
    # Mock dependencies
    monitor.connection = Mock()
    monitor.connection.close = Mock()
    monitor.tasks = []
    
    # Test behavior
    await monitor.stop()
    
    # Assert expectations
    assert monitor.total_outage_seconds >= 0
```

## Common Tasks

### Adding a New Test

1. Add test method to appropriate test class in `tests/`
2. Use descriptive name: `test_<behavior>_<condition>`
3. Add docstring explaining what's being tested
4. Use fixtures for common setup (`monitor`, `temp_output_dir`)
5. Run test to verify: `poetry run pytest tests/test_file.py::TestClass::test_name -v`

### Adding a New Metric

1. Add attribute to `LinkMonitor.__init__()` for tracking
2. Update per-second collection in `_metrics_loop()`
3. Update CSV header in `start()` method
4. Add to final summary in `stop()` method
5. Add tests for the new metric
6. Update README documentation

### Adding a New Connection Type

1. Create new class in `mavlinklinktester/connection/`
2. Inherit from appropriate protocol (DatagramProtocol, Protocol)
3. Implement required methods: `connection_made()`, `data_received()`
4. Add parsing logic in `LinkMonitor.start()` method
5. Add connection string format to CLI help and README
6. Add tests for parsing and basic operation

### Modifying Outage Detection

The outage detection logic is in `LinkMonitor`:
- `_update_packet_time()`: Called on every packet, handles hysteresis
- `_check_outage()`: Called every second, checks timeout
- `stop()`: Ensures ongoing outages are counted when program exits

## Code Style and Conventions

### Python Style
- Follow PEP 8 (enforced by flake8)
- Use type hints (checked by mypy)
- Single quotes for strings (except docstrings)
- Max line length: 100 characters (see `.flake8` if exists)

### Naming Conventions
- Classes: `PascalCase` (e.g., `LinkMonitor`)
- Functions/methods: `snake_case` (e.g., `_handle_timesync_response`)
- Private methods: prefix with `_` (e.g., `_track_sequence`)
- Constants: `UPPER_SNAKE_CASE`
- Unused parameters: prefix with `_` (e.g., `_signum`)

### Docstrings
- Use triple double-quotes for docstrings
- First line is brief summary, period at end
- Module-level docstrings include copyright and GPL license

### Async Patterns
- Use `asyncio.create_task()` for background tasks
- Always cancel tasks in cleanup: `task.cancel()`
- Use `asyncio.gather(..., return_exceptions=True)` for cleanup
- Catch `asyncio.CancelledError` in loops

## Important Gotchas

### 1. Protocol Callbacks
MAVConnection methods like `connection_made()`, `data_received()` are called by asyncio, not directly. Don't call them in tests unless mocking protocol behavior.

### 2. Sequence Wraparound
MAVLink sequence numbers are 8-bit (0-255). Handle wraparound correctly:
```python
expected_seq = (self.last_sequence + 1) % 256
```

### 3. Latency Filtering
Always filter -1 values when calculating latency statistics:
```python
filtered_samples = [lat for lat in self.latency_samples if lat >= 0]
```

### 4. Outage at Shutdown
The `stop()` method MUST check for active outages and count them:
```python
if self.in_outage and self.outage_start_time:
    outage_duration = time.time() - self.outage_start_time
    self.total_outage_seconds += outage_duration
```

### 5. CSV File Handling
CSV files must be flushed after each write for real-time monitoring:
```python
self.csv_writer.writerow([...])
self.csv_file.flush()  # Critical!
```

## CI/CD Pipeline

GitHub Actions runs on push/PR to main:
1. **Lint**: flake8 checks code style
2. **Type Check**: mypy validates type hints
3. **Dead Code**: vulture checks for unused code (80% confidence)
4. **Test**: pytest on Python 3.9, 3.10, 3.11, 3.12
5. **Build**: Creates distribution packages if all checks pass

## Debugging Tips

### Enable Debug Logging
```bash
# Modify logging level in mavlink_link_tester.py
logging.basicConfig(level=logging.DEBUG)
```

### View Coverage Report
```bash
poetry run pytest --cov=mavlinklinktester --cov-report=html
# Open htmlcov/index.html in browser
```

### Test with Real MAVLink
```bash
# Use MAVProxy to simulate a vehicle
mavproxy.py --master=udpout:localhost:14550 --console

# In another terminal, run link tester
poetry run mavlink-link-tester.py --system-id 1 --component-id 1 udpin:0.0.0.0:14550
```

## Related Documentation

- [README.md](README.md) - User documentation and installation
- [LICENSE](LICENSE) - GNU General Public License v3.0
- [pyproject.toml](pyproject.toml) - Dependencies and project metadata
- [.github/workflows/ci.yml](.github/workflows/ci.yml) - CI configuration

## Contact

**Maintainer**: Stephen Dade (stephen_dade@hotmail.com)
**Repository**: https://github.com/stephendade/mavlinklinktester

## Version

This guide is current as of January 2026. Check git history for updates.
