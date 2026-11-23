import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;

import '../core/api.dart';
import '../core/backend.dart';

enum Stage { starting, error, setup, login, ready }

class AppState extends ChangeNotifier {
  Stage stage = Stage.starting;
  String startStep = 'Starting application';
  String? error;
  ThemeMode themeMode = ThemeMode.light;

  BackendHost? _host;
  Api? api;
  Map<String, dynamic>? user;
  int restoredClients = 0;
  int restoredProducts = 0;

  /// Version shown in the UI. Keep in sync with pubspec.yaml and the installer.
  static const version = '2.0.0';

  Future<void> boot() async {
    stage = Stage.starting;
    error = null;
    startStep = 'Starting the billing service';
    notifyListeners();
    try {
      _host ??= await BackendHost.start();
      api = Api(_host!.baseUrl);
      startStep = 'Connecting to your data';
      notifyListeners();
      await _applyInstallerRestore();
      await refreshSetup();
    } catch (e) {
      error = e.toString();
      stage = Stage.error;
      notifyListeners();
    }
  }

  /// The installer can leave a data file from another PC here; load it on first run.
  Future<void> _applyInstallerRestore() async {
    final file = File(p.join(BackendHost.dataDir().path, 'import', 'restore.sftpack'));
    if (!file.existsSync()) return;
    final status = await api!.get('/api/setup/status');
    if (status['needs_account'] != true) return;
    try {
      await api!.upload('/api/setup/restore', 'file', 'restore.sftpack', await file.readAsBytes());
      file.renameSync('${file.path}.done');
    } catch (e) {
      error = 'The data file chosen during installation could not be loaded: $e';
    }
  }

  Future<void> refreshSetup() async {
    final s = await api!.get('/api/setup/status');
    restoredClients = s['clients'] as int;
    restoredProducts = s['products'] as int;
    stage = s['needs_account'] == true ? Stage.setup : Stage.login;
    notifyListeners();
  }

  Future<void> restoreFrom(String name, List<int> bytes) async {
    await api!.upload('/api/setup/restore', 'file', name, bytes);
    await refreshSetup();
  }

  void _signedIn(Map<String, dynamic> data) {
    api!.token = data['token'] as String;
    user = Map<String, dynamic>.from(data['user'] as Map);
    stage = Stage.ready;
    notifyListeners();
  }

  Future<void> register(String username, String mobile, String password) async {
    final data = await api!.post('/api/auth/first-run-setup', {'username': username, 'mobile': mobile, 'password': password});
    _signedIn(Map<String, dynamic>.from(data as Map));
  }

  Future<void> login(String username, String password) async {
    final data = await api!.post('/api/auth/login', {'username': username, 'password': password, 'remember': false});
    _signedIn(Map<String, dynamic>.from(data as Map));
  }

  /// Password reset by registered mobile number.
  Future<String> verifyMobile(String mobile) async {
    final data = await api!.post('/api/auth/forgot-password/verify-mobile', {'mobile': mobile});
    return data['reset_token'] as String;
  }

  Future<void> resetPassword(String token, String password) async {
    await api!.post('/api/auth/forgot-password/reset', {'reset_token': token, 'new_password': password});
  }

  Future<void> logout() async {
    try {
      await api!.post('/api/auth/logout');
    } catch (_) {}
    api!.token = null;
    user = null;
    stage = Stage.login;
    notifyListeners();
  }

  void toggleTheme() {
    themeMode = themeMode == ThemeMode.dark ? ThemeMode.light : ThemeMode.dark;
    notifyListeners();
  }

  void shutdown() => _host?.stop();
}
