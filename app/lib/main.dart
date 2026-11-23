import 'package:flutter/material.dart';
import 'dart:ui' show AppExitResponse;
import 'package:pdfrx/pdfrx.dart';
import 'package:provider/provider.dart';

import 'core/theme.dart';
import 'screens/auth_screens.dart';
import 'screens/setup_wizard.dart';
import 'screens/shell.dart';
import 'screens/startup_screen.dart';
import 'state/app_state.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await pdfrxFlutterInitialize();
  final state = AppState();
  runApp(ChangeNotifierProvider.value(value: state, child: const SftApp()));
  state.boot();
}

class SftApp extends StatefulWidget {
  const SftApp({super.key});
  @override
  State<SftApp> createState() => _SftAppState();
}

class _SftAppState extends State<SftApp> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  Future<AppExitResponse> didRequestAppExit() async {
    context.read<AppState>().shutdown();
    return AppExitResponse.exit;
  }

  @override
  Widget build(BuildContext context) {
    final state = context.watch<AppState>();
    return MaterialApp(
      title: 'SFT Billing',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: state.themeMode,
      home: switch (state.stage) {
        Stage.starting || Stage.error => const StartupScreen(),
        Stage.setup => const SetupWizard(),
        Stage.login => const LoginScreen(),
        Stage.ready => const Shell(),
      },
    );
  }
}


