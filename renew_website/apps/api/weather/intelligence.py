from dataclasses import asdict, dataclass


@dataclass
class WeatherIntelligence:
    solar_reliability_score: float
    expected_pv_factor: float
    battery_protection_needed: bool
    grid_dependency_risk: float
    confidence: float

    def to_dict(self):
        return asdict(self)


class WeatherScoringService:
    @staticmethod
    def calculate(weather_log) -> WeatherIntelligence:
        if not weather_log:
            return WeatherIntelligence(
                solar_reliability_score=0.5,
                expected_pv_factor=0.5,
                battery_protection_needed=False,
                grid_dependency_risk=0.5,
                confidence=0.0,
            )

        cloud = min(max(float(getattr(weather_log, 'cloud_cover', 0.0) or 0.0) / 100.0, 0.0), 1.0)
        irradiance = min(max(float(getattr(weather_log, 'irradiance_wm2', 0.0) or 0.0) / 1000.0, 0.0), 1.0)
        rain = float(getattr(weather_log, 'precipitation_mm', 0.0) or 0.0) > 0.1

        solar_score = max(0.0, min(((1 - cloud) * 0.6) + (irradiance * 0.4), 1.0))
        risk = max(cloud, 0.85 if rain else 0.0)

        return WeatherIntelligence(
            solar_reliability_score=round(solar_score, 3),
            expected_pv_factor=round(solar_score, 3),
            battery_protection_needed=rain or cloud > 0.7,
            grid_dependency_risk=round(risk, 3),
            confidence=0.8,
        )