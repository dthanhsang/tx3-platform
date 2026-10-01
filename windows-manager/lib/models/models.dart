/// TX3 Manager - Data Models

class User {
  final String id;
  final String username;
  final String? email;
  final String? displayName;
  final String status;
  final List<String> roles;
  final DateTime? lastLogin;
  final DateTime createdAt;

  User({
    required this.id,
    required this.username,
    this.email,
    this.displayName,
    required this.status,
    required this.roles,
    this.lastLogin,
    required this.createdAt,
  });

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: json['id'],
        username: json['username'],
        email: json['email'],
        displayName: json['display_name'],
        status: json['status'],
        roles: List<String>.from(json['roles'] ?? []),
        lastLogin: json['last_login'] != null ? DateTime.parse(json['last_login']) : null,
        createdAt: DateTime.parse(json['created_at']),
      );
}

class DeviceLocation {
  final String? customer;
  final String? site;
  final String? building;
  final String? floor;
  final String? room;
  final String? note;

  DeviceLocation({this.customer, this.site, this.building, this.floor, this.room, this.note});

  factory DeviceLocation.fromJson(Map<String, dynamic> json) => DeviceLocation(
        customer: json['customer'],
        site: json['site'],
        building: json['building'],
        floor: json['floor'],
        room: json['room'],
        note: json['note'],
      );

  String get displayLocation {
    final parts = <String>[];
    if (customer != null && customer!.isNotEmpty) parts.add(customer!);
    if (building != null && building!.isNotEmpty) parts.add(building!);
    if (floor != null && floor!.isNotEmpty) parts.add('T$floor');
    if (room != null && room!.isNotEmpty) parts.add('P$room');
    return parts.join(' / ');
  }
}

class Device {
  final String id;
  final String deviceUuid;
  final String? deviceName;
  final String? macWifi;
  final String? macEthernet;
  final String? serial;
  final String? model;
  final String? soc;
  final int? ramMb;
  final String? romVersion;
  final String? agentVersion;
  final String? wgIp;
  final String status;
  final DateTime? lastSeen;
  final int? uptimeSeconds;
  final DeviceLocation? location;
  final List<String> tags;
  final DateTime createdAt;

  Device({
    required this.id,
    required this.deviceUuid,
    this.deviceName,
    this.macWifi,
    this.macEthernet,
    this.serial,
    this.model,
    this.soc,
    this.ramMb,
    this.romVersion,
    this.agentVersion,
    this.wgIp,
    required this.status,
    this.lastSeen,
    this.uptimeSeconds,
    this.location,
    required this.tags,
    required this.createdAt,
  });

  factory Device.fromJson(Map<String, dynamic> json) => Device(
        id: json['id'],
        deviceUuid: json['device_uuid'],
        deviceName: json['device_name'],
        macWifi: json['mac_wifi'],
        macEthernet: json['mac_ethernet'],
        serial: json['serial'],
        model: json['model'],
        soc: json['soc'],
        ramMb: json['ram_mb'],
        romVersion: json['rom_version'],
        agentVersion: json['agent_version'],
        wgIp: json['wg_ip'],
        status: json['status'],
        lastSeen: json['last_seen'] != null ? DateTime.parse(json['last_seen']) : null,
        uptimeSeconds: json['uptime_seconds'],
        location: json['location'] != null ? DeviceLocation.fromJson(json['location']) : null,
        tags: List<String>.from(json['tags'] ?? []),
        createdAt: DateTime.parse(json['created_at']),
      );

  bool get isOnline => status == 'online';

  String get displayName => deviceName ?? deviceUuid;

  String get uptimeDisplay {
    if (uptimeSeconds == null) return '—';
    final d = Duration(seconds: uptimeSeconds!);
    if (d.inDays > 0) return '${d.inDays}d ${d.inHours % 24}h';
    if (d.inHours > 0) return '${d.inHours}h ${d.inMinutes % 60}m';
    return '${d.inMinutes}m';
  }
}

class RemoteSession {
  final String id;
  final String deviceId;
  final String sessionType;
  final DateTime startedAt;
  final DateTime? endedAt;
  final String result;

  RemoteSession({
    required this.id,
    required this.deviceId,
    required this.sessionType,
    required this.startedAt,
    this.endedAt,
    required this.result,
  });

  factory RemoteSession.fromJson(Map<String, dynamic> json) => RemoteSession(
        id: json['id'],
        deviceId: json['device_id'],
        sessionType: json['session_type'],
        startedAt: DateTime.parse(json['started_at']),
        endedAt: json['ended_at'] != null ? DateTime.parse(json['ended_at']) : null,
        result: json['result'],
      );
}

class FileEntry {
  final String name;
  final String type; // file | directory
  final int size;
  final DateTime modified;
  final String permissions;

  FileEntry({
    required this.name,
    required this.type,
    required this.size,
    required this.modified,
    required this.permissions,
  });

  factory FileEntry.fromJson(Map<String, dynamic> json) => FileEntry(
        name: json['name'],
        type: json['type'],
        size: json['size'] ?? 0,
        modified: DateTime.fromMillisecondsSinceEpoch(json['modified'] ?? 0),
        permissions: json['permissions'] ?? '',
      );

  bool get isDirectory => type == 'directory';

  String get sizeDisplay {
    if (isDirectory) return '—';
    double s = size.toDouble();
    for (final unit in ['B', 'KB', 'MB', 'GB']) {
      if (s < 1024 || unit == 'GB') return '${s.toStringAsFixed(s < 10 ? 1 : 0)} $unit';
      s /= 1024;
    }
    return '$size B';
  }
}

class TransferInfo {
  final String id;
  final String direction; // upload | download
  final String filename;
  final int fileSize;
  int transferred;
  String status; // pending | active | paused | completed | failed
  int speedBps;
  DateTime startedAt;

  TransferInfo({
    required this.id,
    required this.direction,
    required this.filename,
    required this.fileSize,
    this.transferred = 0,
    this.status = 'pending',
    this.speedBps = 0,
    DateTime? startedAt,
  }) : startedAt = startedAt ?? DateTime.now();

  double get progress => fileSize > 0 ? transferred / fileSize : 0;

  String get speedDisplay {
    if (speedBps <= 0) return '—';
    double s = speedBps.toDouble();
    for (final unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']) {
      if (s < 1024 || unit == 'GB/s') return '${s.toStringAsFixed(1)} $unit';
      s /= 1024;
    }
    return '$speedBps B/s';
  }

  String get etaDisplay {
    if (speedBps <= 0 || transferred >= fileSize) return '—';
    final remaining = fileSize - transferred;
    final seconds = remaining / speedBps;
    final d = Duration(seconds: seconds.round());
    if (d.inHours > 0) return '${d.inHours}h ${d.inMinutes % 60}m';
    if (d.inMinutes > 0) return '${d.inMinutes}m ${d.inSeconds % 60}s';
    return '${d.inSeconds}s';
  }
}

class AuditLogEntry {
  final String id;
  final String? userId;
  final String? deviceId;
  final String action;
  final String category;
  final String severity;
  final Map<String, dynamic> metadata;
  final DateTime createdAt;

  AuditLogEntry({
    required this.id,
    this.userId,
    this.deviceId,
    required this.action,
    required this.category,
    required this.severity,
    required this.metadata,
    required this.createdAt,
  });

  factory AuditLogEntry.fromJson(Map<String, dynamic> json) => AuditLogEntry(
        id: json['id'],
        userId: json['user_id'],
        deviceId: json['device_id'],
        action: json['action'],
        category: json['category'],
        severity: json['severity'],
        metadata: Map<String, dynamic>.from(json['metadata'] ?? {}),
        createdAt: DateTime.parse(json['created_at']),
      );
}
