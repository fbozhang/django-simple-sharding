import hashlib
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from time import time

# Maximum timestamp value, 41 bits, representing a time range of up to 69 years
MAX_TS = 2**41 - 1
# Maximum instance ID value, 10 bits, representing a maximum of 1024 different machines or nodes
MAX_INSTANCE = 2**10 - 1
# Maximum sequence number value, 12 bits, representing up to 4096 IDs generated per millisecond
MAX_SEQ = 2**12 - 1


def get_network_address() -> int:
    """
    Get the network address of the local machine as the instance, ensuring it does not exceed MAX_INSTANCE.
    Uses a hash of the IP address to guarantee uniqueness within the allowed range.
    """
    # Get the hostname of the local machine
    hostname = socket.gethostname()
    # Get the IP address corresponding to the hostname
    ip_address = socket.gethostbyname(hostname)

    # Hash the entire IP address to ensure uniqueness
    hash_object = hashlib.md5(ip_address.encode())
    # Convert the hash to an integer
    ip_hash_int = int(hash_object.hexdigest(), 16)

    # Ensure the value fits within the MAX_INSTANCE range (0 to 1023)
    instance_id = ip_hash_int % (MAX_INSTANCE + 1)

    return instance_id


@dataclass(frozen=True)
class Snowflake:
    timestamp: int
    instance: int
    epoch: int = 0
    seq: int = 0

    def __post_init__(self):
        if self.epoch < 0:
            raise ValueError("epoch must not be negative!")

        if self.timestamp < 0 or self.timestamp > MAX_TS:
            raise ValueError(f"timestamp must not be negative and must be less than {MAX_TS}!")

        if self.instance < 0 or self.instance > MAX_INSTANCE:
            raise ValueError(f"instance must not be negative and must be less than {MAX_INSTANCE}!")

        if self.seq < 0 or self.seq > MAX_SEQ:
            raise ValueError(f"seq must not be negative and must be less than {MAX_SEQ}!")

    @classmethod
    def parse(cls, snowflake: int, epoch: int = 0) -> "Snowflake":
        return cls(
            epoch=epoch,
            timestamp=snowflake >> 22,
            instance=snowflake >> 12 & MAX_INSTANCE,
            seq=snowflake & MAX_SEQ,
        )

    @property
    def milliseconds(self) -> int:
        return self.timestamp + self.epoch

    @property
    def seconds(self) -> float:
        return self.milliseconds / 1000

    @property
    def datetime(self) -> datetime:
        return datetime.fromtimestamp(self.seconds, timezone.utc)

    def datetime_tz(self, tz: tzinfo = None) -> datetime:
        return datetime.fromtimestamp(self.seconds, tz=tz)

    @property
    def timedelta(self) -> timedelta:
        return timedelta(milliseconds=self.epoch)

    @property
    def value(self) -> int:
        return self.timestamp << 22 | self.instance << 12 | self.seq

    def __int__(self) -> int:
        return self.value


class SnowflakeGenerator:
    def __init__(
        self,
        instance: int,
        *,
        seq: int = 0,
        epoch: int = 0,
        timestamp: int = None,
    ):

        current = int(time() * 1000)
        self._check_ts(current, epoch)

        timestamp = timestamp or current

        if timestamp < 0 or timestamp > current:
            raise ValueError(f"timestamp must not be negative and must be less than {current}!")

        if epoch < 0 or epoch > current:
            raise ValueError(f"epoch must not be negative and must be lower than current time {current}!")

        self._epo = epoch
        self._ts = timestamp - self._epo

        if instance < 0 or instance > MAX_INSTANCE:
            raise ValueError(f"instance must not be negative and must be less than {MAX_INSTANCE}!")

        if seq < 0 or seq > MAX_SEQ:
            raise ValueError(f"seq must not be negative and must be less than {MAX_SEQ}!")

        self._inf = instance << 12
        self._seq = seq

    @staticmethod
    def _check_ts(current_ts: int, epoch: int):
        if current_ts - epoch >= MAX_TS:
            raise OverflowError(
                "The maximum current timestamp has been reached in selected epoch,"
                "so Snowflake cannot generate more IDs!"
            )

    @classmethod
    def from_snowflake(cls, sf: Snowflake) -> "SnowflakeGenerator":
        return cls(sf.instance, seq=sf.seq, epoch=sf.epoch, timestamp=sf.timestamp)

    @property
    def epoch(self) -> int:
        return self._epo

    def __iter__(self):
        return self

    def __next__(self) -> int:
        current = int(time() * 1000) - self._epo
        self._check_ts(current, 0)

        if self._ts == current:
            if self._seq == MAX_SEQ:
                raise OverflowError("Cannot generate more Snowflake IDs in the current millisecond!")
            self._seq += 1
        elif self._ts > current:
            raise OverflowError("Cannot generate Snowflake ID in the future!")
        else:
            self._seq = 0

        self._ts = current

        return self._ts << 22 | self._inf | self._seq


address_snowflake_generator = SnowflakeGenerator(get_network_address())
