import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/app_state.dart';
import '../../widgets.dart';
import 'common.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key});
  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late Future<Map> _future;
  final Map<String, TextEditingController> c = {for (final k in ['name', 'address', 'email', 'phone', 'gstin', 'pan', 'declaration', 'authorizedSignatory']) k: TextEditingController()};
  final Map<String, TextEditingController> bank = {for (final k in ['accountHolder', 'bankName', 'branch', 'accountNumber', 'ifsc']) k: TextEditingController()};
  final cgst = TextEditingController();
  final sgst = TextEditingController();
  final curPass = TextEditingController();
  final newPass = TextEditingController();
  bool _loaded = false, _busy = false;

  Future<Map> _load() async => (await apiOf(context).get('/api/business-profile')) as Map;

  @override
  void initState() {
    super.initState();
    _future = Future.microtask(_load);
  }

  void _fill(Map bp) {
    if (_loaded) return;
    _loaded = true;
    for (final e in c.entries) {
      e.value.text = '${bp[e.key] ?? ''}';
    }
    final b = (bp['bank'] as Map?) ?? {};
    for (final e in bank.entries) {
      e.value.text = '${b[e.key] ?? ''}';
    }
    final g = (bp['defaultGst'] as Map?) ?? {'cgstRate': 0.09, 'sgstRate': 0.09};
    cgst.text = ((g['cgstRate'] as num) * 100).toStringAsFixed(0);
    sgst.text = ((g['sgstRate'] as num) * 100).toStringAsFixed(0);
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    String? orNull(TextEditingController x) => x.text.trim().isEmpty ? null : x.text.trim();
    final hasBank = bank.values.any((x) => x.text.trim().isNotEmpty);
    try {
      await apiOf(context).put('/api/business-profile', {
        'name': c['name']!.text.trim(),
        'address': c['address']!.text.trim(),
        'email': c['email']!.text.trim(),
        'phone': orNull(c['phone']!),
        'gstin': orNull(c['gstin']!),
        'pan': orNull(c['pan']!),
        'declaration': orNull(c['declaration']!),
        'authorizedSignatory': orNull(c['authorizedSignatory']!),
        if (hasBank) 'bank': {for (final e in bank.entries) e.key: e.value.text.trim()},
        'defaultGst': {'cgstRate': (double.tryParse(cgst.text) ?? 9) / 100, 'sgstRate': (double.tryParse(sgst.text) ?? 9) / 100},
      });
      if (mounted) toast(context, 'Settings saved.');
    } catch (e) {
      if (mounted) toast(context, errText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _changePassword() async {
    if (newPass.text.length < 8) return toast(context, 'Use at least 8 characters for the new password.', error: true);
    try {
      await apiOf(context).post('/api/auth/change-password', {'current_password': curPass.text, 'new_password': newPass.text});
      curPass.clear();
      newPass.clear();
      if (mounted) toast(context, 'Password changed.');
    } catch (e) {
      if (mounted) toast(context, errText(e), error: true);
    }
  }

  Widget _section(String title, String text, Widget child) => Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                width: 240,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                  const SizedBox(height: 4),
                  Text(text, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
                ]),
              ),
              Expanded(child: child),
            ]),
          ),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final app = context.watch<AppState>();
    return FutureBody<Map>(
      future: _future,
      onRetry: () => setState(() => _future = _load()),
      builder: (bp) {
        _fill(bp);
        return ListView(children: [
          PageHeader(title: 'Settings', subtitle: 'Business details used on every invoice.', actions: [FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Saving…' : 'Save changes'))]),
          _section(
            'Business',
            'Shown at the top of printed invoices.',
            Column(children: [
              field('Business name', c['name']!),
              const SizedBox(height: 12),
              field('Address', c['address']!, lines: 2),
              const SizedBox(height: 12),
              Row(children: [Expanded(child: field('Email', c['email']!)), const SizedBox(width: 12), Expanded(child: field('Phone', c['phone']!))]),
              const SizedBox(height: 12),
              Row(children: [Expanded(child: field('GSTIN', c['gstin']!)), const SizedBox(width: 12), Expanded(child: field('PAN', c['pan']!))]),
            ]),
          ),
          _section(
            'Bank details',
            'Printed on invoices so clients know where to pay.',
            Column(children: [
              Row(children: [Expanded(child: field('Account holder', bank['accountHolder']!)), const SizedBox(width: 12), Expanded(child: field('Bank name', bank['bankName']!))]),
              const SizedBox(height: 12),
              Row(children: [Expanded(child: field('Branch', bank['branch']!)), const SizedBox(width: 12), Expanded(child: field('Account number', bank['accountNumber']!)), const SizedBox(width: 12), Expanded(child: field('IFSC', bank['ifsc']!))]),
            ]),
          ),
          _section(
            'Invoice defaults',
            'Starting values for new invoices.',
            Column(children: [
              Row(children: [Expanded(child: field('CGST %', cgst, type: TextInputType.number)), const SizedBox(width: 12), Expanded(child: field('SGST %', sgst, type: TextInputType.number))]),
              const SizedBox(height: 12),
              field('Declaration', c['declaration']!, lines: 2),
              const SizedBox(height: 12),
              field('Authorised signatory', c['authorizedSignatory']!),
            ]),
          ),
          _section(
            'Account',
            'Signed in as ${app.user?['username']}.',
            Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Row(children: [
                Expanded(child: field('Current password', curPass, obscure: true)),
                const SizedBox(width: 12),
                Expanded(child: field('New password', newPass, obscure: true, hint: 'At least 8 characters')),
              ]),
              const SizedBox(height: 12),
              OutlinedButton(onPressed: _changePassword, child: const Text('Change password')),
              const SizedBox(height: 18),
              Text('SFT Billing v${AppState.version}', style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ]),
          ),
          const SizedBox(height: 16),
        ]);
      },
    );
  }
}
