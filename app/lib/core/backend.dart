import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;
import 'package:path/path.dart' as p;

/// Starts (and owns) the local Python/FastAPI service the UI talks to.
class BackendHost {
  BackendHost._(this.baseUrl, this._process);

  final String baseUrl;
  final Process? _process;

  /// Folder holding this PC's database: %LOCALAPPDATA%\SFT Billing
  static Directory dataDir() {
    final local = Platform.environment['LOCALAPPDATA'] ?? Directory.systemTemp.path;
    return Directory(p.join(local, 'SFT Billing'));
  }

  static Future<BackendHost> start() async {
    // Development: point at an already running backend.
    final dev = Platform.environment['SFT_BACKEND_URL'];
    if (dev != null && dev.isNotEmpty) {
      await _waitUntilHealthy(dev, null);
      return BackendHost._(dev, null);
    }

    final exeDir = p.dirname(Platform.resolvedExecutable);
    final backendExe = File(p.join(exeDir, 'backend', 'sft-billing-server.exe'));
    if (!backendExe.existsSync()) {
      throw StateError('The billing service is missing from the installation.\n${backendExe.path}');
    }

    final data = dataDir()..createSync(recursive: true);
    final dbUrl = 'sqlite:///${p.join(data.path, 'sft_billing.db').replaceAll('\\', '/')}';
    final port = await _freePort();

    final process = await Process.start(
      backendExe.path,
      ['--port', '$port', '--parent-pid', '$pid'],
      environment: {
        'SFT_BILLING_DATABASE_URL': dbUrl,
        'SFT_BILLING_MIGRATION_DATABASE_URL': dbUrl,
      },
      workingDirectory: p.dirname(backendExe.path),
      mode: ProcessStartMode.normal,
    );
    // The service logs to a file; just keep the pipes drained.
    process.stdout.drain<void>();
    process.stderr.drain<void>();
    final url = 'http://127.0.0.1:$port';
    await _waitUntilHealthy(url, process);
    return BackendHost._(url, process);
  }

  void stop() => _process?.kill();

  static Future<int> _freePort() async {
    final socket = await ServerSocket.bind(InternetAddress.loopbackIPv4, 0);
    final port = socket.port;
    await socket.close();
    return port;
  }

  static Future<void> _waitUntilHealthy(String url, Process? process) async {
    final deadline = DateTime.now().add(const Duration(seconds: 90));
    var exited = false;
    process?.exitCode.then((_) => exited = true);
    while (DateTime.now().isBefore(deadline)) {
      if (exited) throw StateError('The billing service stopped unexpectedly.');
      try {
        final res = await http.get(Uri.parse('$url/api/health')).timeout(const Duration(seconds: 2));
        if (res.statusCode == 200 && (jsonDecode(res.body)['status'] == 'ok')) return;
      } catch (_) {}
      await Future.delayed(const Duration(milliseconds: 500));
    }
    throw TimeoutException('The billing service did not start in time.');
  }
}
