import 'package:flutter/material.dart';

import 'core/api.dart';
import 'core/theme.dart';

void toast(BuildContext context, String message, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(message),
      behavior: SnackBarBehavior.floating,
      width: 460,
      backgroundColor: error ? Colors.red.shade700 : null,
    ));
}

String errText(Object e) => e is ApiException ? e.message : e.toString();

class PageHeader extends StatelessWidget {
  const PageHeader({super.key, required this.title, this.subtitle, this.actions = const []});
  final String title;
  final String? subtitle;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 20),
      child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, style: t.textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
            if (subtitle != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(subtitle!, style: t.textTheme.bodyMedium?.copyWith(color: t.colorScheme.onSurfaceVariant)),
              ),
          ]),
        ),
        for (final a in actions) Padding(padding: const EdgeInsets.only(left: 10), child: a),
      ]),
    );
  }
}

class StatTile extends StatelessWidget {
  const StatTile({super.key, required this.label, required this.value, this.icon, this.color});
  final String label;
  final String value;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final c = color ?? brandBlue;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Row(children: [
          if (icon != null)
            Container(
              width: 46,
              height: 46,
              decoration: BoxDecoration(color: c.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(14)),
              child: Icon(icon, color: c),
            ),
          if (icon != null) const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(label, style: t.textTheme.bodySmall?.copyWith(color: t.colorScheme.onSurfaceVariant)),
              const SizedBox(height: 4),
              FittedBox(
                fit: BoxFit.scaleDown,
                alignment: Alignment.centerLeft,
                child: Text(value, style: t.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.hint});
  final IconData icon;
  final String title;
  final String? hint;
  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.all(48),
      child: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 44, color: t.colorScheme.onSurfaceVariant.withValues(alpha: 0.6)),
          const SizedBox(height: 12),
          Text(title, style: t.textTheme.titleMedium),
          if (hint != null) ...[
            const SizedBox(height: 4),
            Text(hint!, style: t.textTheme.bodySmall?.copyWith(color: t.colorScheme.onSurfaceVariant)),
          ],
        ]),
      ),
    );
  }
}

class StatusChip extends StatelessWidget {
  const StatusChip(this.status, {super.key});
  final String status;
  @override
  Widget build(BuildContext context) {
    final (label, color) = switch (status) {
      'paid' => ('Paid', Colors.green),
      'overdue' => ('Overdue', Colors.red),
      'draft' => ('Draft', Colors.blueGrey),
      'cancelled' => ('Cancelled', Colors.grey),
      'partial' || 'partially_paid' => ('Part paid', Colors.orange),
      _ => ('Pending', brandBlue),
    };
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(20)),
      child: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w600, fontSize: 12)),
    );
  }
}

/// Labeled text field used by all forms.
Widget field(String label, TextEditingController c,
    {bool obscure = false, TextInputType? type, int lines = 1, String? hint, Widget? suffix, bool enabled = true, ValueChanged<String>? onChanged, ValueChanged<String>? onSubmit}) {
  return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
    Text(label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13)),
    const SizedBox(height: 6),
    TextField(
      controller: c,
      obscureText: obscure,
      keyboardType: type,
      maxLines: obscure ? 1 : lines,
      enabled: enabled,
      onChanged: onChanged,
      onSubmitted: onSubmit,
      decoration: InputDecoration(hintText: hint, suffixIcon: suffix),
    ),
  ]);
}
