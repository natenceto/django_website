from renew_website.apps.algorithm.work_modes import SystemWorkMode


ALGORITHM_TO_DEYE_MODE = {
    SystemWorkMode.DYNAMIC_ECO_SOLAR_ONLY: "zero_export_to_load",
    SystemWorkMode.DYNAMIC_MAX_RENEWABLE: "selling_first",
    SystemWorkMode.FAST_CHARGE_GRID: "battery_first",
    SystemWorkMode.PROTECT_BATTERY: "battery_first",
    SystemWorkMode.CHARGE_BATTERY: "battery_first",
    SystemWorkMode.EMERGENCY_BACKUP: "zero_export_to_load",
}


DEYE_MODE_TO_REGISTER = {
    "zero_export_to_load": 0,
    "zero_export_to_ct": 1,
    "selling_first": 2,
    "battery_first": 3,
}


def map_algorithm_mode_to_deye_mode(mode: str) -> str | None:
    """Map the platform algorithm mode to the closest Deye inverter work mode."""
    if mode in DEYE_MODE_TO_REGISTER:
        return mode
    return ALGORITHM_TO_DEYE_MODE.get(mode)


def get_modbus_commands_for_mode(mode: str) -> dict:
    """Return the Modbus register writes needed for an algorithm or Deye mode."""
    target_mode = map_algorithm_mode_to_deye_mode(mode)
    if not target_mode:
        return {}

    commands = {
        131: DEYE_MODE_TO_REGISTER[target_mode],
    }

    if target_mode == "battery_first":
        commands.update({
            231: 1,
            232: 1 if mode == SystemWorkMode.PROTECT_BATTERY else 0,
        })
    elif target_mode in {"selling_first", "zero_export_to_load", "zero_export_to_ct"}:
        commands.update({
            231: 1,
            232: 0,
        })

    return commands
