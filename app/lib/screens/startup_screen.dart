import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/theme.dart';
import '../state/app_state.dart';

class StartupScreen extends StatelessWidget {
  const StartupScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final failed = s.stage == Stage.error;
    return Scaffold(
      backgroundColor: const Color(0xFF05060D),
      body: Stack(children: [
        Positioned.fill(
          child: DecoratedBox(
            decoration: BoxDecoration(
              gradient: RadialGradient(
                center: const Alignment(-0.3, -0.6),
                radius: 1.2,
                colors: [brandBlue.withValues(alpha: 0.35), const Color(0xFF05060D)],
              ),
            ),
          ),
        ),
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 420),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              Image.asset('assets/brand/surfine-emblem.png', height: 72, color: Colors.white),
              const SizedBox(height: 24),
              const Text('SFT Billing', style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              const Text('by Surfine Technology', style: TextStyle(color: Colors.white54)),
              const SizedBox(height: 36),
              if (!failed) ...[
                const SizedBox(width: 280, child: LinearProgressIndicator(minHeight: 4, borderRadius: BorderRadius.all(Radius.circular(4)))),
                const SizedBox(height: 16),
                Text(s.startStep, style: const TextStyle(color: Colors.white70)),
              ] else ...[
                const Icon(Icons.error_outline, color: Colors.orangeAccent, size: 40),
                const SizedBox(height: 12),
                const Text("Couldn't start the billing service", style: TextStyle(color: Colors.white, fontSize: 18, fontWeight: FontWeight.w600)),
                const SizedBox(height: 10),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(color: Colors.black38, borderRadius: BorderRadius.circular(10)),
                  child: Text(s.error ?? '', style: const TextStyle(color: Colors.white60, fontSize: 12, fontFamily: 'Consolas')),
                ),
                const SizedBox(height: 18),
                FilledButton.icon(onPressed: s.boot, icon: const Icon(Icons.refresh), label: const Text('Try again')),
              ],
            ]),
          ),
        ),
        const Positioned(bottom: 20, left: 0, right: 0, child: Center(child: Text('Version ${AppState.version}', style: TextStyle(color: Colors.white30, fontSize: 11)))),
      ]),
    );
  }
}
