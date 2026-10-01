/// TX3 Manager - API Service
/// Handles all HTTP communication with Management Server

import 'dart:convert';
import 'package:http/http.dart' as http;
import '../models/models.dart';

class ApiService {
  String _baseUrl = '';
  String _accessToken = '';
  String _refreshToken = '';

  void configure({required String baseUrl, String? accessToken, String? refreshToken}) {
    _baseUrl = baseUrl.endsWith('/') ? baseUrl.substring(0, baseUrl.length - 1) : baseUrl;
    if (accessToken != null) _accessToken = accessToken;
    if (refreshToken != null) _refreshToken = refreshToken;
  }

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        if (_accessToken.isNotEmpty) 'Authorization': 'Bearer $_accessToken',
      };

  String get accessToken => _accessToken;
  String get refreshToken => _refreshToken;
  String get baseUrl => _baseUrl;
  String get wsUrl => _baseUrl.replaceFirst('http', 'ws').replaceFirst('/api/v1', '/ws');

  // ── Auth ──
  Future<Map<String, dynamic>> login(String username, String password) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/auth/login'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'username': username, 'password': password}),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      _accessToken = data['access_token'];
      _refreshToken = data['refresh_token'];
      return data;
    }
    throw ApiException(response.statusCode, _parseError(response));
  }

  Future<void> refreshAccessToken() async {
    final response = await http.post(
      Uri.parse('$_baseUrl/auth/refresh'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'refresh_token': _refreshToken}),
    );
    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      _accessToken = data['access_token'];
    } else {
      throw ApiException(response.statusCode, 'Token refresh failed');
    }
  }

  Future<void> logout() async {
    try {
      await http.post(
        Uri.parse('$_baseUrl/auth/logout'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'refresh_token': _refreshToken}),
      );
    } catch (_) {}
    _accessToken = '';
    _refreshToken = '';
  }

  Future<User> getMe() async {
    final response = await _get('/auth/me');
    return User.fromJson(response);
  }

  // ── Devices ──
  Future<List<Device>> getDevices({String? query, String? status, int page = 1, int pageSize = 50}) async {
    final params = <String, String>{'page': '$page', 'page_size': '$pageSize'};
    if (query != null && query.isNotEmpty) params['query'] = query;
    if (status != null && status.isNotEmpty) params['status'] = status;
    final uri = Uri.parse('$_baseUrl/devices').replace(queryParameters: params);
    final response = await http.get(uri, headers: _headers);
    _checkResponse(response);
    final list = jsonDecode(response.body) as List;
    return list.map((e) => Device.fromJson(e)).toList();
  }

  Future<Device> getDevice(String deviceId) async {
    final data = await _get('/devices/$deviceId');
    return Device.fromJson(data);
  }

  Future<Map<String, int>> getDeviceCount() async {
    return Map<String, int>.from(await _get('/devices/count'));
  }

  Future<Device> updateDevice(String deviceId, Map<String, dynamic> updates) async {
    final data = await _patch('/devices/$deviceId', updates);
    return Device.fromJson(data);
  }

  Future<void> updateDeviceLocation(String deviceId, Map<String, dynamic> location) async {
    await _put('/devices/$deviceId/location', location);
  }

  Future<void> addDeviceTag(String deviceId, String tagName) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/devices/$deviceId/tags/$tagName'),
      headers: _headers,
    );
    _checkResponse(response);
  }

  Future<void> removeDeviceTag(String deviceId, String tagName) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/devices/$deviceId/tags/$tagName'),
      headers: _headers,
    );
    _checkResponse(response);
  }

  Future<void> rebootDevice(String deviceId) async {
    final response = await http.post(
      Uri.parse('$_baseUrl/devices/$deviceId/reboot'),
      headers: _headers,
    );
    _checkResponse(response);
  }

  Future<void> revokeDevice(String deviceId) async {
    final response = await http.delete(
      Uri.parse('$_baseUrl/devices/$deviceId'),
      headers: _headers,
    );
    _checkResponse(response);
  }

  // ── Licenses ──
  Future<Map<String, dynamic>> validateLicense(String licenseKey) async {
    return await _post('/licenses/validate', {'license_key': licenseKey});
  }

  // ── Audit ──
  Future<List<AuditLogEntry>> getAuditLogs({
    String? deviceId,
    String? action,
    int page = 1,
    int pageSize = 50,
  }) async {
    final params = <String, String>{'page': '$page', 'page_size': '$pageSize'};
    if (deviceId != null) params['device_id'] = deviceId;
    if (action != null) params['action'] = action;
    final uri = Uri.parse('$_baseUrl/audit').replace(queryParameters: params);
    final response = await http.get(uri, headers: _headers);
    _checkResponse(response);
    final list = jsonDecode(response.body) as List;
    return list.map((e) => AuditLogEntry.fromJson(e)).toList();
  }

  // ── Batch ──
  Future<Map<String, dynamic>> createBatch(String operationType, List<String> deviceIds, Map<String, dynamic> payload) async {
    return await _post('/batch', {
      'operation_type': operationType,
      'device_ids': deviceIds,
      'payload': payload,
    });
  }

  // ── Helpers ──
  Future<Map<String, dynamic>> _get(String path) async {
    final response = await http.get(Uri.parse('$_baseUrl$path'), headers: _headers);
    _checkResponse(response);
    return jsonDecode(response.body);
  }

  Future<Map<String, dynamic>> _post(String path, Map<String, dynamic> body) async {
    final response = await http.post(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    _checkResponse(response);
    return jsonDecode(response.body);
  }

  Future<Map<String, dynamic>> _patch(String path, Map<String, dynamic> body) async {
    final response = await http.patch(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    _checkResponse(response);
    return jsonDecode(response.body);
  }

  Future<Map<String, dynamic>> _put(String path, Map<String, dynamic> body) async {
    final response = await http.put(
      Uri.parse('$_baseUrl$path'),
      headers: _headers,
      body: jsonEncode(body),
    );
    _checkResponse(response);
    return jsonDecode(response.body);
  }

  void _checkResponse(http.Response response) {
    if (response.statusCode >= 400) {
      throw ApiException(response.statusCode, _parseError(response));
    }
  }

  String _parseError(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      return body['detail'] ?? body['message'] ?? 'Unknown error';
    } catch (_) {
      return response.body.isNotEmpty ? response.body : 'HTTP ${response.statusCode}';
    }
  }
}

class ApiException implements Exception {
  final int statusCode;
  final String message;
  ApiException(this.statusCode, this.message);

  @override
  String toString() => 'ApiException($statusCode): $message';
}

// Global singleton
final api = ApiService();
