from dataclasses import dataclass

@dataclass
class DeyeBatteryComponent:
    """
    Компонент, представящ състоянието на батерията (свързана към инвертора).
    """
    soc_percentage: float      # State of Charge (0-100%)
    temperature: float         # Температура на батерията
    power_kw: float            # Мощност на батерията (+ зареждане, - разреждане, 0 в покой)

    def is_charging(self) -> bool:
        """Проверява дали батерията в момента се зарежда (положителна мощност)."""
        return self.power_kw > 0.05  # Даваме малък толеранс (напр. 50 вата)

    def is_discharging(self) -> bool:
        """Проверява дали батерията се разрежда (отрицателна мощност)."""
        return self.power_kw < -0.05

    def is_critical(self) -> bool:
        """Проверява дали батерията е критично изтощена (напр. под 35%)."""
        return self.soc_percentage < 35.0

    def needs_charging(self) -> bool:
        """Проверява дали батерията има нужда от заряд (под 100%)."""
        return self.soc_percentage < 100.0

    def has_sufficient_charge_for_ev(self) -> bool:
        """Има ли достатъчно заряд, за да отдава към зарядни станции (напр. над 60%)."""
        return self.soc_percentage > 60.0


@dataclass
class DeyeInverterComponent:
    """
    Компонент, представящ състоянието на инвертора.
    """
    grid_voltage: float        # Напрежение от мрежата
    pv_production_kw: float    # Текущ добив от фотоволтаици
    building_load_kw: float    # Текуща консумация на сградата

    def is_grid_available(self) -> bool:
        """Налична ли е външната мрежа (над определен волтаж)."""
        return self.grid_voltage > 190.0

    def has_excess_solar(self) -> bool:
        """Проверява дали слънчевият добив е по-голям от консумацията на сградата."""
        return self.pv_production_kw > self.building_load_kw

    def get_excess_power_kw(self) -> float:
        """Връща количеството свободна мощност (ако има такава)."""
        excess = self.pv_production_kw - self.building_load_kw
        return excess if excess > 0 else 0.0
