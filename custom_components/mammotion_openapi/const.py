"""Constants for the official Mammotion API integration."""

from homeassistant.const import Platform

DOMAIN = "mammotion_openapi"
PLATFORMS = [
    Platform.LAWN_MOWER,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.BUTTON,
]
API_URL = "https://api-open.mammotion.com"
TOKEN_URL = "https://id.mammotion.com/oauth2/token"
CONF_POLL_INTERVAL = "poll_interval"
CONF_ENABLE_PUSH = "enable_push"
DEFAULT_POLL_INTERVAL = 60
ACTIONS = ("CMD_START", "START", "PAUSE", "RESUME", "STOP", "RETURN", "CANCEL_RETURN")
PROPERTIES = (
    "DEV_ST",
    "CHG_ST",
    "SELF_CHK",
    "SENS_ST",
    "LOC_SRC",
    "BAT_PCT",
    "BMS_INFO",
    "COORD",
    "NET_ST",
    "WK_PRG",
    "KNF_HGT",
    "KNF_ST",
    "WK_TRK",
    "DEV_VER",
    "BASE_STN",
    "OTA_PRG",
    "MAP_UPLD",
    "LOG_SYNC",
    "DEV_INF",
    "TSK_CHG",
    "ENR_BIND",
    "ENR_UNBIND",
    "ERR_CODE",
    "MSG_NOTICE",
)
