import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  ApiException(this.message, [this.status]);
  final String message;
  final int? status;
  @override
  String toString() => message;
}

/// Thin JSON client for the local FastAPI service.
class Api {
  Api(this.base);

  final String base;
  String? token;

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('$base$path').replace(queryParameters: query);

  static String _message(http.Response r) {
    try {
      final body = jsonDecode(utf8.decode(r.bodyBytes));
      final d = body is Map ? body['detail'] : body;
      if (d is String) return d;
      if (d is List && d.isNotEmpty) {
        final first = d.first;
        if (first is Map && first['msg'] != null) return first['msg'].toString().replaceFirst('Value error, ', '');
      }
      if (d is Map && d['message'] != null) return d['message'].toString();
    } catch (_) {}
    return 'Something went wrong (${r.statusCode}).';
  }

  dynamic _decode(http.Response r) {
    if (r.statusCode >= 200 && r.statusCode < 300) {
      if (r.bodyBytes.isEmpty) return null;
      return jsonDecode(utf8.decode(r.bodyBytes));
    }
    throw ApiException(_message(r), r.statusCode);
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) async =>
      _decode(await http.get(_uri(path, query), headers: _headers));

  Future<dynamic> post(String path, [Object? body]) async =>
      _decode(await http.post(_uri(path), headers: _headers, body: jsonEncode(body ?? {})));

  Future<dynamic> put(String path, Object body) async =>
      _decode(await http.put(_uri(path), headers: _headers, body: jsonEncode(body)));

  Future<dynamic> delete(String path) async =>
      _decode(await http.delete(_uri(path), headers: _headers));

  /// Binary download (PDF, Excel, data pack).
  Future<Uint8List> bytes(String path, {String method = 'GET', Object? body}) async {
    final req = http.Request(method, _uri(path))..headers.addAll(_headers);
    if (body != null) req.body = jsonEncode(body);
    final r = await http.Response.fromStream(await req.send());
    if (r.statusCode >= 200 && r.statusCode < 300) return r.bodyBytes;
    throw ApiException(_message(r), r.statusCode);
  }

  Future<dynamic> upload(String path, String field, String fileName, List<int> data) async {
    final req = http.MultipartRequest('POST', _uri(path))
      ..files.add(http.MultipartFile.fromBytes(field, data, filename: fileName));
    final r = await http.Response.fromStream(await req.send());
    return _decode(r);
  }
}
