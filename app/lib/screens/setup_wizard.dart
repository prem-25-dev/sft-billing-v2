import 'package:file_selector/file_selector.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/app_state.dart';
import '../widgets.dart';
import 'auth_screens.dart';

enum _Step { choose, copy, account }

/// First launch on a PC: choose a clean start or copy data from another PC,
/// then create this PC's own user.
class SetupWizard extends StatefulWidget {
  const SetupWizard({super.key});
  @override
  State<SetupWizard> createState() => _SetupWizardState();
}

class _SetupWizardState extends State<SetupWizard> {
  _Step _step = _Step.choose;
  bool _busy = false;
  String? _error, _fileName;

  final _user = TextEditingController();
  final _mobile = TextEditingController();
  final _pass = TextEditingController();
  final _confirm = TextEditingController();
  bool _show = false;

  @override
  void initState() {
    super.initState();
    // Data already loaded (e.g. chosen in the installer): go straight to the account step.
    final s = context.read<AppState>();
    if (s.restoredClients + s.restoredProducts > 0) _step = _Step.account;
  }

  Future<void> _pickFile() async {
    final app = context.read<AppState>();
    final file = await openFile(acceptedTypeGroups: const [
      XTypeGroup(label: 'SFT Billing data file', extensions: ['sftpack']),
    ]);
    if (file == null) return;
    setState(() {
      _busy = true;
      _error = null;
      _fileName = file.name;
    });
    try {
      await app.restoreFrom(file.name, await file.readAsBytes());
      if (mounted) setState(() => _step = _Step.account);
    } catch (e) {
      if (mounted) setState(() => _error = errText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _createAccount() async {
    final digits = _mobile.text.replaceAll(RegExp(r'\D'), '');
    String? problem;
    if (_user.text.trim().isEmpty) {
      problem = 'Choose a username.';
    } else if (digits.length < 10) {
      problem = 'Enter a valid 10-digit mobile number.';
    } else if (_pass.text.length < 8) {
      problem = 'Use at least 8 characters for the password.';
    } else if (_pass.text != _confirm.text) {
      problem = 'The passwords do not match.';
    }
    if (problem != null) return setState(() => _error = problem);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<AppState>().register(_user.text.trim(), digits, _pass.text);
    } catch (e) {
      if (mounted) setState(() => _error = errText(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    final app = context.watch<AppState>();
    final loaded = app.restoredClients + app.restoredProducts > 0;
    return AuthFrame(
      maxFormWidth: 460,
      child: switch (_step) {
        _Step.choose => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Set up this PC', style: t.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            Text('How would you like to start?', style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
            const SizedBox(height: 24),
            _OptionCard(
              icon: Icons.auto_awesome_outlined,
              title: 'Clean installation',
              text: 'Start fresh with a new user and an empty workspace.',
              onTap: () => setState(() => _step = _Step.account),
            ),
            const SizedBox(height: 14),
            _OptionCard(
              icon: Icons.upload_file_outlined,
              title: 'Copy from another PC',
              text: 'Load a data file made with “Copy data” on your other PC — clients, products, settings and invoices.',
              onTap: () => setState(() => _step = _Step.copy),
            ),
          ]),
        _Step.copy => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Copy from another PC', style: t.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            Text('On the other PC open Copy data, save the file, and bring it here (pen drive, WhatsApp, email).',
                style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
            const SizedBox(height: 24),
            OutlinedButton.icon(
              onPressed: _busy ? null : _pickFile,
              icon: const Icon(Icons.folder_open_outlined),
              label: Text(_busy ? 'Loading ${_fileName ?? ''}…' : 'Choose data file (.sftpack)'),
            ),
            if (_error != null) Padding(padding: const EdgeInsets.only(top: 14), child: Text(_error!, style: TextStyle(color: t.colorScheme.error))),
            const SizedBox(height: 12),
            TextButton.icon(onPressed: _busy ? null : () => setState(() => _step = _Step.choose), icon: const Icon(Icons.arrow_back, size: 18), label: const Text('Back')),
          ]),
        _Step.account => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Create your account', style: t.textTheme.headlineMedium?.copyWith(fontWeight: FontWeight.w800)),
            const SizedBox(height: 6),
            Text('This PC gets its own user. Your mobile number is used to reset your password.', style: TextStyle(color: t.colorScheme.onSurfaceVariant)),
            if (loaded)
              Container(
                margin: const EdgeInsets.only(top: 16),
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(color: Colors.green.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
                child: Row(children: [
                  const Icon(Icons.check_circle, color: Colors.green, size: 20),
                  const SizedBox(width: 10),
                  Expanded(child: Text('Data loaded: ${app.restoredClients} clients, ${app.restoredProducts} products.')),
                ]),
              ),
            const SizedBox(height: 22),
            field('Username', _user),
            const SizedBox(height: 14),
            field('Mobile number', _mobile, type: TextInputType.phone, hint: '10-digit mobile number'),
            const SizedBox(height: 14),
            field('Password', _pass,
                obscure: !_show,
                hint: 'At least 8 characters',
                suffix: IconButton(icon: Icon(_show ? Icons.visibility_off_outlined : Icons.visibility_outlined, size: 20), onPressed: () => setState(() => _show = !_show))),
            const SizedBox(height: 14),
            field('Confirm password', _confirm, obscure: !_show, onSubmit: (_) => _createAccount()),
            if (_error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(_error!, style: TextStyle(color: t.colorScheme.error))),
            const SizedBox(height: 20),
            SizedBox(width: double.infinity, child: FilledButton(onPressed: _busy ? null : _createAccount, child: Text(_busy ? 'Creating account…' : 'Create account'))),
            if (!loaded)
              TextButton.icon(onPressed: _busy ? null : () => setState(() => _step = _Step.choose), icon: const Icon(Icons.arrow_back, size: 18), label: const Text('Back')),
          ]),
      },
    );
  }
}

class _OptionCard extends StatelessWidget {
  const _OptionCard({required this.icon, required this.title, required this.text, required this.onTap});
  final IconData icon;
  final String title, text;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context);
    return InkWell(
      borderRadius: BorderRadius.circular(16),
      onTap: onTap,
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(children: [
            Container(
              width: 48,
              height: 48,
              decoration: BoxDecoration(color: t.colorScheme.primary.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(14)),
              child: Icon(icon, color: t.colorScheme.primary),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: t.textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 2),
                Text(text, style: TextStyle(color: t.colorScheme.onSurfaceVariant, fontSize: 13)),
              ]),
            ),
            const Icon(Icons.chevron_right),
          ]),
        ),
      ),
    );
  }
}
