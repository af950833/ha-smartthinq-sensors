"""------------------for AC"""

from __future__ import annotations

import asyncio
import calendar
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging

from ..backports.functools import cached_property
from ..const import AirConditionerFeatures, TemperatureUnit
from ..core_async import ClientAsync
from ..core_exceptions import APIError, InvalidRequestError
from ..core_util import TempUnitConversion
from ..device import Device, DeviceStatus
from ..device_info import DeviceInfo
from ..model_info import TYPE_RANGE

AWHP_MODEL_TYPE = ["AWHP", "SAC_AWHP"]

AC_CONTROL_COMMAND_DELAY = 1.0

WIND_MODE_OFF = "설정 안 함"
DISCOVERED_FEATURE_LABELS = {
    "airClean": "공기청정",
    "iceValley": "쿨파워",
    "flowLongPower": "롱파워",
    "smartCare": "스마트",
}
WIND_MODE_TOKENS = {
    "iceValley": ("ICEVALLEY",),
    "flowLongPower": ("LONGPOWER", "FLOW_LONG_POWER"),
}
LONGPOWER_LABEL = "롱파워"

# ThinQ model data may advertise generic controls that the physical product does
# not implement. Keep these narrowly scoped to models confirmed by diagnostics.
DUAL_FAN_EXCLUDED_MODELS = {"PAC_910604_KR"}
AUTODRY_EXCLUDED_MODELS = {"PAC_910604_KR"}
OP_MODE_TOKENS = {
    "COOL": ("COOL",),
    "DRY": ("DRY",),
    "FAN": ("FAN",),
    "HEAT": ("HEAT",),
    "ACO": ("ACO",),
    "AI": ("AI",),
    "AIRCLEAN": ("AIRCLEAN", "AIR_CLEAN"),
    "AROMA": ("AROMA",),
    "ENERGY_SAVING": ("ENERGY_SAVING", "ENERGYSAVING"),
    "ENERGY_SAVER": ("ENERGY_SAVER", "ENERGYSAVER"),
}
WIND_MODE_SELECT_EXCLUDED = {
    "airClean",
    "jet",
    "smartCare",
}


@dataclass(frozen=True)
class DiscoveredEnumControl:
    """ThinQ enum state paired with its model-advertised control path."""

    key: str
    ctrl_key: str
    use_dataset: bool
    options: dict

CTRL_BASIC = ["Control", "basicCtrl"]
CTRL_WIND_MODE = ["Control", "wModeCtrl"]
CTRL_WIND_DIRECTION = ["Control", "wDirCtrl"]
CTRL_MISC = ["Control", "miscCtrl"]

CTRL_FILTER_V2 = "filterMngStateCtrl"

DUCT_ZONE_V1 = "DuctZone"
DUCT_ZONE_V1_TYPE = "DuctZoneType"
STATE_FILTER_V1 = "Filter"
STATE_FILTER_V1_MAX = "FilterMax"
STATE_FILTER_V1_USE = "FilterUse"
STATE_POWER_V1 = "InOutInstantPower"

# AC Section
STATE_OPERATION = ["Operation", "airState.operation"]
STATE_OPERATION_MODE = ["OpMode", "airState.opMode"]
STATE_CURRENT_TEMP = ["TempCur", "airState.tempState.current"]
STATE_TARGET_TEMP = ["TempCfg", "airState.tempState.target"]
STATE_WIND_STRENGTH = ["WindStrength", "airState.windStrength"]
STATE_WDIR_HSWING = ["WDirLeftRight", "airState.wDir.leftRight"]
STATE_WDIR_VSWING = ["WDirUpDown", "airState.wDir.upDown"]
STATE_DUCT_ZONE = ["ZoneControl", "airState.ductZone.state"]
STATE_POWER = [STATE_POWER_V1, "airState.energy.onCurrent"]
STATE_HUMIDITY = ["SensorHumidity", "airState.humidity.current"]
STATE_MODE_AIRCLEAN = ["AirClean", "airState.wMode.airClean"]
STATE_SMARTCARE = ["SmartCare","airState.wMode.smartCare"]
STATE_POWERSAVE = ["PowerSave","airState.powerSave.basic"]
STATE_AUTODRY = ["AutoDry","airState.miscFuncState.autoDry"]
STATE_MODE_JET = ["Jet", "airState.wMode.jet"]
STATE_LIGHTING_DISPLAY = ["DisplayControl", "airState.lightingState.displayControl"]
STATE_AIRSENSORMON = ["SensorMon", "airState.quality.sensorMon"]
STATE_PM1 = ["SensorPM1", "airState.quality.PM1"]
STATE_PM10 = ["SensorPM10", "airState.quality.PM10"]
STATE_PM25 = ["SensorPM2", "airState.quality.PM2"]
STATE_RESERVATION_SLEEP_TIME = ["SleepTime", "airState.reservation.sleepTime"]

FILTER_TYPES = [
    [
        [
            AirConditionerFeatures.FILTER_MAIN_LIFE,
            AirConditionerFeatures.FILTER_MAIN_USE,
            AirConditionerFeatures.FILTER_MAIN_MAX,
        ],
        [STATE_FILTER_V1_USE, "airState.filterMngStates.useTime"],
        [STATE_FILTER_V1_MAX, "airState.filterMngStates.maxTime"],
        None,
    ],
]

CMD_STATE_OPERATION = [CTRL_BASIC, "Set", STATE_OPERATION]
CMD_STATE_OP_MODE = [CTRL_BASIC, "Set", STATE_OPERATION_MODE]
CMD_STATE_TARGET_TEMP = [CTRL_BASIC, "Set", STATE_TARGET_TEMP]
CMD_STATE_WDIR_HSWING = [CTRL_WIND_DIRECTION, "Set", STATE_WDIR_HSWING]
CMD_STATE_WDIR_VSWING = [CTRL_WIND_DIRECTION, "Set", STATE_WDIR_VSWING]
CMD_STATE_DUCT_ZONES = [CTRL_MISC, "Set", [DUCT_ZONE_V1, "airState.ductZone.control"]]
CMD_STATE_MODE_AIRCLEAN = [CTRL_BASIC, "Set", STATE_MODE_AIRCLEAN]
CMD_STATE_POWERSAVE = [CTRL_BASIC, "Set", STATE_POWERSAVE]
CMD_STATE_AUTODRY = [CTRL_BASIC, "Set", STATE_AUTODRY]
CMD_STATE_MODE_JET = [CTRL_BASIC, "Set", STATE_MODE_JET]
CMD_STATE_LIGHTING_DISPLAY = [CTRL_BASIC, "Set", STATE_LIGHTING_DISPLAY]
CMD_RESERVATION_SLEEP_TIME = [CTRL_BASIC, "Set", STATE_RESERVATION_SLEEP_TIME]

# AWHP Section
STATE_AWHP_TEMP_MODE = ["AwhpTempSwitch", "airState.miscFuncState.awhpTempSwitch"]
STATE_WATER_IN_TEMP = ["WaterInTempCur", "airState.tempState.inWaterCurrent"]
STATE_WATER_OUT_TEMP = ["WaterTempCur", "airState.tempState.outWaterCurrent"]
STATE_WATER_MIN_TEMP = ["WaterTempCoolMin", "airState.tempState.waterTempCoolMin"]
STATE_WATER_MAX_TEMP = ["WaterTempHeatMax", "airState.tempState.waterTempHeatMax"]
STATE_HOT_WATER_TEMP = ["HotWaterTempCur", "airState.tempState.hotWaterCurrent"]
STATE_HOT_WATER_TARGET_TEMP = ["HotWaterTempCfg", "airState.tempState.hotWaterTarget"]
STATE_HOT_WATER_MIN_TEMP = ["HotWaterTempMin", "airState.tempState.hotWaterTempMin"]
STATE_HOT_WATER_MAX_TEMP = ["HotWaterTempMax", "airState.tempState.hotWaterTempMax"]
STATE_HOT_WATER_MODE = ["HotWater", "airState.miscFuncState.hotWater"]
STATE_MODE_AWHP_SILENT = ["SilentMode", "airState.miscFuncState.silentAWHP"]

CMD_STATE_HOT_WATER_MODE = [CTRL_BASIC, "Set", STATE_HOT_WATER_MODE]
CMD_STATE_HOT_WATER_TARGET_TEMP = [CTRL_BASIC, "Set", STATE_HOT_WATER_TARGET_TEMP]
CMD_STATE_MODE_AWHP_SILENT = [CTRL_BASIC, "Set", STATE_MODE_AWHP_SILENT]

CMD_ENABLE_EVENT_V2 = ["allEventEnable", "Set", "airState.mon.timeout"]

DEFAULT_MIN_TEMP = 18
DEFAULT_MAX_TEMP = 30
AWHP_MIN_TEMP = 5
AWHP_MAX_TEMP = 80

TEMP_STEP_WHOLE = 1.0
TEMP_STEP_HALF = 0.5

ADD_FEAT_POLL_INTERVAL = 300  # 5 minutes
ENERGY_USAGE_POLL_INTERVAL = 300  # 5 minutes

LIGHTING_DISPLAY_OFF = "0"
LIGHTING_DISPLAY_ON = "1"

MODE_OFF = "@OFF"
MODE_ON = "@ON"

MODE_AIRCLEAN_OFF = "@OFF"
MODE_AIRCLEAN_ON = "@ON"

AWHP_MODE_AIR = "@AIR"
AWHP_MODE_WATER = "@WATER"

ZONE_OFF = "0"
ZONE_ON = "1"
ZONE_ST_CUR = "current"
ZONE_ST_NEW = "new"

FILTER_STATUS_MAP = {
    STATE_FILTER_V1_USE: "UseTime",
    STATE_FILTER_V1_MAX: "ChangePeriod",
}

_LOGGER = logging.getLogger(__name__)


class ACOp(Enum):
    """Whether a device is on or off."""

    OFF = "@AC_MAIN_OPERATION_OFF_W"
    ON = "@AC_MAIN_OPERATION_ON_W"
    RIGHT_ON = "@AC_MAIN_OPERATION_RIGHT_ON_W"  # Right fan only.
    LEFT_ON = "@AC_MAIN_OPERATION_LEFT_ON_W"  # Left fan only.
    ALL_ON = "@AC_MAIN_OPERATION_ALL_ON_W"  # Both fans (or only fan) on.


class ACMode(Enum):
    """The operation mode for an AC/HVAC device."""

    COOL = "@AC_MAIN_OPERATION_MODE_COOL_W"
    DRY = "@AC_MAIN_OPERATION_MODE_DRY_W"
    FAN = "@AC_MAIN_OPERATION_MODE_FAN_W"
    HEAT = "@AC_MAIN_OPERATION_MODE_HEAT_W"
    ACO = "@AC_MAIN_OPERATION_MODE_ACO_W"
    AI = "@AC_MAIN_OPERATION_MODE_AI_W"
    AIRCLEAN = "@AC_MAIN_OPERATION_MODE_AIRCLEAN_W"
    AROMA = "@AC_MAIN_OPERATION_MODE_AROMA_W"
    ENERGY_SAVING = "@AC_MAIN_OPERATION_MODE_ENERGY_SAVING_W"
    ENERGY_SAVER = "@AC_MAIN_OPERATION_MODE_ENERGY_SAVER_W"


class ACVSwingMode(Enum):
    """The swing mode for an AC/HVAC device."""

    정지 = "@OFF"
    회전 = "@ON"


class ACHSwingMode(Enum):
    """The swing mode for an AC/HVAC device."""

    정지 = "@OFF"
    좌측 = "@LEFT_ON"
    우측 = "@RIGHT_ON"
    좌우 = "@ALL_ON"

class JetMode(Enum):
    """Possible JET modes."""

    OFF = MODE_OFF
    COOL = "@COOL_JET"
    HEAT = "@HEAT_JET"
    DRY = "@DRY_JET_W"
    HIMALAYAS = "@HIMALAYAS_COOL"


class JetModeSupport(Enum):
    """Supported JET modes."""

    NONE = 0
    COOL = 1
    HEAT = 2
    BOTH = 3


class AirConditionerDevice(Device):
    """A higher-level interface for a AC."""

    def __init__(
        self,
        client: ClientAsync,
        device_info: DeviceInfo,
        temp_unit=TemperatureUnit.CELSIUS,
    ):
        """Initialize AirConditionerDevice object."""
        super().__init__(client, device_info, AirConditionerStatus(self))
        self._temperature_unit = (
            TemperatureUnit.FAHRENHEIT
            if temp_unit == TemperatureUnit.FAHRENHEIT
            else TemperatureUnit.CELSIUS
        )

        self._temperature_step = TEMP_STEP_WHOLE
        self._duct_zones = {}

        self._current_power = None
        self._current_power_supported = True
        self._energy_usage = {
            AirConditionerFeatures.ENERGY_TODAY: None,
            AirConditionerFeatures.ENERGY_YESTERDAY: None,
            AirConditionerFeatures.ENERGY_MONTH: None,
        }
        self._energy_usage_supported = True
        self._last_energy_usage_poll: datetime | None = None

        self._filter_status = None
        self._filter_status_supported = True

        self._unit_conv = TempUnitConversion()
        self._control_lock = asyncio.Lock()

    def _f2c(self, value):
        """Convert Fahrenheit to Celsius temperatures for this device if required."""
        if self._temperature_unit == TemperatureUnit.CELSIUS:
            return value
        return self._unit_conv.f2c(value, self.model_info)

    def conv_temp_unit(self, value):
        """Convert Celsius to Fahrenheit temperatures for this device if required."""
        if self._temperature_unit == TemperatureUnit.CELSIUS:
            return float(value)
        return self._unit_conv.c2f(value, self.model_info)

    def _adjust_temperature_step(self, target_temp):
        if self._temperature_step != TEMP_STEP_WHOLE:
            return
        if target_temp is None:
            return
        if int(target_temp) != target_temp:
            self._temperature_step = TEMP_STEP_HALF

    def _resolve_key(self, key_name) -> str:
        """Resolve a legacy key pair or a direct model key to a model data key."""
        if isinstance(key_name, list):
            return self._get_state_key(key_name)
        return key_name

    @cached_property
    def _model_value_keys(self) -> list[str]:
        """Return model keys that can be inspected for dynamic controls."""
        model_data = self.model_info.as_dict()
        keys = []
        for section in ("Value", "MonitoringValue"):
            values = model_data.get(section)
            if isinstance(values, dict):
                keys.extend(values)
        return keys

    def _support_options(self, *tokens: str) -> list[str]:
        """Return model support enum labels whose keys match all tokens."""
        matches = []
        token_set = [token.lower() for token in tokens]
        for key in self._model_value_keys:
            key_l = key.lower()
            if not key_l.startswith("support") and ".support" not in key_l:
                continue
            if not all(token in key_l for token in token_set):
                continue
            matches.extend(self._enum_options(key).values())
        return matches

    @staticmethod
    def _support_token_match(option: str, token: str) -> bool:
        """Return if a support option contains a token as a distinct LG token."""
        option_text = f"_{str(option).strip('@').upper()}_"
        token_text = token.strip("@").upper()
        if f"_{token_text}_" in option_text:
            return True
        if "_" in token_text:
            return all(f"_{part}_" in option_text for part in token_text.split("_"))
        return False

    @classmethod
    def _support_matches(cls, options: list[str], *tokens: str) -> bool | None:
        """Return support match, or None when no support list exists."""
        if not options:
            return None
        return any(
            any(cls._support_token_match(option, token) for token in tokens)
            for option in options
        )

    def _supported_or_unknown(self, support_tokens: tuple[str, ...], *value_tokens: str) -> bool:
        """Return True when support is advertised or no support list exists."""
        supported = self._support_matches(
            self._support_options(*support_tokens), *value_tokens
        )
        return True if supported is None else supported

    def _enum_options(self, key_name) -> dict:
        """Return enum options for a model key."""
        key = self._resolve_key(key_name)
        if not self.model_info.is_enum_type(key):
            return {}
        value = self.model_info.value(key)
        return value.options if value else {}

    def _discover_enum_control(
        self, key_name, fallback_ctrl: str = "basicCtrl"
    ) -> DiscoveredEnumControl | None:
        """Discover an enum state and the control key that can set it."""
        key = self._resolve_key(key_name)
        options = self._enum_options(key)
        if not options:
            return None
        ctrl_key, use_dataset = self._control_for_key(key, fallback_ctrl)
        return DiscoveredEnumControl(key, ctrl_key, use_dataset, options)

    @staticmethod
    def _discovered_feature_label(key: str) -> str:
        """Return a user-facing label for a discovered feature key."""
        name = key.rsplit(".", 1)[-1]
        if name in DISCOVERED_FEATURE_LABELS:
            return DISCOVERED_FEATURE_LABELS[name]
        label = []
        for char in name:
            if char.isupper() and label:
                label.append(" ")
            label.append(char)
        return "".join(label).replace("_", " ").title()

    @cached_property
    def _wind_strength_key(self) -> str | None:
        """Return the model key that represents fan wind strength."""
        for key_name in (STATE_WIND_STRENGTH, "airState.windStrength"):
            key = self._resolve_key(key_name)
            if self._enum_options(key):
                return key
        for key in self._model_value_keys:
            if key.endswith("windStrength") and self._enum_options(key):
                return key
        return None

    @cached_property
    def _wind_mode_map(self) -> dict[str, str]:
        """Return selectable special wind modes discovered from model data."""
        modes = {}
        support_options = self._support_options("wmode")
        for key in self._model_value_keys:
            if ".wMode." not in key:
                continue
            name = key.rsplit(".", 1)[-1]
            if name in WIND_MODE_SELECT_EXCLUDED:
                continue
            if name == "flowLongPower" and self._longpower_wind_strength_value is not None:
                continue
            support_tokens = WIND_MODE_TOKENS.get(name, (name.upper(),))
            supported = self._support_matches(support_options, *support_tokens)
            if supported is False:
                continue
            if self.model_info.enum_value(key, MODE_ON) is None:
                continue
            if self.model_info.enum_value(key, MODE_OFF) is None:
                continue
            modes[self._discovered_feature_label(key)] = key
        return dict(sorted(modes.items()))

    @staticmethod
    def _contains_token(value: str, token: str) -> bool:
        """Return if an LG enum string contains a full token."""
        return f"_{token}_" in value or value.endswith(f"_{token}_W")

    @staticmethod
    def _fan_label_from_enum(value: str) -> str | None:
        """Translate LG wind strength enum text to a HA fan label."""
        if not value:
            return None
        if "LONGPOWER" in value:
            return LONGPOWER_LABEL
        if any(token in value for token in ("SLOW", "AUTO", "POWER", "LONGPOWER")):
            return None
        if "LOW_MID" in value or "MID_HIGH" in value:
            return None
        if AirConditionerDevice._contains_token(value, "LOW"):
            return "약풍"
        if AirConditionerDevice._contains_token(value, "MID"):
            return "중풍"
        if AirConditionerDevice._contains_token(value, "HIGH"):
            return "강풍"
        return None

    def _fan_value_priority(self, value: str) -> int:
        """Prefer whole-unit or same left/right values over partial variants."""
        if not self.model_info.is_info_v2:
            if "CLEAN" in value:
                return 5
            if "LEFT" not in value and "RIGHT" not in value:
                return 40
            if "|" in value and "LEFT" in value and "RIGHT" in value:
                return 20
            return 10
        if "|" in value and "LEFT" in value and "RIGHT" in value:
            return 40
        if "CLEAN" in value:
            return 5
        if "LEFT" not in value and "RIGHT" not in value:
            return 30
        return 10

    @property
    def _is_dual_fan_excluded_model(self) -> bool:
        """Return whether dual fan controls are invalid for this model."""
        return self.device_info.model_name in DUAL_FAN_EXCLUDED_MODELS

    @property
    def _wind_strength_control_key(self) -> str:
        """Return the protocol-specific control key for wind strength."""
        return "basicCtrl" if self.model_info.is_info_v2 else "Control"

    @cached_property
    def _wind_direction_support_options(self) -> list[str]:
        """Return wind-direction support from ThinQ1 or ThinQ2 model data."""
        return self._support_options("wdir") or self._support_options("winddir")

    @cached_property
    def _fan_speed_map(self) -> dict[str, str]:
        """Return HA fan labels mapped to encoded LG wind strength values."""
        if not self._wind_strength_key:
            return {}
        candidates: dict[str, tuple[int, str]] = {}
        for encoded, enum_value in self._enum_options(self._wind_strength_key).items():
            if not (label := self._fan_label_from_enum(enum_value)):
                continue
            priority = self._fan_value_priority(enum_value)
            if priority > candidates.get(label, (-1, ""))[0]:
                candidates[label] = (priority, encoded)
        if not self.model_info.is_info_v2:
            support_options = self._support_options("windstrength")
            supported_labels = {
                label
                for option in support_options
                if (label := self._fan_label_from_enum(option)) is not None
            }
            if supported_labels:
                candidates = {
                    label: candidate
                    for label, candidate in candidates.items()
                    if label in supported_labels
                }
        ordered = ["약풍", "중풍", "강풍", LONGPOWER_LABEL]
        return {
            label: candidates[label][1]
            for label in ordered
            if label in candidates
        }

    @cached_property
    def _longpower_wind_strength_value(self) -> str | None:
        """Return the windStrength value for long power when the model exposes one."""
        if not self._wind_strength_key:
            return None
        candidates: list[tuple[int, str]] = []
        for encoded, enum_value in self._enum_options(self._wind_strength_key).items():
            if "LONGPOWER" in enum_value:
                candidates.append((self._fan_value_priority(enum_value), encoded))
        if not candidates:
            return None
        return max(candidates)[1]

    @cached_property
    def _dual_fan_speed_map(self) -> dict[tuple[str, str], str]:
        """Return left/right fan label pairs mapped to encoded wind strength values."""
        if not self._wind_strength_key:
            return {}
        pairs = {}
        for encoded, enum_value in self._enum_options(self._wind_strength_key).items():
            if "|" not in enum_value:
                continue
            parts = enum_value.split("|", 1)
            if len(parts) != 2:
                continue
            left = self._fan_label_from_enum(parts[0])
            right = self._fan_label_from_enum(parts[1])
            if left and right:
                pairs[(left, right)] = encoded
        return pairs

    def _control_for_key(self, state_key: str, fallback_ctrl: str = "basicCtrl") -> tuple[str, bool]:
        """Find the ThinQ control key and payload shape for a state key."""
        controls = self.model_info.as_dict().get("ControlDevice", [])
        if isinstance(controls, dict):
            controls = controls.values()
        for control in controls:
            if not isinstance(control, dict):
                continue
            ctrl_key = control.get("ctrlKey")
            if not ctrl_key:
                continue
            data_set = control.get("dataSetList")
            if isinstance(data_set, dict) and state_key in data_set:
                return ctrl_key, True
            data_key = control.get("dataKey", "")
            if isinstance(data_key, str) and state_key in data_key.split("|"):
                return ctrl_key, False
        return fallback_ctrl, False

    def _is_wind_mode_state_supported(self, state_key) -> bool:
        """Return if a wind mode state exists and can be toggled."""
        key = self._resolve_key(state_key)
        if not self.model_info.value_exist(key):
            return False
        name = key.rsplit(".", 1)[-1]
        if ".wMode." in key:
            support_tokens = WIND_MODE_TOKENS.get(name, (name.upper(),))
            supported = self._support_matches(
                self._support_options("wmode"), *support_tokens
            )
            if supported is False:
                return False
        elif name == "basic":
            if not self._supported_or_unknown(("pacmode",), "ENERGYSAVING"):
                return False
        elif name == "autoDry":
            if not self._supported_or_unknown(("pacmode",), "AUTODRY"):
                return False
        return (
            self.model_info.enum_value(key, MODE_ON) is not None
            and self.model_info.enum_value(key, MODE_OFF) is not None
        )

    def _current_data_value(self, data_key: str):
        """Return current raw data value for multi-key control payloads."""
        status = self._status.as_dict if self._status else {}
        value = status.get(data_key)
        if value is None:
            value = self.model_info.default(data_key)
        if value is None and self.model_info.is_enum_type(data_key):
            value = self.model_info.enum_value(data_key, MODE_OFF)
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, str):
            try:
                num_value = float(value)
            except ValueError:
                return value
            if num_value.is_integer():
                return str(int(num_value))
        return "0" if value is None else str(value)

    async def _set_enum_value(
        self, state_key, value: str, fallback_ctrl: str = "basicCtrl"
    ):
        """Set an encoded enum value using the model's advertised control shape."""
        control = self._discover_enum_control(state_key, fallback_ctrl)
        if control is None:
            raise ValueError(f"Unsupported enum control for {state_key}")
        key = control.key
        ctrl_key = control.ctrl_key
        use_dataset = control.use_dataset
        if not use_dataset:
            await self.set(ctrl_key, "Set", key=key, value=value)
            return

        payload = {"ctrlKey": ctrl_key, "command": "Set", "dataSetList": {}}
        if ctrl_key == "wModeCtrl":
            payload["dataSetList"][key] = value
            await self.set(payload, None, key=key, value=value)
            return

        controls = self.model_info.as_dict().get("ControlDevice", [])
        if isinstance(controls, dict):
            controls = controls.values()
        data_keys = []
        for control in controls:
            if isinstance(control, dict) and control.get("ctrlKey") == ctrl_key:
                data_set = control.get("dataSetList")
                if isinstance(data_set, dict):
                    data_keys = list(data_set)
                    break
        for data_key in data_keys:
            if self.model_info.is_enum_type(data_key):
                if ctrl_key == "wModeCtrl":
                    payload["dataSetList"][data_key] = (
                        self.model_info.enum_value(data_key, MODE_OFF) or "0"
                    )
                else:
                    payload["dataSetList"][data_key] = self._current_data_value(data_key)
        payload["dataSetList"][key] = value
        await self.set(payload, None, key=key, value=value)

    async def _set_enum_state(
        self, state_key, enum_name: str, fallback_ctrl: str = "basicCtrl"
    ):
        """Set an enum state using the model's advertised control shape."""
        key = self._resolve_key(state_key)
        value = self.model_info.enum_value(key, enum_name)
        if value is None:
            raise ValueError(f"Unsupported enum value for {key}: {enum_name}")
        await self._set_enum_value(key, value, fallback_ctrl)

    async def _set_enum_state_basic(self, state_key, enum_name: str):
        """Set an enum state using basicCtrl even when another control is advertised."""
        key = self._resolve_key(state_key)
        value = self.model_info.enum_value(key, enum_name)
        if value is None:
            raise ValueError(f"Unsupported enum value for {key}: {enum_name}")
        await self.set("basicCtrl", "Set", key=key, value=value)

    def _get_supported_operations(self):
        """Return the list of the ACOp Operations the device supports."""

        key = self._get_state_key(STATE_OPERATION)
        mapping = self.model_info.value(key).options
        return [ACOp(o) for o in mapping.values()]

    @cached_property
    def _supported_on_operation(self):
        """
        Get the most correct "On" operation the device supports.
        :raises ValueError: If ALL_ON is not supported, but there are
            multiple supported ON operations. If a model raises this,
            its behaviour needs to be determined so this function can
            make a better decision.
        """

        operations = self._get_supported_operations()

        # This ON operation appears to be supported in newer AC models
        if ACOp.ALL_ON in operations:
            return ACOp.ALL_ON

        # This ON operation appears to be supported in V2 AC models, to check
        if ACOp.ON in operations:
            return ACOp.ON

        # Older models, or possibly just the LP1419IVSM, do not support ALL_ON,
        # instead advertising only a single operation of RIGHT_ON.
        # Thus, if there's only one ON operation, we use that.
        single_op = [op for op in operations if op != ACOp.OFF]
        if len(single_op) == 1:
            return single_op[0]

        # Hypothetically, the API could return multiple ON operations, neither
        # of which are ALL_ON. This will raise in that case, as we don't know
        # what that model will expect us to do to turn everything on.
        # Or, this code will never actually be reached! We can only hope. :)
        raise ValueError(
            f"could not determine correct 'on' operation:"
            f" too many reported operations: '{str(operations)}'"
        )

    @cached_property
    def _temperature_range(self):
        """Get valid temperature range for model."""

        temp_mode = self._status.awhp_temp_mode
        if temp_mode and temp_mode == AWHP_MODE_WATER:
            min_temp = self._status.water_target_min_temp or AWHP_MIN_TEMP
            max_temp = self._status.water_target_max_temp or AWHP_MAX_TEMP
        else:
            key = self._get_state_key(STATE_TARGET_TEMP)
            range_info = self.model_info.value(key)
            if not range_info:
                min_temp = DEFAULT_MIN_TEMP
                max_temp = DEFAULT_MAX_TEMP
            else:
                min_temp = min(range_info.min, DEFAULT_MIN_TEMP)
                max_temp = max(range_info.max, DEFAULT_MAX_TEMP)
        return [min_temp, max_temp]

    @cached_property
    def _hot_water_temperature_range(self):
        """Get valid hot water temperature range for model."""

        if not self.is_water_heater_supported:
            return None

        min_temp = self._status.hot_water_target_min_temp
        max_temp = self._status.hot_water_target_max_temp
        if min_temp is None or max_temp is None:
            return [AWHP_MIN_TEMP, AWHP_MAX_TEMP]
        return [min_temp, max_temp]

    @cached_property
    def is_duct_zones_supported(self):
        """Check if device support duct zones."""
        return self.model_info.value_exist(self._get_state_key(STATE_DUCT_ZONE)) or (
            not self.model_info.is_info_v2
            and self.model_info.value_exist(DUCT_ZONE_V1_TYPE)
        )

    def is_duct_zone_enabled(self, zone: str) -> bool:
        """Get if a specific zone is enabled"""
        return zone in self._duct_zones

    def get_duct_zone(self, zone: str) -> bool:
        """Get the status for a specific zone"""
        if zone not in self._duct_zones:
            return False
        cur_zone = self._duct_zones[zone]
        if ZONE_ST_NEW in cur_zone:
            return cur_zone[ZONE_ST_NEW] == ZONE_ON
        return cur_zone[ZONE_ST_CUR] == ZONE_ON

    def set_duct_zone(self, zone: str, status: bool):
        """Set the status for a specific zone"""
        if zone not in self._duct_zones:
            return
        self._duct_zones[zone][ZONE_ST_NEW] = ZONE_ON if status else ZONE_OFF

    @property
    def duct_zones(self) -> list:
        """Return a list of available duct zones"""
        return list(self._duct_zones)

    async def update_duct_zones(self):
        """Update the current duct zones status."""
        states = await self._get_duct_zones()
        if not states:
            return

        duct_zones = {}
        send_update = False
        for zone, state in states.items():
            cur_status = state[ZONE_ST_CUR]
            new_status = None
            if zone in self._duct_zones:
                new_status = self._duct_zones[zone].get(ZONE_ST_NEW)
                if new_status and new_status != cur_status:
                    send_update = True
            duct_zones[zone] = {ZONE_ST_CUR: new_status or cur_status}

        self._duct_zones = duct_zones
        if send_update:
            await self._set_duct_zones(duct_zones)

    async def _get_duct_zones(self) -> dict:
        """Get the status of the zones (for ThinQ1 only zone configured).

        return value is a dict with this format:
        - key: The zone index. A string containing a number
        - value: another dict with:
            - key: "current"
            - value: "1" if zone is ON else "0"
        """

        # first check if duct is supported
        if not (self.is_duct_zones_supported and self._status):
            return {}

        duct_state = -1
        # duct zone type is available only for some ThinQ1 devices
        if not self._status.duct_zones_type:
            duct_state = self._status.duct_zones_state
        if not duct_state:
            return {}

        # get real duct zones states

        # For device that provide duct_state in payload we transform
        # the value in the status in binary and than we create the result.
        # We always have 8 duct zone.

        if duct_state > 0:
            bin_arr = list(reversed(f"{duct_state:08b}"))
            return {str(v + 1): {ZONE_ST_CUR: k} for v, k in enumerate(bin_arr)}

        # For ThinQ1 devices result is a list of dicts with these keys:
        # - "No": The zone index. A string containing a number,
        #   starting from 1.
        # - "Cfg": Whether the zone is enabled. A string, either "1" or
        #   "0".
        # - "State": Whether the zone is open. Also "1" or "0".

        zones = await self._get_config(DUCT_ZONE_V1)
        return {
            zone["No"]: {ZONE_ST_CUR: zone["State"]}
            for zone in zones
            if zone["Cfg"] == "1"
        }

    async def _set_duct_zones(self, zones: dict):
        """
        Turn off or on the device's zones.
        The `zones` parameter is the same returned by _get_duct_zones().
        """

        # Ensure at least one zone is enabled: we can't turn all zones
        # off simultaneously.
        on_count = sum(int(zone[ZONE_ST_CUR]) for zone in zones.values())
        if on_count == 0:
            _LOGGER.warning("Turn off all duct zones is not allowed")
            return

        zone_cmd = "/".join(
            f"{key}_{value[ZONE_ST_CUR]}" for key, value in zones.items()
        )
        keys = self._get_cmd_keys(CMD_STATE_DUCT_ZONES)
        await self.set(keys[0], keys[1], key=keys[2], value=zone_cmd)

    @cached_property
    def is_air_to_water(self):
        """Return if is a Air To Water device."""
        return self.model_info.model_type in AWHP_MODEL_TYPE

    @cached_property
    def is_water_heater_supported(self):
        """Return if Water Heater is supported."""
        if not self.is_air_to_water:
            return False
        return self.model_info.value_exist(self._get_state_key(STATE_HOT_WATER_MODE)) or (
            self.model_info.value_exist(self._get_state_key(STATE_HOT_WATER_TARGET_TEMP))
        )

    @cached_property
    def op_modes(self):
        """Return a list of available operation modes."""
        modes = self._get_property_values(STATE_OPERATION_MODE, ACMode)
        support_options = self._support_options("opmode")
        if not support_options:
            return modes
        return [
            mode
            for mode in modes
            if self._support_matches(
                support_options, *OP_MODE_TOKENS.get(mode, (mode,))
            )
        ]

    @cached_property
    def fan_speeds(self):
        """Return fan speed and special wind mode options."""
        return [*self._fan_speed_map, *self._wind_mode_map]

    @cached_property
    def dual_fan_speed_options(self):
        """Return dual fan speed options when the model exposes left/right fan pairs."""
        if self._is_dual_fan_excluded_model or not self._dual_fan_speed_map:
            return []
        return [speed for speed in ("약풍", "중풍", "강풍") if speed in self.fan_speeds]

    @cached_property
    def wind_modes(self):
        """Return special wind modes exposed as a select."""
        if not self._wind_mode_map:
            return []
        return [WIND_MODE_OFF, *self._wind_mode_map]

    @cached_property
    def is_smartcare_supported(self):
        """Return if SmartCare is available."""
        return self._is_wind_mode_state_supported(STATE_SMARTCARE)

    @cached_property
    def horizontal_swing_modes(self):
        """Return a list of available horizontal swing modes."""
        supported = self._support_matches(
            self._wind_direction_support_options, "LEFT_RIGHT"
        )
        if supported is False:
            return []
        return self._get_property_values(STATE_WDIR_HSWING, ACHSwingMode)

    @cached_property
    def vertical_swing_modes(self):
        """Return a list of available vertical swing modes."""
        supported = self._support_matches(
            self._wind_direction_support_options, "UP_DOWN"
        )
        if supported is False:
            return []
        return self._get_property_values(STATE_WDIR_VSWING, ACVSwingMode)

    @property
    def temperature_unit(self):
        """Return the unit used for temperature."""
        return self._temperature_unit

    @property
    def target_temperature_step(self):
        """Return target temperature step used."""
        return self._temperature_step

    @property
    def target_temperature_min(self):
        """Return minimum value for target temperature."""
        temp_range = self._temperature_range
        return self.conv_temp_unit(temp_range[0])

    @property
    def target_temperature_max(self):
        """Return maximum value for target temperature."""
        temp_range = self._temperature_range
        return self.conv_temp_unit(temp_range[1])

    @cached_property
    def is_mode_airclean_supported(self):
        """Return if AirClean mode is supported."""
        if not self._supported_or_unknown(("pacmode",), "AIRCLEAN"):
            return False
        return self._is_wind_mode_state_supported(STATE_MODE_AIRCLEAN)

    @cached_property
    def is_powersave_supported(self):
        """Return if PowerSave mode is supported."""
        return self._is_wind_mode_state_supported(STATE_POWERSAVE)

    @cached_property
    def is_autodry_supported(self):
        """Return if AutoDry mode is supported."""
        if self.device_info.model_name in AUTODRY_EXCLUDED_MODELS:
            return False
        return self._is_wind_mode_state_supported(STATE_AUTODRY)

    @cached_property
    def supported_mode_jet(self):
        """Return if Jet mode is supported."""
        options = set(self._enum_options(STATE_MODE_JET).values())
        support_options = self._support_options("racsubmode")
        supports_cool = any(
            mode.value in options
            for mode in (JetMode.COOL, JetMode.DRY, JetMode.HIMALAYAS)
        )
        supports_heat = JetMode.HEAT.value in options
        support_cool = self._support_matches(support_options, "COOL_JET")
        support_heat = self._support_matches(support_options, "HEAT_JET")
        if support_cool is not None:
            supports_cool = supports_cool and support_cool
        if support_heat is not None:
            supports_heat = supports_heat and support_heat
        if supports_cool and supports_heat:
            return JetModeSupport.BOTH
        if supports_cool:
            return JetModeSupport.COOL
        if supports_heat:
            return JetModeSupport.HEAT
        return JetModeSupport.NONE

    @property
    def is_mode_jet_available(self):
        """Return if JET mode is available."""
        if (supported := self.supported_mode_jet) == JetModeSupport.NONE:
            return False
        if not self._status.is_on:
            return False
        if (curr_op_mode := self._status.operation_mode) is None:
            return False
        if curr_op_mode == ACMode.HEAT.name and supported in (
            JetModeSupport.HEAT,
            JetModeSupport.BOTH,
        ):
            return True
        if curr_op_mode in (ACMode.COOL.name, ACMode.DRY.name) and supported in (
            JetModeSupport.COOL,
            JetModeSupport.BOTH,
        ):
            return True
        return False

    @property
    def is_airclean_incompatible_mode_available(self):
        """Return if modes that do not apply to Airclean can be controlled."""
        if not self._status or not self._status.is_on:
            return False
        return self._status.operation_mode != ACMode.AIRCLEAN.name

    @property
    def is_smartcare_available(self):
        """Return if SmartCare can be controlled in the current mode."""
        if not self._status or not self._status.is_on:
            return False
        return self._status.operation_mode == ACMode.COOL.name

    @cached_property
    def _is_pm_supported(self):
        """Return if PM sensors are supported."""
        support_options = self._support_options("airpolution")
        if not support_options:
            support_options = self._support_options("airpollution")
        support_pm1 = self._support_matches(support_options, "PM1")
        support_pm25 = self._support_matches(support_options, "PM2_5", "PM25")
        support_pm10 = self._support_matches(support_options, "PM10")
        return [
            self.model_info.value_exist(self._get_state_key(STATE_PM1))
            and support_pm1 is not False,
            self.model_info.value_exist(self._get_state_key(STATE_PM25))
            and support_pm25 is not False,
            self.model_info.value_exist(self._get_state_key(STATE_PM10))
            and support_pm10 is not False,
        ]

    @property
    def is_pm1_supported(self):
        """Return if PM1 sensor is supported."""
        return self._is_pm_supported[0]

    @property
    def is_pm25_supported(self):
        """Return if PM2.5 sensor is supported."""
        return self._is_pm_supported[1]

    @property
    def is_pm10_supported(self):
        """Return if PM10 sensor is supported."""
        return self._is_pm_supported[2]

    @property
    def hot_water_target_temperature_step(self):
        """Return target temperature step used for hot water."""
        return TEMP_STEP_WHOLE

    @property
    def hot_water_target_temperature_min(self):
        """Return minimum value for hot water target temperature."""
        temp_range = self._hot_water_temperature_range
        if not temp_range:
            return None
        return self.conv_temp_unit(temp_range[0])

    @property
    def hot_water_target_temperature_max(self):
        """Return maximum value for hot water target temperature."""
        temp_range = self._hot_water_temperature_range
        if not temp_range:
            return None
        return self.conv_temp_unit(temp_range[1])

    async def power(self, turn_on):
        """Turn on or off the device (according to a boolean)."""
        operation = self._supported_on_operation if turn_on else ACOp.OFF
        keys = self._get_cmd_keys(CMD_STATE_OPERATION)
        op_value = self.model_info.enum_value(keys[2], operation.value)
        await self.set(keys[0], keys[1], key=keys[2], value=op_value)

    async def set_op_mode(self, mode):
        """Set the device's operating mode to an `OpMode` value."""
        if mode not in self.op_modes:
            raise ValueError(f"Invalid operating mode: {mode}")
        keys = self._get_cmd_keys(CMD_STATE_OP_MODE)
        mode_value = self.model_info.enum_value(keys[2], ACMode[mode].value)
        await self.set(keys[0], keys[1], key=keys[2], value=mode_value)
        if mode != ACMode.AIRCLEAN.name:
            await self._set_mode_airclean_value(False)

    async def set_fan_speed(self, speed):
        """Set fan speed or special wind mode discovered from the model JSON."""
        if speed not in self.fan_speeds:
            raise ValueError(f"Invalid fan speed: {speed}")
        if speed == LONGPOWER_LABEL and self._longpower_wind_strength_value is not None:
            await self._set_longpower_mode(True)
            return
        if speed in self._wind_mode_map:
            await self.set_wind_mode(speed)
            return
        if self._wind_mode_map and self._status.wind_mode != WIND_MODE_OFF:
            await self.set_wind_mode(WIND_MODE_OFF)
        speed_value = self._fan_speed_map[speed]
        await self._set_enum_value(
            self._wind_strength_key, speed_value, self._wind_strength_control_key
        )

    async def set_wind_mode(self, mode):
        """Set special wind mode discovered from ThinQ model data."""
        if mode not in self.wind_modes:
            raise ValueError(f"Invalid wind mode: {mode}")
        current_mode = self._status.wind_mode
        if mode == current_mode:
            return
        if current_mode != WIND_MODE_OFF:
            current_key = self._wind_mode_map.get(current_mode)
            if current_key is not None:
                await self._set_enum_state_basic(current_key, MODE_OFF)
        if mode == WIND_MODE_OFF:
            return
        state_key = self._wind_mode_map[mode]
        await self._set_enum_state_basic(state_key, MODE_ON)

    async def _set_longpower_mode(self, status: bool):
        """Set Ice Long Power using the ThinQ Web control value."""
        if status:
            speed_value = self._longpower_wind_strength_value
            if speed_value is None:
                raise ValueError("Long Power wind strength not supported")
            await self._set_enum_value(
                self._wind_strength_key, speed_value, self._wind_strength_control_key
            )

    def _current_dual_fan_speeds(self) -> tuple[str | None, str | None]:
        """Return current left/right fan labels parsed from current wind strength."""
        key = self._wind_strength_key
        if not (key and self._status):
            return (None, None)
        if (value := self._status.lookup_enum(key, True)) is None:
            return (None, None)
        if "|" not in value:
            label = self._fan_label_from_enum(value)
            return (label, label)
        left_raw, right_raw = value.split("|", 1)
        return (self._fan_label_from_enum(left_raw), self._fan_label_from_enum(right_raw))

    async def set_dual_fan_speed(self, side: str, speed: str):
        """Set left or right fan speed while preserving the other side."""
        if speed not in self.dual_fan_speed_options:
            raise ValueError(f"Invalid dual fan speed: {speed}")
        left, right = self._current_dual_fan_speeds()
        left = left or speed
        right = right or speed
        if side == "left":
            left = speed
        elif side == "right":
            right = speed
        else:
            raise ValueError(f"Invalid fan side: {side}")
        if (speed_value := self._dual_fan_speed_map.get((left, right))) is None:
            raise ValueError(f"Unsupported dual fan speed combination: {left}/{right}")
        await self._set_enum_value(
            self._wind_strength_key, speed_value, self._wind_strength_control_key
        )

    async def set_smartcare(self, status: bool):
        """Set SmartCare on or off."""
        if not self.is_smartcare_supported:
            raise ValueError("SmartCare not supported")
        if status and not self.is_smartcare_available:
            raise ValueError("SmartCare not available in current AC mode")
        key = self._resolve_key(STATE_SMARTCARE)
        value = self.model_info.enum_value(key, MODE_ON if status else MODE_OFF)
        if value is None:
            raise ValueError(f"Unsupported enum value for {key}: {status}")
        await self.set("basicCtrl", "Set", key=key, value=value)

    async def set_horizontal_swing_mode(self, mode):
        """Set the horizontal swing to a value from the `ACHSwingMode` enum.""" 
        if mode not in self.horizontal_swing_modes:
            raise ValueError(f"Invalid horizontal swing mode: {mode}")
        keys = self._get_cmd_keys(CMD_STATE_WDIR_HSWING)
        swing_mode = self.model_info.enum_value(keys[2], ACHSwingMode[mode].value)
        await self.set(keys[0], keys[1], key=keys[2], value=swing_mode)

    async def set_vertical_swing_mode(self, mode):
        """Set the vertical swing to a value from the `ACVSwingMode` enum."""
        if mode not in self.vertical_swing_modes:
            raise ValueError(f"Invalid vertical swing mode: {mode}")
        keys = self._get_cmd_keys(CMD_STATE_WDIR_VSWING)
        swing_mode = self.model_info.enum_value(keys[2], ACVSwingMode[mode].value)
        await self.set(keys[0], keys[1], key=keys[2], value=swing_mode)

    async def set_target_temp(self, temp):
        """Set the device's target temperature in Celsius degrees."""
        range_info = self._temperature_range
        conv_temp = self._f2c(temp)
        if range_info and not (range_info[0] <= conv_temp <= range_info[1]):
            raise ValueError(f"Target temperature out of range: {temp}")
        keys = self._get_cmd_keys(CMD_STATE_TARGET_TEMP)
        await self.set(keys[0], keys[1], key=keys[2], value=conv_temp)

    async def set_mode_airclean(self, status: bool):
        """Set the Airclean mode on or off."""
        if not self.is_mode_airclean_supported:
            raise ValueError("Airclean mode not supported")
        await self._set_mode_airclean_value(status)

    async def _set_mode_airclean_value(self, status: bool):
        """Set Airclean flag when the raw model state exists."""
        keys = self._get_cmd_keys(CMD_STATE_MODE_AIRCLEAN)
        mode_key = MODE_AIRCLEAN_ON if status else MODE_AIRCLEAN_OFF
        mode = self.model_info.enum_value(keys[2], mode_key)
        await self.set(keys[0], keys[1], key=keys[2], value=mode)

    async def set_powersave(self, status: bool):
        """Set the Powersave or off."""
        if not self.is_powersave_supported:
            raise ValueError("Powersave not supported")
        if status and not self.is_airclean_incompatible_mode_available:
            raise ValueError("Powersave not available in Airclean mode")

        keys = self._get_cmd_keys(CMD_STATE_POWERSAVE)
        mode_key = MODE_ON if status else MODE_OFF
        mode = self.model_info.enum_value(keys[2], mode_key)
        await self.set(keys[0], keys[1], key=keys[2], value=mode)

    async def set_autodry(self, status: bool):
        """Set the Autodry or off."""
        if not self.is_autodry_supported:
            raise ValueError("Autodry not supported")

        keys = self._get_cmd_keys(CMD_STATE_AUTODRY)
        mode_key = MODE_ON if status else MODE_OFF
        mode = self.model_info.enum_value(keys[2], mode_key)
        await self.set(keys[0], keys[1], key=keys[2], value=mode)

    async def set_mode_jet(self, status: bool):
        """Set the Jet mode on or off."""
        if self.supported_mode_jet == JetModeSupport.NONE:
            raise ValueError("Jet mode not supported")
        if not self.is_mode_jet_available:
            raise ValueError("Invalid device status for jet mode")

        if status:
            if self._status.operation_mode == ACMode.HEAT.name:
                jet_key = JetMode.HEAT
            else:
                jet_key = JetMode.COOL
        else:
            jet_key = JetMode.OFF
        keys = self._get_cmd_keys(CMD_STATE_MODE_JET)
        jet = self.model_info.enum_value(keys[2], jet_key.value)
        await self.set(keys[0], keys[1], key=keys[2], value=jet)

    async def set_lighting_display(self, status: bool):
        """Set the lighting display on or off."""
        keys = self._get_cmd_keys(CMD_STATE_LIGHTING_DISPLAY)
        lighting = LIGHTING_DISPLAY_ON if status else LIGHTING_DISPLAY_OFF
        await self.set(keys[0], keys[1], key=keys[2], value=lighting)

    async def set_mode_awhp_silent(self, value: bool):
        """Set the AWHP silent mode on or off."""
        if not self.is_air_to_water:
            raise ValueError("AWHP silent mode not supported")
        mode = MODE_ON if value else MODE_OFF
        keys = self._get_cmd_keys(CMD_STATE_MODE_AWHP_SILENT)
        if (silent_mode := self.model_info.enum_value(keys[2], mode)) is None:
            raise ValueError(f"Invalid AWHP silent mode: {mode}")
        await self.set(keys[0], keys[1], key=keys[2], value=silent_mode)

    async def hot_water_mode(self, value: bool):
        """Set the device hot water mode on or off."""
        if not self.is_water_heater_supported:
            raise ValueError("Hot water mode not supported")
        mode = MODE_ON if value else MODE_OFF
        keys = self._get_cmd_keys(CMD_STATE_HOT_WATER_MODE)
        if (hot_water_mode := self.model_info.enum_value(keys[2], mode)) is None:
            raise ValueError(f"Invalid hot water mode: {mode}")
        await self.set(keys[0], keys[1], key=keys[2], value=hot_water_mode)

    async def set_hot_water_target_temp(self, temp):
        """Set the device hot water target temperature in Celsius degrees."""
        if not self.is_water_heater_supported:
            raise ValueError("Hot water mode not supported")
        range_info = self._hot_water_temperature_range
        conv_temp = self._f2c(temp)
        if range_info and not (range_info[0] <= conv_temp <= range_info[1]):
            raise ValueError(f"Target temperature out of range: {temp}")
        keys = self._get_cmd_keys(CMD_STATE_HOT_WATER_TARGET_TEMP)
        await self.set(keys[0], keys[1], key=keys[2], value=conv_temp)

    async def get_power(self):
        """Get the instant power usage in watts of the whole unit."""
        if not self._current_power_supported:
            return None
        try:
            value = await self._get_config(STATE_POWER_V1)
            return value[STATE_POWER_V1]
        except (ValueError, InvalidRequestError) as exc:
            # Device does not support whole unit instant power usage
            _LOGGER.debug("Error calling get_power methods: %s", exc)
            self._current_power_supported = False
            return None

    @staticmethod
    def _energy_kwh(value) -> float:
        """Convert ThinQ energy values from Wh to kWh."""
        try:
            if value in (None, "NO_DATA"):
                return 0
            return round(int(float(value)) / 1000, 2)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _energy_wh(value) -> int:
        """Convert ThinQ energy values to Wh."""
        try:
            if value in (None, "NO_DATA"):
                return 0
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    async def get_energy_usage(self):
        """Get daily and monthly energy usage in kWh from ThinQ2 energy history."""
        if self._should_poll or not self._energy_usage_supported:
            return None

        now = datetime.now()

        async def _get_month_history(year: int, month: int):
            start_date = datetime(year, month, 1).strftime("%Y-%m-%d")
            end_date = datetime(
                year, month, calendar.monthrange(year, month)[1]
            ).strftime("%Y-%m-%d")
            path = (
                f"service/aircon/{self.device_info.device_id}/energy-history"
                f"?period=day&startDate={start_date}&endDate={end_date}"
                "&saveEnergyYn=N"
            )
            return await self._client.session.get2(path)

        try:
            history = await _get_month_history(now.year, now.month)
        except (ValueError, APIError) as exc:
            _LOGGER.debug("Error calling get_energy_usage method: %s", exc)
            return None
        if not isinstance(history, list):
            _LOGGER.debug("Unexpected get_energy_usage response: %s", history)
            self._energy_usage_supported = False
            return None

        today_key = now.strftime("%Y-%m-%d")
        yesterday_key = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        today = None
        yesterday = None
        month_wh = 0
        for item in history:
            if not isinstance(item, dict):
                continue
            used_date = str(item.get("usedDate", ""))[:10]
            energy_wh = self._energy_wh(item.get("energyData"))
            energy = round(energy_wh / 1000, 2)
            month_wh += energy_wh
            if used_date == today_key:
                today = energy
            elif used_date == yesterday_key:
                yesterday = energy

        if yesterday is None and now.day == 1:
            prev_month = now.month - 1 or 12
            prev_year = now.year - 1 if now.month == 1 else now.year
            try:
                prev_history = await _get_month_history(prev_year, prev_month)
            except (ValueError, APIError) as exc:
                _LOGGER.debug("Error calling previous get_energy_usage method: %s", exc)
            else:
                if isinstance(prev_history, list):
                    for item in prev_history:
                        if not isinstance(item, dict):
                            continue
                        if str(item.get("usedDate", ""))[:10] == yesterday_key:
                            yesterday = self._energy_kwh(item.get("energyData"))
                            break

        return {
            AirConditionerFeatures.ENERGY_TODAY: today,
            AirConditionerFeatures.ENERGY_YESTERDAY: yesterday,
            AirConditionerFeatures.ENERGY_MONTH: round(month_wh / 1000, 2),
        }

    async def _update_energy_usage(self):
        """Update energy usage values on a slower polling interval."""
        if not self._energy_usage_supported:
            return
        if not self._client.monitoring_active:
            return
        now = datetime.now()
        first_energy_poll = self._last_energy_usage_poll is None
        if self._last_energy_usage_poll is not None:
            diff = (now - self._last_energy_usage_poll).total_seconds()
            if diff < ENERGY_USAGE_POLL_INTERVAL:
                return
        if first_energy_poll:
            self._client.refresh_client_id()
        self._last_energy_usage_poll = now
        if energy_usage := await self.get_energy_usage():
            self._energy_usage.update(energy_usage)

    async def get_filter_state(self):
        """Get information about the filter."""
        if not self._filter_status_supported:
            return None
        try:
            return await self._get_config(STATE_FILTER_V1)
        except (ValueError, InvalidRequestError) as exc:
            # Device does not support filter status
            _LOGGER.debug("Error calling get_filter_state methods: %s", exc)
            self._filter_status_supported = False
            return None

    async def get_filter_state_v2(self):
        """Get information about the filter."""
        if not self._filter_status_supported:
            return None
        try:
            return await self._get_config_v2(CTRL_FILTER_V2, "Get")
        except (ValueError, InvalidRequestError) as exc:
            # Device does not support filter status
            _LOGGER.debug("Error calling get_filter_state_v2 methods: %s", exc)
            self._filter_status_supported = False
            return None

    @cached_property
    def sleep_time_range(self) -> list[int]:
        """Return valid range for sleep time."""
        key = self._get_state_key(STATE_RESERVATION_SLEEP_TIME)
        if (range_val := self.model_info.value(key, TYPE_RANGE)) is None:
            return [0, 420]
        return [range_val.min, range_val.max]

    @property
    def is_reservation_sleep_time_available(self) -> bool:
        """Return if reservation sleep time is available."""
        if (status := self._status) is None:
            return False
        if (
            status.device_features.get(AirConditionerFeatures.RESERVATION_SLEEP_TIME)
            is None
        ):
            return False
        return status.is_on and (
            status.operation_mode
            in [ACMode.ACO.name, ACMode.FAN.name, ACMode.COOL.name, ACMode.DRY.name]
        )

    async def set_reservation_sleep_time(self, value: int):
        """Set the device sleep time reservation in minutes."""
        if not self.is_reservation_sleep_time_available:
            raise ValueError("Reservation sleep time is not available")
        valid_range = self.sleep_time_range
        if not (valid_range[0] <= value <= valid_range[1]):
            raise ValueError(
                f"Invalid sleep time value. Valid range: {valid_range[0]} - {valid_range[1]}"
            )
        keys = self._get_cmd_keys(CMD_RESERVATION_SLEEP_TIME)
        await self.set(keys[0], keys[1], key=keys[2], value=str(value))

    async def set(
        self, ctrl_key, command, *, key=None, value=None, data=None, ctrl_path=None
    ):
        """Set a device control and serialize AC command bursts."""
        async with self._control_lock:
            await super().set(
                ctrl_key, command, key=key, value=value, data=data, ctrl_path=ctrl_path
            )
            if self._status:
                self._status.update_status(key, value)
            await asyncio.sleep(AC_CONTROL_COMMAND_DELAY)

    def reset_status(self):
        """Reset the device's status"""
        self._status = AirConditionerStatus(self)
        return self._status

    async def _pre_update_v2(self):
        """Call additional methods before data update for v2 API."""
        return

    async def _get_device_info(self):
        """
        Call additional method to get device information for API v1.
        Called by 'device_poll' method using a lower poll rate.
        """
        # this commands is to get power usage and filter status on V1 device
        if not self.is_air_to_water:
            self._current_power = await self.get_power()
            if filter_status := await self.get_filter_state():
                self._filter_status = {
                    k: filter_status.get(v, 0) for k, v in FILTER_STATUS_MAP.items()
                }

    async def _get_device_info_v2(self):
        """
        Call additional method to get device information for V2 API.
        Override in specific device to call requested methods.
        """
        # this commands is to get filter status on V2 device
        if not self.is_air_to_water:
            self._filter_status = await self.get_filter_state_v2()
            await self._update_energy_usage()

    async def poll(self) -> AirConditionerStatus | None:
        """Poll the device's current state."""
        res = await self._device_poll(
            additional_poll_interval_v1=ADD_FEAT_POLL_INTERVAL,
            additional_poll_interval_v2=ADD_FEAT_POLL_INTERVAL,
        )
        if not res:
            return None

        # update power for ACv1
        if self._should_poll and not self.is_air_to_water:
            if self._current_power is not None:
                res[STATE_POWER_V1] = self._current_power

        self._status = AirConditionerStatus(self, res)
        if not self._should_poll:
            await self._update_energy_usage()
        # adjust temperature step
        if self._temperature_step == TEMP_STEP_WHOLE:
            self._adjust_temperature_step(self._status.target_temp)
        # update filter status
        if self._filter_status:
            if not self._status.update_filter_status(self._filter_status):
                self._filter_status = None
                self._filter_status_supported = False

        # manage duct devices, does nothing if not ducted
        try:
            await self.update_duct_zones()
        except Exception as ex:  # pylint: disable=broad-except
            _LOGGER.exception("Duct zone control failed", exc_info=ex)

        return self._status


class AirConditionerStatus(DeviceStatus):
    """Higher-level information about a AC's current status."""

    _device: AirConditionerDevice

    def __init__(self, device: AirConditionerDevice, data: dict | None = None):
        """Initialize device status."""
        super().__init__(device, data)
        self._operation = None
        self._airmon_on = None
        self._filter_use_time_inverted = True
        self._current_temp = None

    def _str_to_temp(self, str_temp):
        """Convert a string to either an `int` or a `float` temperature."""
        temp = self._str_to_num(str_temp)
        if not temp:  # value 0 return None!!!
            return None
        return self._device.conv_temp_unit(temp)

    def _get_operation(self):
        """Get current operation."""
        if self._operation is None:
            key = self._get_state_key(STATE_OPERATION)
            operation = self.lookup_enum(key, True)
            if not operation:
                return None
            self._operation = operation
        try:
            return ACOp(self._operation)
        except ValueError:
            return None

    def update_filter_status(self, values: dict) -> bool:
        """Update device filter status."""
        self._filter_use_time_inverted = False

        if not self.is_info_v2:
            self._data.update(values)
            return True

        # ACv2 could return filter value in the payload
        # if max_time key is in the payload <> 0, we don't update
        updated = False
        for filters in FILTER_TYPES:
            max_key = self._get_state_key(filters[2])  # this is the max_time key
            cur_val = self.to_int_or_none(self._data.get(max_key, 0))
            if cur_val:
                continue
            for index in range(1, 3):
                upd_key = self._get_state_key(filters[index])
                if upd_key in values:
                    self._data[upd_key] = values[upd_key]
                    updated = True

        # for models that return use_time directly in the payload,
        # the value actually represent remaining time
        self._filter_use_time_inverted = not updated

        return updated

    def update_status(self, key, value):
        """Update device status."""
        if not super().update_status(key, value):
            return False
        if key in STATE_OPERATION:
            self._operation = None
        return True

    @property
    def is_on(self):
        """Return if device is on."""
        if not (operation := self._get_operation()):
            return False
        return operation != ACOp.OFF

    @property
    def operation(self):
        """Return current device operation."""
        if not (operation := self._get_operation()):
            return None
        return operation.name

    @property
    def operation_mode(self):
        """Return current device operation mode."""
        key = self._get_state_key(STATE_OPERATION_MODE)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        try:
            return ACMode(value).name
        except ValueError:
            return None

    @property
    def is_hot_water_on(self):
        """Return if hot water is on."""
        key = self._get_state_key(STATE_HOT_WATER_MODE)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        return value == MODE_ON

    @property
    def fan_speed(self):
        """Return current fan speed."""
        wind_mode = self.wind_mode
        if wind_mode != WIND_MODE_OFF:
            return wind_mode
        key = self._device._wind_strength_key
        if not key:
            return None
        if (value := self.lookup_enum(key, True)) is None:
            return None
        return self._device._fan_label_from_enum(value)

    @property
    def left_fan_speed(self):
        """Return current left fan speed."""
        left, _ = self._device._current_dual_fan_speeds()
        return left

    @property
    def right_fan_speed(self):
        """Return current right fan speed."""
        _, right = self._device._current_dual_fan_speeds()
        return right

    @property
    def wind_mode(self):
        """Return current special wind mode."""
        key = self._device._wind_strength_key
        if key and (value := self.lookup_enum(key, True)) and "LONGPOWER" in value:
            return LONGPOWER_LABEL
        if self.lookup_enum("airState.wMode.flowLongPower", True) == MODE_ON:
            return LONGPOWER_LABEL
        for label, key in self._device._wind_mode_map.items():
            if self.lookup_enum(key, True) == MODE_ON:
                return label
        return WIND_MODE_OFF

    @property
    def horizontal_swing_mode(self):
        """Return current horizontal swing mode."""
        key = self._get_state_key(STATE_WDIR_HSWING)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        try:
            return ACHSwingMode(value).name
        except ValueError:
            return None

    @property
    def is_horizontal_swing_on(self):
        """Return current horizontal swing mode."""
        key = self._get_state_key(STATE_WDIR_HSWING)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        return value == MODE_ON

    @property
    def vertical_swing_mode(self):
        """Return current vertical step mode."""
        key = self._get_state_key(STATE_WDIR_VSWING)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        try:
            return ACVSwingMode(value).name
        except ValueError:
            return None

    @property
    def is_vertical_swing_on(self):
        """Return current vertical swing mode."""
        key = self._get_state_key(STATE_WDIR_VSWING)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        return value == MODE_ON

    @property
    def room_temp(self):
        """Return room temperature."""
        key = self._get_state_key(STATE_CURRENT_TEMP)
        value = self._str_to_temp(self._data.get(key))
        return self._update_feature(AirConditionerFeatures.ROOM_TEMP, value, False)

    @property
    def current_temp(self):
        """Return current temperature."""
        if self._current_temp is None:
            curr_temp = None
            mode = self.awhp_temp_mode
            if mode and mode == AWHP_MODE_WATER:
                curr_temp = self.water_out_current_temp
            if curr_temp is None:
                curr_temp = self.room_temp
            self._current_temp = curr_temp
        return self._current_temp

    @property
    def target_temp(self):
        """Return target temperature."""
        key = self._get_state_key(STATE_TARGET_TEMP)
        return self._str_to_temp(self._data.get(key))

    @property
    def duct_zones_state(self):
        """Return current state for duct zones."""
        key = self._get_state_key(STATE_DUCT_ZONE)
        return self.to_int_or_none(self._data.get(key))

    @property
    def duct_zones_type(self):
        """Return the type of configured duct zones (for V1 devices)."""
        if self.is_info_v2:
            return None
        return self.to_int_or_none(self._data.get(DUCT_ZONE_V1_TYPE))

    @property
    def energy_current(self):
        """Return current energy usage."""
        key = self._get_state_key(STATE_POWER)
        if (value := self.to_int_or_none(self._data.get(key))) is None:
            return None
        if not self.is_on:
            # decrease power when power off
            value = 5
        return self._update_feature(AirConditionerFeatures.ENERGY_CURRENT, value, False)

    @property
    def energy_today(self):
        """Return today's energy usage."""
        return self._update_feature(
            AirConditionerFeatures.ENERGY_TODAY,
            self._device._energy_usage.get(AirConditionerFeatures.ENERGY_TODAY),
            False,
            allow_none=True,
        )

    @property
    def energy_yesterday(self):
        """Return yesterday's energy usage."""
        return self._update_feature(
            AirConditionerFeatures.ENERGY_YESTERDAY,
            self._device._energy_usage.get(AirConditionerFeatures.ENERGY_YESTERDAY),
            False,
            allow_none=True,
        )

    @property
    def energy_month(self):
        """Return this month's energy usage."""
        return self._update_feature(
            AirConditionerFeatures.ENERGY_MONTH,
            self._device._energy_usage.get(AirConditionerFeatures.ENERGY_MONTH),
            False,
            allow_none=True,
        )

    @property
    def humidity(self):
        """Return current humidity."""
        key = self._get_state_key(STATE_HUMIDITY)
        if (value := self.to_int_or_none(self.lookup_range(key))) is None:
            return None
        # some V1 and V2 devices return humidity with value = 0
        # when humidity sensor is not available
        if value == 0:
            return None
        if value >= 100:
            value = value / 10
        return self._update_feature(AirConditionerFeatures.HUMIDITY, value, False)

    @property
    def mode_airclean(self):
        """Return AirClean Mode status."""
        if not self._device.is_mode_airclean_supported:
            return None
        key = self._get_state_key(STATE_MODE_AIRCLEAN)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        status = value == MODE_AIRCLEAN_ON
        return self._update_feature(AirConditionerFeatures.MODE_AIRCLEAN, status, False)

    @property
    def powersave(self):
        """Return Powersave status."""
        if not self._device.is_powersave_supported:
            return None
        key = self._get_state_key(STATE_POWERSAVE)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        status = value == MODE_ON
        return self._update_feature(AirConditionerFeatures.POWERSAVE, status, False)

    @property
    def autodry(self):
        """Return Autodry status."""
        if not self._device.is_autodry_supported:
            return None
        key = self._get_state_key(STATE_AUTODRY)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        status = value == MODE_ON
        return self._update_feature(AirConditionerFeatures.AUTODRY, status, False)

    @property
    def smartcare(self):
        """Return SmartCare status."""
        if not self._device.is_smartcare_supported:
            return None
        key = self._get_state_key(STATE_SMARTCARE)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        status = value == MODE_ON
        return self._update_feature(AirConditionerFeatures.SMARTCARE, status, False)

    @property
    def mode_jet(self):
        """Return Jet Mode status."""
        if self._device.supported_mode_jet == JetModeSupport.NONE:
            return None
        key = self._get_state_key(STATE_MODE_JET)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        try:
            status = JetMode(value) != JetMode.OFF
        except ValueError:
            status = False
        return self._update_feature(AirConditionerFeatures.MODE_JET, status, False)

    @property
    def lighting_display(self):
        """Return display lighting status."""
        key = self._get_state_key(STATE_LIGHTING_DISPLAY)
        if (value := self.to_int_or_none(self._data.get(key))) is None:
            return None
        return self._update_feature(
            AirConditionerFeatures.LIGHTING_DISPLAY,
            str(value) == LIGHTING_DISPLAY_ON,
            False,
        )

    @property
    def filters_life(self):
        """Return percentage status for all filters."""
        result = {}

        for filter_def in FILTER_TYPES:
            status = self._get_filter_life(
                filter_def[1],
                filter_def[2],
                use_time_inverted=self._filter_use_time_inverted,
            )
            if status is not None:
                for index, feat in enumerate(filter_def[0]):
                    if index >= len(status):
                        break
                    self._update_feature(feat, status[index], False)
                    result[feat] = status[index]

        return result

    @property
    def airmon_on(self):
        """Return if AirMon sensor is on."""
        if self._airmon_on is None:
            self._airmon_on = False
            key = self._get_state_key(STATE_AIRSENSORMON)
            if (value := self.lookup_enum(key, True)) is not None:
                self._airmon_on = value == MODE_ON
        return self._airmon_on

    @property
    def pm1(self):
        """Return Air PM1 value."""
        if not self._device.is_pm1_supported:
            return None
        key = self._get_state_key(STATE_PM1)
        if (value := self.lookup_range(key)) is None:
            return None
        if not (self.is_on or self.airmon_on):
            value = None
        return self._update_feature(
            AirConditionerFeatures.PM1, value, False, allow_none=True
        )

    @property
    def pm10(self):
        """Return Air PM10 value."""
        if not self._device.is_pm10_supported:
            return None
        key = self._get_state_key(STATE_PM10)
        if (value := self.lookup_range(key)) is None:
            return None
        if not (self.is_on or self.airmon_on):
            value = None
        return self._update_feature(
            AirConditionerFeatures.PM10, value, False, allow_none=True
        )

    @property
    def pm25(self):
        """Return Air PM2.5 value."""
        if not self._device.is_pm25_supported:
            return None
        key = self._get_state_key(STATE_PM25)
        if (value := self.lookup_range(key)) is None:
            return None
        if not (self.is_on or self.airmon_on):
            value = None
        return self._update_feature(
            AirConditionerFeatures.PM25, value, False, allow_none=True
        )

    @property
    def awhp_temp_mode(self):
        """Return if AWHP is set in air or water mode."""
        if not self._device.is_air_to_water:
            return None
        key = self._get_state_key(STATE_AWHP_TEMP_MODE)
        if (value := self.lookup_enum(key, True)) is not None:
            if value == AWHP_MODE_AIR:
                return AWHP_MODE_AIR
        return AWHP_MODE_WATER

    @property
    def water_in_current_temp(self):
        """Return AWHP in water current temperature."""
        if not self._device.is_air_to_water:
            return None
        key = self._get_state_key(STATE_WATER_IN_TEMP)
        value = self._str_to_temp(self._data.get(key))
        return self._update_feature(AirConditionerFeatures.WATER_IN_TEMP, value, False)

    @property
    def water_out_current_temp(self):
        """Return AWHP out water current temperature."""
        if not self._device.is_air_to_water:
            return None
        key = self._get_state_key(STATE_WATER_OUT_TEMP)
        value = self._str_to_temp(self._data.get(key))
        return self._update_feature(AirConditionerFeatures.WATER_OUT_TEMP, value, False)

    @property
    def water_target_min_temp(self):
        """Return AWHP water target minimum allowed temperature."""
        if not self._device.is_air_to_water:
            return None
        key = self._get_state_key(STATE_WATER_MIN_TEMP)
        return self._str_to_temp(self._data.get(key))

    @property
    def water_target_max_temp(self):
        """Return AWHP water target maximun allowed temperature."""
        if not self._device.is_air_to_water:
            return None
        key = self._get_state_key(STATE_WATER_MAX_TEMP)
        return self._str_to_temp(self._data.get(key))

    @property
    def mode_awhp_silent(self):
        """Return AWHP silent mode status."""
        if not (self._device.is_air_to_water and self.is_info_v2):
            return None
        key = self._get_state_key(STATE_MODE_AWHP_SILENT)
        if (value := self.lookup_enum(key, True)) is None:
            return None
        status = value == MODE_ON
        return self._update_feature(
            AirConditionerFeatures.MODE_AWHP_SILENT, status, False
        )

    @property
    def hot_water_current_temp(self):
        """Return AWHP hot water current temperature."""
        if not self._device.is_water_heater_supported:
            return None
        key = self._get_state_key(STATE_HOT_WATER_TEMP)
        value = self._str_to_temp(self._data.get(key))
        return self._update_feature(AirConditionerFeatures.HOT_WATER_TEMP, value, False)

    @property
    def hot_water_target_temp(self):
        """Return AWHP hot water target temperature."""
        if not self._device.is_water_heater_supported:
            return None
        key = self._get_state_key(STATE_HOT_WATER_TARGET_TEMP)
        return self._str_to_temp(self._data.get(key))

    @property
    def hot_water_target_min_temp(self):
        """Return AWHP hot water target minimum allowed temperature."""
        if not self._device.is_water_heater_supported:
            return None
        key = self._get_state_key(STATE_HOT_WATER_MIN_TEMP)
        return self._str_to_temp(self._data.get(key))

    @property
    def hot_water_target_max_temp(self):
        """Return AWHP hot water target maximum allowed temperature."""
        if not self._device.is_water_heater_supported:
            return None
        key = self._get_state_key(STATE_HOT_WATER_MAX_TEMP)
        return self._str_to_temp(self._data.get(key))

    @property
    def reservation_sleep_time(self):
        """Return reservation sleep time in minutes."""
        key = self._get_state_key(STATE_RESERVATION_SLEEP_TIME)
        if (value := self.to_int_or_none(self.lookup_range(key))) is None:
            return None
        return self._update_feature(
            AirConditionerFeatures.RESERVATION_SLEEP_TIME, value, False
        )

    def _update_features(self):
        _ = [
            self.room_temp,
            self.energy_current,
            self.energy_today,
            self.energy_yesterday,
            self.energy_month,
            self.filters_life,
            self.humidity,
            self.pm10,
            self.pm25,
            self.pm1,
            self.mode_airclean,
            self.powersave,
            self.autodry,
            self.smartcare,
            self.mode_jet,
            self.lighting_display,
            self.water_in_current_temp,
            self.water_out_current_temp,
            self.mode_awhp_silent,
            self.hot_water_current_temp,
            self.reservation_sleep_time,
        ]
