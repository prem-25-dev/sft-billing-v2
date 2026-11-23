import 'package:flutter/material.dart';

import '../../widgets.dart';
import 'common.dart';

class ClientsPage extends StatefulWidget {
  const ClientsPage({super.key});
  @override
  State<ClientsPage> createState() => _ClientsPageState();
}

class _ClientsPageState extends State<ClientsPage> {
  late Future<List<Map>> _future;
  final _search = TextEditingController();

  Future<List<Map>> _load() async => ((await apiOf(context).get('/api/clients')) as List).cast<Map>();

  @override
  void initState() {
    super.initState();
    _future = Future.microtask(_load);
  }

  void _reload() => setState(() => _future = _load());

  Future<void> _edit([Map? c]) async {
    final saved = await showDialog<bool>(context: context, builder: (_) => _ClientDialog(client: c));
    if (saved == true) _reload();
  }

  Future<void> _delete(Map c) async {
    if (!await confirm(context, 'Delete client?', 'Delete ${c['name']}? Clients with invoices cannot be deleted.')) return;
    try {
      await apiOf(context).delete('/api/clients/${c['id']}');
      _reload();
    } catch (e) {
      if (mounted) toast(context, errText(e), error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    return FutureBody<List<Map>>(
      future: _future,
      onRetry: _reload,
      builder: (all) {
        final q = _search.text.toLowerCase();
        final list = all.where((c) => '${c['name']} ${c['gstin']} ${c['phone']}'.toLowerCase().contains(q)).toList();
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PageHeader(
            title: 'Clients',
            subtitle: '${all.length} clients',
            actions: [
              SizedBox(width: 260, child: TextField(controller: _search, onChanged: (_) => setState(() {}), decoration: const InputDecoration(hintText: 'Search clients', prefixIcon: Icon(Icons.search)))),
              FilledButton.icon(onPressed: () => _edit(), icon: const Icon(Icons.add, size: 18), label: const Text('Add client')),
            ],
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: DataCard(
                headers: const ['Name', 'GSTIN', 'Phone', 'Address', ''],
                flex: const [3, 3, 2, 4, 2],
                empty: const EmptyState(icon: Icons.groups_2_outlined, title: 'No clients found', hint: 'Add your first client to start billing.'),
                rows: [
                  for (final c in list)
                    [
                      Text('${c['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text('${c['gstin'] ?? '-'}'),
                      Text('${c['phone'] ?? '-'}'),
                      Text('${c['billingAddress'] ?? ''}', maxLines: 2, overflow: TextOverflow.ellipsis),
                      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                        IconButton(tooltip: 'Edit', onPressed: () => _edit(c), icon: const Icon(Icons.edit_outlined, size: 19)),
                        IconButton(tooltip: 'Delete', onPressed: () => _delete(c), icon: const Icon(Icons.delete_outline, size: 19)),
                      ]),
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

class _ClientDialog extends StatefulWidget {
  const _ClientDialog({this.client});
  final Map? client;
  @override
  State<_ClientDialog> createState() => _ClientDialogState();
}

class _ClientDialogState extends State<_ClientDialog> {
  late final Map<String, TextEditingController> c = {
    for (final k in ['name', 'contactName', 'phone', 'email', 'gstin', 'pan', 'billingAddress'])
      k: TextEditingController(text: (widget.client?[k] ?? '').toString())
  };
  String? _error;
  bool _busy = false;

  Future<void> _save() async {
    if (c['name']!.text.trim().isEmpty || c['billingAddress']!.text.trim().isEmpty) {
      return setState(() => _error = 'Name and billing address are required.');
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final body = {for (final e in c.entries) e.key: e.value.text.trim().isEmpty ? null : e.value.text.trim()};
    try {
      final api = apiOf(context);
      if (widget.client == null) {
        await api.post('/api/clients', body);
      } else {
        await api.put('/api/clients/${widget.client!['id']}', body);
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) setState(() => _error = errText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.client == null ? 'Add client' : 'Edit client'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            field('Client / company name *', c['name']!),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: field('Contact person', c['contactName']!)),
              const SizedBox(width: 12),
              Expanded(child: field('Phone', c['phone']!, type: TextInputType.phone)),
            ]),
            const SizedBox(height: 12),
            field('Email', c['email']!, type: TextInputType.emailAddress),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: field('GSTIN', c['gstin']!)),
              const SizedBox(width: 12),
              Expanded(child: field('PAN', c['pan']!)),
            ]),
            const SizedBox(height: 12),
            field('Billing address *', c['billingAddress']!, lines: 3),
            if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Saving…' : 'Save')),
      ],
    );
  }
}
