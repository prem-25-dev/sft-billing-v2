import 'dart:typed_data';

import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/api.dart';
import '../../state/app_state.dart';
import '../../widgets.dart';

Api apiOf(BuildContext context) => context.read<AppState>().api!;

/// Shows a spinner, an error with retry, or the loaded data.
class FutureBody<T> extends StatelessWidget {
  const FutureBody({super.key, required this.future, required this.builder, required this.onRetry});
  final Future<T> future;
  final Widget Function(T data) builder;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<T>(
      future: future,
      builder: (context, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Text(errText(snap.error!)),
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onRetry, child: const Text('Retry')),
            ]),
          );
        }
        return builder(snap.data as T);
      },
    );
  }
}

/// Save bytes to a place the user chooses.
Future<bool> saveBytes(BuildContext context, Uint8List data, String suggestedName, String label, List<String> extensions) async {
  final location = await getSaveLocation(
    suggestedName: suggestedName,
    acceptedTypeGroups: [XTypeGroup(label: label, extensions: extensions)],
  );
  if (location == null) return false;
  await XFile.fromData(data, name: suggestedName).saveTo(location.path);
  return true;
}

Future<bool> confirm(BuildContext context, String title, String text, {String action = 'Delete'}) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (c) => AlertDialog(
      title: Text(title),
      content: Text(text),
      actions: [
        TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(c, true), child: Text(action)),
      ],
    ),
  );
  return ok ?? false;
}

/// A simple card-wrapped table: header row + body rows.
class DataCard extends StatelessWidget {
  const DataCard({super.key, required this.headers, required this.rows, this.flex, this.empty});
  final List<String> headers;
  final List<List<Widget>> rows;
  final List<int>? flex;
  final Widget? empty;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final f = flex ?? List.filled(headers.length, 1);
    Widget cells(List<Widget> cs, {bool head = false}) => Padding(
          padding: EdgeInsets.symmetric(horizontal: 18, vertical: head ? 12 : 14),
          child: Row(children: [
            for (var i = 0; i < cs.length; i++) Expanded(flex: f[i], child: Padding(padding: const EdgeInsets.only(right: 10), child: cs[i])),
          ]),
        );
    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        Container(
          color: t.colorScheme.onSurface.withValues(alpha: 0.04),
          child: cells([for (final h in headers) Text(h, style: TextStyle(fontWeight: FontWeight.w600, fontSize: 12, color: t.colorScheme.onSurfaceVariant))], head: true),
        ),
        if (rows.isEmpty) empty ?? const SizedBox.shrink(),
        Expanded(
          child: ListView.separated(
            itemCount: rows.length,
            separatorBuilder: (_, __) => const Divider(),
            itemBuilder: (_, i) => cells(rows[i]),
          ),
        ),
      ]),
    );
  }
}
