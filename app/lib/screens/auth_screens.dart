import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/theme.dart';
import '../state/app_state.dart';
import '../widgets.dart';

/// 35/65 split: form on the left, product showcase on the right.
class AuthFrame extends StatelessWidget {
  const AuthFrame({super.key, required this.child, this.maxFormWidth = 380});
  final Widget child;
  final double maxFormWidth;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final dark = Theme.of(context).brightness == Brightness.dark;
    return Scaffold(
      body: Row(children: [
        Expanded(
          flex: 35,
          child: Column(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(32, 24, 24, 0),
              child: Row(children: [
                Image.asset('assets/brand/surfine-horizontal.png', height: 34, color: dark ? Colors.white : null),
                const Spacer(),
                TextButton.icon(
                  onPressed: s.toggleTheme,
                  icon: Icon(dark ? Icons.light_mode_outlined : Icons.dark_mode_outlined, size: 18),
                  label: Text(dark ? 'Light' : 'Dark'),
                ),
              ]),
            ),
            Expanded(
              child: Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(32),
                  child: ConstrainedBox(constraints: BoxConstraints(maxWidth: maxFormWidth), child: child),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.only(bottom: 18),
              child: Text('SFT Billing · v${AppState.version} · © Surfine Technology',
                  style: TextStyle(fontSize: 11, color: Theme.of(context).colorScheme.onSurfaceVariant)),
            ),
          ]),
        ),
        const Expanded(flex: 65, child: _Showcase()),
      ]),
    );
  }
}

class _Showcase extends StatelessWidget {
  const _Showcase();

  @override
  Widget build(BuildContext context) {
    const points = [
      (Icons.receipt_long_outlined, 'GST invoices in seconds', 'Exact Excel-format bills, previewed as PDF.'),
      (Icons.groups_2_outlined, 'Clients and products', 'Everything saved on this PC, always available offline.'),
      (Icons.swap_horiz, 'Move to a new PC easily', 'Copy your data to a file and load it on the next computer.'),
    ];
    return Container(
      decoration: const BoxDecoration(
        gradient: LinearGradient(begin: Alignment.topLeft, end: Alignment.bottomRight, colors: [Color(0xFF0B1226), Color(0xFF14307F), brandBlue]),
      ),
      padding: const EdgeInsets.all(64),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Billing that stays\nsimple and yours.',
            style: TextStyle(color: Colors.white, fontSize: 44, height: 1.1, fontWeight: FontWeight.w800)),
        const SizedBox(height: 16),
        const Text('Invoices, clients, products and payments — in one desktop app that keeps your data on your own computer.',
            style: TextStyle(color: Colors.white70, fontSize: 16, height: 1.5)),
        const SizedBox(height: 40),
        for (final (icon, title, text) in points)
          Padding(
            padding: const EdgeInsets.only(bottom: 18),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Container(
                width: 42,
                height: 42,
                decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
                child: Icon(icon, color: Colors.white, size: 22),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w600)),
                  Text(text, style: const TextStyle(color: Colors.white60)),
                ]),
              ),
            ]),
          ),
      ]),
    );
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _show = false, _busy = false;
  String? _error;

  Future<void> _submit() async {
    if (_user.text.trim().isEmpty || _pass.text.isEmpty) {
      setState(() => _error = 'Enter your username and password.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<AppState>().login(_user.text.trim(), _pass.text);
    } catch (e) {
      if (mounted) setState(() => _error = errText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return AuthFrame(
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('Welcome back', style: t.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
        const SizedBox(height: 6),
        Text('Sign in to manage invoices, clients and payments.', style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
        const SizedBox(height: 28),
        field('Username', _user),
        const SizedBox(height: 16),
        field('Password', _pass,
            obscure: !_show,
            onSubmit: (_) => _submit(),
            suffix: IconButton(icon: Icon(_show ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: 20), onPressed: () => setState(() => _show = !_show))),
        if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: t.colorScheme.error))),
        Align(
          alignment: Alignment.centerRight,
          child: TextButton(onPressed: () => showDialog(context: context, builder: (_) => const ForgotPasswordDialog()), child: const Text('Forgot password?')),
        ),
        const SizedBox(height: 6),
        SizedBox(
          width: double.infinity,
          child: FilledButton(onPressed: _busy ? null : _submit, child: Text(_busy ? 'Signing in…' : 'Sign in')),
        ),
        const SizedBox(height: 14),
        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(Icons.shield_outlined, size: 14, color: t.colorScheme.onSurfaceVariant),
          const SizedBox(width: 6),
          Text('Your data stays on this device', style: TextStyle(fontSize: 12, color: t.colorScheme.onSurfaceVariant)),
        ]),
      ]),
    );
  }
}

/// Reset the password using the registered mobile number.
class ForgotPasswordDialog extends StatefulWidget {
  const ForgotPasswordDialog({super.key});
  @override
  State<ForgotPasswordDialog> createState() => _ForgotPasswordDialogState();
}

class _ForgotPasswordDialogState extends State<ForgotPasswordDialog> {
  final _mobile = TextEditingController();
  final _new = TextEditingController();
  final _confirm = TextEditingController();
  String? _token, _error;
  bool _busy = false, _done = false;

  Future<void> _run(Future<void> Function() job) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await job();
    } catch (e) {
      if (mounted) setState(() => _error = errText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = context.read<AppState>();
    Widget body;
    if (_done) {
      body = const Text('Your password has been changed. Sign in with the new password.');
    } else if (_token == null) {
      body = Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('Enter the mobile number you registered with.'),
        const SizedBox(height: 14),
        field('Mobile number', _mobile, type: TextInputType.phone, hint: '10-digit mobile number'),
      ]);
    } else {
      body = Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
        field('New password', _new, obscure: true, hint: 'At least 8 characters'),
        const SizedBox(height: 14),
        field('Confirm new password', _confirm, obscure: true),
      ]);
    }
    return AlertDialog(
      title: Text(_done ? 'Password updated' : _token == null ? 'Recover your account' : 'Set a new password'),
      content: SizedBox(
        width: 380,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          body,
          if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))),
        ]),
      ),
      actions: [
        if (!_done) TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
        FilledButton(
          onPressed: _busy
              ? null
              : () {
                  if (_done) return Navigator.pop(context);
                  if (_token == null) {
                    _run(() async {
                      final token = await app.verifyMobile(_mobile.text.trim());
                      setState(() => _token = token);
                    });
                  } else {
                    if (_new.text.length < 8) return setState(() => _error = 'Use at least 8 characters.');
                    if (_new.text != _confirm.text) return setState(() => _error = 'The passwords do not match.');
                    _run(() async {
                      await app.resetPassword(_token!, _new.text);
                      setState(() => _done = true);
                    });
                  }
                },
          child: Text(_done ? 'Back to sign in' : _token == null ? 'Continue' : 'Update password'),
        ),
      ],
    );
  }
}
