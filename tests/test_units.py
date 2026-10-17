import unittest

from speedchecker.units import convert_latency, convert_speed, format_speed


class UnitConversionTests(unittest.TestCase):
    def test_decimal_bit_and_byte_conversions(self):
        self.assertEqual(convert_speed(1, "Mbps"), 1)
        self.assertEqual(convert_speed(1, "Kbps"), 1000)
        self.assertEqual(convert_speed(1, "bps"), 1_000_000)
        self.assertEqual(convert_speed(1, "MB/s"), 0.125)
        self.assertEqual(convert_speed(1, "KB/s"), 125)
        self.assertEqual(convert_speed(1, "B/s"), 125_000)

    def test_binary_byte_units(self):
        self.assertAlmostEqual(convert_speed(1, "KiB/s"), 125_000 / 1024)
        self.assertAlmostEqual(convert_speed(1, "MiB/s"), 125_000 / 1024**2)
        self.assertAlmostEqual(convert_speed(1, "GiB/s"), 125_000 / 1024**3)

    def test_format_and_latency_units(self):
        self.assertEqual(format_speed(100.5, "MB/s"), "12.56 MB/s")
        self.assertEqual(convert_latency(1000, "s"), 1)
        self.assertEqual(convert_latency(1, "µs"), 1000)
        with self.assertRaises(ValueError):
            convert_speed(10, "unsupported")


if __name__ == "__main__":
    unittest.main()
