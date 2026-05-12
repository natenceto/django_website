from django.test import SimpleTestCase

from .conditions import EVSession, SystemState
from .engine import DecisionEngine
from .work_modes import SystemWorkMode


class DecisionEngineTests(SimpleTestCase):
	def test_weighted_allocation_prioritizes_urgent_low_soc_session(self):
		state = SystemState(
			battery_soc=72.0,
			is_grid_available=True,
			pv_production_kw=8.0,
			building_load_kw=1.0,
			active_ev_sessions=2,
			total_ev_demand_kw=22.0,
			cloud_cover_percent=10.0,
			is_raining=False,
			weather_condition='sunny',
			is_night_tariff=False,
			ev_sessions=[
				EVSession(
					session_id='ev-1',
					vehicle_soc=15.0,
					requested_power_kw=11.0,
					max_acceptance_kw=11.0,
					estimated_departure_hours=1.0,
				),
				EVSession(
					session_id='ev-2',
					vehicle_soc=72.0,
					requested_power_kw=11.0,
					max_acceptance_kw=11.0,
					estimated_departure_hours=10.0,
				),
			],
		)

		decision = DecisionEngine.evaluate(state)
		allocations = decision['allocation_plan']['session_allocations']

		self.assertEqual(decision['strategy'], SystemWorkMode.DYNAMIC_MAX_RENEWABLE)
		self.assertGreater(allocations[0]['allocated_power_kw'], allocations[1]['allocated_power_kw'])
		self.assertGreater(decision['allocation_plan']['battery_to_ev_kw'], 0)

	def test_constraints_pause_charging_before_strategy_labeling(self):
		state = SystemState(
			battery_soc=38.0,
			is_grid_available=True,
			pv_production_kw=2.0,
			building_load_kw=2.0,
			active_ev_sessions=1,
			total_ev_demand_kw=11.0,
			cloud_cover_percent=5.0,
			is_raining=False,
			weather_condition='clear',
			is_night_tariff=True,
		)

		decision = DecisionEngine.evaluate(state)

		self.assertEqual(decision['strategy'], SystemWorkMode.PROTECT_BATTERY)
		self.assertEqual(decision['allocation_plan']['ev_charge_limit_kw'], 0.0)
		self.assertIn('Charging Paused', decision['constraint_state']['labels'])

	def test_grid_assist_is_derived_from_constraints_not_mode(self):
		state = SystemState(
			battery_soc=80.0,
			is_grid_available=True,
			pv_production_kw=1.0,
			building_load_kw=2.0,
			active_ev_sessions=1,
			total_ev_demand_kw=11.0,
			cloud_cover_percent=0.0,
			is_raining=False,
			weather_condition='clear',
			is_night_tariff=False,
			site_max_import_kw=20.0,
			grid_policy_preference='assist',
			ev_sessions=[
				EVSession(
					session_id='ev-1',
					vehicle_soc=20.0,
					requested_power_kw=11.0,
					max_acceptance_kw=11.0,
					estimated_departure_hours=2.0,
				)
			],
		)

		decision = DecisionEngine.evaluate(state)

		self.assertEqual(decision['strategy'], SystemWorkMode.FAST_CHARGE_GRID)
		self.assertTrue(decision['constraint_state']['grid_assist_allowed'])
		self.assertGreater(decision['allocation_plan']['grid_to_ev_kw'], 0.0)

	def test_weather_score_drives_battery_allowance(self):
		clear_state = SystemState(
			battery_soc=80.0,
			is_grid_available=True,
			pv_production_kw=1.0,
			building_load_kw=0.5,
			active_ev_sessions=1,
			total_ev_demand_kw=11.0,
			cloud_cover_percent=20.0,
			is_raining=False,
			weather_condition='clear',
			is_night_tariff=False,
			weather_solar_score=0.9,
			weather_risk_score=0.1,
			weather_confidence=0.8,
			ev_sessions=[
				EVSession(
					session_id='ev-1',
					vehicle_soc=30.0,
					requested_power_kw=11.0,
					max_acceptance_kw=11.0,
				)
			],
		)
		risky_state = SystemState(
			battery_soc=80.0,
			is_grid_available=True,
			pv_production_kw=1.0,
			building_load_kw=0.5,
			active_ev_sessions=1,
			total_ev_demand_kw=11.0,
			cloud_cover_percent=80.0,
			is_raining=True,
			weather_condition='rain',
			is_night_tariff=False,
			weather_solar_score=0.2,
			weather_risk_score=0.9,
			weather_confidence=0.8,
			ev_sessions=[
				EVSession(
					session_id='ev-1',
					vehicle_soc=30.0,
					requested_power_kw=11.0,
					max_acceptance_kw=11.0,
				)
			],
		)

		clear_decision = DecisionEngine.evaluate(clear_state)
		risky_decision = DecisionEngine.evaluate(risky_state)

		self.assertGreater(
			clear_decision['allocation_plan']['battery_to_ev_kw'],
			risky_decision['allocation_plan']['battery_to_ev_kw'],
		)
