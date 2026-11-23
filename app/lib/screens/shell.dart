import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/theme.dart';
import '../state/app_state.dart';
import 'pages/clients_page.dart';
import 'pages/copy_data_page.dart';
import 'pages/invoices_page.dart';
import 'pages/overview_page.dart';
import 'pages/payments_page.dart';
import 'pages/products_page.dart';
import 'pages/reports_page.dart';
import 'pages/settings_page.dart';

class _Dest {
  const _Dest(this.label, this.icon, this.section);
  final String label;
  final IconData icon;
  final String section;
}

const _dests = [
  _Dest('Overview', Icons.dashboard_outlined, 'WORKSPACE'),
  _Dest('Invoices', Icons.receipt_long_outlined, 'WORKSPACE'),
  _Dest('Clients', Icons.groups_2_outlined, 'WORKSPACE'),
  _Dest('Products', Icons.inventory_2_outlined, 'WORKSPACE'),
  _Dest('Payments', Icons.payments_outlined, 'WORKSPACE'),
  _Dest('Reports', Icons.insights_outlined, 'INSIGHTS'),
  _Dest('Copy data', Icons.drive_file_move_outlined, 'SYSTEM'),
  _Dest('Settings', Icons.settings_outlined, 'SYSTEM'),
];

class Shell extends StatefulWidget {
  const Shell({super.key});
  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  int _index = 0;
  int _epoch = 0; // bump to rebuild (and reload) the current page

  void go(int i) => setState(() {
        _index = i;
        _epoch++;
      });

  Widget _page() {
    final key = ValueKey('$_index-$_epoch');
    return switch (_index) {
      0 => OverviewPage(key: key, go: go),
      1 => InvoicesPage(key: key),
      2 => ClientsPage(key: key),
      3 => ProductsPage(key: key),
      4 => PaymentsPage(key: key),
      5 => ReportsPage(key: key),
      6 => CopyDataPage(key: key),
      _ => SettingsPage(key: key),
    };
  }

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    final name = (app.user?['username'] ?? '') as String;
    String? lastSection;
    return Scaffold(
      body: Row(children: [
        Container(
          width: 248,
          color: sidebarColor,
          padding: const EdgeInsets.fromLTRB(14, 20, 14, 14),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 0, 8, 22),
              child: Image.asset('assets/brand/surfine-horizontal.png', height: 34, color: Colors.white, alignment: Alignment.centerLeft),
            ),
            FilledButton.icon(
              onPressed: () => go(1),
              icon: const Icon(Icons.add, size: 18),
              label: const Text('New invoice'),
              style: FilledButton.styleFrom(minimumSize: const Size.fromHeight(44)),
            ),
            const SizedBox(height: 14),
            Expanded(
              child: ListView(children: [
                for (var i = 0; i < _dests.length; i++) ...[
                  if (_dests[i].section != lastSection)
                    Padding(
                      padding: const EdgeInsets.fromLTRB(10, 14, 10, 6),
                      child: Text(lastSection = _dests[i].section, style: const TextStyle(color: Colors.white38, fontSize: 11, letterSpacing: 1, fontWeight: FontWeight.w600)),
                    ),
                  _NavItem(dest: _dests[i], selected: _index == i, onTap: () => go(i)),
                ],
              ]),
            ),
            const Divider(color: Colors.white12),
            Row(children: [
              CircleAvatar(radius: 17, backgroundColor: brandBlue, child: Text(name.isEmpty ? '?' : name[0].toUpperCase(), style: const TextStyle(color: Colors.white))),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(name, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                  const Text('Owner', style: TextStyle(color: Colors.white38, fontSize: 12)),
                ]),
              ),
              IconButton(tooltip: 'Dark / light', onPressed: app.toggleTheme, icon: const Icon(Icons.brightness_6_outlined, color: Colors.white54, size: 20)),
              IconButton(tooltip: 'Sign out', onPressed: app.logout, icon: const Icon(Icons.logout, color: Colors.white54, size: 20)),
            ]),
          ]),
        ),
        Expanded(
          child: AnimatedSwitcher(
            duration: const Duration(milliseconds: 180),
            child: Padding(
              key: ValueKey('$_index-$_epoch'),
              padding: const EdgeInsets.fromLTRB(32, 28, 32, 0),
              child: _page(),
            ),
          ),
        ),
      ]),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.dest, required this.selected, required this.onTap});
  final _Dest dest;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 2),
      child: Material(
        color: selected ? Colors.white.withValues(alpha: 0.10) : Colors.transparent,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
            child: Row(children: [
              Icon(dest.icon, size: 20, color: selected ? Colors.white : Colors.white60),
              const SizedBox(width: 12),
              Text(dest.label, style: TextStyle(color: selected ? Colors.white : Colors.white70, fontWeight: selected ? FontWeight.w600 : FontWeight.w500)),
            ]),
          ),
        ),
      ),
    );
  }
}
