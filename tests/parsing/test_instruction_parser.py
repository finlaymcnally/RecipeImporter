"""Tests for instruction metadata extraction."""

import pytest

from cookimport.parsing.instruction_parser import (
    InstructionMetadata,
    TimeItem,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    parse_instruction,
    parse_instructions,
)


class TestTimeExtraction:
    """Test time duration extraction from instruction text."""

    def test_simple_minutes(self):
        meta = parse_instruction("Cook for 30 minutes")
        assert meta.total_time_seconds == 1800
        assert len(meta.time_items) == 1
        assert meta.time_items[0].seconds == 1800
        assert "30 minutes" in meta.time_items[0].original_text

    def test_simple_hours(self):
        meta = parse_instruction("Bake for 2 hours")
        assert meta.total_time_seconds == 7200

    def test_simple_seconds(self):
        meta = parse_instruction("Microwave for 45 seconds")
        assert meta.total_time_seconds == 45

    def test_range_hours(self):
        """Range times should use midpoint."""
        meta = parse_instruction("Simmer for 1-2 hours")
        # Midpoint of 1-2 hours = 1.5 hours = 5400 seconds
        assert meta.total_time_seconds == 5400

    def test_range_with_to(self):
        meta = parse_instruction("Cook for 20 to 30 minutes")
        # Midpoint = 25 minutes = 1500 seconds
        assert meta.total_time_seconds == 1500

    def test_abbreviated_units(self):
        """Test abbreviated time units."""
        assert parse_instruction("Cook 10 mins").total_time_seconds == 600
        assert parse_instruction("Bake 1 hr").total_time_seconds == 3600
        assert parse_instruction("Wait 30 secs").total_time_seconds == 30

    def test_multiple_times(self):
        """Multiple time references should be summed."""
        meta = parse_instruction("Cook for 10 minutes, then simmer for 30 minutes")
        assert meta.total_time_seconds == 2400  # 10 + 30 = 40 minutes
        assert len(meta.time_items) == 2

    def test_approximate_time(self):
        meta = parse_instruction("Bake for about 45 minutes")
        assert meta.total_time_seconds == 2700

    def test_no_time(self):
        meta = parse_instruction("Stir until combined")
        assert meta.total_time_seconds is None
        assert len(meta.time_items) == 0


class TestTemperatureExtraction:
    """Test temperature extraction from instruction text."""

    def test_fahrenheit_simple(self):
        meta = parse_instruction("Bake at 400F")
        assert meta.temperature == 400.0
        assert meta.temperature_unit == "fahrenheit"

    def test_fahrenheit_with_degree(self):
        meta = parse_instruction("Preheat oven to 350°F")
        assert meta.temperature == 350.0
        assert meta.temperature_unit == "fahrenheit"

    def test_fahrenheit_degrees_word(self):
        meta = parse_instruction("Set oven to 375 degrees F")
        assert meta.temperature == 375.0
        assert meta.temperature_unit == "fahrenheit"

    def test_fahrenheit_full_word(self):
        meta = parse_instruction("Bake at 425 degrees fahrenheit")
        assert meta.temperature == 425.0
        assert meta.temperature_unit == "fahrenheit"

    def test_celsius_simple(self):
        meta = parse_instruction("Preheat oven to 180C")
        assert meta.temperature == 180.0
        assert meta.temperature_unit == "celsius"

    def test_celsius_with_degree(self):
        meta = parse_instruction("Bake at 200°C")
        assert meta.temperature == 200.0
        assert meta.temperature_unit == "celsius"

    def test_celsius_full_word(self):
        meta = parse_instruction("Roast at 220 degrees celsius")
        assert meta.temperature == 220.0
        assert meta.temperature_unit == "celsius"

    def test_no_temperature(self):
        meta = parse_instruction("Cook over medium heat")
        assert meta.temperature is None
        assert meta.temperature_unit is None

    def test_temperature_text_preserved(self):
        meta = parse_instruction("Bake at 400°F until golden")
        assert meta.temperature_text is not None
        assert "400" in meta.temperature_text


class TestCombinedExtraction:
    """Test extraction of both time and temperature."""

    def test_full_instruction(self):
        meta = parse_instruction("Bake at 350°F for 45 minutes")
        assert meta.temperature == 350.0
        assert meta.temperature_unit == "fahrenheit"
        assert meta.total_time_seconds == 2700

    def test_preheat_then_bake(self):
        meta = parse_instruction("Preheat oven to 400F. Bake for 30 minutes.")
        assert meta.temperature == 400.0
        assert meta.total_time_seconds == 1800

    def test_complex_instruction(self):
        meta = parse_instruction(
            "Place in a 375°F oven and roast for 25 to 30 minutes until golden"
        )
        assert meta.temperature == 375.0
        assert meta.temperature_unit == "fahrenheit"
        # Midpoint of 25-30 = 27.5 minutes = 1650 seconds
        assert meta.total_time_seconds == 1650


class TestEdgeCases:
    """Test edge cases and false positive prevention."""

    def test_step_numbers_not_extracted(self):
        """'Step 1' should not be extracted as time."""
        meta = parse_instruction("Step 1: Mix the ingredients")
        assert meta.total_time_seconds is None

    def test_serving_numbers_not_extracted(self):
        """'Serves 4' should not be extracted as time."""
        meta = parse_instruction("Serves 4 people")
        assert meta.total_time_seconds is None

    def test_quantity_not_extracted_as_temp(self):
        """'2 cups' should not extract the 2 as temperature."""
        meta = parse_instruction("Add 2 cups of flour")
        assert meta.temperature is None

    def test_medium_heat_no_temp(self):
        """Qualitative heat descriptions should not extract temperature."""
        meta = parse_instruction("Cook over medium-high heat")
        assert meta.temperature is None

    def test_empty_string(self):
        meta = parse_instruction("")
        assert meta.total_time_seconds is None
        assert meta.temperature is None

    def test_only_numbers(self):
        meta = parse_instruction("Add 3 eggs and 2 tablespoons butter")
        assert meta.total_time_seconds is None
        assert meta.temperature is None


class TestParseInstructions:
    """Test batch parsing of multiple instructions."""

    def test_multiple_steps(self):
        steps = [
            "Preheat oven to 350°F.",
            "Mix ingredients for 5 minutes.",
            "Bake for 30 minutes.",
        ]
        results = parse_instructions(steps)

        assert len(results) == 3

        # Step 1: temperature only
        text, meta = results[0]
        assert text == steps[0]
        assert meta.temperature == 350.0

        # Step 2: time only
        _, meta = results[1]
        assert meta.total_time_seconds == 300

        # Step 3: time only
        _, meta = results[2]
        assert meta.total_time_seconds == 1800


class TestTemperatureConversions:
    """Test F<->C conversion functions."""

    def test_f_to_c_common_temps(self):
        assert fahrenheit_to_celsius(350) == 177
        assert fahrenheit_to_celsius(400) == 204
        assert fahrenheit_to_celsius(450) == 232
        assert fahrenheit_to_celsius(32) == 0
        assert fahrenheit_to_celsius(212) == 100

    def test_c_to_f_common_temps(self):
        assert celsius_to_fahrenheit(180) == 356
        assert celsius_to_fahrenheit(200) == 392
        assert celsius_to_fahrenheit(0) == 32
        assert celsius_to_fahrenheit(100) == 212
