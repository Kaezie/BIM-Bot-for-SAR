"""One conservative camera/sensor transport profile; firmware stays unchanged."""
from types import MappingProxyType

PROFILE = MappingProxyType({
    'name': 'conservative-2',
    'upstream_read_timeout_seconds': 10,
    'snapshot_lease_seconds': 8,
    'inference_interval_seconds': .5,
    'thermal_poll_seconds': 1.,
    'video_interval_ms': 167,
    'background_video_interval_ms': 1000,
    'thermal_view_poll_ms': 1000,
    'thermal_summary_poll_ms': 2000,
    'device_poll_ms': 3000,
    'retry_interval_ms': 500,
})
