import 'package:flutter/material.dart';

import '../../widgets.dart';
import 'common.dart';

/// Export this PC's data to one file that a new PC can load during setup.
class CopyDataPage extends StatefulWidget {
  const CopyDataPage({super.key});
  @override
  State<CopyDataPage> createState() => _CopyDataPageState();
}

class _CopyDataPageState extends State<CopyDataPage> {
  late Future<Map> _future;
  bool master = true, business = true, transactions = false, _busy = false;

  @override
  void initState() {
    super.initState();
    _future = Future.microtask(() async => (await apiOf(context).get('/api/transfer/summary')) as Map);
  }

  Future<void> _copy() async {
    setState(() => _busy = true);
    try {
      final bytes = await apiOf(context).bytes('/api/transfer/export', method: 'POST', body: {
        'master': master || transactions,
        'business': business,
        'transactions': transactions,
      });
      final stamp = DateTime.now();
      String two(int n) => n.toString().padLeft(2, '0');
      final name = 'SFT-Billing-Data-${stamp.year}${two(stamp.month)}${two(stamp.day)}-${two(stamp.hour)}${two(stamp.minute)}.sftpack';
      final saved = await saveBytes(context, bytes, name, 'SFT Billing data file', ['sftpack']);
      if (saved && mounted) toast(context, 'Data file saved. Take it to the new PC and choose “Copy from another PC” during setup.');
    } catch (e) {
      if (mounted) toast(context, errText(e), error: true);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return FutureBody<Map>(
      future: _future,
      onRetry: () => setState(() => _future = Future(() async => (await apiOf(context).get('/api/transfer/summary')) as Map)),
      builder: (s) => ListView(children: [
        const PageHeader(title: 'Copy data', subtitle: 'Move your workspace to another PC with one file.'),
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Column(children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('What should be copied?', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 8),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: master || transactions,
                      onChanged: transactions ? null : (v) => setState(() => master = v ?? false),
                      title: const Text('Clients and products'),
                      subtitle: Text('${s['clients']} clients, ${s['products']} products'),
                    ),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: business,
                      onChanged: (v) => setState(() => business = v ?? false),
                      title: const Text('Business profile and settings'),
                      subtitle: const Text('Company name, GSTIN, address, bank details, GST defaults'),
                    ),
                    CheckboxListTile(
                      contentPadding: EdgeInsets.zero,
                      value: transactions,
                      onChanged: (v) => setState(() {
                        transactions = v ?? false;
                        if (transactions) master = true;
                      }),
                      title: const Text('All invoices and payments'),
                      subtitle: Text('${s['invoices']} invoices, ${s['payments']} payments — an exact copy (includes clients and products)'),
                    ),
                  ]),
                ),
              ),
              const SizedBox(height: 16),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Row(children: [
                    Icon(Icons.info_outline, color: t.colorScheme.primary),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Text(
                        'The new PC always creates its own user and password — logins are never copied. '
                        'Install SFT Billing there, choose “Copy from another PC” and pick the file saved here.',
                        style: TextStyle(color: t.colorScheme.onSurfaceVariant, height: 1.4),
                      ),
                    ),
                  ]),
                ),
              ),
              const SizedBox(height: 20),
              Align(
                alignment: Alignment.centerRight,
                child: FilledButton.icon(
                  onPressed: _busy || !(master || business || transactions) ? null : _copy,
                  icon: const Icon(Icons.drive_file_move_outlined),
                  label: Text(_busy ? 'Preparing…' : 'Copy data to a file'),
                ),
              ),
            ]),
          ),
        ),
      ]),
    );
  }
}
