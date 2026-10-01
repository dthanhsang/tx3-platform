/// TX3 Manager - Transfer Provider
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import '../models/models.dart';
import '../services/api_service.dart';

class TransferProvider extends ChangeNotifier {
  final Map<String, TransferInfo> _transfers = {};
  WebSocketChannel? _channel;

  List<TransferInfo> get transfers => _transfers.values.toList();
  List<TransferInfo> get activeTransfers =>
      _transfers.values.where((t) => t.status == 'active' || t.status == 'pending').toList();

  void addTransfer(TransferInfo transfer) {
    _transfers[transfer.id] = transfer;
    notifyListeners();
  }

  void updateTransfer(String id, {int? transferred, String? status, int? speedBps}) {
    final t = _transfers[id];
    if (t == null) return;
    if (transferred != null) t.transferred = transferred;
    if (status != null) t.status = status;
    if (speedBps != null) t.speedBps = speedBps;
    notifyListeners();
  }

  void removeTransfer(String id) {
    _transfers.remove(id);
    notifyListeners();
  }

  void clearCompleted() {
    _transfers.removeWhere((_, t) => t.status == 'completed' || t.status == 'failed');
    notifyListeners();
  }

  /// Send file listing request for a device
  void requestFileList(String deviceUuid, String path) {
    _channel?.sink.add(jsonEncode({
      'type': 'client.file_list',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'device_uuid': deviceUuid,
        'session_id': DateTime.now().millisecondsSinceEpoch.toRadixString(36),
        'path': path,
      },
    }));
  }

  /// Start upload to device
  void startUpload({
    required String deviceUuid,
    required String filename,
    required String destination,
    required int fileSize,
    required String hashSha256,
  }) {
    final transferId = 'upload-${DateTime.now().millisecondsSinceEpoch}';
    final transfer = TransferInfo(
      id: transferId,
      direction: 'upload',
      filename: filename,
      fileSize: fileSize,
    );
    addTransfer(transfer);

    _channel?.sink.add(jsonEncode({
      'type': 'client.file_upload_start',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'device_uuid': deviceUuid,
        'transfer_id': transferId,
        'filename': filename,
        'destination': destination,
        'file_size': fileSize,
        'chunk_size': 4 * 1024 * 1024,
        'hash_sha256': hashSha256,
        'resume_offset': 0,
      },
    }));
  }

  /// Start download from device
  void startDownload({
    required String deviceUuid,
    required String remotePath,
    required String filename,
    required int fileSize,
  }) {
    final transferId = 'download-${DateTime.now().millisecondsSinceEpoch}';
    final transfer = TransferInfo(
      id: transferId,
      direction: 'download',
      filename: filename,
      fileSize: fileSize,
    );
    addTransfer(transfer);

    _channel?.sink.add(jsonEncode({
      'type': 'client.file_download_start',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'device_uuid': deviceUuid,
        'transfer_id': transferId,
        'path': remotePath,
        'resume_offset': 0,
      },
    }));
  }

  void pauseTransfer(String transferId) {
    _channel?.sink.add(jsonEncode({
      'type': 'transfer.pause',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {'transfer_id': transferId},
    }));
    updateTransfer(transferId, status: 'paused');
  }

  void resumeTransfer(String transferId) {
    _channel?.sink.add(jsonEncode({
      'type': 'transfer.resume',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {'transfer_id': transferId},
    }));
    updateTransfer(transferId, status: 'active');
  }

  void cancelTransfer(String transferId) {
    _channel?.sink.add(jsonEncode({
      'type': 'transfer.cancel',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {'transfer_id': transferId},
    }));
    updateTransfer(transferId, status: 'cancelled');
  }

  /// Create directory on device
  void createDirectory(String deviceUuid, String path) {
    _channel?.sink.add(jsonEncode({
      'type': 'client.file_mkdir',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'device_uuid': deviceUuid,
        'session_id': DateTime.now().millisecondsSinceEpoch.toRadixString(36),
        'path': path,
      },
    }));
  }

  /// Delete file/directory on device
  void deleteFile(String deviceUuid, String path) {
    _channel?.sink.add(jsonEncode({
      'type': 'client.file_delete',
      'timestamp': DateTime.now().millisecondsSinceEpoch,
      'payload': {
        'device_uuid': deviceUuid,
        'session_id': DateTime.now().millisecondsSinceEpoch.toRadixString(36),
        'path': path,
      },
    }));
  }

  void setChannel(WebSocketChannel channel) {
    _channel = channel;
  }

  @override
  void dispose() {
    _channel = null;
    super.dispose();
  }
}
