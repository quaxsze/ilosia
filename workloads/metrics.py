from prometheus_client import Counter

service_launch_total = Counter(
    "ilosia_service_launch_total",
    "Number of service launch attempts.",
)
service_launch_failed_total = Counter(
    "ilosia_service_launch_failed_total",
    "Number of failed service launches.",
)
service_delete_total = Counter(
    "ilosia_service_delete_total",
    "Number of successfully deleted services.",
)
