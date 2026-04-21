from dataclasses import dataclass

@dataclass
class WeatherConditionComponent:
    """
    Компонент, представящ метеорологичната обстановка (текуща и бъдеща).
    """
    cloud_cover_percentage: float  # Процент облачност
    is_raining: bool               # Дъжд
    forecast_solar_irradiation: float # Предвиждане за слънчев добив (например W/m²)

    def is_favorable_for_solar(self) -> bool:
        """
        Проверява дали времето в момента или в близко бъдеще благоприятства
        силна слънчева генерация.
        """
        if self.is_raining or self.cloud_cover_percentage > 50.0:
            return False
            
        # Може да се добавят допълнителни проверки по час от деня и др.
        return True

    def expect_low_generation(self) -> bool:
        """
        Времето е изцяло лошо, очакваме предимно мрежова консумация.
        """
        return self.cloud_cover_percentage > 80.0 or self.is_raining
