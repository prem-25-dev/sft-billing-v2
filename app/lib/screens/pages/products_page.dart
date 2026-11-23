import 'package:flutter/material.dart';

import '../../core/theme.dart';
import '../../widgets.dart';
import 'common.dart';

class ProductsPage extends StatefulWidget {
  const ProductsPage({super.key});
  @override
  State<ProductsPage> createState() => _ProductsPageState();
}

class _ProductsPageState extends State<ProductsPage> {
  late Future<List<Map>> _future;
  final _search = TextEditingController();

  Future<List<Map>> _load() async => ((await apiOf(context).get('/api/products')) as List).cast<Map>();

  @override
  void initState() {
    super.initState();
    _future = Future.microtask(_load);
  }

  void _reload() => setState(() => _future = _load());

  Future<void> _edit([Map? p]) async {
    final saved = await showDialog<bool>(context: context, builder: (_) => _ProductDialog(product: p));
    if (saved == true) _reload();
  }

  Future<void> _delete(Map p) async {
    if (!await confirm(context, 'Delete product?', 'Delete ${p['name']}?')) return;
    try {
      await apiOf(context).delete('/api/products/${p['id']}');
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
        final list = all.where((p) => '${p['name']} ${p['code']} ${p['hsnCode']}'.toLowerCase().contains(q)).toList();
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          PageHeader(
            title: 'Products',
            subtitle: '${all.length} items in your catalogue',
            actions: [
              SizedBox(width: 260, child: TextField(controller: _search, onChanged: (_) => setState(() {}), decoration: const InputDecoration(hintText: 'Search products', prefixIcon: Icon(Icons.search)))),
              FilledButton.icon(onPressed: () => _edit(), icon: const Icon(Icons.add, size: 18), label: const Text('Add product')),
            ],
          ),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: 24),
              child: DataCard(
                headers: const ['Code', 'Name', 'HSN', 'Unit', 'Price', 'GST', ''],
                flex: const [2, 5, 2, 1, 2, 1, 2],
                empty: const EmptyState(icon: Icons.inventory_2_outlined, title: 'No products found'),
                rows: [
                  for (final p in list)
                    [
                      Text('${p['code']}'),
                      Text('${p['name']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                      Text('${p['hsnCode'] ?? ''}'),
                      Text('${p['unit']}'),
                      Text(money(p['defaultUnitPrice'] as num)),
                      Text('${((p['defaultGstRate'] as num) * 100).toStringAsFixed(0)}%'),
                      Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                        IconButton(tooltip: 'Edit', onPressed: () => _edit(p), icon: const Icon(Icons.edit_outlined, size: 19)),
                        IconButton(tooltip: 'Delete', onPressed: () => _delete(p), icon: const Icon(Icons.delete_outline, size: 19)),
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

class _ProductDialog extends StatefulWidget {
  const _ProductDialog({this.product});
  final Map? product;
  @override
  State<_ProductDialog> createState() => _ProductDialogState();
}

class _ProductDialogState extends State<_ProductDialog> {
  late final code = TextEditingController(text: '${widget.product?['code'] ?? ''}');
  late final name = TextEditingController(text: '${widget.product?['name'] ?? ''}');
  late final hsn = TextEditingController(text: '${widget.product?['hsnCode'] ?? ''}');
  late final unit = TextEditingController(text: '${widget.product?['unit'] ?? 'nos'}');
  late final price = TextEditingController(text: '${widget.product?['defaultUnitPrice'] ?? ''}');
  late final gst = TextEditingController(text: widget.product == null ? '18' : ((widget.product!['defaultGstRate'] as num) * 100).toStringAsFixed(0));
  late String type = (widget.product?['type'] ?? 'product') as String;
  String? _error;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    if (widget.product == null) {
      Future.microtask(() async {
        try {
          final r = await apiOf(context).get('/api/products/next-code');
          if (mounted && code.text.isEmpty) code.text = '${r['code'] ?? r['nextCode'] ?? ''}';
        } catch (_) {}
      });
    }
  }

  Future<void> _save() async {
    final p = double.tryParse(price.text.trim());
    final g = double.tryParse(gst.text.trim());
    if (code.text.trim().isEmpty || name.text.trim().isEmpty || p == null || g == null) {
      return setState(() => _error = 'Code, name, price and GST % are required.');
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    final body = {
      'code': code.text.trim(),
      'name': name.text.trim(),
      'type': type,
      'hsnCode': hsn.text.trim(),
      'unit': unit.text.trim().isEmpty ? 'nos' : unit.text.trim(),
      'defaultUnitPrice': p,
      'defaultGstRate': g / 100,
    };
    try {
      final api = apiOf(context);
      if (widget.product == null) {
        await api.post('/api/products', body);
      } else {
        await api.put('/api/products/${widget.product!['id']}', body);
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
      title: Text(widget.product == null ? 'Add product' : 'Edit product'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(flex: 2, child: field('Code', code)),
              const SizedBox(width: 12),
              Expanded(flex: 5, child: field('Name', name)),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: field('HSN / SAC', hsn)),
              const SizedBox(width: 12),
              Expanded(child: field('Unit', unit)),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: field('Price (₹)', price, type: TextInputType.number)),
              const SizedBox(width: 12),
              Expanded(child: field('GST %', gst, type: TextInputType.number)),
            ]),
            const SizedBox(height: 14),
            SegmentedButton<String>(
              segments: const [ButtonSegment(value: 'product', label: Text('Product')), ButtonSegment(value: 'service', label: Text('Service'))],
              selected: {type},
              onSelectionChanged: (s) => setState(() => type = s.first),
            ),
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
