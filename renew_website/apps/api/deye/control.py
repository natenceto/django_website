from renew_website.apps.algorithm.work_modes import SystemWorkMode

def get_modbus_commands_for_mode(mode: str) -> dict:
    """
    Deye TOU Registers (Based on correct 200+ offset):
    - 231: TOU Enable (0 = OFF, 1 = ON)
    - 232: Grid Charge Enable Mask (Bitmask for the 6 periods)
    - 256-261: Target SOC % for Period 1-6
    - 244-249: Power limit for Period 1-6 (W)
    """
    commands = {}

    if mode == SystemWorkMode.BATTERY_CHARGING or mode == SystemWorkMode.EV_GRID_CHARGE:
        # MACRO CHANGE: Night tariff started or manual force charge.
        commands = {
            231: 1,      # TOU Enable
            232: 1,      # Grid Charge Enable (Assuming Period 1 is active, 2^0 = 1)
            # We don't overwrite SOC (256) constantly, assume it's pre-configured to 100% on the screen
        }

    elif mode == SystemWorkMode.BATTERY_MAINTENANCE or mode == SystemWorkMode.EV_ECO_CHARGE:
        # MACRO CHANGE: Day time started, protect the battery from grid charging.
        commands = {
            231: 1,      # TOU Enable
            232: 0,      # Grid Charge Disable (Bitmask 0)
        }
        
    elif mode == SystemWorkMode.EMERGENCY_BACKUP:
        # Extreme case, maximize output, ignore tariffs
        pass

    return commands
