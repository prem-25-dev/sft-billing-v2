import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../widgets.dart';
import 'common.dart';

class ReportsPage extends StatefulWidget {
  const ReportsPage({super.key});
  @override
  State<ReportsPage> createState() => _ReportsPageState();
}

class _ReportsPageState extends State<ReportsPage> {
  late Future<Map<String, dynamic>> _future;

  Future<Map<String, dynamic>> _load() async {
    final api = apiOf(context);
    final r = await Future.wait([api.get('/api/invoices'), api.get('/api/clients')]);
    return {'invoices': (r[0] as List).cast<Map>(), 'clients': (r[1] as List).cast<Map>()};
  }

  @override
  void initState() {
    super.initState();
    _future = Future.microtask(_load);
  }

  @override
  Widget build(BuildContext context) {
    return FutureBody<Map<String, dynamic>>(
      future: _future,
      onRetry: () => setState(() => _future = _load()),
      builder: (d) {
        final invoices = (d['invoices'] as List<Map>).where((i) => i['isDraft'] != true && i['status'] != 'cancelled').toList();
        final names = {for (final c in d['clients'] as List<Map>) c['id']: c['name']};

        final byClient = <dynamic, List<double>>{}; // billed, received, balance
        final byMonth = <String, double>{};
        for (final i in invoices) {
          final tot = i['totals'] as Map;
          final row = byClient.putIfAbsent(i['clientId'], () => [0, 0, 0]);
          row[0] += tot['total'] as num;
          row[1] += tot['paidAmount'] as num;
          row[2] += tot['balanceDue'] as num;
          final m = '${i['issueDate']}'.substring(0, 7);
          byMonth[m] = (byMonth[m] ?? 0) + (tot['total'] as num);
        }
        final clients = byClient.entries.toList()..sort((a, b) => b.value[0].compareTo(a.value[0]));
        final months = byMonth.entries.toList()..sort((a, b) => b.key.compareTo(a.key));
        final maxMonth = months.fold<double>(1, (m, e) => e.value > m ? e.value : m);
        final t = Theme.of(context);

        return ListView(children: [
          const PageHeader(title: 'Reports', subtitle: 'Billing by month and by client.'),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 2,
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Billed per month', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 14),
                    if (months.isEmpty) const EmptyState(icon: Icons.insights_outlined, title: 'No billing yet'),
                    for (final m in months.take(12))
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 5),
                        child: Row(children: [
                          SizedBox(width: 70, child: Text(m.key, style: TextStyle(color: t.colorScheme.onSurfaceVariant))),
                          Expanded(child: ClipRRect(borderRadius: BorderRadius.circular(6), child: LinearProgressIndicator(value: m.value / maxMonth, minHeight: 12))),
                          SizedBox(width: 110, child: Text(money(m.value), textAlign: TextAlign.right, style: const TextStyle(fontWeight: FontWeight.w600))),
                        ]),
                      ),
                  ]),
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              flex: 3,
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('By client', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 10),
                    Table(columnWidths: const {0: FlexColumnWidth(3), 1: FlexColumnWidth(2), 2: FlexColumnWidth(2), 3: FlexColumnWidth(2)}, children: [
                      TableRow(children: [for (final h in ['Client', 'Billed', 'Received', 'Balance']) Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(h, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12, color: t.colorScheme.onSurfaceVariant)))]),
                      for (final c in clients)
                        TableRow(children: [
                          Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text('${names[c.key] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w600))),
                          Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(money(c.value[0]))),
                          Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(money(c.value[1]), style: const TextStyle(color: Colors.green))),
                          Padding(padding: const EdgeInsets.symmetric(vertical: 8), child: Text(money(c.value[2]), style: TextStyle(color: c.value[2] > 0 ? Colors.orange.shade800 : null, fontWeight: FontWeight.w600))),
                        ]),
                    ]),
                  ]),
                ),
              ),
            ),
          ]),
          const SizedBox(height: 24),
        ]);
      },
    );
  }
}
