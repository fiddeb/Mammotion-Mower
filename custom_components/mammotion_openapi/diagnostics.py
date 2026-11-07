"""Diagnostics containing only non-identifying status fields."""


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    # Use an allowlist: API payloads may grow new identifying fields over time.
    return {
        "options": dict(entry.options),
        "last_update_success": coordinator.last_update_success,
        "push_status": coordinator.push_status,
        "mowers": [
            {
                "model": mower.info.get("model"),
                "version": mower.info.get("version"),
                "status": mower.info.get("status"),
                "online": mower.online,
                "reachable": mower.reachable,
                "battery_level": mower.info.get("batteryLevel"),
                "plans_available": mower.plans_available,
                "plan_count": len(mower.plans),
            }
            for mower in coordinator.data.values()
        ],
    }
