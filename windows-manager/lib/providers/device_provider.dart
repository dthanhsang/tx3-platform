/// TX3 Manager - Device Provider
import 'dart:async';
import 'package:flutter/foundation.dart';
import '../models/models.dart';
import '../services/api_service.dart';
import 'auth_provider.dart';

class DeviceProvider extends ChangeNotifier {
  List<Device> _devices = [];
  Device? _selectedDevice;
  bool _loading = false;
  String? _error;
  String _searchQuery = '';
  String? _statusFilter;
  Timer? _refreshTimer;

  List<Device> get devices => _devices;
  Device? get selectedDevice => _selectedDevice;
  bool get loading => _loading;
  String? get error => _error;
  String get searchQuery => _searchQuery;

  List<Device> get filteredDevices {
    var result = _devices;
    if (_searchQuery.isNotEmpty) {
      final q = _searchQuery.toLowerCase();
      result = result.where((d) {
        return d.displayName.toLowerCase().contains(q) ||
            d.deviceUuid.toLowerCase().contains(q) ||
            (d.macWifi ?? '').toLowerCase().contains(q) ||
            (d.macEthernet ?? '').toLowerCase().contains(q) ||
            (d.serial ?? '').toLowerCase().contains(q) ||
            (d.wgIp ?? '').toLowerCase().contains(q) ||
            (d.location?.displayLocation ?? '').toLowerCase().contains(q) ||
            (d.location?.note ?? '').toLowerCase().contains(q) ||
            d.tags.any((t) => t.toLowerCase().contains(q));
      }).toList();
    }
    if (_statusFilter != null) {
      result = result.where((d) => d.status == _statusFilter).toList();
    }
    return result;
  }

  int get onlineCount => _devices.where((d) => d.isOnline).length;
  int get offlineCount => _devices.where((d) => !d.isOnline).length;

  void updateAuth(AuthProvider auth) {
    if (auth.isAuthenticated) {
      _startAutoRefresh();
    } else {
      _stopAutoRefresh();
      _devices = [];
      _selectedDevice = null;
      notifyListeners();
    }
  }

  void setSearchQuery(String query) {
    _searchQuery = query;
    notifyListeners();
  }

  void setStatusFilter(String? status) {
    _statusFilter = status;
    notifyListeners();
  }

  Future<void> loadDevices() async {
    _loading = true;
    _error = null;
    notifyListeners();

    try {
      _devices = await api.getDevices(query: _searchQuery.isEmpty ? null : _searchQuery, status: _statusFilter);
      // Sort: online first, then by name
      _devices.sort((a, b) {
        if (a.isOnline != b.isOnline) return a.isOnline ? -1 : 1;
        return a.displayName.compareTo(b.displayName);
      });
      _error = null;
    } on ApiException catch (e) {
      _error = e.message;
    } catch (e) {
      _error = 'Lỗi tải danh sách: $e';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> selectDevice(String deviceId) async {
    try {
      _selectedDevice = await api.getDevice(deviceId);
      notifyListeners();
    } catch (e) {
      _error = 'Không tải được chi tiết thiết bị';
      notifyListeners();
    }
  }

  void clearSelection() {
    _selectedDevice = null;
    notifyListeners();
  }

  Future<void> updateDeviceName(String deviceId, String name) async {
    await api.updateDevice(deviceId, {'device_name': name});
    await loadDevices();
    if (_selectedDevice?.id == deviceId) await selectDevice(deviceId);
  }

  Future<void> updateDeviceLocation(String deviceId, Map<String, dynamic> location) async {
    await api.updateDeviceLocation(deviceId, location);
    if (_selectedDevice?.id == deviceId) await selectDevice(deviceId);
  }

  Future<void> addTag(String deviceId, String tag) async {
    await api.addDeviceTag(deviceId, tag);
    if (_selectedDevice?.id == deviceId) await selectDevice(deviceId);
  }

  Future<void> removeTag(String deviceId, String tag) async {
    await api.removeDeviceTag(deviceId, tag);
    if (_selectedDevice?.id == deviceId) await selectDevice(deviceId);
  }

  Future<void> rebootDevice(String deviceId) async {
    await api.rebootDevice(deviceId);
  }

  Future<void> revokeDevice(String deviceId) async {
    await api.revokeDevice(deviceId);
    _selectedDevice = null;
    await loadDevices();
  }

  void _startAutoRefresh() {
    _refreshTimer?.cancel();
    loadDevices();
    _refreshTimer = Timer.periodic(const Duration(seconds: 15), (_) => loadDevices());
  }

  void _stopAutoRefresh() {
    _refreshTimer?.cancel();
    _refreshTimer = null;
  }

  @override
  void dispose() {
    _stopAutoRefresh();
    super.dispose();
  }
}
