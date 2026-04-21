from dataclasses import dataclass
from typing import Optional

@dataclass
class EVStationComponent:
    """
    Компонент, представящ зарядната станция и автомобила свързан към нея.
    """
    station_id: str               # Идентификатор на станцията
    is_plugged: bool              # Индикатор дали кабелът е включен в колата (CP state)
    current_draw_kw: float        # Текуща мощност на зареждане (0, ако не зарежда)
    
    # Някои автомобили (через ISO 15118 или Modbus) връщат статуса на батерията си.
    ev_battery_soc: Optional[float] = None 
    
    def is_actively_charging(self) -> bool:
        """Проверява дали в момента станцията отдава енергия към колата."""
        return self.is_plugged and self.current_draw_kw > 0.5 

    def needs_charge(self) -> bool:
        """Дали автомобилът всъщност има нужда от енергия (не е зареден до 100%)."""
        if not self.is_plugged:
            return False
            
        if self.ev_battery_soc is not None:
            return self.ev_battery_soc < 100.0
            
        # Ако нямаме данни за SOC от автомобила, съдим по това дали приема ток > 0.
        return True

    def ev_is_nearly_full(self) -> bool:
        """Проверява дали батерията на автомобила е почти пълна (над 80%).
        Полезно за Load Balancing: почти пълните коли поемат по-малко ток."""
        if self.ev_battery_soc is not None:
            return self.ev_battery_soc >= 80.0
            
        return False
