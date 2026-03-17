try:
    from deye_controller import HoldingRegisters
    print("HoldingRegisters attributes:")
    print([a for a in dir(HoldingRegisters) if not a.startswith('__')])
except ImportError:
    print("Could not import deye_controller")
except Exception as e:
    print(f"Error: {e}")
