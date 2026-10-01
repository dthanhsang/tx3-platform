/// TX3 Manager - Auth Provider
import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../models/models.dart';
import '../services/api_service.dart';

class AuthProvider extends ChangeNotifier {
  User? _user;
  bool _loading = false;
  String? _error;
  String _serverUrl = '';
  String _licenseStatus = '';

  User? get user => _user;
  bool get isAuthenticated => _user != null;
  bool get loading => _loading;
  String? get error => _error;
  String get serverUrl => _serverUrl;
  String get licenseStatus => _licenseStatus;

  AuthProvider() {
    _loadSavedSession();
  }

  Future<void> _loadSavedSession() async {
    final prefs = await SharedPreferences.getInstance();
    _serverUrl = prefs.getString('server_url') ?? '';
    final token = prefs.getString('access_token') ?? '';
    final refresh = prefs.getString('refresh_token') ?? '';

    if (_serverUrl.isNotEmpty && token.isNotEmpty) {
      api.configure(baseUrl: '$_serverUrl/api/v1', accessToken: token, refreshToken: refresh);
      try {
        _user = await api.getMe();
        notifyListeners();
      } catch (_) {
        // Token expired, clear
        await _clearSession();
      }
    }
  }

  Future<void> login(String serverUrl, String username, String password, {String? licenseKey}) async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      _serverUrl = serverUrl.endsWith('/') ? serverUrl.substring(0, serverUrl.length - 1) : serverUrl;
      api.configure(baseUrl: '$_serverUrl/api/v1');

      // Validate license if provided
      if (licenseKey != null && licenseKey.isNotEmpty) {
        final licResult = await api.validateLicense(licenseKey);
        if (licResult['valid'] != true) {
          throw ApiException(403, 'License không hợp lệ hoặc đã hết hạn');
        }
        _licenseStatus = '${licResult['plan']} - ${licResult['organization_name'] ?? ''}';
      }

      final result = await api.login(username, password);
      _user = User.fromJson(result['user']);

      // Save session
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('server_url', _serverUrl);
      await prefs.setString('access_token', api.accessToken);
      await prefs.setString('refresh_token', api.refreshToken);

      _error = null;
    } on ApiException catch (e) {
      _error = e.message;
      _user = null;
    } catch (e) {
      _error = 'Không thể kết nối server: $e';
      _user = null;
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> logout() async {
    await api.logout();
    await _clearSession();
    _user = null;
    _licenseStatus = '';
    notifyListeners();
  }

  Future<void> _clearSession() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('access_token');
    await prefs.remove('refresh_token');
  }
}
