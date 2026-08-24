import os
import subprocess
import time
from typing import NamedTuple
from pathlib import Path



temperature_celcius() -> int:
    temperature_path = Path("sys/class/thermal/thermal_zone0/temp")
    temp_int = int(temperature_path.read_text().strip())
    normalized_temp = temp_int / 1000
    return normalized_temp

memory_usage() -> str:
    return "i remember everything"

uptime_seconds() -> str:
    return "67 seconds"


