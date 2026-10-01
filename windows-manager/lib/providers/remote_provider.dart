/// TX3 Manager - Remote Session Provider
import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/models.dart';
import '../services/api_service.dart';

class RemoteProvider extends ChangeNotifier {
  WebSocketChannel? _channel;
  String? _activeSessionId;
  String? _activeDeviceUuid;
  bool _connected = false;
  bool _streaming = false;
  String? _error;
  int _fps = 0;
  int _bitrateKbps = 0;
  bool _hwEncoder = false;
  int _width = 0;
  int _height = 0;

  bool get connected => _connected;
  bool get streaming => _streaming;
  String? get activeSessionId => _activeSessionId;
  String? get error => _error;
  int get fps => _fps;
  int get bitrateKbps => _bitrateKbps;
  bool get hwEncoder => _hwEncoder;
  int get width => _width;
  int get height => _height;

  StreamController<List<int>>? _videoStreamController;
  Stream<List<int>>? get videoStream => _videoStreamController?.stream;

  Future<void> connect() async {
    if (_connected) return;
    _error = null;

    try {
      final wsUrl = api.wsUrl;
      _channel = WebSocketChannel.connect(Uri.parse('$wsUrl/manager'));

      // Send auth message
      _channel!.sink.add(jsonEncode({
        'type': 'auth',
        'token': api.accessToken,
      }));

      _channel!.stream.listen(
        _handleMessage,
        onError: (error) {
          _error = 'WebSocket error: $error';
          _connected = false;
          notifyListeners();
        },
        onDone: () {
          _connected = false;
          _streaming = false;
          notifyListeners();
        },
      );

      _connected = true;
      notifyListeners();
    } catch (e) {
      _error = 'Không thể kết nối WebSocket: $e';
      notifyListeners();
    }
  }

  void _handleMessage(dynamic data) {
    try {
      final msg = jsonDecode(data as String);
      final type = msg['type'] as String? ?? '';
      final payload = msg['payload'] as Map<String, dynamic>? ?? {};

      switch (type) {
        case 'auth_ok':
          _connected = true;
          break;
        case 'box.remote_ready':
          _activeSessionId = payload['session_id'];
          _streaming = true;
          _width = payload['width'] ?? 1280;
          _height = payload['height'] ?? 720;
          _fps = payload['fps'] ?? 20;
          _bitrateKbps = payload['bitrate_kbps'] ?? 2000;
          _hwEncoder = payload['hw_encoder'] ?? false;
          break;
        case 'box.remote_stopped':
          _streaming = false;
          _activeSessionId = null;
          _videoStreamController?.close();
          _videoStreamController = null;
          break;
        case 'box.resource_report':
          _fps = (payload['encoder_fps'] as num?)?.toInt() ?? _fps;
          _bitrateKbps = payload['encoder_bitrate_kbps'] ?? _bitrateKbps;
          break;
        case 'error':
          _error = payload['message'] ?? 'Unknown error';
          break;
      }
      notifyListeners();
    } catch (e) {
      debugPrint('WS message parse error: $e');
    }
  }

  Future<void> startRemote(String deviceUuid, {String profile = 'auto'}) async {
    if (!_connected) await connect();
    if (!_connected) return;

    _activeDeviceUuid = deviceUuid;
    _activeSessionId = DateTime.now().millisecondsSinceEpoch.toRadixString(36);
    _videoStreamController = StreamController<List<int>>.broadcast();
    _error = null;

    _channel?.sink.add(jsonEncode({
      'type': 'client.remote_start',
      'id': _activeSessionId,
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'session_id': _activeSessionId,
        'device_uuid': deviceUuid,
        'profile': profile,
        'audio': false,
      },
    }));

    notifyListeners();
  }

  void stopRemote() {
    if (_activeSessionId == null) return;

    _channel?.sink.add(jsonEncode({
      'type': 'client.remote_stop',
      'id': DateTime.now().millisecondsSinceEpoch.toRadixString(36),
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {'session_id': _activeSessionId},
    }));

    _streaming = false;
    _activeSessionId = null;
    _activeDeviceUuid = null;
    _videoStreamController?.close();
    _videoStreamController = null;
    notifyListeners();
  }

  // ── Input Methods ──
  void sendMouseInput(String action, double x, double y, {int? scrollDelta}) {
    if (!_streaming || _channel == null) return;
    _channel!.sink.add(jsonEncode({
      'type': 'client.input_mouse',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'session_id': _activeSessionId,
        'action': action,
        'x': x,
        'y': y,
        if (scrollDelta != null) 'scroll_delta': scrollDelta,
      },
    }));
  }

  void sendKeyboardInput(String action, int keycode, {int metaState = 0}) {
    if (!_streaming || _channel == null) return;
    _channel!.sink.add(jsonEncode({
      'type': 'client.input_keyboard',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'session_id': _activeSessionId,
        'action': action,
        'keycode': keycode,
        'meta_state': metaState,
      },
    }));
  }

  void sendAndroidKey(String key) {
    if (!_streaming || _channel == null) return;
    _channel!.sink.add(jsonEncode({
      'type': 'client.input_android',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'session_id': _activeSessionId,
        'key': key,
      },
    }));
  }

  void changeProfile(String profile, {int? maxFps, int? maxBitrateKbps}) {
    if (!_streaming || _channel == null) return;
    _channel!.sink.add(jsonEncode({
      'type': 'client.profile_change',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'session_id': _activeSessionId,
        'profile': profile,
        if (maxFps != null) 'max_fps': maxFps,
        if (maxBitrateKbps != null) 'max_bitrate_kbps': maxBitrateKbps,
      },
    }));
  }

  void disconnect() {
    if (_streaming) stopRemote();
    _channel?.sink.close();
    _channel = null;
    _connected = false;
    notifyListeners();
  }

  @override
  void dispose() {
    disconnect();
    super.dispose();
  }
}
