import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

const brandBlue = Color(0xFF2E67FF);
const sidebarColor = Color(0xFF0B1226);

ThemeData buildTheme(Brightness brightness) {
  final scheme = ColorScheme.fromSeed(seedColor: brandBlue, brightness: brightness).copyWith(primary: brandBlue);
  final dark = brightness == Brightness.dark;
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    fontFamily: 'Segoe UI',
    scaffoldBackgroundColor: dark ? const Color(0xFF0E1320) : const Color(0xFFF5F7FB),
    cardTheme: CardThemeData(
      elevation: 0,
      color: dark ? const Color(0xFF151B2B) : Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: BorderSide(color: dark ? const Color(0xFF232B40) : const Color(0xFFE5E9F2)),
      ),
      margin: EdgeInsets.zero,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF1A2135) : const Color(0xFFF8F9FC),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: dark ? const Color(0xFF2A3350) : const Color(0xFFE1E6F0)),
      ),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12), borderSide: const BorderSide(color: brandBlue, width: 1.6)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, 48),
        padding: const EdgeInsets.symmetric(horizontal: 22),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, 48),
        padding: const EdgeInsets.symmetric(horizontal: 22),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    dividerTheme: DividerThemeData(color: dark ? const Color(0xFF232B40) : const Color(0xFFE5E9F2), space: 1),
  );
}

final _money = NumberFormat.currency(locale: 'en_IN', symbol: '₹', decimalDigits: 2);
String money(num v) => _money.format(v);
String shortDate(String? iso) {
  if (iso == null || iso.isEmpty) return '-';
  final d = DateTime.tryParse(iso);
  return d == null ? iso : DateFormat('dd MMM yyyy').format(d);
}
