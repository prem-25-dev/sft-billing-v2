import 'dart:math';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:pdfrx/pdfrx.dart';

import '../../core/theme.dart';
import '../../widgets.dart';
import 'common.dart';

String _newId(String prefix) {
  const chars = 'abcdef0123456789';
  final r = Random.secure();
  return '${prefix}_${List.generate(12, (_) => chars[r.nextInt(chars.length)]).join()}';
}

class InvoicesPage extends StatefulWidget {
  const InvoicesPage({super.key});
  @override
  State<InvoicesPage> createState() => _InvoicesPageState();
}

class _InvoicesPageState extends State<InvoicesPage> {
  late Future<Map<String, dynamic>> _future;
  final _search = TextEditingController();
  String _filter = 'all';
  Map? _open;
  bool _creating = false;

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

  void _reload() => setState(() => _future = _load());

  @override
  Widget build(BuildContext context) {
    return FutureBody<Map<String, dynamic>>(
      future: _future,
      onRetry: _reload,
      builder: (d) {
        final invoices = (d['invoices'] as List<Map>)..sort((a, b) => '${b['issueDate']}${b['number']}'.compareTo('${a['issueDate']}${a['number']}'));
        final clients = d['clients'] as List<Map>;
        final names = {for (final c in clients) c['id']: c['name']};

        if (_creating) {
          return CreateInvoiceView(
            clients: clients,
            onDone: (saved) {
              setState(() => _creating = false);
              if (saved) _reload();
            },
          );
        }
        if (_open != null) {
          return InvoiceDetailView(
            invoice: _open!,
            clientName: '${names[_open!['clientId']] ?? ''}',
            onBack: (changed) {
              setState(() => _open = null);
              if (changed) _reload();
            },
          );
        }

        final q = _search.text.toLowerCase();
        final list = invoices.where((i) {
          final status = '${i['status']}';
          final matchesFilter = _filter == 'all' ||
              (_filter == 'unpaid' && !{'paid', 'draft', 'cancelled'}.contains(status)) ||
              status == _filter;
          return matchesFilter && '${i['number']} ${names[i['clientId']]}'.toLowerCase().contains(q);
        }).toList();

        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PageHeader(
            title: 'Invoices',
            subtitle: '${invoices.length} invoices',
            actions: [
              SizedBox(width: 260, child: TextField(controller: _search, onChanged: (_) => setState(() {}), decoration: const InputDecoration(hintText: 'Search number or client', prefixIcon: Icon(Icons.search)))),
              FilledButton.icon(
                onPressed: clients.isEmpty ? () => toast(context, 'Add a client first.', error: true) : () => setState(() => _creating = true),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('New invoice'),
              ),
            ],
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 14),
            child: Wrap(spacing: 8, children: [
              for (final f in const [('all', 'All'), ('unpaid', 'Unpaid'), ('overdue', 'Overdue'), ('paid', 'Paid'), ('draft', 'Drafts')])
                ChoiceChip(label: Text(f.$2), selected: _filter == f.$1, onSelected: (_) => setState(() => _filter = f.$1)),
            ]),
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: DataCard(
                headers: const ['Invoice', 'Client', 'Date', 'Due', 'Amount', 'Balance', 'Status'],
                flex: const [2, 4, 2, 2, 2, 2, 2],
                empty: const EmptyState(icon: Icons.receipt_long_outlined, title: 'No invoices yet', hint: 'Create your first invoice with “New invoice”.'),
                rows: [
                  for (final i in list)
                    [
                      InkWell(onTap: () => setState(() => _open = i), child: Text('${i['number']}', style: TextStyle(fontWeight: FontWeight.w700, color: Theme.of(context).colorScheme.primary))),
                      Text('${names[i['clientId']] ?? ''}'),
                      Text(shortDate(i['issueDate'])),
                      Text(shortDate(i['dueDate'])),
                      Text(money((i['totals'] as Map)['total'])),
                      Text(money((i['totals'] as Map)['balanceDue'])),
                      Align(alignment: Alignment.centerLeft, child: StatusChip('${i['status']}')),
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

// ---------------------------------------------------------------- detail ----

class InvoiceDetailView extends StatefulWidget {
  const InvoiceDetailView({super.key, required this.invoice, required this.clientName, required this.onBack});
  final Map invoice;
  final String clientName;
  final void Function(bool changed) onBack;
  @override
  State<InvoiceDetailView> createState() => _InvoiceDetailViewState();
}

class _InvoiceDetailViewState extends State<InvoiceDetailView> {
  late Future<Uint8List> _pdf;
  bool _changed = false;
  late Map _invoice = widget.invoice;

  @override
  void initState() {
    super.initState();
    _pdf = Future.microtask(() => apiOf(context).bytes('/api/invoices/${_invoice['id']}/pdf'));
  }

  Future<void> _refresh() async {
    final fresh = await apiOf(context).get('/api/invoices/${_invoice['id']}');
    if (mounted) setState(() => _invoice = fresh as Map);
  }

  Future<void> _download(String kind) async {
    try {
      final bytes = await apiOf(context).bytes('/api/invoices/${_invoice['id']}/$kind');
      final safe = '${_invoice['number']}'.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '-');
      final ok = await saveBytes(context, bytes, 'Invoice_$safe.${kind == 'pdf' ? 'pdf' : 'xlsx'}', kind == 'pdf' ? 'PDF' : 'Excel', [kind == 'pdf' ? 'pdf' : 'xlsx']);
      if (ok && mounted) toast(context, 'Saved.');
    } catch (e) {
      if (mounted) toast(context, errText(e), error: true);
    }
  }

  Future<void> _delete() async {
    if (!await confirm(context, 'Delete invoice?', 'Delete invoice ${_invoice['number']}? This cannot be undone.')) return;
    try {
      await apiOf(context).delete('/api/invoices/${_invoice['id']}');
      widget.onBack(true);
    } catch (e) {
      if (mounted) toast(context, errText(e), error: true);
    }
  }

  Future<void> _pay() async {
    final saved = await showDialog<bool>(context: context, builder: (_) => _PaymentDialog(invoice: _invoice));
    if (saved == true) {
      _changed = true;
      await _refresh();
      if (mounted) toast(context, 'Payment recorded.');
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final totals = _invoice['totals'] as Map;
    final balance = (totals['balanceDue'] as num);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        IconButton.filledTonal(onPressed: () => widget.onBack(_changed), icon: const Icon(Icons.arrow_back)),
        const SizedBox(width: 12),
        Text('Invoice ${_invoice['number']}', style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
        const SizedBox(width: 12),
        StatusChip('${_invoice['status']}'),
      ]),
      const SizedBox(height: 18),
      Expanded(
        child: Padding(
          padding: const EdgeInsets.only(bottom: 24),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(
              flex: 3,
              child: Card(
                clipBehavior: Clip.antiAlias,
                child: FutureBuilder<Uint8List>(
                  future: _pdf,
                  builder: (_, snap) {
                    if (snap.connectionState != ConnectionState.done) return const Center(child: CircularProgressIndicator());
                    if (snap.hasError) return Center(child: Text('Could not build the invoice PDF.\n${errText(snap.error!)}', textAlign: TextAlign.center));
                    return PdfViewer.data(snap.data!, sourceName: 'invoice-${_invoice['id']}');
                  },
                ),
              ),
            ),
            const SizedBox(width: 16),
            SizedBox(
              width: 320,
              child: Column(children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text(widget.clientName, style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 14),
                      _kv('Issued', shortDate(_invoice['issueDate'])),
                      _kv('Due', shortDate(_invoice['dueDate'])),
                      const Divider(height: 24),
                      _kv('Subtotal', money(totals['subtotal'])),
                      _kv('CGST', money(totals['cgstAmount'])),
                      _kv('SGST', money(totals['sgstAmount'])),
                      if ((totals['roundOff'] as num) != 0) _kv('Round off', money(totals['roundOff'])),
                      _kv('Total', money(totals['total']), bold: true),
                      _kv('Received', money(totals['paidAmount'])),
                      _kv('Balance due', money(balance), bold: true, color: balance > 0 ? Colors.orange.shade800 : Colors.green),
                    ]),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(width: double.infinity, child: FilledButton.icon(onPressed: balance > 0 ? _pay : null, icon: const Icon(Icons.add_card), label: const Text('Record payment'))),
                const SizedBox(height: 8),
                SizedBox(width: double.infinity, child: OutlinedButton.icon(onPressed: () => _download('pdf'), icon: const Icon(Icons.picture_as_pdf_outlined), label: const Text('Download PDF'))),
                const SizedBox(height: 8),
                SizedBox(width: double.infinity, child: OutlinedButton.icon(onPressed: () => _download('excel'), icon: const Icon(Icons.table_chart_outlined), label: const Text('Download Excel'))),
                const SizedBox(height: 8),
                SizedBox(width: double.infinity, child: TextButton.icon(onPressed: _delete, icon: const Icon(Icons.delete_outline), label: const Text('Delete invoice'), style: TextButton.styleFrom(foregroundColor: Colors.red))),
              ]),
            ),
          ]),
        ),
      ),
    ]);
  }

  Widget _kv(String k, String v, {bool bold = false, Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [
          Text(k, style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
          const Spacer(),
          Text(v, style: TextStyle(fontWeight: bold ? FontWeight.w700 : FontWeight.w500, color: color)),
        ]),
      );
}

class _PaymentDialog extends StatefulWidget {
  const _PaymentDialog({required this.invoice});
  final Map invoice;
  @override
  State<_PaymentDialog> createState() => _PaymentDialogState();
}

class _PaymentDialogState extends State<_PaymentDialog> {
  late final amount = TextEditingController(text: '${(widget.invoice['totals'] as Map)['balanceDue']}');
  final reference = TextEditingController();
  String method = 'upi';
  DateTime date = DateTime.now();
  String? _error;
  bool _busy = false;

  Future<void> _save() async {
    final a = double.tryParse(amount.text.trim());
    if (a == null || a <= 0) return setState(() => _error = 'Enter a valid amount.');
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await apiOf(context).post('/api/payments', {
        'invoiceId': widget.invoice['id'],
        'clientId': widget.invoice['clientId'],
        'amount': a,
        'method': method,
        'receivedAt': date.toIso8601String().substring(0, 10),
        'reference': reference.text.trim().isEmpty ? null : reference.text.trim(),
      });
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
      title: const Text('Record payment'),
      content: SizedBox(
        width: 400,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          field('Amount (₹)', amount, type: TextInputType.number),
          const SizedBox(height: 14),
          const Text('Method', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
          const SizedBox(height: 6),
          DropdownButtonFormField<String>(
            initialValue: method,
            items: const [
              DropdownMenuItem(value: 'upi', child: Text('UPI')),
              DropdownMenuItem(value: 'bank_transfer', child: Text('Bank transfer')),
              DropdownMenuItem(value: 'cash', child: Text('Cash')),
              DropdownMenuItem(value: 'cheque', child: Text('Cheque')),
              DropdownMenuItem(value: 'card', child: Text('Card')),
            ],
            onChanged: (v) => setState(() => method = v!),
          ),
          const SizedBox(height: 14),
          OutlinedButton.icon(
            onPressed: () async {
              final d = await showDatePicker(context: context, initialDate: date, firstDate: DateTime(2020), lastDate: DateTime(2100));
              if (d != null) setState(() => date = d);
            },
            icon: const Icon(Icons.event),
            label: Text('Received on ${shortDate(date.toIso8601String())}'),
          ),
          const SizedBox(height: 14),
          field('Reference (optional)', reference),
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        ]),
      ),
      actions: [
        TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(onPressed: _busy ? null : _save, child: Text(_busy ? 'Saving…' : 'Save payment')),
      ],
    );
  }
}

// ---------------------------------------------------------------- create ----

class _Line {
  _Line() : id = _newId('it');
  final String id;
  String? productId;
  final desc = TextEditingController();
  final hsn = TextEditingController();
  final qty = TextEditingController(text: '1');
  final price = TextEditingController();
  double get q => double.tryParse(qty.text) ?? 0;
  double get p => double.tryParse(price.text) ?? 0;
}

class CreateInvoiceView extends StatefulWidget {
  const CreateInvoiceView({super.key, required this.clients, required this.onDone});
  final List<Map> clients;
  final void Function(bool saved) onDone;
  @override
  State<CreateInvoiceView> createState() => _CreateInvoiceViewState();
}

class _CreateInvoiceViewState extends State<CreateInvoiceView> {
  String? clientId;
  DateTime issue = DateTime.now();
  DateTime due = DateTime.now().add(const Duration(days: 30));
  final lines = [_Line()];
  final cgst = TextEditingController(text: '9');
  final sgst = TextEditingController(text: '9');
  final discount = TextEditingController(text: '0');
  final notes = TextEditingController();
  List<Map> products = [];
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    Future.microtask(() async {
      final api = apiOf(context);
      try {
        final p = ((await api.get('/api/products')) as List).cast<Map>();
        final bp = await api.get('/api/business-profile') as Map;
        final g = bp['defaultGst'] as Map?;
        if (!mounted) return;
        setState(() {
          products = p;
          if (g != null) {
            cgst.text = ((g['cgstRate'] as num) * 100).toStringAsFixed(0);
            sgst.text = ((g['sgstRate'] as num) * 100).toStringAsFixed(0);
          }
        });
      } catch (_) {}
    });
  }

  double get subtotal => lines.fold(0.0, (s, l) => s + l.q * l.p);
  double get disc => double.tryParse(discount.text) ?? 0;
  double get taxable => (subtotal - disc).clamp(0, double.infinity);
  double get cg => taxable * (double.tryParse(cgst.text) ?? 0) / 100;
  double get sg => taxable * (double.tryParse(sgst.text) ?? 0) / 100;
  double get total => taxable + cg + sg;

  Future<void> _save(bool draft) async {
    if (clientId == null) return setState(() => _error = 'Choose a client.');
    final valid = lines.where((l) => l.desc.text.trim().isNotEmpty).toList();
    if (valid.isEmpty || valid.any((l) => l.q <= 0)) return setState(() => _error = 'Add at least one item with a description and quantity.');
    setState(() {
      _busy = true;
      _error = null;
    });
    final api = apiOf(context);
    String? reservedId;
    try {
      final r = await api.post('/api/invoices/reserve-number', {}) as Map;
      reservedId = r['invoiceId'] as String;
      await api.post('/api/invoices', {
        'id': reservedId,
        'number': r['number'],
        'clientId': clientId,
        'issueDate': issue.toIso8601String().substring(0, 10),
        'dueDate': due.toIso8601String().substring(0, 10),
        'items': [
          for (final l in valid)
            {
              'id': l.id,
              if (l.productId != null) 'productId': l.productId,
              'description': l.desc.text.trim(),
              'hsnCode': l.hsn.text.trim().isEmpty ? null : l.hsn.text.trim(),
              'quantity': l.q,
              'unitPrice': l.p,
            }
        ],
        'gst': {'cgstRate': (double.tryParse(cgst.text) ?? 0) / 100, 'sgstRate': (double.tryParse(sgst.text) ?? 0) / 100},
        'discount': disc,
        'roundOff': 0,
        'notes': notes.text.trim().isEmpty ? null : notes.text.trim(),
        'isDraft': draft,
      });
      widget.onDone(true);
    } catch (e) {
      if (reservedId != null) {
        try {
          await api.delete('/api/invoices/reserve-number/$reservedId');
        } catch (_) {}
      }
      if (mounted) setState(() => _error = errText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Widget _date(String label, DateTime v, ValueChanged<DateTime> set) => Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
          const SizedBox(height: 6),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(50), alignment: Alignment.centerLeft),
            onPressed: () async {
              final d = await showDatePicker(context: context, initialDate: v, firstDate: DateTime(2020), lastDate: DateTime(2100));
              if (d != null) set(d);
            },
            icon: const Icon(Icons.event, size: 18),
            label: Text(shortDate(v.toIso8601String())),
          ),
        ]),
      );

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return ListView(children: [
      Row(children: [
        IconButton.filledTonal(onPressed: _busy ? null : () => widget.onDone(false), icon: const Icon(Icons.arrow_back)),
        const SizedBox(width: 12),
        Text('New invoice', style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
      ]),
      const SizedBox(height: 18),
      Card(
        child: Padding(
          padding: const EdgeInsets.all(22),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                flex: 2,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('Client', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
                  const SizedBox(height: 6),
                  DropdownButtonFormField<String>(
                    initialValue: clientId,
                    isExpanded: true,
                    hint: const Text('Choose a client'),
                    items: [for (final c in widget.clients) DropdownMenuItem(value: c['id'] as String, child: Text('${c['name']}'))],
                    onChanged: (v) => setState(() => clientId = v),
                  ),
                ]),
              ),
              const SizedBox(width: 14),
              _date('Invoice date', issue, (d) => setState(() => issue = d)),
              const SizedBox(width: 14),
              _date('Due date', due, (d) => setState(() => due = d)),
            ]),
            const SizedBox(height: 22),
            Text('Items', style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 10),
            for (var i = 0; i < lines.length; i++) _lineRow(i),
            TextButton.icon(onPressed: () => setState(() => lines.add(_Line())), icon: const Icon(Icons.add), label: const Text('Add item')),
          ]),
        ),
      ),
      const SizedBox(height: 16),
      Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [
                  Expanded(child: field('CGST %', cgst, type: TextInputType.number, onChanged: (_) => setState(() {}))),
                  const SizedBox(width: 12),
                  Expanded(child: field('SGST %', sgst, type: TextInputType.number, onChanged: (_) => setState(() {}))),
                  const SizedBox(width: 12),
                  Expanded(child: field('Discount (₹)', discount, type: TextInputType.number, onChanged: (_) => setState(() {}))),
                ]),
                const SizedBox(height: 14),
                field('Notes (optional)', notes, lines: 2),
              ]),
            ),
          ),
        ),
        const SizedBox(width: 16),
        SizedBox(
          width: 340,
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(22),
              child: Column(children: [
                _sum('Subtotal', money(subtotal)),
                if (disc > 0) _sum('Discount', '- ${money(disc)}'),
                _sum('CGST', money(cg)),
                _sum('SGST', money(sg)),
                const Divider(height: 22),
                _sum('Total (approx.)', money(total), bold: true),
                const SizedBox(height: 4),
                Text('Final total is rounded when the invoice is saved.', style: TextStyle(fontSize: 11, color: t.colorScheme.onSurfaceVariant)),
              ]),
            ),
          ),
        ),
      ]),
      if (_error != null) Padding(padding: const EdgeInsets.only(top: 14), child: Text(_error!, style: TextStyle(color: t.colorScheme.error))),
      const SizedBox(height: 16),
      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
        OutlinedButton(onPressed: _busy ? null : () => _save(true), child: const Text('Save as draft')),
        const SizedBox(width: 10),
        FilledButton.icon(onPressed: _busy ? null : () => _save(false), icon: const Icon(Icons.check), label: Text(_busy ? 'Saving…' : 'Create invoice')),
      ]),
      const SizedBox(height: 32),
    ]);
  }

  Widget _sum(String k, String v, {bool bold = false}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 4),
        child: Row(children: [Text(k), const Spacer(), Text(v, style: TextStyle(fontWeight: bold ? FontWeight.w800 : FontWeight.w500, fontSize: bold ? 17 : 14))]),
      );

  Widget _lineRow(int i) {
    final l = lines[i];
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          flex: 3,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            if (i == 0) const Text('Product (optional)', style: TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
            if (i == 0) const SizedBox(height: 6),
            DropdownButtonFormField<String>(
              initialValue: l.productId,
              isExpanded: true,
              hint: const Text('Pick from catalogue'),
              items: [for (final p in products) DropdownMenuItem(value: p['id'] as String, child: Text('${p['name']}', overflow: TextOverflow.ellipsis))],
              onChanged: (v) => setState(() {
                l.productId = v;
                final p = products.firstWhere((p) => p['id'] == v);
                l.desc.text = '${p['name']}';
                l.hsn.text = '${p['hsnCode'] ?? ''}';
                l.price.text = '${p['defaultUnitPrice']}';
              }),
            ),
          ]),
        ),
        const SizedBox(width: 10),
        Expanded(flex: 4, child: _lab(i, 'Description', l.desc, null)),
        const SizedBox(width: 10),
        Expanded(flex: 2, child: _lab(i, 'HSN', l.hsn, null)),
        const SizedBox(width: 10),
        Expanded(flex: 1, child: _lab(i, 'Qty', l.qty, TextInputType.number)),
        const SizedBox(width: 10),
        Expanded(flex: 2, child: _lab(i, 'Rate (₹)', l.price, TextInputType.number)),
        const SizedBox(width: 6),
        SizedBox(
          width: 40,
          child: IconButton(
            tooltip: 'Remove',
            onPressed: lines.length == 1 ? null : () => setState(() => lines.removeAt(i)),
            icon: const Icon(Icons.close, size: 18),
          ),
        ),
      ]),
    );
  }

  Widget _lab(int i, String label, TextEditingController c, TextInputType? type) =>
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (i == 0) Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
        if (i == 0) const SizedBox(height: 6),
        TextField(controller: c, keyboardType: type, onChanged: (_) => setState(() {})),
      ]);
}
