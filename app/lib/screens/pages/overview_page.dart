import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../widgets.dart';
import 'common.dart';

class OverviewPage extends StatefulWidget {
  const OverviewPage({super.key, required this.go});
  final void Function(int) go;
  @override
  State<OverviewPage> createState() => _OverviewPageState();
}

class _OverviewPageState extends State<OverviewPage> {
  late Future<Map<String, dynamic>> _future;

  Future<Map<String, dynamic>> _load() async {
    final api = apiOf(context);
    final results = await Future.wait([
      api.get('/api/dashboard/summary'),
      api.get('/api/dashboard/outstanding-invoices'),
      api.get('/api/dashboard/recent-payments', query: {'limit': '6'}),
      api.get('/api/clients'),
    ]);
    return {'summary': results[0], 'outstanding': results[1], 'payments': results[2], 'clients': results[3]};
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
        final s = d['summary'] as Map;
        final outstanding = (d['outstanding'] as List).cast<Map>();
        final payments = (d['payments'] as List).cast<Map>();
        final names = {for (final c in (d['clients'] as List).cast<Map>()) c['id']: c['name']};
        final t = Theme.of(context);
        return ListView(children: [
          PageHeader(
            title: 'Overview',
            subtitle: 'How your business is doing — billed, received and what needs attention.',
            actions: [FilledButton.icon(onPressed: () => widget.go(1), icon: const Icon(Icons.add, size: 18), label: const Text('New invoice'))],
          ),
          Row(children: [
            Expanded(child: StatTile(label: 'Total billed', value: money(s['totalInvoiced']), icon: Icons.receipt_long, color: brandBlue)),
            const SizedBox(width: 16),
            Expanded(child: StatTile(label: 'Received', value: money(s['totalCollected']), icon: Icons.check_circle_outline, color: Colors.green)),
            const SizedBox(width: 16),
            Expanded(child: StatTile(label: 'Outstanding', value: money(s['totalOutstanding']), icon: Icons.hourglass_bottom, color: Colors.orange)),
            const SizedBox(width: 16),
            Expanded(child: StatTile(label: 'Overdue invoices', value: '${s['overdueCount']}', icon: Icons.warning_amber_rounded, color: Colors.red)),
          ]),
          const SizedBox(height: 20),
          Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 3,
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Waiting for payment', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 10),
                    if (outstanding.isEmpty) const EmptyState(icon: Icons.task_alt, title: 'Nothing outstanding', hint: 'Unpaid invoices will appear here.'),
                    for (final inv in outstanding.take(6))
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text('${inv['number']}  ·  ${names[inv['clientId']] ?? ''}'),
                        subtitle: Text('Due ${shortDate(inv['dueDate'])}'),
                        trailing: Text(money((inv['totals'] as Map)['balanceDue']), style: const TextStyle(fontWeight: FontWeight.w700)),
                      ),
                  ]),
                ),
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              flex: 2,
              child: Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text('Recent payments', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                    const SizedBox(height: 10),
                    if (payments.isEmpty) const EmptyState(icon: Icons.payments_outlined, title: 'No payments yet'),
                    for (final p in payments)
                      ListTile(
                        contentPadding: EdgeInsets.zero,
                        title: Text(names[p['clientId']]?.toString() ?? ''),
                        subtitle: Text(shortDate(p['receivedAt'])),
                        trailing: Text(money(p['amount']), style: const TextStyle(fontWeight: FontWeight.w700, color: Colors.green)),
                      ),
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
