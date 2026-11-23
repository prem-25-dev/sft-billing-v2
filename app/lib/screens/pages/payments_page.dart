import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../widgets.dart';
import 'common.dart';

class PaymentsPage extends StatefulWidget {
  const PaymentsPage({super.key});
  @override
  State<PaymentsPage> createState() => _PaymentsPageState();
}

class _PaymentsPageState extends State<PaymentsPage> {
  late Future<Map<String, dynamic>> _future;

  Future<Map<String, dynamic>> _load() async {
    final api = apiOf(context);
    final r = await Future.wait([api.get('/api/payments'), api.get('/api/clients'), api.get('/api/invoices')]);
    return {'payments': (r[0] as List).cast<Map>(), 'clients': (r[1] as List).cast<Map>(), 'invoices': (r[2] as List).cast<Map>()};
  }

  @override
  void initState() {
    super.initState();
    _future = Future.microtask(_load);
  }

  void _reload() => setState(() => _future = _load());

  static const _methods = {'upi': 'UPI', 'bank_transfer': 'Bank transfer', 'cash': 'Cash', 'cheque': 'Cheque', 'card': 'Card'};

  @override
  Widget build(BuildContext context) {
    return FutureBody<Map<String, dynamic>>(
      future: _future,
      onRetry: _reload,
      builder: (d) {
        final payments = (d['payments'] as List<Map>)..sort((a, b) => '${b['receivedAt']}'.compareTo('${a['receivedAt']}'));
        final names = {for (final c in d['clients'] as List<Map>) c['id']: c['name']};
        final numbers = {for (final i in d['invoices'] as List<Map>) i['id']: i['number']};
        final total = payments.fold<double>(0, (s, p) => s + (p['amount'] as num));
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PageHeader(title: 'Payments', subtitle: '${payments.length} payments · ${money(total)} received'),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: DataCard(
                headers: const ['Date', 'Client', 'Invoice', 'Method', 'Reference', 'Amount', ''],
                flex: const [2, 4, 2, 2, 3, 2, 1],
                empty: const EmptyState(icon: Icons.payments_outlined, title: 'No payments yet', hint: 'Record a payment from an invoice.'),
                rows: [
                  for (final p in payments)
                    [
                      Text(shortDate(p['receivedAt'])),
                      Text('${names[p['clientId']] ?? ''}'),
                      Text('${numbers[p['invoiceId']] ?? ''}'),
                      Text(_methods[p['method']] ?? '${p['method']}'),
                      Text('${p['reference'] ?? '-'}'),
                      Text(money(p['amount'] as num), style: const TextStyle(fontWeight: FontWeight.w700, color: Colors.green)),
                      IconButton(
                        tooltip: 'Delete',
                        icon: const Icon(Icons.delete_outline, size: 19),
                        onPressed: () async {
                          if (!await confirm(context, 'Delete payment?', 'The invoice balance will go back up.')) return;
                          try {
                            await apiOf(context).delete('/api/payments/${p['id']}');
                            _reload();
                          } catch (e) {
                            if (context.mounted) toast(context, errText(e), error: true);
                          }
                        },
                      ),
                    ],
                ],
              ),
            ),
          ),
        ]);
      },
    );
  }
}
